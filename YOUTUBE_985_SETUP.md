# YouTube channel setup in the 985 public repository

This project intentionally keeps the legacy YouTube publishing workflow disabled. Connection checks do not upload videos.

1. Find existing **authorized-user OAuth token JSON** files on the user's Windows PC, **not** the Google Cloud OAuth client download:
   - Tarladaki Fasulye: `token_channel1.json`. The repository's `auth_setup.py` instead creates `token.json`; verify the selected YouTube channel before reusing it.
   - Beyinsiz Penguen: `token_channel2.json` (created by `auth_channel2.py`).
   - Daily Laugh Lab: `token_daily_laugh_lab.json`, if previously generated.
2. [985 GitHub Secrets](https://github.com/emirhankaya985-cloud/auto-video-publisher/settings/secrets/actions) → **New repository secret**, one per channel. Copy the **entire JSON file content**, not a filesystem path:
   - `TOKEN_CHANNEL1_JSON`
   - `TOKEN_CHANNEL2_JSON`
   - `TOKEN_DAILY_LAUGH_LAB_JSON`
3. [No-upload YouTube authorization check](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/workflows/youtube_readonly_connection.yml) → Run workflow → choose the channel. The check verifies that Google OAuth works and that the connected channel identity matches expectations. It makes only a YouTube `channels.list` read call, never a media upload.
4. Do **not** set `AUTOMATION_ENABLED=true`. `omnichannel_schedule.yml` also has `YOUTUBE_PUBLISHING_ENABLED=false`, and the active `public_link_schedule.yml` is Meta-only. YouTube requires an independent publishing safety/claim migration before activation.

If no authorized-user token file exists, use the project's existing `auth_setup.py` (first channel) or `auth_channel2.py` (second channel) locally with the existing `client_secrets.json` OAuth desktop client. Do not upload `client_secrets.json`, `token*.json`, or their contents to the public repository or chat. A Google OAuth client JSON is **not** a channel token, and uploading it as a GitHub Secret under `TOKEN_*_JSON` will not work.

Be aware: new Google OAuth projects left in **Testing** mode may issue 7-day refresh tokens. A user's existing previously approved production OAuth token is preferable if it works. A valid authorization does not prove that videos were published.
