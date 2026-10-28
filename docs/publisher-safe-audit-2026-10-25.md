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

## 28 October 2026 — verified film source-copy audit

After PR #30 and 599 passing regression cases, inspect the live catalog and exact existing remote post for the two Avanak Apti Part 3 sources. Require MP4 validation and equal full byte SHA-256 before recording a local alias to the confirmed old post. Expected report: DUPLICATE VERIFIED for the already-published Part 3 copy and NEXT for the ordered Part 4. This is audit-only, with no Meta uploads, media_publish, phone notifications, remote source/claim mutation or rights bypass. Actual Part 4 publication must be observed independently from a normal scheduled run.
