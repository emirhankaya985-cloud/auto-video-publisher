# Read-only publisher source audit — 2026-10-25

This marker is the exact allowlisted GitHub Actions push trigger for
`.github/workflows/public_link_schedule.yml`.

Safety contract:
- A commit on `main` touching this marker runs the publisher's `audit` mode.
- The publisher's Meta upload and notification steps explicitly exclude push events.
- The audit may read public Drive inventory and Meta publishing history and create
  local report and incident artifacts, but must not send posts or modify remote claims.
- Production publishing continues only under existing schedule and ownership gates.
- A green audit or CI run is NOT evidence that every planned video is published.

Triggered after the updated no-send regression tests were added.

## Verified CI follow-through

Run an additional source-inventory and Meta history audit after the 489-test
credential-free regression passed on current code. Push is audit-only and must
never invoke media_publish, upload video, or phone notifications.
