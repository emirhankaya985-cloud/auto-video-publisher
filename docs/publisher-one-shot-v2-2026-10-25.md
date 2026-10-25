# One-time real Meta publish marker v2

User authorization: immediately complete the existing Meta-only automation
without requiring a manual Actions button. Created exactly once on main.

The guarded publisher uses git diff HEAD^ HEAD and an exact commit subject to
verify this newly added marker. Subsequent edits cannot re-authorize a publish.
The existing remote-history reconciliation, rights gates, state intent
persistence, duplicate protection, and per-post notifications remain mandatory.

Do not turn on legacy OAuth or YouTube routes. Do not erase old intent/state or
retry uncertain Meta posts. Missing or unapproved ToonZone covers stay on hold.
Success requires a real post_id for each successfully published platform item.
