"""BACKEND 3 - NVIDIA NIM, three models, two of three must agree.

    python pipeline/nim_judge.py --client <key> --limit 60          # one batch, judged
    python pipeline/nim_judge.py --client <key> --all               # every line for that client
    python pipeline/nim_judge.py --report                           # agreement + Claude comparison

WHY THREE MODELS. Sameer, 2026-08-14: *"i want to use 3 models, where 2 models need to agree with
eachother, this will give me more confidence with our working."* Three DIFFERENT LINEAGES, not the
three best - three models from one family share training data, therefore share failure modes, and
their agreement proves nothing. NVIDIA / OpenAI / Mistral.

WHAT IT BUYS AND WHAT IT DOES NOT. 2-of-3 removes one model's off moment. It cannot remove a wrong
prior all three share. **Agreement is a triage signal, never a calibration one** - the same trap as
the analyst override rate. `split` is the review queue, and the split RATE is a live measurement of
how hard the task actually is.

NO NEW TABLES AND NO NEW ROWS. Sameer: *"any writing into sql strictly do it in only qa_line ...
having 8000 rows from a 2000 sample is duplication if nothing else."* One run per model would have
been 8,000 rows. So the three votes live in COLUMNS on the same 2,000 rows:
`NIM_1..3_{MODEL,VERDICT,CONFIDENCE,SUGGESTED_KEY}` plus the consensus block. `qa_line` keeps
2,000 rows and one run_id, and Claude's 1,462 verdicts in VERDICT/CONFIDENCE/BASIS are NEVER
touched - that is what makes the comparison a column-vs-column read on one row.

THE PROMPT IS judge.py's, UNCHANGED. Change the model and the prompt together and the comparison
measures nothing. Only the transport is new.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import threading
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import judge  # noqa: E402
from db import connect_qa, load_env  # noqa: E402

# The free tier is ~40 requests/minute and NVIDIA describe it as varying with model, use case and
# current traffic - so a 429 is expected, not exceptional. A throttled call that is allowed to fail
# leaves a PARTIAL generation, which is the failure mode that has already cost this project once.
RETRY_STATUS = (408, 409, 425, 429, 500, 502, 503, 504, 529)
MAX_TRIES = 6
BACKOFF = 4.0
# A TIMEOUT IS NOT A 429 AND MUST NOT BE RETRIED LIKE ONE. Measured 2026-08-14: a throttled call
# comes back in milliseconds and clears on the next attempt, so patience is exactly right for it.
# A model that has gone unhealthy does not answer AT ALL - and six patient retries against that is
# 6 x 300s = thirty minutes of a batch spent waiting on a corpse, which is what
# meta/llama-3.3-70b-instruct cost this project before it was measured. Two strikes, then dead.
MAX_TIMEOUTS = 2
TIMEOUT = 180

# PER-MODEL REQUEST EXTRAS, matched on a substring of the model id.
# A REASONING MODEL SPENDS ITS ANSWER BUDGET ON THINKING. `max_tokens` caps thinking and answer
# together, so nemotron-3-super deliberated over a 350-category candidate list and returned JSON cut
# off mid-object - the calibration run's `Expecting ',' delimiter: line 42` and, when it thought
# right to the cap, `Expecting value: line 1 column 1` for an empty `content`. Measured 2026-08-14:
# `thinking: False` takes its reasoning output from 1,064 characters to 0 at the same accuracy of
# parse (10/10 either way). The cost is real and worth stating - a judge that cannot deliberate is
# a weaker judge - but it is ONE of three votes, and the alternative was a model that mostly failed.
MODEL_EXTRAS = {
    "nemotron": {"chat_template_kwargs": {"thinking": False}},
}


def extras_for(model):
    for frag, ex in MODEL_EXTRAS.items():
        if frag in model:
            return ex
    return {}


def models(env):
    raw = (env.get("NIM_MODELS") or env.get("NIM_MODEL") or "").strip()
    got = [m.strip() for m in raw.split(",") if m.strip()]
    if not got:
        raise SystemExit("  NIM_MODELS is empty in .env - nothing to judge with")
    return got


def call(env, model, payload, timeout=TIMEOUT):
    """One chat completion. Returns the parsed verdict list, or raises."""
    body = json.dumps({
        **extras_for(model),
        "model": model,
        "messages": [
            {"role": "system", "content":
                "You are auditing spend categorisation. Reply with JSON only - no prose, no code "
                "fences. Shape: {\"verdicts\": [{\"line_id\": <int>, \"verdict\": \"Correct\"|"
                "\"Incorrect\"|\"Uncertain\", \"confidence\": <0-1>, \"basis\": <one of the basis "
                "strings given>, \"suggested_key\": <candidate key or null>, \"rationale\": "
                "<one sentence>}]}. One entry per unit, every line_id present."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        # Deterministic as the API allows. A judge that answers differently on identical input is
        # contradicting itself, and judge.py's self-consistency check exists to catch exactly that.
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": 8192,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{env['NIM_BASE_URL'].rstrip('/')}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {env['NIM_API_KEY'].strip()}",
                 "Content-Type": "application/json", "Accept": "application/json"})
    last, timeouts = None, 0
    for attempt in range(1, MAX_TRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            return parse(data["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as ex:
            last = f"HTTP {ex.code} {ex.reason}"
            if ex.code not in RETRY_STATUS:
                # RuntimeError, NOT SystemExit. These run on worker threads, where SystemExit is a
                # BaseException that no `except Exception` catches - the thread dies unreported and
                # the batch silently becomes a two-model vote still labelled "2of3".
                raise RuntimeError(f"{last} - {ex.read().decode()[:200]}")
        except Exception as ex:                                   # noqa: BLE001
            last = f"{type(ex).__name__}: {ex}"
            # Detected by BOTH type and message: urllib surfaces a read timeout as TimeoutError but
            # a connect timeout as a URLError WRAPPING one, and only the message distinguishes it.
            if isinstance(ex, TimeoutError) or "timed out" in str(ex).lower():
                timeouts += 1
                if timeouts >= MAX_TIMEOUTS:
                    raise RuntimeError(f"no response in {timeout}s on {timeouts} attempts "
                                       f"- model is unhealthy, not throttled") from ex
        wait = BACKOFF * attempt
        print(f"      {model}: {last} - retry {attempt}/{MAX_TRIES} in {wait:.0f}s", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"gave up after {MAX_TRIES} tries - {last}")


def parse(text):
    """Models wrap JSON in prose or fences however they like. Take the object, not the packaging."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise
        obj = json.loads(m.group(0))
    rows = obj.get("verdicts", obj) if isinstance(obj, dict) else obj
    return {int(v["line_id"]): v for v in rows if v.get("line_id") is not None}


