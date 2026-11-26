# Low-view cleanup — implementation checkpoint

Date: 2026-11-26 (Europe/Istanbul)

## Current state — supersedes the historical status below

- Current `main`: `3d10708c8df10216cb573d6fe49360ac1dff23fd` (PR #339 merged; includes #338, #336, #335 and #334). PR #339 CI passed: low-view tests passed; its live assessment job was correctly skipped for the pull request.
- Latest fresh live run [#45828662906](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/45828662906) completed successfully at 16:34 Istanbul. The six-account Instagram collection was complete: 307 threshold candidates, 1,318 held, 0 unavailable accounts, 0 collection errors. It was read-only and deleted nothing. These are historical candidates and will be deliberately excluded at activation, so enabling the future policy will not bulk-delete old posts.
- Automatic cleanup is active for Instagram only. A post is eligible only after it is at least 48 hours old, has fewer than 10 lifetime views, is from a fully complete six-account scan, belongs to a verified account, and was published at or after the explicit activation timestamp. Eligible videos are deleted oldest to newest, at most 3 per account per run. Film Mağarası and ToonZone remain excluded. A current-view recheck occurs immediately before DELETE; a missing/rejected metric or API error stops further deletion in the run.
- The collector uses the existing page token for account-bound reads and the existing Facebook user token for DELETE, as required by [Meta's Instagram Media deletion documentation](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/v21.0/). Permission audit previously confirmed `instagram_basic` and `instagram_manage_contents`; no new token or paid service is needed.
- Ordering change is merged: eligible videos are sorted by publication time, oldest first, before the per-account cap. A regression test confirms the oldest three are selected when four eligible posts are present. Local `test_low_view_cleanup.py`: 16 passed; CI passed.
- Production variables are set: `LOW_VIEW_DELETE_ENABLED=true`; `LOW_VIEW_DELETE_START_AT=2026-11-26T13:36:23Z`. The system is enabled. Existing candidates from run #45828662906 remain untouched; only posts published at or after the activation timestamp can be deleted.
- First post-activation manual verification run [#45830849174](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/45830849174) completed successfully. Six-account scan complete; 307 candidates, 1,318 held, no unavailable accounts or collection errors. Deletion was enabled; all 307 candidates were skipped as pre-activation, 0 deleted, 0 deletion errors. This confirms the activation cutoff is working and existing low-view posts remain untouched.

## Historical checkpoint (before PR #334/#335)

## Live state checked 2026-11-26

- GitHub `main` is `7f104ccdb496b6b9c322d8cf44569d642fc31115` (includes PR #332). The requested filename `MEDIA_AUTOMATION_CHECKPOINT_2026-11-26.md` is absent; this file is the current low-view checkpoint.
- PR #330 merged as commit `9233648a60ca5e035eb9739b50b8035e858b0c29`.
- Run #45801967238 assessed the snapshot but failed because collection was incomplete. Its private artifact contains 484 review candidates and 1,397 held rows; these are historical run counts only, not current totals. No video was deleted. The test job was skipped because this was a scheduled run.
- The run's workflow log showed all six configured `*_THREADS_USER_ID` repository variables empty. The token/username secret entries existed as masked values, but no live platform request was made during this verification. This prevents identity verification; it does not prove whether each token is valid or which exact OAuth grant it has.
- This makes the prior artifact's 484 candidates non-actionable. The fix on `fix/low-view-fail-closed` makes any collection error, unavailable snapshot, or missing required platform suppress all candidates and mark every measured item held.
- Auto deletion remains disabled. The workflow contains no delete operation and no platform DELETE call was made.

## Current work

- Read-only Meta permission audit [45805151378](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/45805151378) passed: `instagram_basic`, `instagram_manage_contents`, and `pages_manage_posts` are granted. Page identity audit [45804776622](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/45804776622) passed.
- Fresh-token stats run [45805382927](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/45805382927) failed overall due to non-Instagram sources: six Facebook snapshots hit the existing zero-heavy metric guard, four YouTube OAuth refreshes returned `invalid_grant`, and Beyinsiz Penguen Threads failed. Its private artifact had 307 Instagram and 177 Threads historical candidates. Those mixed-scope candidates are not eligible for action; none were deleted.
- Updating PR #334 to scope the read-only scan to the six configured Instagram routes only. Facebook, Threads, and YouTube are excluded from candidate generation. Any missing/error Instagram route suppresses all candidates; Film Mağarası and ToonZone remain protected. No deletion endpoint is added or enabled.
- Local focused tests: `test_low_view_cleanup.py` 11 passed; `test_stats_reporter.py` 13 passed. PR CI is pending after this narrow update.
- PR #334: https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/334, branch `fix/low-view-fail-closed`, base main `7f104ccdb496b6b9c322d8cf44569d642fc31115`.
- No Threads variables/secrets are required by the Instagram-only assessment. No production deletion is authorized by this checkpoint.

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
