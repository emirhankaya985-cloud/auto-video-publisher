"""Read-only readiness check before the owner's corrected Instagram restart."""
import json
from pathlib import Path
import publisher_alert_history as archive
from public_link_runtime import FOLDERS, inventory, graph_rows, download, probe
from threads_toonzone_season import ordered_catalog
from toonzone_instagram_season import page_for_toonzone, instagram_identity, graph_get, NAMES, WORKFLOW

ROOT = Path("toonzone-instagram-restart-audit")


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    page = page_for_toonzone()
    user_id = instagram_identity(page)
    live = graph_rows(page, "instagram")
    live_ids = {str(row["id"]) for row in live}
    history = archive.restore(names=NAMES, workflow_path=WORKFLOW)
    old = [row for row in history["records"].values() if row.get("post_id")
           and row.get("user_id") == user_id and row.get("route") == "toonzone"]
    visible_old = [row for row in old if str(row["post_id"]) in live_ids]
    videos = ordered_catalog(inventory(FOLDERS["toonzone"]))
    covers = inventory(FOLDERS["covers"])
    matches = []
    for video in videos:
        name = Path(video["name"]).stem + ".png"
        cover = covers.get(name)
        matches.append(dict(video_id=video["id"], file=video["name"],
                            episode=video["episode"], part=video["part"],
                            cover_file=name, cover_id=cover["id"] if cover else None))
    first = next((row for row in matches if row["cover_id"]), None)
    cover_check = None
    if first:
        path = download(first["cover_id"], ROOT / first["cover_file"])
        streams = [s for s in probe(path).get("streams", []) if s.get("codec_type") == "video"]
        if not streams:
            raise RuntimeError("matched_cover_not_readable")
        cover_check = dict(file=first["cover_file"], width=streams[0].get("width"),
                           height=streams[0].get("height"), bytes=path.stat().st_size)
    try:
        container_status = graph_get(page, "17911307358580142", "id,status_code,status").get("status_code")
    except Exception as exc:
        container_status = type(exc).__name__
    data = dict(measured_at=archive.now_utc().isoformat(), instagram_id=user_id,
                visible_videos=len(live), cancelled_campaign_posts_still_visible=len(visible_old),
                cancelled_campaign_post_ids_still_visible=[str(row["post_id"]) for row in visible_old],
                catalog_parts=len(videos), exact_cover_matches=sum(bool(row["cover_id"]) for row in matches),
                first_matched_cover_check=cover_check, previous_failed_container_status=container_status,
                matches=matches, publishing_attempted=False)
    (ROOT / "readiness.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("INSTAGRAM_RESTART_AUDIT " + json.dumps({k: v for k, v in data.items() if k != "matches"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
