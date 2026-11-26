# Low-view cleanup — implementation checkpoint

Date: 2026-11-26 (Europe/Istanbul)

## Implemented in this change

- Added a pure assessment rule: only an owned platform video with a timezone-aware publication timestamp at least 48 hours old and a valid lifetime view count from 0 through 9 is listed as a candidate.
- At 10 or more views the video is retained. Missing, malformed, negative, or unavailable measurements and timestamps are held; they are never treated as zero.
- Film Mağarası and ToonZone are excluded because episode order must be preserved.
- Added a GitHub Actions assessment workflow scheduled every three hours, using the repository's existing read-only statistics collectors and account secrets.
- Exact candidate IDs are kept only in the private GitHub Actions artifact, retained for 90 days. The public step summary contains only counts.
- No delete API request, token rotation, publication, or external notification is made by this workflow.

## Not enabled / blocking conditions for automatic deletion

- This is an assessment-only release (`deletion_enabled: false`). The repo's current collectors and workflow credentials are read-only. There is no safe evidence that every account has the platform-specific content-delete grant.
- No durable delete-result ledger exists for this threshold policy. A delete action must not be enabled until exact account identity, per-platform delete scope, idempotent result recording, and retry behavior are verified.
- Official API references confirm YouTube `videos.delete` needs `youtube`, `youtube.force-ssl`, or `youtubepartner` scope; Instagram media deletion requires Facebook Login and `instagram_basic` plus `instagram_manage_contents`. These scopes have not been checked in production. Facebook and Threads deletion must likewise be separately verified per current app grant before use.
- Periodic sampling checks the current lifetime counter once after age 48h; actual age at evaluation can be 48–51h because the scheduler runs every three hours.

## Verification

- `python -m unittest -v test_low_view_cleanup.py`: 6 passed.
- `python -m unittest -v test_stats_reporter.py`: 13 passed.
- `py_compile`, workflow YAML parse, and `git diff --check`: passed.
- No production API call was made in this development run. Await PR CI and a read-only scheduled/manual assessment before claiming live collection works.
