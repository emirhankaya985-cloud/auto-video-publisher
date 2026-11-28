# GitHub Actions secret-name preflight

`actions_secret_names_preflight.py` checks whether the 985 repository has the
required Actions secret **names** for the legacy Drive/YouTube utilities. It
never requests or prints secret values.

Required names:

- `DRIVE_TOKEN_JSON`
- `TOKEN_CHANNEL1_JSON`
- `TOKEN_CHANNEL2_JSON`

NTFY is optional; either `NTFY_TOPIC_URL` or `NTFY_TOPIC` is sufficient for the
name-only check.

Run from the repository root after authenticating GitHub CLI as
`emirhankaya985-cloud`:

```powershell
gh auth switch --user emirhankaya985-cloud
python actions_secret_names_preflight.py
```

Exit code `0` means all required names are present. Exit code `2` lists missing
required names. Exit code `1` means the check could not safely inspect this
repository (for example, the wrong GitHub CLI identity or insufficient read
access). Output contains booleans, fixed secret names, and a `secret_values_read:
false` marker only.

This is an inventory check, not an OAuth readiness result. It does not validate
secret contents, OAuth scopes, Google Drive access, YouTube channel identity,
or publication permissions. In particular, a present `TOKEN_CHANNEL*_JSON`
name does not prove that its value is a refreshable authorized-user credential
or that it belongs to the expected channel.

OAuth/channel verification is a separate check: `youtube_readonly_connection.py`
checks one configured target at a time and reports only safe status fields. Its
offline tests are:

```powershell
python -m unittest -v test_youtube_readonly_connection.py
```

Those tests use mocks and do not validate the real GitHub secret values. The
GitHub connection workflow is also guarded by `AUTOMATION_ENABLED`; this
name-only preflight does not invoke it or change that switch. Treat OAuth and
Drive access as **unverified** until an authorized read-only connection check
has actually completed. This tool does not edit secrets or variables, enable
automation, start a workflow, send a notification, or publish media. Keep the
legacy `AUTOMATION_ENABLED` switch unchanged; the active Meta-only schedule is
separate from the legacy OAuth/YouTube utilities.

Run the offline unit tests with:

```powershell
python -m unittest -v test_actions_secret_names_preflight.py
```
