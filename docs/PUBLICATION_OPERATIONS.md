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
No provider writes, notification sends or secret changes were performed while developing this PR.

## Content stock and local quality

The planner exports content-stock.json and a step-summary table. Remaining stock
is a conservative candidate estimate, not a guarantee of publishability. It
requires exact TXT presence, excludes unresolved intents and filename aliases,
and respects shared humor ownership in the ledger. It does not count generated
TXT fallbacks or check captions/rights itself. Failed folder reads produce N/A,
not zero. Existing post notifications add a low-stock note below three estimated
days; no new standalone notification stream is created. Estimates use the normal
daily quota (5, Daily Laugh 8, ToonZone 4), not the current hour's due slots.

MEDIA_QUALITY_ENABLED defaults on in the proposed publisher workflow and can be
disabled with the same repository variable set to false. Local FFprobe validates
dimensions/duration; FFmpeg samples up to three eight-second windows and rejects
decode failures, near-total black samples and missing/silent audio. Sampling is
not exhaustive video review, speech comprehension, subtitle or copyright review.
Silent-by-design clips can be held by this conservative gate. No upload is called
on a failed quality check; the source remains ready for later review. Per-source
quality evidence is archived with publication-operations.

## Engagement history

The proposed daily workflow enables ENGAGEMENT_HISTORY_ENABLED (false disables).
The existing canonical JSONL archive now receives Meta per-video likes/comments
and per-account followers when available. Daily follower differences require a
valid previous-day reading; missing fields remain unavailable, never invented
zero. Optional field/permission failures preserve successful earlier readings and
are recorded in engagement-collection.json without failing unrelated view data.
The normal daily Telegram report includes a follower count/change section.
YouTube and Threads engagement are not newly collected by this extension.
Provider field availability requires live GET acceptance after merge; offline
tests are not evidence that all account permissions provide these counters.

Validation: 811 unittest tests including real generated FFmpeg clips and a
publisher test asserting neither Meta upload is called after quality rejection.
Production deployment and permanent independent backup remain separate acceptance
items. Revert this PR or disable the two feature variables to roll back gates.
