# Advanced operations — six features (staged)

Scope: Only the existing Meta publisher and daily report. No second publisher,
auto-secret rotation, new paid host, media POST testing, removal of state,
rights bypass, or automatic production restore.

1. **Visual similarity:** media_similarity.py hashes three frames of the
original source MP4 before ToonZone cover rendering. A strict same-route and
same-platform match blocks all new Meta POSTs, preserves previous state and
marks the current intent held for review. Legacy posts lacking fingerprints
cannot be retrospectively compared. Low-information frames are ignored.
The owner-requested rollout enables ADVANCED_DEDUPE_ENABLED in the normal
workflow unless its repository variable is explicitly false. Tests explicitly
disable the gate except for isolated fingerprint tests. Legacy posts without
fingerprints are still not retrospectively compared.
Existing #79 caption-alias PR is independent and should not be replaced blindly.

2. **Better hours:** adaptive_publish_times.py joins saved views and engagement
to actual ledger post IDs, refusing missing counts and duplicate observations.
A new nightly read-only recommendation artifact needs four distinct posts over
three days in the last 30 days. No schedule or Film/ToonZone ordering change
was made in the initial staged release. The follow-up adaptive policy may
select five corroborated hours for Tarladaki/Penguen/Gonle only, for the NEXT
Istanbul day. Every selected hour needs four posts over three days on BOTH
Facebook and Instagram. Film/ToonZone and Daily Laugh clocks are unchanged.
The first policy (including fallback) is frozen in the publication ledger for
the day; later reports cannot move that day's remaining slots. Insufficient
data preserves existing slots. ADAPTIVE_SCHEDULE_ENABLED=false disables this.

3. **Speech subtitles:** offline_subtitles.py generates SRT only from speech
decoded by an already installed, local faster-whisper model; no fabricated
dialogue from descriptive TXT. It does not download weights, publish clips
or burn captions in. Model/compute and safe automatic production integration
are now wired into local preparation for film/film_second Turkish speech.
AUTO_SUBTITLES_ENABLED=true opts into a cached, commit-pinned Systran small
model downloaded on the Actions runner. SRT and redacted receipts are archived.
Captions are burned into a derived MP4; original Drive bytes are preserved.
Unverified-language routes are skipped. A preparation failure is recorded and
falls back to the original video; it never invents dialogue from TXT.
Real ASR quality/production acceptance remains separate from FFmpeg testing.

4. **Telegram control:** the existing owner-authenticated single worker accepts
/stok, /durdur, /devam. Stock uses a read-only publisher artifact. Only when
TELEGRAM_CONTROL_ENABLED=true and a separate authorized GITHUB_CONTROL_TOKEN
exists do /durdur and /devam PATCH the existing scheduled-automation variable
and then verify it by GET. Running tasks, manual dispatch and rights gates
are unaffected. A permanent online worker is not created by the code;
never start another competing Telegram getUpdates/webhook consumer.

5. **Token and rate early warnings:** Meta's existing single
META_ACCESS_TOKEN discovery stays intact. A GET-only preflight inspects
X-App-Usage and X-Page-Usage; 80% triggers warning and 95% triggers fail-closed
preflight before any video POST. Missing headers are unknown, not 0.
Token code 190/463 proves expiry. Meta token expiry time cannot be
guaranteed or fabricated from an opaque string.

6. **Safe recovery decision:** the decision helper never permits automatic
reposting for ambiguous writes. Existing publisher_recovery.py and the
production recovery runbook remain authoritative. No new auto POST
retry, state deletion, auto-restore or forced recovery is added.

## Acceptance and rollback

Run the new secretless advanced_operations_ci workflow and existing publisher
regressions. Only after passing CI and GET-only/source-local verification should
the live duplicate gate be enabled. Offline tests do not establish live Telegram,
ASR model, scheduled recommended-hour changes or actual social posts.
Rollback: set ADVANCED_DEDUPE_ENABLED=false, AUTO_SUBTITLES_ENABLED=false and
ADAPTIVE_SCHEDULE_ENABLED=false; revert only these changes, preserve
all history/claims/intents and remote IDs. All features use 0 TL additional
services. Optional ASR runs on the existing Actions runner with a model cache;
no separate paid server is created.
