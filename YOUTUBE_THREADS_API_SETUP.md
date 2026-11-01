# YouTube + Threads API onboarding — 985 cloud publisher

> No production publication is enabled by this change. The active `.github/workflows/public_link_schedule.yml` is Meta-only; do **not** turn on the legacy `AUTOMATION_ENABLED` switch. All first-stage checks are read-only. No cloud user secret values are available to this repository's source code.

## YouTube (3 channels)

1. Open https://console.cloud.google.com/apis/library/youtube.googleapis.com and enable **YouTube Data API v3** in an existing or new Google Cloud project. In Google Auth Platform configure the consent screen and add the signing-in account to the test users, if still in Testing. Configure an OAuth **Desktop** client; download its JSON and save it locally next to this project's files as `client_secrets.json`. **Never commit this file.**
2. On a trusted Windows computer with a browser, install the pinned dependencies once: `python -m pip install --require-hashes -r requirements.txt`.
3. Run the one-time OAuth flow for each YouTube channel:
   - `python youtube_authorize_channel.py channel1` — Tarladaki Fasulye
   - `python youtube_authorize_channel.py channel2` — Beyinsiz Penguen
   - `python youtube_authorize_channel.py daily_laugh` — Daily Laugh Lab
   Each flow checks the selected YouTube identity **before** creating the local credential file. An existing token file is not overwritten.
4. Copy the **full content** of each generated authorized-user token JSON file into https://github.com/emirhankaya985-cloud/auto-video-publisher/settings/secrets/actions :
   - `token_channel1.json` → `TOKEN_CHANNEL1_JSON`
   - `token_channel2.json` → `TOKEN_CHANNEL2_JSON`
   - `token_daily_laugh_lab.json` → `TOKEN_DAILY_LAUGH_LAB_JSON`
   Never save a path or the downloaded OAuth client JSON into these token secrets.
5. After merge to `main`, open https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/workflows/youtube_readonly_connection.yml and manually verify each channel, **without video upload**.

The OAuth scope for upload is `https://www.googleapis.com/auth/youtube.upload`. **An API key alone cannot publish** to a YouTube channel. OAuth Testing-mode refresh tokens can expire quickly; the durable app verification/production process is separate from these tests.

This does **not** enable scheduled YouTube uploads. Before that step, reconcile the Drive file, permissions, claim/intent state, exact channel ID, upload privacy policy, quota, and current 985 publisher ownership. The old YouTube upload implementation exists, but the public Meta-only workflow does not call it.

## Threads (6 accounts)

Create or reuse a Meta developers app with the **Threads API** use case. Use Threads-specific authorization with `threads_basic` and `threads_content_publish` (and `threads_manage_insights` only when needed for metrics). Instagram or Facebook tokens are not interchangeable with Threads tokens.

| Route | PREFIX | Profile |
|---|---|---|
| `tarladaki` | `TARLADAKI` | Tarladaki Fasulye |
| `penguen` | `PENGUEN` | Beyinsiz Penguen |
| `gonle` | `GONLE` | Gönle Düşen |
| `daily_laugh` | `DAILY_LAUGH` | Daily Laugh Lab |
| `film` | `FILM` | Film Mağarası |
| `toonzone` | `TOONZONE` | ToonZone |

For each PREFIX set the following in https://github.com/emirhankaya985-cloud/auto-video-publisher/settings :
- **Actions secret:** `PREFIX_THREADS_ACCESS_TOKEN` (the token for exactly this Threads account)
- **Actions variable:** `PREFIX_THREADS_USERNAME` (without `@`)
- **Actions variable (recommended):** `PREFIX_THREADS_USER_ID` (expected Threads API user ID)
- **Actions secret, only before publishing:** `PREFIX_THREADS_VIDEO_URL_TEMPLATE` (actual public HTTPS MP4 host, supporting `{file_id}` and/or `{filename}`)
- **Actions variable, only after publishing is safely integrated and approved:** `ENABLE_PREFIX_THREADS=true`

Compatibility: `THREADS_ACCESS_TOKEN` is accepted as a fallback **only** for Penguen; no other account inherits its token.

After the branch is merged, open https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/workflows/threads_connection_audit.yml and select **Run workflow → account: all** (default). A single run performs six separate authenticated `GET /me` checks, verifies each account's username and optional user ID, and reports each route as PASS or FAIL without revealing credentials. You can also select just one route. It **does not** create a video container or publish anything. Missing or mismatched accounts make the overall audit fail safely; other accounts are still checked. This cannot independently prove the presence of the publish permission until an authorized publish-specific API check is carried out.

**Production prerequisites:** the selected accounts must have approved Threads authorization, tokens must be rotated/refreshed before expiry, media must be accessible to Meta from a real public HTTPS video URL (a Google Drive share-page URL is not a direct MP4), and the multi-account posting path must be integrated with per-account Drive intent/claim/idempotency before enabling any route. Existing `threads_publisher.py` is only the low-level video client. Do not cross-publish the same file automatically without rights clearance.

## Acceptance evidence

- Offline mocks succeed on the exact branch SHA.
- Each real account read-only check succeeds with the correct account ID.
- Token values and private URLs never enter logs, source, chat, or issue bodies.
- New publishing remains OFF until explicit activation and separate live post IDs plus duplicate-avoidance verification.

## 31 October 2026 live failure diagnosis (no upload)

Two actual manual runs failed after GitHub runner tests passed:
- Channel test: https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41195920953
- Channel test: https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41195981538

Both `google-readonly` jobs returned `{"status":"not_an_authorized_user_token"}` BEFORE an authenticated YouTube API request. This **does not prove** an expired token or an invalid channel; it means the JSON in the selected Actions secret is not a complete authorized-user token. The screenshot confirmed the two names were present, not the secret values. Do not delete or regenerate credentials blindly.

Owner recovery: inspect the **local** JSON type without pasting any content into chat. An OAuth client download usually contains a top-level `installed` or `web` object, and is **not** the expected token. An authorized-user token must contain top-level `client_id`, `client_secret`, `refresh_token` and `token_uri` values; it must authorize YouTube upload. If an existing matching `token_channel1.json` / `token_channel2.json` contains these fields, use that entire JSON as the matching GitHub secret. If it does not, use `youtube_authorize_channel.py` from this branch on a trusted computer to generate an authorized-user token, confirm the exact channel identity, and copy the resulting JSON into the matching GitHub Actions Secret (not source code, not chat). Keep production publishing disabled.

The checked-in read-only diagnostic now safely identifies the missing fixed field *names* and whether the input looks like OAuth client JSON, without ever exposing values. Re-run the manual no-upload check for `channel1` and `channel2` after correcting their secret values. Only `status=verified` with the expected channel identity is acceptable; a green isolated unit test is not sufficient. No video was uploaded in these failed checks.
