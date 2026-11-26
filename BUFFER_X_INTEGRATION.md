# Buffer X video integration

## API and plan constraints

- GraphQL endpoint: `POST https://api.buffer.com` with `Authorization: Bearer $BUFFER_API_KEY`.
- Video posts use `createPost(input:)` and `assets: [{video: {url}}]`. Queue mode follows the X posting schedule configured in Buffer; custom times use `customScheduled` and UTC `dueAt`.
- Buffer must be able to fetch the HTTPS media URL without authentication. `webViewLink` is not a media URL. The worker makes a bounded public `Range` request to validate individual Google Drive MP4s and never changes folder sharing.
- Buffer Free allows three channels and ten queued/scheduled posts per channel. API use is rate-limited; the worker records structured rate-limit responses and pauses at 90% use. A `429` is held for a later workflow run. An ambiguous create result is marked `uncertain` and is never blindly retried.

Official references: [Quick Start](https://developers.buffer.com/guides/getting-started.html), [video post](https://developers.buffer.com/examples/create-video-post.html), [media hosting](https://developers.buffer.com/guides/hosting-media.html), [API limits](https://developers.buffer.com/guides/api-limits.html), [Free plan](https://buffer.com/pricing).

## What the integration does

`buffer_x.py` provides the GraphQL client, X-channel allowlist, media preflight, idempotent job store, queue-cap guard and status reconciliation. `buffer_x_worker.py` reads the existing per-account `plan.json` artifacts in a separate sidecar job after the Meta workflow. It stores X queue state in additive Neon tables from `migrations/20261126_buffer_x.sql`; it does not modify Meta publication records. It uses existing ntfy/Telegram notification settings when available.

The `film_sahneleri` route is separate from Film Mağarası. It can stage at most one exact same-stem MP4/TXT pair from `FILM_SAHNELERI_DRIVE_FOLDER_ID` per run. Other routes reuse only the existing plan's single Drive file ID and caption.

## GitHub configuration

The sidecar is skipped unless `BUFFER_X_CONNECTION_CHECK` or `BUFFER_X_ENABLED` is the repository variable `true`.

1. Add `BUFFER_API_KEY` as a GitHub Actions secret. `DASHBOARD_DATABASE_URL` is the existing Neon secret used to store the durable queue.
2. In Buffer, connect the X account(s) you intend to use. The Free plan supports up to three channels.
3. Add `BUFFER_X_CHANNEL_ID_<ROUTE>` repository variables for the exact X channel IDs. Supported suffixes: `TARLADAKI`, `GONLE`, `PENGUEN`, `DAILY_LAUGH`, `FILM`, `TOONZONE`, `FILM_SAHNELERI`. Map no more than three, and never map one Buffer channel ID to two routes.
4. For a connection-only check, set `BUFFER_X_CONNECTION_CHECK=true`. This discovers channels but does not queue posts. The API key and channel IDs are still required for route mapping.
5. Keep each `BUFFER_X_RIGHTS_<ROUTE>` variable unset/false until the owner has approved the rights for that route. Exact supported suffixes are listed above.
6. `BUFFER_X_ENABLED=true` enables queue processing, but dry-run remains on by default. For live queueing, explicitly set `BUFFER_X_DRY_RUN=false`; channel mapping and the corresponding rights variable must also be set. Buffer's own X posting schedule controls when queued posts go out.
7. For Film Sahneleri only, set `FILM_SAHNELERI_DRIVE_FOLDER_ID` as a secret to its distinct approved folder. Do not point it at Film Mağarası's folder.

No X post is created while disabled or in dry-run. The worker does not publish X videos during setup. The initial Drive validation performed for this change was a single 64-byte range read of one shared MP4: the server returned HTTP 206, `video/mp4`, and an MP4 `ftyp` signature. This does not certify the video's full codec compatibility or validate other files.

## Tests

`python -m unittest -v test_buffer_x.py test_buffer_x_worker.py` uses offline mocks and temporary files; it does not call Buffer or publish. The dedicated PR workflow runs these focused tests under Python 3.12.
