# Paired YouTube publishing

The active `public_link_schedule.yml` workflow attaches YouTube to the exact video already selected for each corresponding Meta route. It does not start the legacy omnichannel workflow or select a separate queue. Existing source folders, rights gates, route time zones and daily slot counts remain unchanged.

| Meta route | YouTube channel | Secret |
| --- | --- | --- |
| tarladaki | Tarladaki Fasulye | TOKEN_CHANNEL1_JSON |
| penguen | Beyinsiz Penguen | TOKEN_CHANNEL2_JSON |
| daily_laugh | Daily Laugh Lab | TOKEN_DAILY_LAUGH_LAB_JSON |
| gonle | Gönle Düşen | TOKEN_GONLE_DUSEN_JSON |

Every credential is checked against its exact channel ID before planning and again before upload. Missing credentials hold only YouTube; Meta continues. Both upload and readonly OAuth scopes are required. Google OAuth applications in Testing can issue short-lived refresh tokens; move to an appropriate production consent configuration before relying on unattended operation.

YouTube uses the same prepared source MP4, the filename stem as title, and the selected Meta caption as description (unless a YouTube caption exists). Daily Laugh uses English metadata; the other three use Turkish. Posts are public. Upload occurs within the same scheduled run, after Meta uploads; completion time can differ. No old backlog is uploaded automatically.

The existing shared artifact ledger persists YouTube intent before any upload and records its confirmed video ID. Interrupted or ambiguous uploads hold the channel until manually reconciled against YouTube Studio. They are never blindly retried. Do not delete state to clear a hold. Restored done source IDs cannot be uploaded again. Youtube notifications join the existing confirmed-post notification preparation; this change does not send test messages.

Rollback: set YOUTUBE_PUBLISHING_ENABLED to false in the active workflow. Keep the shared ledger and tokens. No migration of existing Meta state is needed.

Validation: focused offline runtime, pairing and notification tests; no live upload was used to validate this change. Activation occurs only after merging into main and on a normal authorized publish run.
