# TikTok Content Posting API — safe preflight (6 November 2026)

Only opt-in readiness exists. **No TikTok video upload, publishing, OAuth refresh, or secret modification.** The standalone module `tiktok_preflight.py` does not enter any scheduled publishing workflow.

Official prerequisites: TikTok for Developers app with Content Posting API, approved `video.publish` permission, an authorizing user with access token + open ID, creator-info query before publishing, privacy options chosen by creator, and audited client for public viewing. Without audit, publishing is restricted to private visibility. See:
- https://developers.tiktok.com/docs/en/content-posting-api-get-started
- https://developers.tiktok.com/docs/en/content-posting-api-reference-query-creator-info
- https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post

Reserved (unset by default) GitHub secrets: `TIKTOK_ACCESS_TOKEN`, `TIKTOK_OPEN_ID`. Optional variables `TIKTOK_APP_AUDITED`, `TIKTOK_PUBLISH_ENABLED`, `TIKTOK_PREFLIGHT_PROBE_ENABLED` all default to false. The flags alone are not verification of account permissions.

`python tiktok_preflight.py` emits only safe Boolean readiness facts. `python tiktok_preflight.py --probe-creator` makes **one** official creator-info query only if the explicit probe flag is enabled and a token is present. The module never posts media and never prints a token. Live integration must have a separate safety review and verified posting ledger to prevent duplicates.
