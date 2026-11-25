# TikTok official Content Posting API — actual eligibility (14 Nov 2026)

## Verified repository state

Trusted `main` run [43633715391](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/43633715391) ran `tiktok_preflight.py` and reported **false** for each of `token_configured`, `open_id_configured`, `app_audited_declared`, `publishing_requested` and `authorization_live_verified`. The workflow intentionally performed **zero uploads** and no credential-backed creator-info request. Passing its unit tests does **not** mean TikTok is connected.

## Requirements (official documentation, current 14 Nov 2026)

- [Direct Post quickstart](https://developers.tiktok.com/docs/en/content-posting-api-get-started): a registered TikTok app with Content Posting API/Direct Post enabled, approved `video.publish` scope, and explicit OAuth authorization from each creator are prerequisites.
- [Direct Post reference](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post): read current creator information before any publishing attempt; respect the user's available privacy settings, allowed duration and media format. Request metadata and explicit creator consent before upload. Only the official status API or a verified live post should mark success.
- [Content Sharing Guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines): unaudited clients are restricted to `SELF_ONLY` / private posting, and a review is required to lift the restriction. The policies explicitly disallow internal utilities limited to uploading to the developer's/team's accounts, and apps that merely copy arbitrary posts from other platforms. An app intended to support a wide creator audience and meaningful editing/consent UX is required for audit eligibility.

## Accepted safe path

1. Leave `TIKTOK_PUBLISH_ENABLED` disabled and do **not** create `video.publish` claims without provider approval or correct user OAuth.
2. If a compliant creator-facing app is proposed, complete its audit/UX requirements: account display, true preview, editable caption/hashtags, user-chosen privacy with **no default**, selectable comments/duet/stitch, commercial-content disclosure, explicit TikTok music/brand acknowledgements, per-creator limits, and appropriate origin/domain ownership proof for `PULL_FROM_URL`.
3. Only with actual authorization, invoke existing `tiktok_preflight.py --probe-creator` behind its explicit gate. This sends a creator-info query (`POST`, but **not** a media upload). Test the `tiktok_post_status.py` parser with existing IDs. No `content/init` or publish request should run under a preflight result alone.
4. If the intended product remains strictly a private/internal managed-account uploader, **do not represent public Direct Post automation as an approved integration.** Manual creator-controlled posting is the safe external alternative.

This document authorizes no TikTok uploads, OAuth permission changes, or paid services.