def _conf(v):
    """A model's confidence, coerced safely. NEVER let a malformed field kill a run.

    🔒 FOUND BY THE CONCURRENCY TEST, 2026-08-18, and it took out an entire client pass:

        ValueError: could not convert string to float:
            'When there is no evidence at all, answer Uncertain'

    A model returned a SENTENCE FROM THE PROMPT in the `confidence` field, `float()` was called on
    it bare, and the exception propagated out of the worker thread, through `ex.map`, and killed
    `western_health` after 365 of 375 lines. Nine minutes of judging discarded because one field in
    one response was prose.

    🔑 THE LESSON: EVERY FIELD COMING BACK FROM A MODEL IS UNTRUSTED INPUT, INCLUDING THE NUMERIC
    ONES. The verdict and suggested_key were already validated against fixed sets; confidence was
    not, purely because it "is a number". At 2,000 lines this fired once. At 2.7M it is a
    certainty, and a run that dies 97% of the way through a client is the expensive way to learn it.

    An unparseable confidence becomes 0.0 - the honest reading, since the model told us nothing
    usable about its own certainty - and the verdict itself still stands, because it was voted on
    separately and validated separately.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    # Confidence outside 0-1 is not confidence. Clamp rather than reject: the verdict is sound.
    return min(max(f, 0.0), 1.0)


def vote(votes, valid_keys, uncategorised):
    """2 of 3. Verdict and suggestion are voted SEPARATELY.

    Two models can agree a line is Incorrect and still disagree on where it belongs. That is an
    honest Incorrect with no agreed destination - the row an analyst should see - not a failure,
    and collapsing it would invent an agreement that does not exist.
    """
    got = [v for v in votes if v and v.get("verdict") in judge.VERDICTS]
    if not got:
        return None
    tally = {}
    for v in got:
        tally[v["verdict"]] = tally.get(v["verdict"], 0) + 1
    top = max(tally.values())
    winners = sorted(k for k, n in tally.items() if n == top)
    if top < 2:
        # Three different answers. Uncertain is a real answer and this is exactly when to use it.
        return {"verdict": "Uncertain", "agreement": "split", "confidence": 0.0,
                "basis": "no_evidence", "suggested_key": None,
                "rationale": "The three models returned three different verdicts; "
                             "no two agreed, so this is flagged for review rather than decided."}
    winner = winners[0]
    agreeing = [v for v in got if v["verdict"] == winner]
    # Suggestions are voted only among the models that agreed on the VERDICT - a suggestion from a
    # model that thought the line was Correct is not a vote for where an Incorrect line should go.
    keys = {}
    for v in agreeing:
        k = (str(v.get("suggested_key")).strip() if v.get("suggested_key") else None)
        if k and k in valid_keys and (uncategorised or valid_keys[k]):
            keys[k] = keys.get(k, 0) + 1
    best = max(keys.items(), key=lambda kv: kv[1])[0] if keys and max(keys.values()) >= 2 else None
    conf = round(sum(_conf(v.get("confidence")) for v in agreeing) / len(agreeing), 3)
    bases = [v.get("basis") for v in agreeing if v.get("basis") in judge.BASES]
    return {
        "verdict": winner,
        "agreement": f"{len(agreeing)}of{len(got)}",
        "confidence": conf,
        "basis": max(set(bases), key=bases.count) if bases else "no_evidence",
        "suggested_key": best,
        "rationale": next((v.get("rationale") for v in agreeing if v.get("rationale")), None),
    }


def ensure_column(qa, qcur, name, decl):
    """Add a qa_line column if it is not already there. COLUMNS, never rows."""
    qcur.execute("""SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME='qa_line' AND COLUMN_NAME=?""", name)
    if qcur.fetchone()[0]:
        return False
    qcur.execute(f"ALTER TABLE qa_line ADD {name} {decl}")
    qa.commit()
    return True


def responded(per_model):
    """How many of the three models actually ANSWERED this line.

    🔒 A DROPPED MODEL IS OTHERWISE INVISIBLE, AND 2of2 READS EXACTLY LIKE AGREEMENT.
    Measured 2026-08-18 by the concurrency test: at 24 workers 26 lines lost a model, at 32 it was
    36, at 48 it was 102 - against 2 at 16 workers. A throttled model that exhausts its retries
    drops out silently and the line is decided by a SMALLER JURY, but nothing in the output
    distinguished "two models agreed" from "one model never answered". At 2.7M lines that hollows
    out the jury while every check still reads OK.

    🔑 The data was always in NIM_1/2/3_VERDICT; what was missing was anything that SURFACED
    it. This is that column - jury health as a value on the row an analyst can filter, not a fact
    someone has to go looking for.
    """
    return sum(1 for v in per_model if v and v.get("verdict"))


def write(qa, qcur, run_id, results, keyed, used):
    """Write the votes and the consensus into qa_line. COLUMNS, never rows - the table stays at
    2,000 rows and one run_id, and VERDICT/CONFIDENCE/BASIS keep Claude's answer untouched."""
    sets = []
    for i in range(1, 4):
        sets += [f"NIM_{i}_MODEL=?", f"NIM_{i}_VERDICT=?", f"NIM_{i}_CONFIDENCE=?",
                 f"NIM_{i}_SUGGESTED_KEY=?"]
    sets += ["NIM_VERDICT=?", "NIM_CONFIDENCE=?", "NIM_BASIS=?", "NIM_AGREEMENT=?",
             "NIM_SUGGESTED_KEY=?"] + [f"NIM_SUGGESTED_CATEGORY_LVL_{i}=?" for i in range(5)] + \
            ["NIM_RATIONALE=?", "NIM_PROMPT_VERSION=?",
             "NIM_MODELS_RESPONDED=?", "NIM_JUDGED_AT=?"]
    ensure_column(qa, qcur, "NIM_MODELS_RESPONDED", "TINYINT NULL")
    # 🔒 A TOP-UP MAY ONLY IMPROVE A LINE, NEVER DEGRADE IT. The guard is in the WHERE clause and
    # not in Python, because it has to hold against a concurrent writer as well as a careless one:
    # if this row already carries THREE answering models, a later two-model result must not land on
    # it. Without this, re-running the top-up on a slow day would quietly undo the good day's work.
    # NULL is the first write of a generation and always proceeds.
    sql = (f"UPDATE qa_line SET {', '.join(sets)} WHERE qa_line_id=? AND run_id=? "
           f"AND (NIM_MODELS_RESPONDED IS NULL OR NIM_MODELS_RESPONDED <= ?)")
    now, rows = datetime.now(), []
    for line_id, (per_model, con) in results.items():
        args = []
        for i in range(3):
            v = per_model[i] or {}
            args += [used[i], v.get("verdict"),
                     # _conf, NOT bare float(): this is the SAME untrusted dict vote() reads,
                     # and the 2026-08-18 crash came back through this path. None stays None
                     # (the model never answered - a dropout, not a zero); prose becomes 0.0.
                     _conf(v["confidence"]) if v.get("confidence") is not None else None,
                     (str(v.get("suggested_key")).strip() if v.get("suggested_key") else None)]
        lv = keyed.get(con["suggested_key"]) if con.get("suggested_key") else None
        args += [con["verdict"], con["confidence"], con["basis"], con["agreement"],
                 con.get("suggested_key")] + list(lv or [None] * 5) + \
                [(con.get("rationale") or "")[:2000], judge.PROMPT_VERSION,
                 responded(per_model), now, line_id, run_id, responded(per_model)]
        rows.append(tuple(args))
    qcur.fast_executemany = False
    qcur.executemany(sql, rows)
    qa.commit()
    return len(rows)


