# ToonZone S01E04–S01E12: historical receipts and current publication acceptance

Recorded 9 November 2026 (Türkiye). This record is evidence-based, not a claim that every historic Reel is still visible.

## Proven historical Meta publishing (36 ordered parts × 2 platforms)

- **Facebook:** 36/36 unique numeric post IDs recorded as `done` for the exact source file, route, and original run ID.
- **Instagram:** 36/36 unique numeric media IDs recorded as `done`. All 36 original `media_publish kabul edildi` lines and original Instagram Reel permalinks were independently found in the actual GitHub Actions logs.
- The 35 distinct original Meta workflow runs covering the 36 parts were checked. All 36 Facebook and 36 Instagram post-ID receipt lines are present in those run logs. A whole-workflow `failure` can coexist with successful individual ToonZone Meta POSTs because other routes/jobs failed.
- Original receipt examples:
  - S01E04 Part1: [run 40479513634](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40479513634): FB `2296740134458494`; IG `18100507712530539`; original [IG Reel permalink](https://www.instagram.com/reel/De_lnslEsPH/).
  - S01E09 Parts1–3: [run 41331077663](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41331077663), 3 FB and 3 IG accepted posts, despite overall workflow failure.
  - S01E12 Part4: [run 42472667230](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42472667230): FB `2242223253301365`; IG `17925740985443101`; original [IG Reel permalink](https://www.instagram.com/reel/DfekzDBjlA0/).
- Durable original state: [run 42521169732](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42521169732), `link-state-result` artifact `13633826021`, `state.json`, `toonzone:{facebook|instagram}:{source_id}`.
- **Historical publication receipt acceptance: PASS (72/72).** This is NOT proof of current visibility, cover bytes, or content rights clearance by Meta.

## Current owned-account list verification (read-only)

Source: [run 42527047105](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42527047105), artifact `toonzone-4-8-readonly-audit`, id `13636360306`. Same ToonZone FB page `1298191963387372` and IG account `17841477404255851`.

| Platform | Historic done + post ID | Exact historic ID seen in current owned media list | Not present in list (NOT proof of deletion) |
|---|---:|---:|---:|
| Facebook | 36 | 36 | 0 |
| Instagram | 36 | 5 | 31 |

- The separate current Instagram media list contained 31 videos. Exactly 5 of the 36 original S01E04–E12 IG IDs were present.
- Specifically S01E04–S01E08 **20/20** historical IG media IDs did not appear in the current IG media list. Their individual Graph GET and alternate owner-free/username/basic reads returned HTTP400 Graph code `100` subcode `33`. A different currently listed IG media ID was readable with HTTP200 and the exact correct owner. **This proves an access/object visibility mismatch, not deletion or permission to repost.**
- Facebook `/videos` listed 51 videos in the latest read and 36/36 original S01E04–E12 Facebook IDs were present. Only six current FB captions used the S01E04–12 Part markers; other title formats do not invalidate exact-ID matches.
- Drive inventory: 36/36 requested MP4 source names and 36/36 exact matching PNG cover names exist. A new **real Drive byte-level audit** (below) successfully downloaded and validated all 36 PNGs. The full MP4 bytes, posted first-frame equivalence and remote Instagram thumbnail remain unverified.

## Operational acceptance and next technical gate

1. HISTORICAL_META_POST_ACCEPTANCE: **PASS** (36 FB + 36 IG genuine prior publishing receipts).
2. CURRENT_FB_POST_ID_VISIBILITY: **PASS 36/36** (ID presence only, not a thumbnail/content comparison).
3. CURRENT_IG_POST_ID_VISIBILITY: **BLOCKED, 5/36 visible, 31/36 currently unmatched**.
4. DRIVE_EXACT_COVER_PNG_BYTES: **PASS 36/36** (full decode, original exact names, unique SHA256 for every part). COVER_FIRST_FRAME_AND_REMOTE_THUMBNAIL: **UNVERIFIED**.
5. NEW_POSTS_CREATED_BY_THIS_ACCEPTANCE_AUDIT: **0**. Never claim a new publish from a green read-only workflow.
6. Do not clear archived `done`/intent state or issue any replacement IG POST for one of the 31 absent IDs without independent exact account/published-media reconciliation or explicit confirmed removal plus source/cover/rights safety. Provider code100/33 alone is never a deletion certificate.
7. User opted out of failure notifications. Persist errors and evidence in GitHub silently; retain success receipts and the requested 23:59 report. Hourly ToonZone/Film rescue automation carries this evidence; no duplicate notification automation needed.

Implementation PRs: [#201](https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/201) 36-source/cover and FB candidates, [#203](https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/203) canonical owner-free IG GET fallback, [#204](https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/204) historic-vs-current 72-receipt acceptance accounting.


## 9 Kasım — 36 kapak dosyası gerçek byte kabulü

- Implementation [PR #207](https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/207) merged main. Live read-only [GitHub run 42527916806](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42527916806) **success**, artifact `toonzone-36-cover-byte-acceptance` ID `13636431458`, `result.json`.
- The actual public Drive PNG file for **each of the 36 S01E04–E12 parts** was downloaded into a temporary directory, checked for PNG magic, PIL structural validation, complete decoded pixel data, dimensions and SHA256. **36/36** validated; **0** missing, corrupted or duplicate-byte covers.
- Example: S01E04 Part1 original exact PNG `S01E04_Death_Punchies_Part1.png`, **1086×1448**, SHA256 `e46f65513e118ecaaf905976ab865470a34a0c5f27287a15bae1c2cf75225197`.
- **New provider writes: 0**. This proves file integrity and exact filename-to-part identity, but NOT that Instagram's historical published video still exists, nor that the remote media thumbnail matches that source cover. Do not call all 72 media currently accessible.
- The old 20 IG Graph 100/33 responses and 31/36 missing live-list IDs remain outstanding provider visibility matters. Never blind-republish old source IDs; retain all 72 historical post receipts.
