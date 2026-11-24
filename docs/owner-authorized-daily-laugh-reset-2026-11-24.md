# Owner-authorized Daily Laugh Lab state reset — 24 November 2026

This marker authorizes exactly one operational reset for the daily_laugh account.

- Remove active confirmed Meta and YouTube publication ledger rows (status=done with a real post ID) for Daily Laugh Lab so its internal completed count starts at zero.
- Preserve the complete prior state in a 90-day reset backup.
- Keep uncertain, held, and intent rows active so an ambiguous publish is never retried blindly.
- Keep every other account's publication ledger unchanged.
- Do not reset Film Mağarası, Filmmagrasi, or ToonZone.
- Do not delete Instagram/Facebook posts, alter Drive files, or change tokens.
- This resets the publisher's active receipt count; historical analytics and published platform posts remain.

No content-publishing workflow is authorized by this marker.\n\nThe reset includes Daily Laugh's YouTube receipt rows as well as Meta receipts. Public platform posts remain untouched.

The initial reset workflow stopped before changing any state because its artifact lookup command failed. This corrected workflow may perform the same single authorized reset once; no other account is in scope.
