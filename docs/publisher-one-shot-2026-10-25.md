# Authorized one-shot Meta publish — 2026-10-25

User request: proactively finish and operate the existing Facebook/Instagram
automation without requiring manual GitHub Actions clicks.

This newly ADDED file, paired with commit message token
`authorized-once-meta-publish-2026-10-25`, is the sole one-time
production push gate. Editing this file later must NOT trigger publishing:
the workflow requires the exact path in head_commit.added.

Existing safety remains mandatory:
- First restore prior state and query live Meta account history.
- Do not republish an already-confirmed video.
- Never retry a possibly successful media_publish POST blindly.
- Preserve each publish intent before any upload, then result and error journal.
- Respect route pause/rights flags, missing captions and exact ToonZone covers.
- Keep user tags disabled unless separately opted in.
- Send Telegram and ntfy per confirmed platform publication, and record failures.
- Do not turn on YouTube or legacy OAuth publisher workflows.
- A green workflow without verified platform post IDs is not acceptance.

The operator explicitly requested immediate action. This file does not grant
any new external permissions or change secrets.
