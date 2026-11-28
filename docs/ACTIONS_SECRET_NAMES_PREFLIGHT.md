# GitHub Actions secret-name preflight

`actions_secret_names_preflight.py` checks the names of credentials used by
the 985 dashboard's YouTube reporting. It never requests or prints secret
values. Drive-backed utilities are optional and do not block the core
monitoring preflight.

Required names:

- `TOKEN_CHANNEL1_JSON`
- `TOKEN_CHANNEL2_JSON`

Optional integrations:

- `DRIVE_TOKEN_JSON` enables Drive-backed audits, analytics archive reads, the
  durable backup, and legacy Drive-based publishing paths. It is not required
  for the core YouTube/Meta monitoring preflight.
- NTFY: either `NTFY_TOPIC_URL` or `NTFY_TOPIC` is sufficient.

Run from the repository root after authenticating GitHub CLI as
`emirhankaya985-cloud`:

```powershell
gh auth switch --user emirhankaya985-cloud
python actions_secret_names_preflight.py
```

Exit code `0` means the two required names are present. The output field
`required_names_present` makes no claim about optional Drive features or live
connectivity. Exit code `2` lists missing
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
The manual Drive audit workflow is guarded by `AUTOMATION_ENABLED`; the legacy
Drive publisher is also disabled by that switch. Optional Drive consumers are:

| Code/workflow | Drive operation | Folder ID or source |
| --- | --- | --- |
| `connection_audit.py:new_youtube_preflight` and `candidate_inventory` via `.github/workflows/connection_audit.yml` | Read-only `files.get` / `files.list` for candidate videos and TXT files | Daily Laugh Lab `137--TeBht1yikZpMfV9VSEADbKuXZtLT`; Gönle Düşen `1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt` |
| `analytics_sheets.py:load_archive_records` via `.github/workflows/analytics_sheets_sync.yml` | Read-only download of existing analytics JSONL | `ANALYTICS_DRIVE_FOLDER_ID`, default `1oX3LwQyxofYYxUirJSSv9E2SI3mOJ2uo`; compatibility search for `Auto Video Publisher Analytics` folder |
| `analytics_sheets.py:_drive_publications` via `.github/workflows/analytics_sheets_sync.yml` | Read-only publication metadata/appProperties reads across account folders | `DRIVE_FOLDER_ID`, `DAILY_LAUGH_DRIVE_FOLDER_ID`, `GONLE_DUSEN_DRIVE_FOLDER_ID`; Film default `1NvEuGQ83BmCMrzdK6ziI1nC_0zzshqJW`; ToonZone default `14ee4AnUdf03dYUAdtfpHa-E9Zxyh4UZF` |
| `durable_backup.py:persist` via `.github/workflows/publication_backup.yml` | Writes and verifies a private content-addressed recovery archive | Private folder discovered/created by marker; no fixed folder ID |

The publishing schedule in this repository is a separate product path; the
current Meta-only public-link route does not need this Google Drive OAuth
secret. Keep `DRIVE_TOKEN_JSON` optional unless one of the listed Drive-backed
features is deliberately enabled. Do not reconnect or copy credentials from
another repository for this name-only check. This tool does not edit secrets
or variables, enable automation, start a workflow, send a notification, or
publish media.

Run the offline unit tests with:

```powershell
python -m unittest -v test_actions_secret_names_preflight.py
```
