# Owner-authorized production acceptance and independent backup

PR #80 merged on 2 November after owner approval. This marker triggers GET-only
live acceptance and private Drive backup; it cannot trigger the media publisher.
No Meta POST, YouTube insert, notification send, state/claim overwrite or permission
change is performed. Existing DRIVE_TOKEN_JSON is used; no new secret requested.

Backup includes the full authoritative publication ledger and last complete
analytics history. Each ZIP is content-addressed, immutable and checked by an
actual download plus isolated restoration. Existing identical data is reused.
The destination must have only its owner's permission. No retention deletion,
sharing, paid resources or automatic production restore. Drive quota is checked
before creating a backup. A failed/ambiguous upload is reconciled by its hash on
the next run; it is not blindly retried in the same execution.

Backup runs after completed normal publisher and nightly analytics workflows,
with a daily fallback at 23:50 TRT. Set the workflow disabled to pause backups;
keep existing backup files. Missing credentials or remote integrity mismatch
fails the backup and preserves a redacted receipt. Code is not live acceptance.

Restore: download one recovery ZIP and call durable_backup.restore_isolated on
its bytes into a new directory, inspect source/intent/post records, then obtain
explicit production-recovery approval before modifying the publisher state.
No expiration is configured for Drive backups; retention depends on account
availability, free Drive quota and the owner not deleting the destination.

Initial run 41515910390: backup failed with missing_drive_credentials; no Drive
write occurred. Acceptance setup failed because the new ubuntu-latest runner did
not include FFmpeg. The safe repair installs FFmpeg/FFprobe like the normal
publisher, then repeats only GET/local acceptance. Credential access is not
repaired by this change. Provider publishing remains untouched.

Final live GET/local acceptance job 125520221690 in run 41516183167 passed:
13 stock platform rows, 43 existing post IDs confirmed, 4811 engagement records,
13/13 follower counters and three quality samples from a real 180-second source.
No publishing was attempted. The overall run was red solely because its separate
direct Drive backup job lacked credentials.

Connected Drive fallback was completed without moving secrets: private folder
1q--FLaDauwGGierN95PDBBAOhU_f3jgh owner-only permissions verified, recovery file
1CTqkOEYGFrMdQ_6pWBmU8eXFEIThh64N uploaded and actually downloaded again.
SHA256 1ddd55455fcbaea540c0c4abe75d3eba26b27409158bc0d6ff79b05ed12c4c04
matched; isolated restore verified 1005 publication entries and 19537 analytics
rows. Source state run 41510394181, analytics run 41433751338. This is a snapshot
of those source runs, not a claim that every possible later measurement is saved.

New scheduled task creation hit the plan's five-task limit. Backup work was added
to the existing hourly Meta watch task 6ae5d8a0392481918f750987d8a5f5a9,
preserving its monitoring instructions and schedule. It copies only new artifacts
through the connected Drive tools, deduplicates and verifies downloads. Its next
automatic execution has not yet been accepted. The credential-less direct runner
backup is now opt-in via DURABLE_DRIVE_BACKUP_ENABLED=true; no repeated known
missing-credential jobs and no new secret setup are required for the fallback.