def candidates(qcur):
    """The candidate keys, and whether each is inside the indirect programme. The scope guard is the
    same one apply_verdicts enforces: a line that already carries a category may be redirected only
    WITHIN scope, so a Clinical hand-off cannot be applied to it."""
    qcur.execute("SELECT category_key, in_scope, CATEGORY_LVL_0, CATEGORY_LVL_1, CATEGORY_LVL_2, "
                 "CATEGORY_LVL_3, CATEGORY_LVL_4 FROM qa_category WHERE client_code=?",
                 judge.MERGED_CLIENT)
    rows = qcur.fetchall()
    return {r[0]: bool(r[1]) for r in rows}, {r[0]: tuple(r[2:7]) for r in rows}


# How many extra attempts a DEAD model gets on the same batch before we accept a smaller jury.
# 🔑 The loss is per BATCH, not per line - ask_models returns {} for a model whose request failed,
# and tally_batch then gives every one of the 10 lines a None for it. Measured 2026-08-24 on the
# pilot: 16 failed requests, 160 hollowed-out votes, exactly one short answer. One extra attempt
# aimed at the failed model only is therefore worth 10 lines, not one.
REDRIVE_DEAD = 1


def ask_models(env, used, payload, tag="", redrive=REDRIVE_DEAD):
    """One batch to all three models CONCURRENTLY. Returns (per_model, dead).

    Sequential would multiply the wall clock by three for nothing - the endpoints are independent
    and `call` holds no shared state. No database handle is touched on these threads.
    """
    per_model = [None] * len(used)
    n_units = len(payload.get("units", []))
    # THE SET WE SENT. Coverage is measured against this, never against a count - see _one().
    sent_ids = {u["line_id"] for u in payload.get("units", [])}
    # line_id -> how many models actually answered ABOUT THAT LINE. Returned to the caller so a
    # run can report coverage as a rate rather than leaving it to a later audit to discover.
    covered = {lid: 0 for lid in sent_ids}
    cov_lock = threading.Lock()

    def _one(i, m):
        t0 = time.time()
        try:
            got = call(env, m, payload)
        except BaseException as exc:                  # noqa: BLE001 - reported, never swallowed
            print(f"      {tag}{m:38} FAILED  {exc}", flush=True)
            return
        per_model[i] = got
        # 🔒 DID WE GET BACK WHAT WE SENT? Nothing checked this until 2026-08-24, and it is a
        # SECOND, SILENT dropout path: tally_batch reads each line with pm.get(line_id), so a model
        # that answers the batch but omits some line_ids costs exactly those lines their vote - no
        # exception, no FAILED line, nothing in the output. One pilot line was lost this way and it
        # was found only by reconstructing the batches from the stored data. Rare is not never, and
        # at 278,000 batches rare is a daily event.
        # 🔒 COVERAGE, NOT COUNT - 2026-08-25, Finding 124.
        #
        # The check here USED to be `short = n_units - len(got)`: did the model send back as many
        # answers as we sent lines? It passes whenever the arithmetic works out, and the arithmetic
        # can work out while lines go unanswered. `parse()` returns {line_id: verdict}, so a model
        # that answers about line_ids WE NEVER SENT still produces the right length.
        #
        # That is not hypothetical. Measured on the pilot 2026-08-25: openai/gpt-oss-120b returned
        # 8, 8 and 7 verdicts for batches of 8, 8 and 7 - the count check saw nothing wrong - and
        # EIGHT of those 23 lines ended up with two votes instead of three. `2of2` in the data
        # reads exactly like agreement, so nothing downstream would have said otherwise either.
        #
        # A COUNT PROVES THE ARITHMETIC. ONLY THE ID SET PROVES THE COVERAGE. Same lesson as
        # "a self-consistency check cannot see a contaminated input" - it has to be measured
        # against something outside itself, and here that something is the ids we sent.
        got_ids = set(got)
        uncovered = sent_ids - got_ids          # lines this model never answered about
        alien = got_ids - sent_ids              # answers about lines we did not send
        with cov_lock:
            for lid in (got_ids & sent_ids):
                covered[lid] += 1

        flag = ""
        if uncovered:
            shown = ", ".join(str(x) for x in sorted(uncovered)[:5])
            more = f" +{len(uncovered) - 5}" if len(uncovered) > 5 else ""
            flag += (f"   ** {len(uncovered)}/{n_units} LINE(S) LOSE THIS MODEL: "
                     f"{shown}{more} **")
        if alien:
            # A model inventing line_ids is a different fault from a model going quiet, and it has
            # to be named separately or it hides inside the count. tally_batch already ignores
            # them - it reads by unit - so they cost nothing but they must not pass unseen.
            flag += f"   ** {len(alien)} answer(s) about line_ids NOT IN THIS BATCH - ignored **"
        print(f"      {tag}{m:38} {len(got):>4} verdicts   {time.time() - t0:>6.1f}s{flag}",
              flush=True)

    def _round(idxs):
        threads = [threading.Thread(target=_one, args=(i, used[i])) for i in idxs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    _round(range(len(used)))
    # RE-DRIVE THE DEAD MODEL, not the whole batch. The two that answered are already in hand and
    # re-asking them would spend three requests to recover one. `call` has its own retry ladder;
    # this sits ABOVE it, for the case where that ladder was exhausted - which on a slow day is
    # every one of these. The pause is deliberate: an immediate retry lands in the same rate-limit
    # window that just refused us.
    for attempt in range(redrive):
        idxs = [i for i, g in enumerate(per_model) if g is None]
        if not idxs:
            break
        print(f"      {tag}RE-DRIVING {len(idxs)} dead model(s), attempt {attempt + 1}/{redrive}",
              flush=True)
        time.sleep(BACKOFF * 2 * (attempt + 1))
        _round(idxs)

    dead = [m for m, g in zip(used, per_model) if g is None]

    # COVERAGE SUMMARY FOR THE BATCH. Reported at the point of failure rather than left for an
    # audit weeks later: at 2.78M lines a 1% two-model rate is ~30,600 lines carrying a verdict
    # that reads like agreement and is not one.
    thin = sorted(lid for lid, n in covered.items() if n < len(used))
    if thin and not dead:
        # `dead` already prints its own warning, and a dead model explains its own gap. This line
        # is for the case where every model ANSWERED and lines were still left short - which is
        # the failure the count check could not see.
        print(f"      {tag}** COVERAGE: {len(thin)}/{n_units} line(s) got fewer than "
              f"{len(used)} votes although no model failed **", flush=True)
    return [g if g is not None else {} for g in per_model], dead, covered


def tally_batch(units, per_model, valid, uncategorised):
    results, missing = {}, 0
    for u in units:
        lid = u["line_id"]
        votes = [pm.get(lid) for pm in per_model]
        if not any(votes):
            missing += 1
            continue
        con = vote(votes, valid, uncategorised)
        if con:
            results[lid] = (votes, con)
    return results, missing


def judge_client(qa, qcur, run_id, client, env, limit, uncategorised, batch=None, workers=1,
                 topup=False, vendor=None, quiet=False):
    """Judge up to `limit` lines for one client. Returns lines written, or -1 on a total outage.

    BATCHES RUN CONCURRENTLY, and that is the difference between a 3.5-hour run and a 40-minute
    one. Measured 2026-08-14: google/gemma-4-31b-it took 160s for 25 lines - 6.4s per line - so
    2,000 lines through three models one batch at a time is three and a half hours of mostly
    waiting on the network. Batch size and worker count are separate knobs on purpose:
      * BATCH is bounded by max_tokens and by the slowest model's patience. A reasoning model
        spends output tokens thinking, so nvidia/nemotron-3-super-120b-a12b timed out at 25 lines
        while answering 8 comfortably. Too large does not error - it TRUNCATES.
      * WORKERS is bounded by the free tier's ~40 requests/minute. Each worker holds three
        requests open at once, so workers x 3 is the concurrency the endpoint actually sees.
    """
    used = models(env)
    if len(used) != 3:
        print(f"  WARNING: {len(used)} model(s) configured, not 3 - a 2-of-3 vote needs three",
              flush=True)
    payload = judge.emit_batch(qcur, run_id, client, limit, None, uncategorised=uncategorised,
                               rejudge=True, topup=topup, vendor=vendor)
    units = payload.get("units", [])
    if not units:
        # In queue mode this is the NORMAL case on a resume - most vendors are already done - so
        # it must not print 29,469 times.
        if not quiet:
            print(f"  {client}: nothing to judge", flush=True)
        return 0
    valid, keyed = candidates(qcur)

    size = batch or len(units)
    chunks = [units[i:i + size] for i in range(0, len(units), size)]
    if not quiet:
        print(f"  {client}: {len(units)} lines x {len(used)} models   "
              f"{len(chunks)} batches of <={size}, {workers} at a time", flush=True)

    # ONE LOCK, AND EVERY DATABASE CALL IS INSIDE IT. pyodbc connections are not thread-safe, and
    # a torn write here would be a partial generation - the failure this project has already paid
    # for. The HTTP waiting is what runs concurrently; the writing is serialised.
    lock = threading.Lock()
    t_start = time.time()
    state = {"written": 0, "missing": 0, "outages": 0, "tally": {},
             # COVERAGE, run-level. thin = lines that got fewer votes than there are
             # models. Reported as a RATE at the end so it cannot cry wolf on one line
             # and cannot hide 30,000 of them either.
             "thin": 0, "seen": 0}

    def run_chunk(idx, chunk):
        p = dict(payload)
        p["units"] = chunk
        tag = f"[{idx + 1}/{len(chunks)}] "
        per_model, dead, covered = ask_models(env, used, p, tag)
        if len(dead) == len(used):
            print(f"      {tag}all models failed - nothing written for these {len(chunk)} lines",
                  flush=True)
            with lock:
                state["outages"] += 1
            return
        if dead:
            # A silent two-model batch would still be written as a consensus and read as agreement
            # when one model never answered. Say it every time.
            print(f"      {tag}WARNING: no answer from {', '.join(dead)}", flush=True)
        results, missing = tally_batch(chunk, per_model, valid, uncategorised)
        with lock:
            state["seen"] += len(covered)
            state["thin"] += sum(1 for n in covered.values() if n < len(used))
            n = write(qa, qcur, run_id, results, keyed, (used + [None, None, None])[:3])
            state["written"] += n
            state["missing"] += missing
            for _, con in results.values():
                state["tally"][con["agreement"]] = state["tally"].get(con["agreement"], 0) + 1
            el = time.time() - t_start
            print(f"      {tag}wrote {n}   running total {state['written']}/{len(units)}   "
                  f"{el / 60:.1f} min   {state['written'] / el * 60:.0f} lines/min", flush=True)

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda a: run_chunk(*a), enumerate(chunks)))

    # In queue mode judge_queue already prints one line per vendor carrying the same numbers, and
    # this would fire TWICE per vendor across 29,469 of them. The per-MODEL lines above are kept
    # either way - silent jury dropout is a defect this project has already paid for.
    _say = print if not quiet else (lambda *a, **k: None)
    # 🔒 SILENT WHEN FINE, NEVER SILENT WHEN NOT. In queue mode the per-vendor summary is
    # suppressed - it would print 29,469 times - but a THIN batch must still surface, because the
    # whole point of Finding 124 is that this failure is invisible unless something says so.
    if quiet and state["thin"]:
        print(f"    ** {client}: {state['thin']}/{state['seen']} line(s) got fewer than "
              f"{len(used)} votes - re-run with --topup **", flush=True)
    _say(f"    {client}: wrote {state['written']} lines in {(time.time() - t_start) / 60:.1f} min"
          f"   agreement: " + "  ".join(f"{k} {v}" for k, v in sorted(state["tally"].items()))
          + (f"   ({state['missing']} lines no model answered)" if state["missing"] else "")
          + (f"   ** {state['outages']} batch(es) lost to a total outage - RE-RUN TO FILL THEM"
             if state["outages"] else "")
          # COVERAGE AS A RATE, every run. Stated whether it is good or bad: a check that only
          # speaks up when it is unhappy is a check nobody knows is running.
          + (f"   coverage: {state['seen'] - state['thin']}/{state['seen']} lines got all "
             f"{len(used)} votes"
             + (f"  ** {state['thin']} THIN - re-run with --topup **" if state["thin"] else "")
             if state["seen"] else ""), flush=True)
    # -1 only if EVERY batch died. A partial outage still made progress, and a re-run picks up the
    # gap because selection is on NIM_VERDICT IS NULL.
    return state["written"] if state["written"] else -1


