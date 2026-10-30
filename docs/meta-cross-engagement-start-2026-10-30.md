# Owner-requested first manual engagement batch — 30 October 2026

The owner explicitly requested the first live batch now and daily execution at
13:00 Europe/Istanbul. This exact marker path triggers the initial main-branch
batch after CI and merge. Unrelated pushes do not trigger engagement.

Scope: confirmed native Facebook/Instagram posts from verified publisher runs
in the last 24 hours, all enabled and verified managed accounts, existing
permission and ownership gates, and the independent no-repeat ledger.

Supported writes: official Facebook/Instagram likes when permissions exist;
Facebook video-link shares to the other Pages. Saves and Instagram native
reposts remain unsupported reports, never fabricated successes. The latest
read-only report showed both like permissions missing; activation cannot grant
these permissions. No video re-upload, token/secret change, or state reset.

Daily schedule: 0 10 * * * UTC = 13:00 Europe/Istanbul. Normal publisher
workflow completions no longer trigger engagement. GitHub cron may start late.
Kill switch: META_CROSS_ENGAGEMENT_ENABLED=false. The owner-approved default
is now enabled; UI workflow_dispatch still defaults to dry_run for previews.

## Corrected Video preflight, same authorized initial batch

Initial run 41044986946 sent zero POSTs: all 210 planned shares stopped before
posting. The publisher's numeric IDs represent Video nodes. Read id/from for
ownership and construct the canonical Facebook Watch link from that verified
Video ID instead of requesting the PagePost permalink_url field on a Video.
Only this audited run's no-POST preflight failures may be rechecked once with
source_check_version=2. Accepted/uncertain/reserved/rejected POST states are
never reopened. This marker edit starts the corrected initial attempt.
