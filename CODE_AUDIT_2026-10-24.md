# 985 Video Automation — Code Audit (24 Oct 2026)

Scope: inspected repository inventory (156 tracked files), production Python code, GitHub workflows, Meta identity, state ledger, duplicate protection, notifications, reporting, TXT and cover matching. Test suites are automated; **this is not proof of successful live posting after the fixes.**

## Code fixes committed

1. Daily Laugh confirmed publication days are recorded in the New York schedule timezone, including midnight-boundary tests.
2. Instagram history excludes image and carousel posts when determining completed video/Reels slots. Missing media type fails closed.
3. ToonZone daily audit reports exact part-specific PNG matches and missing covers. Incorrect part artwork is never substituted.
4. ToonZone has additional GitHub scheduled check slots for 12:00/12:10/12:20/12:30 TRT. GitHub cron may start late.
5. New Meta-only health watchdog checks scheduled workflow runs without publishing videos, with ntfy/Telegram alerts when configured and redacted errors.
6. Public .gitignore now includes local secrets, private certificates and runtime logs (future protection only).

Observed CI: https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40064720836 — 359 Python unit tests passing and 57 extra function assertions; scheduler JS tests run by CI.

## Not yet proven or still needing work

- **Live publication:** the last observed automatic Meta runs before these fixes failed; latest code still needs a scheduled real-world run and platform post-ID/history verification.
- **Daily views:** daily_stats.yml and analytics workflows still use the disabled legacy AUTOMATION_ENABLED toggle and require missing OAuth/Drive credentials. Do not enable legacy publishing just to start reporting. A separate Meta-only view reporting path is needed.
- **Secrets:** the last setup-status run counted 2 configured secret values out of 23 listed names; most relate to optional/legacy systems. Do not paste tokens in public source.
- **Cover shortage:** the last successful inventory (Oct 23) listed ToonZone 159 MP4, 0 TXT and a separate cover folder with 48 total files. The exact matching count must be checked live.
- **TXT policy:** the runtime uses matching TXT where possible but falls back to episode metadata for ToonZone or a generic filename caption on other routes when the TXT is missing/unreadable. The older operating guide incorrectly suggests TXT is mandatory for non-ToonZone routes. Per-account strictness versus permitted fallback needs a deliberate policy decision.
- **Scale:** approved account names and routes are hardcoded. Add a validated route registry before growing the number of accounts.
- **Notifications:** ntfy/Telegram HTTP success is server acknowledgment only, not proof of an Android push notification.

## Safety

Keep LINK_AUTOMATION_ENABLED and AUTOMATION_ENABLED distinct. Never enable a parallel legacy publisher for the same accounts. Persist and reconcile publication intent/results before deciding whether retry is safe. CI, API access, Meta post IDs, daily quota completion and views are different validation levels.

## Live scheduled Meta check after the fixes

Run https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40064851111
at 2026-10-24 08:04 TRT completed successfully. All 19 runtime safety
tests passed; the workflow read the actual shared Drive catalogs and Meta
history, persisted state artifacts and completed the publish step.
No video was due or published at that early hour; workflow success must not
be counted as a real post.

The live audit measured 159 ToonZone MP4s, **48 matching exact PNG covers**
and **111 missing exact covers**, with zero ToonZone TXT files.
A later reporting fix distinguishes NOT DUE from a completed daily target
when the daily target is zero.
