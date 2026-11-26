# Low-view cleanup — implementation checkpoint

Date: 2026-11-26 (Europe/Istanbul)

## Latest status checked 2026-11-26

- PR #334 merged as `1de43066b1210129caa7da919951c7fdd6c22eb3`; PR #335 merged as `2d0ac7abb6f90892e28190db0d444e068cb4e23e`. Current `main`: `2d0ac7a`. Run #45807133431 succeeded. No content was deleted.
- The assessment now covers six Instagram accounts only. Facebook, Threads, and YouTube are explicitly excluded. An identity lookup failure, incomplete Instagram inventory, or invalid publication/view measurement marks the run incomplete and suppresses all candidates.
- GitHub Actions run #45807133431: `test` job success; `assess` skipped for the PR event. Local tests after syncing main: `test_low_view_cleanup.py` 12 passed; `test_stats_reporter.py` 13 passed.
- The 484 candidate / 1,397 held values are historical counts from failed run #45801967238, not current totals. No content was deleted in that run.
- Automatic deletion remains disabled. The 48-hour and fewer-than-10 rule can only produce review candidates from a complete Instagram scan.

## Live state checked 2026-11-26

- GitHub `main` is `7f104ccdb496b6b9c322d8cf44569d642fc31115` (includes PR #332). The requested filename `MEDIA_AUTOMATION_CHECKPOINT_2026-11-26.md` is absent; this file is the current low-view checkpoint.
- PR #330 merged as commit `9233648a60ca5e035eb9739b50b8035e858b0c29`.
- Run #45801967238 assessed the snapshot but failed because collection was incomplete. Its private artifact contains 484 review candidates and 1,397 held rows; these are historical run counts only, not current totals. No video was deleted. The test job was skipped because this was a scheduled run.
- The run's workflow log showed all six configured `*_THREADS_USER_ID` repository variables empty. The token/username secret entries existed as masked values, but no live platform request was made during this verification. This prevents identity verification; it does not prove whether each token is valid or which exact OAuth grant it has.
- This makes the prior artifact's 484 candidates non-actionable. The fix on `fix/low-view-fail-closed` makes any collection error, unavailable snapshot, or missing required platform suppress all candidates and mark every measured item held.
- Auto deletion remains disabled. The workflow contains no delete operation and no platform DELETE call was made.

## Current work

- Added whole-inventory completeness gating, expected-platform checks, and regression coverage for missing identities/platforms and collection errors.
- Local focused tests: `test_low_view_cleanup.py` 9 passed; `test_stats_reporter.py` 13 passed. GitHub PR CI remains pending.
- PR #334: https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/334, branch `fix/low-view-fail-closed`, current head `5f94976cf4fe51dbfc2e7541c77794bbc7f6f9e8`; base main `7f104ccdb496b6b9c322d8cf44569d642fc31115`. Open, draft, mergeable.
- PR #334 was reviewed; the completeness guard and regression cases are scoped to assessment only. GitHub CI run #45806885853 has been pending with no jobs visible at last check.
- Required user configuration before a future complete Threads scan: set each of the six `*_THREADS_USER_ID` repository variables to the correct numeric ID after confirming account identity. Do not put token values in chat; check/edit existing token secrets only in GitHub's secure Actions settings.
- No production workflow was dispatched from this branch. Merge awaits PR CI and verified Threads IDs in secure repository variables.

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