def judge_queue(qa, qcur, run_id, client, env, batch, workers, topup=False, top=None):
    """Judge one client VENDOR BY VENDOR, in the spend queue's rank order. Stage 3, 2026-08-25.

    THE ORDER IS THE POINT. 2,786,018 lines at ~50 lines/min is ~40 days, so what gets judged
    FIRST decides what we can act on if the run is stopped early. Sameer, 2026-08-17: the rollup is
    per vendor name, largest spends first; SIGNED, settled 2026-08-21 on the full population.

    ⚠️ IT IS NOT A PREDICTION ABOUT WHERE THE ERRORS ARE. Sameer, 2026-08-25: "we dont know where
    the miscategorising is thats our assumption the judge will decide." The order decides which
    findings are worth ACTING ON, not where they are.

    A VENDOR IS JUDGED WHOLE - both passes, categorised and uncategorised, before the next vendor
    begins. Half a vendor's answer is not an answer: you cannot tell an account manager anything
    about a supplier you have only partly looked at.

    THE QUEUE SUPPLIES THE ORDER AND NOTHING ELSE. What still needs judging is decided by
    `NIM_VERDICT IS NULL` inside emit_batch, against qa_line, every time - never by this table's
    LINES_UNJUDGED, which is a snapshot taken when the queue was built. That is deliberate: a queue
    that believed its own record of progress would be a generated artefact used as its own input,
    which is Finding 93 wearing different clothes. It also means a resume is automatic and a
    rebuilt queue cannot lose work.
    """
    qcur.execute("""SELECT VENDOR_RANK, SUPPLIER_NAME, LINES_TOTAL, SPEND_SIGNED,
                           DATA_QUALITY_FLAG, HAS_NO_EVIDENCE
                    FROM qa_vendor_queue WHERE RUN_ID=? AND CLIENT_CODE=?
                    ORDER BY VENDOR_RANK""", run_id, client)
    vendors = qcur.fetchall()
    if not vendors:
        raise SystemExit(
            f"\n  STOP - no vendor queue for {client} on run {run_id}.\n"
            f"  Build it first:  python pipeline/vendor_queue.py [--production]\n")

    if top:
        vendors = vendors[:top]
    print(f"\n  {client}: {len(vendors):,} vendors in the queue"
          f"{f' (top {top} only - the STOP AND LOOK slice)' if top else ''}", flush=True)

    t0 = time.time()
    done_v = judged = skipped = 0
    for rank, name, lines, spend, flag, no_ev in vendors:
        selector = judge.NO_VENDOR_NAME if name is None else name
        shown = "(no vendor name)" if name is None else name

        # BOTH PASSES, so the vendor is finished before the next one starts.
        n = 0
        for uncat in (False, True):
            n += max(0, judge_client(qa, qcur, run_id, client, env, None, uncat,
                                     batch=batch, workers=workers, topup=topup,
                                     vendor=selector, quiet=True))
        done_v += 1
        if not n:
            skipped += 1
            continue
        judged += n
        note = f"  [{flag}]" if flag else ""
        if no_ev:
            # Said in advance rather than discovered afterwards: no vendor AND no usable
            # description means no evidence exists, so the hierarchy resolves these to Uncertain.
            note += f"  ({no_ev:,} lines have no evidence - Uncertain is the expected verdict)"
        rate = judged / max(1e-9, (time.time() - t0) / 60.0)
        print(f"    #{rank:<6} {shown[:38]:<38} {n:>6,} judged  "
              f"{spend or 0:>15,.0f}  [{judged:,} lines, {rate:.0f}/min]{note}", flush=True)

    el = (time.time() - t0) / 60.0
    print(f"  {client}: {judged:,} lines judged across {done_v - skipped:,} vendors "
          f"in {el:.1f} min ({skipped:,} already complete)", flush=True)
    return judged


