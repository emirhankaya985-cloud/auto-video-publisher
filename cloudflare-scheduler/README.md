# Cloudflare fallback scheduler

This Worker never reads Drive or publishes a post. Every five minutes, during
hours when the existing GitHub cron is expected, it checks the main and backup
workflow run history. In `dry-run` mode it performs read-only GitHub checks and
never dispatches. After that check is verified, changing `FALLBACK_MODE` to
`enabled` makes it dispatch the existing publisher workflow only when there
has been no recent schedule/manual dispatch for 12 minutes and no matching
publisher workflow is queued or running.

If a delayed GitHub schedule races with this check, both invocations still use
the same GitHub concurrency group and the publisher's Drive slot/history
guards. Those controls prevent a second publishing attempt for an already
completed slot; the Worker itself never selects or uploads content.

## Required setup (not performed by this change)

1. Create/use a Cloudflare account on the Workers Free plan and authenticate
   Wrangler (`npx wrangler login`).
2. Create a GitHub fine-grained personal access token restricted to this
   repository with **Actions: read and write** permission. The token is needed
   only by the Worker and must not be pasted into chat or committed.
3. Bootstrap the Worker with no public route or cron trigger:
   `npx wrangler deploy --config cloudflare-scheduler/wrangler.bootstrap.toml`.
4. Add the GitHub token through Wrangler's hidden prompt:
   `npx wrangler secret put GITHUB_TOKEN --config cloudflare-scheduler/wrangler.bootstrap.toml`.
5. Deploy the production schedule in `dry-run` mode:
   `npx wrangler deploy --config cloudflare-scheduler/wrangler.toml`.
6. Verify the dashboard shows `*/5 * * * *` and a read-only run logs a
   decision. Then set `FALLBACK_MODE = "enabled"` in `wrangler.toml` and
   deploy again to activate dispatches.

The Cron Trigger uses UTC and mirrors the hours in the current workflow files.
Keep `ACTIVE_UTC_HOURS` in `index.mjs` synchronized if those GitHub cron hours
change. The 12-minute threshold is configurable within the safe 5-60 minute
range via `STALE_AFTER_MINUTES`.

## Free-tier footprint

At one invocation every five minutes, the Worker uses 288 Cron invocations per
day and four GitHub API reads plus one dispatch only when the scheduler is
stale. It does not download video or call social APIs. Cloudflare currently
documents 100,000 daily Worker requests and a 10 ms CPU budget per Cron Trigger
on its Free plan; GitHub's workflow-dispatch endpoint requires Actions write
permission. Neither service guarantees uninterrupted execution.
