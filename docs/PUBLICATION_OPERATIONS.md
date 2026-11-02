# Publication operations

The normal publisher now prepares a separate read-only report after its Meta and
YouTube steps, including partial failures. It never updates done/uncertain state,
changes source identity or retries an upload. Current-run Meta done IDs are
checked in the configured account video history. Delayed visibility or GET errors
produce unverified and fail the new step, while always() result uploads continue.
YouTube verification remains in the existing channel-bound bridge.

Film and ToonZone reports group observed ledger parts per route and platform.
ToonZone expects four parts per observed episode; film gaps are detected up to
the highest observed part. This does not claim complete source inventory, movie
length or missing episodes outside the observed ledger. Multiple distinct post IDs
for the same part are flagged, never automatically merged or deleted. Existing
publisher order gates remain authoritative; this report is diagnostic.

The lossless ZIP includes all state fields (including YouTube, intents and future
fields) plus a SHA-256/byte-count manifest. It is validated before upload.
Restore validates before writing and refuses an existing destination:

    python publication_operations.py --restore backup.zip --destination restored-state.json

The isolated restore file is for review, never automatic production replacement.
SHA-256 detects corruption; it is not proof against a malicious archive author.

## Storage boundary

The publication-operations artifact is retained for 90 days. This is an additional
checked backup, NOT permanent independent disaster recovery. Continuous scheduled
runs create fresh backups of the cumulative ledger, but deleting the repository
or allowing all artifacts to expire loses that protection. An independent durable
storage destination still needs to be connected before permanent backup acceptance.
No new paid service or public raw-state git branch is created.

Rollback: revert this PR's workflow steps. Preserve all existing state/artifacts.
No provider writes, notifications, secrets or activation flags are changed.
