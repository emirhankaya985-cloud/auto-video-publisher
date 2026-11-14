# YouTube OAuth on the 985 GitHub repository — safe recovery

**Current read-only evidence (14 Nov 2026):** four channel routes failed token refresh with `oauth_refresh_rejected` in [the 985 YouTube action](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/43633715452). This is **not** evidence of successful YouTube uploads or of an incorrect channel. Google might reject a revoked/expired refresh token, deleted/mismatched client, or an app in `Testing` whose refresh token expired after 7 days. The precise cause is not proven by the redacted result.

## Windows — one owner-initiated command for two priority channels (or all four)

1. On the **correct Google Cloud OAuth project**, confirm the consent screen's publishing status and download the **Desktop app OAuth client JSON** into this local repository folder as `client_secrets.json`. Do not put it in Git, Drive, chat, or an artifact. If the app is still in `Testing`, Google can issue refresh tokens that expire after seven days. Do not change the Cloud app or project without reviewing its consent implications.
2. Install Python and [GitHub CLI](https://cli.github.com/); authenticate `gh auth login` as **emirhankaya985-cloud**. In PowerShell inside the repository, install the pinned Python dependencies if necessary with `python -m pip install --require-hashes -r requirements.txt`.
3. Run `.\youtube_oauth_renew_windows.ps1` for **Tarladaki Fasulye** and **Beyinsiz Penguen**; for all four configured channels, use `.\youtube_oauth_renew_windows.ps1 -AllFour`. Each channel requires its own browser consent and Google channel selection. The script rejects an incorrect channel identity before writing local credentials. `--renew` atomically replaces an expired local token only after successful exact-ID verification. It uses GitHub CLI stdin to store the refreshed authorized-user JSON into the corresponding Actions Secret and starts an independent read-only verification per channel.

Channel and secret bindings (immutable IDs; do not substitute channel titles):
- `channel1` Tarladaki Fasulye — `UCrUF3mT4oF26JNBLcyKPcGQ` — `TOKEN_CHANNEL1_JSON`
- `channel2` Beyinsiz Penguen — `UCUG-NSyXpEt9PLt5RS4iumw` — `TOKEN_CHANNEL2_JSON`
- `daily_laugh` Daily Laugh Lab — `UCF4KwI3alXzlExviMFmmJAA` — `TOKEN_DAILY_LAUGH_LAB_JSON`
- `gonle_dusen` Gönle Düşen — `UCvSvo5WghuXqsjwLRmIz22g` — `TOKEN_GONLE_DUSEN_JSON`

Evidence: [YouTube read-only workflow](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/workflows/youtube_readonly_connection.yml) and [985 Actions Secrets settings](https://github.com/emirhankaya985-cloud/auto-video-publisher/settings/secrets/actions).

**Never** commit token JSON or `client_secrets.json`, paste a refresh token into chat, or change any `YOUTUBE_PUBLISHING_ENABLED` gate until each expected channel identity is verified independently. A successful `channels.list` proves identity, not `videos.insert` permission and not a published video.
