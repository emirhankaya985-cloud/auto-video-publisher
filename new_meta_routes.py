"""Disabled-by-default definitions and dry-run validation for new Meta routes.

This module deliberately contains no upload call. Activation requires verified
Meta identities, an explicit rights approval and a separate production change.
"""
from dataclasses import dataclass

from ordered_channels import CARTOON_FOLDER_ID, FILM_FOLDER_ID
from cover_artwork import CoverScope, match_toonzone_cover

DAILY_LAUGH_FOLDER_ID = "137--TeBht1yikZpMfV9VSEADbKuXZtLT"
EXCLUDED_META_PAGES = frozenset({"Dizimaratonu"})


@dataclass(frozen=True)
class MetaTarget:
    key: str
    page_name: str
    platform: str
    page_id: str | None = None


@dataclass(frozen=True)
class MetaRoute:
    key: str
    folder_id: str
    targets: tuple[MetaTarget, ...]
    selection: str
    language: str
    enabled: bool = False


ROUTES = {
    "film": MetaRoute(
        "film", FILM_FOLDER_ID,
        (
            MetaTarget("film_magrasi_fb", "Film Mağarası", "facebook", "1239298989276639"),
            MetaTarget("filmmagrasi1_fb", "Filmmagrasi", "facebook", "854990964375370"),
            MetaTarget("film_magrasi_ig", "Film Mağarası", "instagram", "1239298989276639"),
        ),
        "ordered-film-part", "turkish", False,
    ),
    "toonzone": MetaRoute(
        "toonzone", CARTOON_FOLDER_ID,
        (
            MetaTarget("toonzone_fb", "ToonZone", "facebook"),
            MetaTarget("toonzone_ig", "ToonZone", "instagram"),
        ),
        "ordered-season-episode-part", "turkish", False,
    ),
    "daily_laugh_instagram": MetaRoute(
        "daily_laugh_instagram", DAILY_LAUGH_FOLDER_ID,
        (MetaTarget("daily_laugh_ig", "Daily Laugh Lab", "instagram"),),
        "random-unused", "english", False,
    ),
}


def verified_pages(meta_auth):
    """Return exact configured identities, rejecting duplicate names and exclusions."""
    pages = {}
    for page in meta_auth.get("pages", []):
        name = str(page.get("page_name") or "").strip()
        if not name or name in EXCLUDED_META_PAGES:
            continue
        if name in pages:
            raise RuntimeError(f"Meta sayfa adı tekil değil: {name}")
        if not page.get("page_id") or not page.get("page_token"):
            raise RuntimeError(f"Meta sayfa kimliği eksik: {name}")
        pages[name] = page
    return pages


def page_for_target(meta_auth, target):
    pages = verified_pages(meta_auth)
    if target.page_id:
        page = next((row for row in pages.values() if str(row.get("page_id")) == str(target.page_id)), None)
        if page:
            return page
    return pages.get(target.page_name)


def dry_run_route(route_key, meta_auth, selected_video, rights_approved=False):
    """Validate exact identities and create a non-publishing target plan."""
    route = ROUTES[route_key]
    if route.enabled:
        raise RuntimeError("Yeni rota dry-run sırasında açık olmamalı")
    if rights_approved is not True:
        raise RuntimeError("Telif/kullanım hakkı doğrulanmadı")
    if route.folder_id not in (selected_video.get("parents") or []):
        raise RuntimeError("Drive parent allowlist eşleşmedi")
    pages = verified_pages(meta_auth)
    plan = []
    for target in route.targets:
        page = page_for_target(meta_auth, target)
        if page is None:
            raise RuntimeError(f"Meta hedefi doğrulanmadı: {target.page_name}")
        account_id = page["page_id"]
        if target.platform == "instagram":
            account_id = page.get("instagram_id")
            if not account_id:
                raise RuntimeError(f"Instagram hesabı doğrulanmadı: {target.page_name}")
        plan.append({
            "route": route.key,
            "target": target.key,
            "platform": target.platform,
            "account_id": str(account_id),
            "drive_file_id": selected_video["id"],
            "drive_folder_id": route.folder_id,
            "publishing_enabled": False,
        })
    return plan


def assert_same_film_file(plan):
    ids = {row["drive_file_id"] for row in plan}
    if len(ids) != 1 or len(plan) != 3:
        raise RuntimeError("Film üç hedefi aynı Drive dosyasını kullanmalı")
    return True


def toonzone_metadata_draft(content_review, rights_approved=False):
    """Build Turkish metadata only from an explicit, verified content review."""
    if rights_approved is not True:
        raise RuntimeError("Telif/kullanım hakkı doğrulanmadı")
    if not isinstance(content_review, dict) or content_review.get("verified") is not True:
        raise RuntimeError("Çizgi film içeriği doğrulanmadı")
    if content_review.get("language") != "tr":
        raise RuntimeError("Türkçe içerik doğrulaması yok")
    if content_review.get("concept") != "cartoon":
        raise RuntimeError("Çizgi film konsepti doğrulanmadı")
    title = str(content_review.get("title") or "").strip()
    summary = str(content_review.get("summary") or "").strip()
    if not title or not summary:
        raise RuntimeError("Doğrulanmış başlık veya içerik özeti eksik")
    if len(title) > 100 or len(summary) > 1800:
        raise RuntimeError("Metadata sınırı aşıldı")
    return {"title": title, "description": summary + "\n\n#çizgifilm #toonzone"}


def toonzone_asset_dry_run(selected_video, cover_files, cover_subfolder_id,
                           rights_approved=False):
    """Validate one ToonZone MP4 and its exact Drive cover without publishing."""
    if rights_approved is not True:
        raise RuntimeError("Telif/kullanım hakkı doğrulanmadı")
    if CARTOON_FOLDER_ID not in (selected_video.get("parents") or []):
        raise RuntimeError("ToonZone Drive parent allowlist eşleşmedi")
    cover = match_toonzone_cover(
        selected_video,
        cover_files,
        CoverScope("cartoon_tr", CARTOON_FOLDER_ID, cover_subfolder_id),
    )
    return {"video_id": selected_video["id"], "cover_id": cover["id"],
            "publishing_enabled": False}
