# Task 2 — Platform reliability checkpoint (2026-11-14)

This branch is independent of analytics PR #265/#266. It does not enable any new publisher, rotate secrets, alter copyright/route gates, erase intents, edit captions, or upload videos.

## Implemented
- YouTube: validate that the videos.insert response contains an exact-shaped 11-character video ID before logging success. Existing youtube_main_bridge.py still reconciles identity, upload processing and visibility with the channel's Google API.
- TikTok: validate caption maximum (2200 UTF-16 units), duration against live creator limits, and an explicitly selected privacy level; no default privacy or implied consent.
- TikTok: status/fetch GET-like status reconciliation through TikTok's official POST API, only with a previously archived publish_id, an explicitly enabled probe and an authorized token. Public publication is not verified without returned public post IDs. No post initiation, upload or retry is added.
- Routine Threads/YouTube publication Telegram notices: scheduled and workflow-completion triggers removed; old success-delivery job disabled. Task 1 error-only reporting remains independent.
- No-network regression tests added.

## Existing integrations
- Instagram/Facebook: Meta-only public_link_schedule.yml with per-route preflight, receipt and uncertain-state protections.
- Threads: independent route credentials and identities via threads_accounts.py, with separate opt-in.
- YouTube: channel1 and channel2 already have dedicated OAuth secrets, expected channel IDs, and a local consent flow in youtube_authorize_channel.py. Google GET identity must match before upload. Other existing channels remain untouched.
- ToonZone S1 E1–E3 are the owner-provided published baseline; E4 is next. Film Part 17 and missing sources require production receipts. Episode order, caps and account TXT settings are unchanged.

## Unverified / external blockers
- TikTok's Content Posting API requires appropriate creator-granted video.publish scope, compliant creator UX with explicit preview/consent, and app audit for unrestricted visibility. TikTok's Content Sharing Guidelines state that internal-only tools posting to accounts owned by the developer/team do not qualify. No automated TikTok publication is claimed.
- A manually authorized channel-specific OAuth grant is needed wherever a YouTube token is missing or invalid. No random channel selection.
- Live account tokens, post IDs, and Meta/Threads YouTube publication outcomes remain unverified in this PR; no upload was executed.
- Dashboard/database PR #266 is open and CI full-regression checks are failing. This branch does not claim durable DB deployment.

Official references:
- https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status
- https://developers.tiktok.com/docs/en/content-sharing-guidelines
