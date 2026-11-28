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

The check does not validate secret contents, OAuth scopes, Google Drive access,
YouTube channel identity, or publication permissions. Use the existing
read-only connection checks for those. It does not edit secrets or variables,
enable automation, start a workflow, send a notification, or publish media.
Keep the legacy `AUTOMATION_ENABLED` switch unchanged; the active Meta-only
schedule is separate from the legacy OAuth/YouTube utilities.

Run the offline unit tests with:

```powershell
python -m unittest -v test_actions_secret_names_preflight.py
```
