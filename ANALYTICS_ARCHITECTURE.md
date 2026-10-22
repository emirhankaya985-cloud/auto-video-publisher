# Analytics archive and daily reporting

`stats_reporter.py` collects paginated per-video lifetime view snapshots from the
configured YouTube, Facebook, and Instagram accounts. It computes daily changes
only from a prior successful snapshot; the first measurement is a baseline.
Unavailable, missing, deleted, or reset counters are not fabricated as zero.
JSONL is the canonical upserted history, with a CSV export stored in the
dedicated `Auto Video Publisher Analytics` Drive folder. The daily workflow is
scheduled for 20:59 UTC (23:59 TRT). Changes remain local until committed and
deployed; API access and data availability still require a real workflow run.

| Provider | Current access | Additional access likely needed |
|---|---|---|
| YouTube | OAuth channel uploads playlist and video statistics | Missing videos/counters or expired OAuth scopes are reported unavailable |
| Facebook | Page video views, all cursor pages | API access and availability of `views` depend on Page permissions/API version |
| Instagram | Professional-account video media insights (`views`) | Metric access depends on account type, permissions, and API availability |
| Threads/TikTok | Not included in view collection; Threads publishing is separately optional | Account authorization and product access |

Platform definitions remain separate; cross-platform totals are labeled partial
when any configured platform is unavailable. API view definitions may differ.
