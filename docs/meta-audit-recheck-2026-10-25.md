# Final read-only Meta account verification recheck — October 25, 2026

This marker triggers the updated read-only Meta audit only after merge into main. It does not dispatch Meta posts, daily statistics reports, credentials updates or Drive mutations.

If `META_APP_ID` and `META_APP_SECRET` are not configured, the token expiry introspection is explicitly reported as unverified rather than creating a false token-revocation error. Page identity and granted permissions remain verified through live GET requests.
