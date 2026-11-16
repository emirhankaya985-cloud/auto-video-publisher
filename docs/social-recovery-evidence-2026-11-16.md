# Production incident evidence and recovery boundary — 2026-11-16

This document is an observation, not a claim that held publications or credentials are repaired. No Meta/YouTube POSTs or secrets are included. `main` baseline: `3bd7cfe1ce6841f6ff4fb15195cf160727234fc3` (PR #280).

## 9–16 November failed GitHub Actions: 357

Query: `/actions/runs?status=failure&created=2026-11-09..2026-11-16`, four pages, 357 distinct run IDs. Events: **158 scheduled**, **158 pull-request**, **41 push**. A failed read-only gate/test is not proof of a failed publication.

Scheduled workflow breakdown (sums to 158):
- YouTube accepted receipt GET-only: 59 (requires OAuth/receipt validation; no upload).
- ToonZone S01E04 owner-authorized relaunch: 43 (do not infer which parts published without individual evidence).
- Public link Meta automation: 17 (inspect account jobs independently; a failed route does not mean all accounts failed).
- Meta cross-account engagement: 12; independent account engagement diagnostic: 6.
- Tracked Meta daily target read-only: 11.
- Daily-report missed-run watchdog: 3; daily stats report: 2.
- Owner status-only Telegram inbox: 3.
- Threads safe token rotation: 2 (owner secret-write authority missing).

The other 199 failures were 158 pull-request workflows and 41 push workflows, mostly no-write CI checks. They must not be counted as failed media uploads. Root causes are workflow/attempt specific; repeated status alone is not a single proven cause.

## Live statistics after PR #280

Trusted main push [43848391912](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/43848391912), GET-only `live-stats-readonly-coverage` artifact:
- 13/13 Meta (Facebook/Instagram) platform counters measured.
- 18/19 available platform view totals; Threads 5/6. Beyinsiz Penguen Threads remains unavailable.
- YouTube 0 channels measured in this Meta-only probe; this is intentionally excluded, **not a measured zero**.
- No Telegram, ntfy or provider writes in this probe.
- This is not a verified 23:59 TRT scheduled report or a successful ingest.

## Critical historical Instagram intents

Evidence from publication-state artifacts of [43833670883](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/43833670883) and [43841610844](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/43841610844).

| Route | Source file | Original run | IG creation container | Original IG status | Cross-platform receipt |
|---|---|---|---|---|---|
| Tarladaki Fasulye | `192.mp4` | `41301342606` | `18111440750133751` | uncertain, no verified IG post ID | Facebook ID `1166885602570314` (not IG evidence) |
| Film Mağarası | `En_Buyuk_Saban_Part_17.mp4` | `43235604132` | `17906869221599675` | uncertain, no verified IG post ID | Facebook ID `1435010394958762` (not IG evidence) |

The original Instagram upload stage returned HTTP 400. Read-only container GET later reported `EXPIRED`. A container terminal status is insufficient to prove full post absence. Film17 has a saved source SHA256; Tarladaki192's original IG ledger does **not** have an exact binary SHA256. Require exact owned Instagram video ID, account, timestamp, caption **and source provenance** for a completed reconciliation. A unique caption is a candidate, not verified original video bytes. Never reupload on missing bounded history alone.

Neon social project `gentle-paper-07806508` currently stores 98,241 historic metric_snapshots but **zero publication_events**, **zero daily_reports** and **zero api_errors**. Do not manufacture publication records from the metrics.

## Threads / YouTube credentials

- Beyinsiz Penguen Threads insights reported HTTP 401 Graph code 190 in the last daily report. Official Graph 190/subcodes distinguish invalid authorization states but a code without subcode cannot distinguish expired vs revoked with certainty. The six-account GET-only workflow is `threads_connection_audit.yml`; it persists sanitized per-account receipts.
- Scheduled token refresh [43817660772](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/43817660772) failed before rotation: `THREADS_SECRET_ROTATION_PAT` was empty. The code refuses to persist unverified tokens; renewal without secure GitHub secret-write authority is intentionally blocked. Provide an owner-authorized, minimum-scope secret-write credential via GitHub Secrets; do not commit it or share it in PRs. An expired token that cannot refresh needs fresh owner consent.
- The YouTube exact-channel GET-only inventory is `youtube_readonly_connection.yml`. An OAuth refresh rejection is not proof a video was uploaded. The independent `youtube_accepted_audit.yml` does not call video insert and retains ambiguous records; Google consent may be required for four configured channels. YouTube must not block Meta.

## Reporting / notifications / dashboard

- Daily workflow: `daily_stats.yml`, 20:59 UTC = 23:59 TRT scheduled. Actual completion must be checked at `actions/workflows/daily_stats.yml`; no future run is declared successful.
- PR #280 isolates optional dashboard ingestion from the preserved report. A missing `DASHBOARD_INGEST_URL` or `DASHBOARD_INGEST_TOKEN` cannot be reported as a successful import.
- Report and publisher notifications must remain independent: one failed provider should not delete good metrics; a delivery failure does not imply a failed publication.
- GitHub repository `emirhankaya985-cloud/985-ai-control-center` exists and is **private**; Neon project `still-fog-00690156` has control tables. Render `Emirhan's workspace` has **no 985 AI Control Center service** at this audit, so no live URL or ingest target is verified. No service was created. 985 Control Center is read-only and does not by itself provide the social dashboard `/api/archive` ingest endpoint.
- The existing `dashboard_archive_push.py` expects a separately deployed, authenticated `/api/archive` and `/api/archive/import-run` target. Do not point it at the control panel merely because both use Neon. Provider connection secrets are still required. The existing integrations must run independently until an authorized service exists.

Every regression in the follow-up PR is mock-only; trusted main GET-only acceptance runs must be inspected separately. No automatic retry is allowed for an uncertain provider write.
