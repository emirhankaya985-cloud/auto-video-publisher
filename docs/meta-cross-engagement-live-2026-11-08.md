# Authorized bounded Meta engagement activation — 8 November 2026

Owner request: stop operating solely in `dry_run`; prioritize the Instagram/Facebook cross-account engagement pipeline now, leaving YouTube remediation for later.

This merge marker triggers ONE bounded real attempt on main. The scheduled runner also attempts at most ONE verified official-API like per 15-minute tick; never bulk 332 actions. A zero-eligible tick makes zero provider writes.

Safety constraints:
- Only previously confirmed, original Meta publication IDs from a checked source run within the verified recent window.
- Owner/source and actor identity, API grants, and supported operations verified on every attempt.
- No self-likes. No save/repost writes; those remain disabled or unsupported by the validated provider API.
- Reserve a durable ledger artifact before external POST. Never repeat ambiguous POSTs, and respect Meta provider restrictions including Graph code 368.
- Send Telegram receipt only for a confirmed accepted like; a successful workflow status alone is not proof of an accepted like.
- Manual GitHub dispatch remains audit-only and focus-scoped. Do not alter video publication schedules, OAuth, Threads, or YouTube.
- Initial live acceptance requires `cross-engagement-result` with `instagram/like/accepted` or `facebook/like/accepted`, plus archived intent and evidence from Graph responses.
