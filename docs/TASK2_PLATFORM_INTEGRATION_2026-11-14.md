# Task 2 — Verified checkpoint and production gates (2026-11-14)

These changes are based on PR #267, separate from PR #266. No media has been uploaded or retried manually by this work; no OAuth secret was read or rotated. Existing Facebook/Instagram publish rights gates, prior claims, serial cursors and archives remain intact.

## Changes and opt-in policy

1. YouTube: a malformed/missing videos.insert video ID is never reported as successful. The existing bridge additionally needs owner-authenticated channel ID and processed/public video status. The pre-existing four independent OAuth mappings remain; channel1 and channel2 are Tarladaki Fasulye and Beyinsiz Penguen respectively.
2. TikTok: validate user-selected privacy, creator-specific maximum duration and UTF-16 caption length; securely query ONLY a previously archived publish_id via Content Posting API status/fetch. PUBLISH_COMPLETE without a public post ID is not publicly verified. No unauthorized video.init/write API was introduced.
3. Independent fixed caption files for Tarladaki Fasulye, Beyinsiz Penguen, Gönle Düşen and Daily Laugh Lab. Requires ENABLE_FIXED_ACCOUNT_TXT=true, each account's own uniquely named public-Drive TXT and explicit FIXED_<ROUTE>_TXT_SHA256. Default stays OFF to preserve existing approved copy. Missing/altered content fails closed. Film and ToonZone always keep their per-video captions. A fixed caption repeated on multiple videos is never a source-identity proof and cannot reconcile an uncertain upload via caption-only matching. OddFrames is not part of the current Meta routes.
4. Film Mağarası En_Buyuk_Saban_Part_17.mp4: original Facebook Part17 was archived with post ID 1435010394958762; Instagram had an HTTP 400 in the binary stage, before media_publish, with container 17906869221599675. The 14 Nov GET-only diagnostic recorded EXPIRED. An exact source/SHA/caption/origin/IG-page/remote-history and renewed EXPIRED status gate is now available, **OFF by default** behind FILM_PART17_EXPIRED_RECOVERY_ENABLED=true. No upload or state reset was executed in this PR.
5. Meta's active publishing workflow now sets PUBLISH_ALERTS_ONLY=true: routine success alerts are suppressed; one grouped actionable failure notice is prepared per isolated account/run, alongside structured incident artifacts and existing archived delivery intents. The old notification sender is retained for retries/ACK tracking; it cannot trigger media repost. Threads/YouTube routine Telegram publication notifications remain disabled.
6. Mocked regression tests cover text pinning, distinct accounts, retry safety, Film Part17 gate, TikTok status/metadata, YouTube receipt, and error-only notices. Production account secrets are deliberately absent on PR checks.

## Evidence (read-only production records)

- 2026-11-14 run 43628268890: Tarladaki Fasulye Facebook 392.mp4 post 1180738111310679 and Instagram 392.mp4 post 18119823491322811, with 2 current-run confirmed posts. Independent read-only publication operations verification passed.
- 2026-11-14 run 43628650394: Tarladaki Fasulye Threads verified post 18014266028988419.
- 2026-11-14 run 43630375238: per-account Meta diagnostics show 13 distinct verified platform identities across 7 Facebook pages and 6 IG identities. This GET identity count is not a claim that every account has published recently.
- Run 43571144382: Film Part17 original IG container EXPIRED (GET-only). No live IG receipt has been verified.
- ToonZone historical ledger has entries for S01E04–12, but archived DONE IDs still must be compared against current provider video history and exact source/cover before the series can be declared complete. Never restart E04 blindly.

## Blocked / not claimed

- No production database, retention beyond expiring GitHub Actions artifacts, or dashboard URL is proven. PR #266 is an independent still-open dashboard/report/notification change; its latest 3 mocked CI checks passed, but that is not a deployed database.
- YouTube channel1 and channel2 OAuth identities are configured, not proven live for this task. Missing/expired grants need channel-owner authorization; no uploads occurred.
- TikTok direct post requires an eligible reviewed app, appropriate creator authorization and official UX/privacy/consent controls; unsupported auto-post is held.
- Film Part17 replay remains blocked until the exact-source live GET gate, rights approval and scheduled platform action are explicitly authorized. Original FB ID must not be reposted.
- Account fixed TXT activation needs each owner's approved TXT file and hash. An opt-in flag is not an authorization to invent or edit explanations.

Official TikTok references:
- https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status
- https://developers.tiktok.com/docs/en/content-sharing-guidelines