def judge_global(qa, qcur, run_id, env, batch, workers, topup=False, top=None):
    """Judge ALL FOUR HOSPITALS in one spend order - the largest supplier anywhere goes first.

    Sameer, 2026-08-25: "cant we start juding largest supplier spend first? irrespective of the
    hospitals ... since we have the spend weighted approach." So the ATO's $943m at Northern is
    judged before Melbourne's largest supplier, even though Melbourne is the bigger hospital.

    🔒 THE JUDGED UNIT IS UNCHANGED: still (client, vendor), still judged against THAT CLIENT'S OWN
    taxonomy. Only the ORDER crosses hospitals. emit_batch reloads the client's candidate list on
    every call and is passed the client from the queue row, so hopping between hospitals cannot mix
    yardsticks - key 379 is Cheese at Melbourne and Facilities Management at Northern, and a global
    order must never become a shared candidate list.

    ⚠️ A GLOBAL ORDER UNDER-SERVES THE SMALLEST HOSPITAL EARLY. Measured on production 2026-08-25,
    global top 100: northern 86.2% of its signed spend, melbourne 52.9%, western 45.1%, SYDNEY
    ADVENTIST 32.7%. It evens out by the top 500 (every hospital above 61.9%), so it matters only
    if the run is stopped early - and Sydney Adventist is a client too. Use --client for a
    per-hospital order when that matters more.
    """
    qcur.execute("""SELECT GLOBAL_RANK, CLIENT_CODE, SUPPLIER_NAME, LINES_TOTAL, SPEND_SIGNED,
                           DATA_QUALITY_FLAG, HAS_NO_EVIDENCE
                    FROM qa_vendor_queue WHERE RUN_ID=? AND GLOBAL_RANK IS NOT NULL
                    ORDER BY GLOBAL_RANK""", run_id)
    vendors = qcur.fetchall()
    if not vendors:
        raise SystemExit(
            f"\n  STOP - no vendor queue for run {run_id}, or GLOBAL_RANK is not populated.\n"
            f"  Build it first:  python pipeline/vendor_queue.py [--production]\n")
    if top:
        vendors = vendors[:top]

    spread = {}
    for v in vendors:
        spread[v[1]] = spread.get(v[1], 0) + 1
    print(f"\n  GLOBAL spend order: {len(vendors):,} vendors"
          f"{f' (top {top} - the STOP AND LOOK slice)' if top else ''}", flush=True)
    print("    across " + " · ".join(f"{k} {n:,}" for k, n in sorted(spread.items())), flush=True)

    t0 = time.time()
    judged = skipped = 0
    for rank, client, name, lines, spend, flag, no_ev in vendors:
        selector = judge.NO_VENDOR_NAME if name is None else name
        shown = "(no vendor name)" if name is None else name
        n = 0
        for uncat in (False, True):
            n += max(0, judge_client(qa, qcur, run_id, client, env, None, uncat,
                                     batch=batch, workers=workers, topup=topup,
                                     vendor=selector, quiet=True))
        if not n:
            skipped += 1
            continue
        judged += n
        note = f"  [{flag}]" if flag else ""
        if no_ev:
            note += f"  ({no_ev:,} lines have no evidence - Uncertain is the expected verdict)"
        rate = judged / max(1e-9, (time.time() - t0) / 60.0)
        print(f"    #{rank:<6} {client:<18} {shown[:32]:<32} {n:>6,} judged  "
              f"{spend or 0:>15,.0f}  [{judged:,} lines, {rate:.0f}/min]{note}", flush=True)

    el = (time.time() - t0) / 60.0
    print(f"  GLOBAL: {judged:,} lines judged in {el:.1f} min "
          f"({skipped:,} vendors already complete)", flush=True)
    return judged


