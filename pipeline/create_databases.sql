/* ===========================================================================
   Medical QA (Indirects) — create the QA databases and grant scoped access
   ---------------------------------------------------------------------------
   Run as an admin login (sysadmin, or dbcreator + securityadmin).
   The [Claude] login has NO server roles and cannot run this.

   Server verified 2026-07-30:
     SQL Server 2022 (16.0.1000.6), Developer Edition, default instance
     Server collation SQL_Latin1_General_CP1_CI_AS — matches every client DB

   SAFE TO RE-RUN. Every step is guarded; running it twice changes nothing.
   The PILOT already exists (Sameer created it via SSMS on 2026-07-30), so on
   this server section 1 will create only production and skip the pilot.

   In SSMS: open this file, check the toolbar says the right server, then
   Execute (F5). Do not run it a chunk at a time — the GO batches matter.

   ---------------------------------------------------------------------------
   REWRITTEN 2026-08-18, and DO NOT run any earlier copy of this file.

   1. THE NAMES WERE WRONG. Until today this script created
      PI_Hospital_Indirects_QA and PI_Hospital_Indirects_QA_Pilot. Neither is
      the database in use. The live pilot is PI_Medical_QA_Indirect_Pilot, and
      .env points at it. Running the old script would have created two empty
      databases that nothing references, alongside the real one — a naming
      scheme abandoned before the pilot was built and never cleaned up here.

   2. SECTION 2's REASONING HAD EXPIRED. It justified SIMPLE recovery with
      "nothing here is a system of record — every table is rebuildable from
      the client views by re-running the pipeline". That was TRUE while every
      column was a deterministic derivation of client data. IT IS NO LONGER
      TRUE: qa_line now holds three-model jury verdicts that cost ~15.5 days
      of continuous inference to produce at full scale, and no amount of
      re-reading the client views reproduces them. See section 2a.
   =========================================================================== */


/* --- 1. Create the databases ---------------------------------------------
   Collation is set explicitly rather than inherited. It already matches the
   server default, but if that default is ever changed these must still line
   up with the client databases or cross-database string joins fail with a
   collation conflict.

   Production sizing, measured 2026-08-18 rather than guessed: the pilot's
   qa_line is 8.64 MB at 2,000 rows (~4,530 bytes/row). Scaled to 2,764,531
   in-scope lines that is roughly 12 GB of data, plus indexes. Still not
   pre-sizing the files — that is an order of magnitude from a 2,000-row
   rule-led sample, and it should be re-measured after the FIRST client is
   loaded, when it can be a real number instead of an extrapolation.        */

IF DB_ID('PI_Medical_QA_Indirect') IS NULL
BEGIN
    CREATE DATABASE PI_Medical_QA_Indirect
        COLLATE SQL_Latin1_General_CP1_CI_AS;
    PRINT 'Created PI_Medical_QA_Indirect';
END
ELSE PRINT 'PI_Medical_QA_Indirect already exists - skipped';
GO

IF DB_ID('PI_Medical_QA_Indirect_Pilot') IS NULL
BEGIN
    CREATE DATABASE PI_Medical_QA_Indirect_Pilot
        COLLATE SQL_Latin1_General_CP1_CI_AS;
    PRINT 'Created PI_Medical_QA_Indirect_Pilot';
END
ELSE PRINT 'PI_Medical_QA_Indirect_Pilot already exists - skipped';
GO


/* --- 2. Recovery model: SIMPLE -------------------------------------------
   This project bulk-loads millions of rows. Under FULL recovery every insert
   is retained in the transaction log until a log backup runs; with no log
   backup scheduled the log grows until the volume fills. SIMPLE truncates on
   checkpoint.

   SIMPLE means NO point-in-time recovery. That is an accepted trade, but it
   is only acceptable alongside section 2a — read it before running this.    */

ALTER DATABASE PI_Medical_QA_Indirect       SET RECOVERY SIMPLE;
ALTER DATABASE PI_Medical_QA_Indirect_Pilot SET RECOVERY SIMPLE;
GO


/* --- 2a. BACKUPS. Required on production. Not optional. -------------------
   Decided by Sameer 2026-08-18: one full backup after the load and before
   judging starts, then NIGHTLY through the judging run.

   WHY THIS CHANGED. The old comment here said point-in-time recovery would
   only be "protecting a derived copy". At pilot scale that is right — the
   whole 2,000-row pilot regenerates in about 16 minutes. At production it is
   wrong twice over:

     the extract   2,764,531 lines, hours to load (never yet timed)
     the verdicts  ~15.5 days of continuous three-model judging

   The verdicts are NOT derivable from the client views. They are the output
   of hosted models that are not deterministic — re-running does not even
   reproduce the same answers, measured at 91.5% self-consistency. Lose the
   table and you do not "re-derive" it, you spend another fortnight.

   AND THE LIKELY CAUSE IS US, NOT HARDWARE. Every one of these has already
   happened at pilot scale, where it cost minutes:

     run_generation.py --reset   one flag; NULLs every NIM_* column on every
                                 row in a single unqualified UPDATE
     an aborted run              2026-08-04: 528,091 rows left across two
                                 run_ids by a killed rebuild
     an experiment on the live   2026-08-18: a concurrency test contaminated
       generation                the live table and dropped the score to 41.2%
     a schema change             [Claude] holds db_ddladmin by design

   Restoring turns "re-judge for 15 days" into "restore and resume":
   nim_judge selects on NIM_VERDICT IS NULL, so it continues from wherever
   the restored copy stopped.

   SIZE, measured: ~12 GB of data, so a full backup is roughly the same
   again — about 25 GB all in. Cheap enough that the trade-off disappears.

   Schedule this in the server's maintenance plan; it is deliberately NOT in
   this script, because a backup destination is the DBA's decision and a
   hard-coded path here would rot. Sketch:

     BACKUP DATABASE PI_Medical_QA_Indirect
       TO DISK = N'<backup path>\PI_Medical_QA_Indirect_afterload.bak'
       WITH INIT, COMPRESSION, STATS = 5;
                                                                            */


