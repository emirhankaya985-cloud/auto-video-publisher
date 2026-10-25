# Final read-only Meta account verification recheck — October 25, 2026

This marker triggers the updated read-only Meta audit only after merge into main. It does not dispatch Meta posts, daily statistics reports, credentials updates or Drive mutations.

If `META_APP_ID` and `META_APP_SECRET` are not configured, the token expiry introspection is explicitly reported as unverified rather than creating a false token-revocation error. Page identity and granted permissions remain verified through live GET requests.

## Follow-up verified source audit (separate safe push trigger)

The linked user requested proactive completion without manual Actions clicks.
This documentation-only update deliberately triggers the existing read-only
`meta_connection_audit.yml` on `main`. It checks page identities, permissions,
and, when configured, token validity; it does not dispatch or repeat any media
publication. A missing optional debug-token credential is not proof of a
revoked page token. Do not log token values.

## Post-CI current account recheck

This marker update triggers read-only Meta connection auditing after the latest
confirmed mock CI pass. This is not a new token request, not a media upload,
and not proof of a confirmed Facebook or Instagram post.
