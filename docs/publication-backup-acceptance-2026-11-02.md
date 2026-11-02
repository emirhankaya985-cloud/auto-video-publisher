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