def report(qcur, run_id):
    print(f"\n{'=' * 88}\nNIM vs CLAUDE - run {run_id}\n{'=' * 88}", flush=True)
    qcur.execute("""SELECT client_code, COUNT(*),
            SUM(CASE WHEN nim_verdict IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN nim_agreement='3of3' THEN 1 ELSE 0 END),
            SUM(CASE WHEN nim_agreement='2of3' THEN 1 ELSE 0 END),
            SUM(CASE WHEN nim_agreement='split' THEN 1 ELSE 0 END)
        FROM qa_line WHERE run_id=? GROUP BY client_code ORDER BY 1""", run_id)
    print(f"  {'client':20} {'lines':>7} {'judged':>7} {'3of3':>7} {'2of3':>7} {'split':>7}", flush=True)
    print("  " + "-" * 62, flush=True)
    for r in qcur.fetchall():
        print(f"  {r[0]:20} {r[1]:>7,} {r[2]:>7,} {r[3]:>7,} {r[4]:>7,} {r[5]:>7,}", flush=True)
    print("\n  'split' is the review queue - three models, three answers. It is NOT a failure;", flush=True)
    print("  it is the measurement of how hard the task actually is, which we have never had.", flush=True)

    qcur.execute("""SELECT verdict, nim_verdict, COUNT(*) FROM qa_line
        WHERE run_id=? AND verdict IS NOT NULL AND nim_verdict IS NOT NULL
          AND basis NOT LIKE 'deterministic%'
        GROUP BY verdict, nim_verdict ORDER BY 3 DESC""", run_id)
    rows = qcur.fetchall()
    if rows:
        same = sum(r[2] for r in rows if r[0] == r[1])
        tot = sum(r[2] for r in rows)
        print(f"\n  CLAUDE vs NIM on the same {tot:,} lines - agree on {same:,} ({same / tot:.1%})", flush=True)
        print(f"    {'Claude':12} {'NIM':12} {'lines':>8}", flush=True)
        for a, b, n in rows:
            print(f"    {a:12} {b:12} {n:>8,}" + ("" if a == b else "   <- disagree"), flush=True)
        print("\n  Agreement here is NOT accuracy. Both can be wrong the same way; this says how", flush=True)
        print("  far the model swap moves the answer, which is the question the re-run was for.", flush=True)

    qcur.execute("""SELECT COUNT(*) FROM qa_line
        WHERE run_id=? AND nim_suggested_category_lvl_0='Clinical'""", run_id)
    print(f"\n  handed to the clinical project: {qcur.fetchone()[0]:,}"
          f"   (v3 baseline was 167 of 500 uncategorised - a much higher rate means the models")
    print("   are using the hand-off as a dumping ground rather than as a finding)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client")
    ap.add_argument("--run-id")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--all", action="store_true",
                    help="EVERY unjudged line for the client - no cap. Until 2026-08-24 this "
                         "silently meant the first 100,000, which is 11%% of Melbourne.")
    ap.add_argument("--production", action="store_true",
                    help="⚠️ judge PI_Medical_QA_Indirect, the real 2,786,018-line run. Without "
                         "this every connection is the 2,000-row pilot, which is the safe default "
                         "on purpose.")
    ap.add_argument("--batch", type=int, default=10,
                    help="lines per request. Bounded by max_tokens and by the slowest model - "
                         "nemotron is a reasoning model and timed out at 25")
    ap.add_argument("--workers", type=int, default=4,
                    help="batches in flight at once. Each holds 3 requests open, so this x3 is "
                         "the concurrency the free tier's ~40 req/min actually sees")
    ap.add_argument("--uncategorised", action="store_true")
    ap.add_argument("--topup", action="store_true",
                    help="ALSO re-offer lines that fewer than 3 models answered. Without this a "
                         "hollowed-out jury is permanent: those lines hold a NIM_VERDICT, so the "
                         "normal `NIM_VERDICT IS NULL` resume skips them forever and the only "
                         "repair is --reset. write() refuses to lower NIM_MODELS_RESPONDED, so a "
                         "top-up can improve a line and can never make it worse.")
    ap.add_argument("--report", action="store_true")
    # 🔒 STAGE 3, 2026-08-25 - CONSUME THE VENDOR SPEND QUEUE. Judges the client one vendor at a
    # time, largest signed spend first, BOTH passes per vendor so a vendor is finished before the
    # next begins. Without it the old behaviour is unchanged: the whole client in one selection.
    ap.add_argument("--queue", action="store_true",
                    help="judge in vendor spend order from qa_vendor_queue, a vendor at a time. "
                         "WITHOUT --client this is the GLOBAL order - all four hospitals in one "
                         "queue, largest supplier spend anywhere first. WITH --client it is that "
                         "hospital's own order")
    ap.add_argument("--top", type=int, default=None,
                    help="with --queue: stop after the top N vendors. THE STOP AND LOOK SLICE - "
                         "100 vendors carry 68-93%% of signed spend, so --top 100 buys most of "
                         "the value of the run in a fraction of the time, and then you look "
                         "before committing the rest")
    args = ap.parse_args()

    env = load_env()
    qa = connect_qa(pilot=not args.production, production=args.production, env=env)
    qcur = qa.cursor()
    run_id = args.run_id
    if not run_id:
        qcur.execute("SELECT TOP 1 run_id FROM qa_run ORDER BY loaded_at DESC")
        row = qcur.fetchone()
        if not row:
            raise SystemExit("  no runs in qa_run")
        run_id = row[0]
    # THE ONE-GENERATION INVARIANT, checked before anything is written. Sameer, 2026-08-14: more
    # than one generation in this table means duplication, and every figure taken from it
    # double-counts. ⚠️ This is a check on the number of RUN_IDs, never on the number of rows -
    # 2,000 is a fact about the pilot and production holds 2,786,018.
    qcur.execute("SELECT COUNT(DISTINCT run_id), COUNT(*) FROM qa_line")
    nrun, nrow = qcur.fetchone()
    if nrun != 1:
        raise SystemExit(f"  qa_line holds {nrun} run_ids - expected exactly 1. STOP.")
    print(f"run {run_id}   qa_line {nrow:,} rows / {nrun} run_id   models: {', '.join(models(env))}")

    if args.report:
        report(qcur, run_id)
        qa.close()
        return 0
    # 🔒 GLOBAL SPEND ORDER, 2026-08-25. --queue with NO --client walks all four hospitals in one
    # order, largest supplier spend anywhere first. --queue WITH --client keeps the per-hospital
    # order. Both are sorts of the same rows; which to stop early on is a decision for the day.
    if args.queue and not args.client:
        judge_global(qa, qcur, run_id, env, batch=args.batch, workers=args.workers,
                     topup=args.topup, top=args.top)
        qcur.execute("SELECT COUNT(DISTINCT run_id), COUNT(*) FROM qa_line")
        nrun2, nrow2 = qcur.fetchone()
        if (nrun2, nrow2) != (nrun, nrow):
            raise SystemExit(f"  ** qa_line CHANGED SHAPE during the run: "
                             f"{nrun}/{nrow:,} -> {nrun2}/{nrow2:,} **")
        qa.close()
        return 0

    if not args.client:
        raise SystemExit("  --client is required (or use --queue alone for the GLOBAL order)")

    if args.queue:
        judge_queue(qa, qcur, run_id, args.client, env, batch=args.batch, workers=args.workers,
                    topup=args.topup, top=args.top)
        qcur.execute("SELECT COUNT(DISTINCT run_id), COUNT(*) FROM qa_line")
        nrun2, nrow2 = qcur.fetchone()
        if (nrun2, nrow2) != (nrun, nrow):
            raise SystemExit(f"  ** qa_line CHANGED SHAPE during the run: "
                             f"{nrun}/{nrow:,} -> {nrun2}/{nrow2:,} **")
        qa.close()
        return 0
    if args.top:
        raise SystemExit("  --top only means something with --queue")
    # ONE REQUEST PER BATCH, NOT ONE PER CLIENT. `max_tokens` is 8,192 and each line costs a
    # verdict, a confidence, a key and a sentence of rationale - so a 500-line prompt does not
    # error, it TRUNCATES, and the lines past the cut are silently missing.
    # The run is resumable either way: selection is on NIM_VERDICT IS NULL, so anything already
    # written is skipped and an interrupted run continues exactly where it stopped.
    judge_client(qa, qcur, run_id, args.client, env,
                 None if args.all else args.limit, args.uncategorised,
                 batch=args.batch, workers=args.workers, topup=args.topup)

    qcur.execute("SELECT COUNT(DISTINCT run_id), COUNT(*) FROM qa_line")
    nrun2, nrow2 = qcur.fetchone()
    print(f"  qa_line after: {nrow2:,} rows / {nrun2} run_id"
          + ("   UNCHANGED" if (nrow2, nrun2) == (nrow, nrun) else "   <- CHANGED, investigate"))
    qa.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
