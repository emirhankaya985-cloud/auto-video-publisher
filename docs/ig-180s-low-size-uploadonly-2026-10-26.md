# Exactly one no-publish Meta test: 180s below 12 MB

The Film Part16 and ToonZone Part3 source clips are independently rights-approved
by the same production route gates. Their old approximately 180-second 42-44MB
rupload requests failed HTTP400 ProcessingFailedError before media_publish.
On 26 Oct 2026, two **15-second, approximately 5MB** exact-source uploads
both reached HTTP200 / FINISHED without any publication:
[GitHub Actions #40288506373](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40288506373).

This exact push marker authorizes **only two new 180-second small-binary diagnostic
containers** (720×1280 H264, ~300 kbps video, 96 kbps AAC, total <=12MB)
for the **same pinned Drive and Meta Page/IG IDs**. This is a
non-public quality-degraded diagnostic, not approval to publish or alter
the original videos. Final call uses `publish=False`.

Strict prohibitions: no Instagram `media_publish`, no Facebook upload,
no state.json / previous intent changes, no old container retry,
no publishing to another account, no user-tags or text changes to posts.
The diagnosis discriminates transfer-size/media-workload from duration:
a 180s small file that FINISHED means duration alone is not the cause;
a failure remains inconclusive (low quality itself may be rejected).
Never assume an undocumented size threshold or override moderation.
