# Instagram source intake checkpoint — 2026-11-26

## Local implementation

- Feature branch: `feat/instagram-source-ingestion-20261125`
- Local feature commits include the rebased implementation (`542b5e0`) and scheduled NTFY regression test (`d07505d`).
- Base: `bca890599f1fa8b60b13bafdd2d2dda96ee0d2c0` (latest GitHub `main`, fetched successfully and rebased locally)
- Film Second is excluded from new collection and scheduled publisher account matrices; legacy history/schema support remains.
- Existing publisher hours were preserved. Source collection is opt-in and runs separately; source publishing remains off.
- Existing nightly statistics/NTFY flow now includes a read-only source health and collection summary.
- No production secrets/configuration were changed and no live Instagram, Drive, Neon or publisher writes were made.

## Local verification

- Full `python -m unittest discover -q` passed after the latest rebase: 1,506 tests, 16 skipped (`unittest`, 2026-11-26). The prior 268 focused tests also passed. Coverage includes six-route defaults, 3-new/3-archive planning, existing publish hours, Film Second exclusion, and the single scheduled NTFY source-summary path.
- Python compilation, workflow YAML parsing, and `git diff --check` passed.
- Test-generated `link-runtime` artifacts were removed from the worktree.

## Integration status

- Current GitHub `main` advanced to `bca8905`; local changes were rebased without conflicts, preserving the current publisher schedule and report protections.
- Local `gh auth status` reports its CLI credential is invalid. The connected GitHub API successfully transferred the verified tree to the feature branch, created PR #324, and updated its description.
- PR #324's prior code CI passed all 13 workflows after a legacy-only Film Second fixture fix. GitHub `main` then advanced again; the new local rebase and 1,506-test run passed. The feature branch still needs updating to the latest base and the latest-head CI result before merge.
- Do not merge unless required checks pass. Keep all collection and publishing activation switches off until account rights, Meta access, and Drive child folders are verified.

## Live connection and permission audit

- No Instagram source usernames/IDs, rights evidence, or dedicated collection folder IDs are configured.
- Meta source access and reuse permissions remain unverified. No collection was run.
- Google Drive connector profile responded. All five distinct configured publishing parents returned folder metadata, but the connector reported `source_visibility_status=access_not_verified`; six dedicated source intake folder IDs remain blank. Production `DRIVE_TOKEN_JSON` access was not tested.
- Neon connector performed only `SELECT current_database(), current_schema(), current_user` against project `auto-video-publisher-free`, branch `main`; it returned database `auto_video_publisher_live`, schema `public`. This verifies the connected Neon app path, not that GitHub's `DASHBOARD_DATABASE_URL` points to it. No migration or write was run.
- NTFY CI safety tests passed. No live topic message was sent, so phone delivery remains unverified.
- No source media was collected or published, no production secrets/settings were changed, and no new paid service was added.

## User setup

See [`USER_ACTION_REQUIRED.md`](USER_ACTION_REQUIRED.md) for the source rights, Meta actor ID, Drive folders, existing secret names, and NTFY phone-delivery checks required before live activation.