/* --- 3. Grant [Claude] scoped access, in these databases only -------------
   db_ddladmin   - create/alter the QA tables
   db_datawriter - load data
   db_datareader - read it back

   Deliberately NOT granted: db_owner, and nothing at server level. Confirmed
   again by Sameer 2026-08-18 for production, with the reason now sharper
   than when the pilot was set up: db_owner can DROP the database, and once
   production holds a completed run that is a fortnight of compute behind a
   single command. The three roles above cover every table, column and row
   operation the pipeline performs. The ONLY thing they cannot do is
   ALTER DATABASE — which is section 2 above, run once by an admin.

   The four client databases and the MSD stay read-only. That separation is
   the whole reason for creating separate databases rather than widening
   rights on existing ones.                                                 */

USE PI_Medical_QA_Indirect;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'Claude')
    CREATE USER [Claude] FOR LOGIN [Claude];
GO
IF IS_ROLEMEMBER('db_ddladmin',   'Claude') = 0 ALTER ROLE db_ddladmin   ADD MEMBER [Claude];
IF IS_ROLEMEMBER('db_datawriter', 'Claude') = 0 ALTER ROLE db_datawriter ADD MEMBER [Claude];
IF IS_ROLEMEMBER('db_datareader', 'Claude') = 0 ALTER ROLE db_datareader ADD MEMBER [Claude];
GO

USE PI_Medical_QA_Indirect_Pilot;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'Claude')
    CREATE USER [Claude] FOR LOGIN [Claude];
GO
IF IS_ROLEMEMBER('db_ddladmin',   'Claude') = 0 ALTER ROLE db_ddladmin   ADD MEMBER [Claude];
IF IS_ROLEMEMBER('db_datawriter', 'Claude') = 0 ALTER ROLE db_datawriter ADD MEMBER [Claude];
IF IS_ROLEMEMBER('db_datareader', 'Claude') = 0 ALTER ROLE db_datareader ADD MEMBER [Claude];
GO


/* --- 4. Verify ------------------------------------------------------------
   Expect 6 rows: 2 databases x 3 roles, all with is_member = 1, and both
   databases reading recovery_model_desc = SIMPLE.                          */

SELECT name, state_desc, recovery_model_desc, collation_name
FROM   sys.databases
WHERE  name IN ('PI_Medical_QA_Indirect', 'PI_Medical_QA_Indirect_Pilot');
GO

USE PI_Medical_QA_Indirect;
SELECT DB_NAME() AS database_name, 'db_ddladmin'   AS role, IS_ROLEMEMBER('db_ddladmin',   'Claude') AS is_member
UNION ALL SELECT DB_NAME(), 'db_datawriter', IS_ROLEMEMBER('db_datawriter', 'Claude')
UNION ALL SELECT DB_NAME(), 'db_datareader', IS_ROLEMEMBER('db_datareader', 'Claude');
GO

USE PI_Medical_QA_Indirect_Pilot;
SELECT DB_NAME() AS database_name, 'db_ddladmin'   AS role, IS_ROLEMEMBER('db_ddladmin',   'Claude') AS is_member
UNION ALL SELECT DB_NAME(), 'db_datawriter', IS_ROLEMEMBER('db_datawriter', 'Claude')
UNION ALL SELECT DB_NAME(), 'db_datareader', IS_ROLEMEMBER('db_datareader', 'Claude');
GO


/* --- 5. AFTER RUNNING THIS -----------------------------------------------
   Creating the database does NOT make production work, and this is worth
   stating here so it is not discovered later:

     pipeline/schema.sql currently defines 54 qa_line columns. The LIVE pilot
     table has 84. Twenty-six of the missing thirty — the whole NIM_* jury
     block — have no DDL anywhere in the repo; they were added by hand.
     apply_schema.py against a fresh production database therefore produces a
     qa_line that nim_judge.py CANNOT WRITE TO.

   So the order is: fix schema.sql first, then run this, then apply the
   schema and verify the column count matches the pilot's 84 name-by-name.

   QA_DATABASE in .env stays BLANK until that verification passes. Nothing in
   the pipeline reads it yet in any case — every call site is pinned to
   pilot=True — which is a separate piece of work, not an oversight.        */
