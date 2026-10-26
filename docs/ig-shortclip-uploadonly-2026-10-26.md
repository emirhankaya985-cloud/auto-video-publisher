# 26 October 2026 — One-time Film & ToonZone 15-second upload-only test

This document is an exact allowlisted **one-time GitHub Actions push marker**.

The allowed operation: for each rights-enabled Film / ToonZone route, read only
the exact original MP4 from its already-approved public Drive folder, cut a
15-second H.264/AAC compatibility test clip using the 112 kbps AAC encoder,
create a new *unpublished* Instagram resumable media container, transfer only
that short diagnostic media, poll until FINISHED, then **stop before media_publish**.

No posting to Instagram or Facebook, no changes to the existing two old
IN_PROGRESS containers, no clearing uncertain claim/intent state, no new video
in public profiles, no upload from disallowed files or accounts. Existing saved
Page/IG identities and route + rights switches are mandatory.

A successful short clip only confirms that a short file processes; it does not
prove that full 180s Reel will publish. If this fails, preserve safe error type
and stage; never reuse/retry old Reel intents automatically.

Existing 26 October 2026 production state: Film Part16 and ToonZone Part3
Instagram are still unverified; both already-confirmed Facebook Part posts
remain preserved. Same prior full-length media gave rupload HTTP400
ProcessingFailedError; an amended sound-bitrate validator was merged through
PR #13, but no new Reel or permission to replay was claimed.

## 26 October targeted follow-up, no media publication

Live full-length 720p/96kbps recoveries on run 40281812561 both failed before media_publish at rupload with HTTP 400 ProcessingFailedError. Trigger the existing 15-second diagnostic exactly for these sources, only with publish=False, do not change stored production intents. Record result in evidence issue #11. Never blindly retry the 180-second Reels.
