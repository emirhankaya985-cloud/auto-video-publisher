# Instagram source video intake

This feature adds an opt-in intake lane for six active publisher routes. Film Second is excluded from new collection and scheduled account matrices; its old route data and publisher history are preserved. It discovers eligible videos through Meta's official Instagram Business Discovery API, stores source attribution and dedupe state in the existing Neon database, and places immutable intake copies in isolated Google Drive child folders. It does not scrape Instagram or publish as part of collection.

## Default state and activation

All six route settings in `instagram_source_accounts.json` are disabled. `source_accounts` is empty and `collection_folder_id` is blank. The collection workflow additionally requires the GitHub Actions variable `IG_SOURCE_COLLECTION_ENABLED=true`. Source publication requires both the existing global publisher switch and `IG_SOURCE_PUBLISHING_ENABLED=true`; each route also needs its own explicit `enabled`, `auto_collection`, and `auto_publish` settings. It follows the existing per-account schedule and does not add or move publish slots. Current production configuration is unchanged until these settings are deliberately enabled on the main branch.

When source accounts are added, configure each entry like this:

```json
{
  "username": "public_creator_username",
  "enabled": true,
  "rights_approved": true,
  "rights_evidence": "license or permission reference",
  "official_api_download_allowed": true
}
```

Only public professional Business or Creator accounts accessible through the official API are supported. An API response or a publicly visible post does not itself grant reuse rights. Record permission/licensing evidence before enabling download. If Meta does not return a media URL, the item is held and reported without scraping or alternate downloading.

For each route, set `collection_folder_id` to a dedicated child folder of the existing `target_folder_id`. The collector verifies this parent relationship and never writes source videos into the flat publishing folder. Do not reuse a collection folder across routes. Keep the source filename prefix, which identifies route ownership for Tarladaki and Penguen's shared parent folder.

## Collection and selection

The intake checks all pages for configured sources every 30 minutes, keeps video posts published on the current Europe/Istanbul calendar day, ignores photos, validates the official CDN URL, size, MP4 signature and video stream, then records the SHA-256 hash and source metadata. It also stores source account IDs, content categories, permission evidence and per-scan results in Neon. Existing Drive objects are reused only when their stored source identity, byte size and Drive checksum match; collisions are held. Captions and API-provided thumbnails are stored alongside the video. No source media URLs or access tokens are written to logs or Neon.

Neon keeps global asset hashes, route-specific inventories, daily plans and independent publication state for Facebook and Instagram. Eligible unpublished items are ranked by measured video quality and available public metrics. Each route plans up to three new and three archive clips daily, with a maximum of two selected items per source. A short pool remains a visible deficit; it is never silently filled from the other pool. Unselected new clips roll into the archive pool on the next Istanbul day.

The existing public-link publisher consumes only IDs present in that route's Neon plan and only from the isolated intake folder. It verifies the downloaded bytes against the stored hash and requires the matching caption and cover before publishing. New source auto-publishing is held for Film Mağarası and ToonZone to preserve serial order. This lane currently integrates Facebook and Instagram only; it does not change Threads or YouTube routes.

## Required GitHub configuration

Use existing secrets `META_ACCESS_TOKEN`, `DRIVE_TOKEN_JSON`, and `DASHBOARD_DATABASE_URL`; set `IG_SOURCE_DISCOVERY_ACTOR_ID` to the authorized professional Instagram actor ID. The database URL must point to the existing Neon `neondb` database. No credentials belong in this repository. The collection job installs the existing hash-pinned requirements and the pinned psycopg driver, and uses FFprobe for file validation.

Before enabling collection, add permitted source usernames, document rights, provision and verify each isolated Drive child folder, then run local checks. Keep collection and publishing switches off until those prerequisites are complete. Collection can be activated independently from source publishing.
