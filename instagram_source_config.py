"""Validated, opt-in configuration for official Instagram source ingestion."""
from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

CONFIG_PATH = Path(__file__).with_name("instagram_source_accounts.json")
ROUTES = {
    "tarladaki", "penguen", "gonle", "daily_laugh", "film", "toonzone"
}
PLATFORMS = {"facebook", "instagram", "threads", "youtube"}
USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")
FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")


def _validate_source(source: object, route: str) -> dict:
    if not isinstance(source, dict):
        raise ValueError(f"{route}: source entry must be an object")
    username = str(source.get("username", "")).strip().lstrip("@").lower()
    if not USERNAME.fullmatch(username):
        raise ValueError(f"{route}: invalid Instagram username")
    for key in ("enabled", "rights_approved", "official_api_download_allowed"):
        if type(source.get(key)) is not bool:
            raise ValueError(f"{route}/{username}: {key} must be boolean")
    evidence = source.get("rights_evidence")
    if evidence is not None and (not isinstance(evidence, str) or len(evidence) > 500):
        raise ValueError(f"{route}/{username}: rights_evidence must be short text")
    if source["enabled"] and (not source["rights_approved"] or not (evidence or "").strip()):
        raise ValueError(f"{route}/{username}: enabled sources need rights approval and evidence")
    categories = source.get("content_categories", [])
    if (not isinstance(categories, list) or any(not isinstance(value, str)
            or not value.strip() or len(value) > 80 for value in categories)):
        raise ValueError(f"{route}/{username}: content_categories must be short strings")
    account_id = source.get("instagram_user_id")
    if account_id is not None and (not isinstance(account_id, str)
            or not re.fullmatch(r"[0-9]{1,30}", account_id)):
        raise ValueError(f"{route}/{username}: instagram_user_id must be numeric")
    return {**source, "username": username}


def validate_config(payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("Unsupported Instagram source config schema")
    if payload.get("timezone") != "Europe/Istanbul":
        raise ValueError("Instagram source schedules must use Europe/Istanbul")
    if payload.get("scan_interval_minutes") != 30:
        raise ValueError("Instagram source scan interval must remain 30 minutes")
    accounts = payload.get("accounts")
    if not isinstance(accounts, dict) or set(accounts) != ROUTES:
        raise ValueError("Instagram source config must define exactly the six active source routes")
    result = dict(payload)
    result["accounts"] = {}
    for route, account in accounts.items():
        if not isinstance(account, dict):
            raise ValueError(f"{route}: account config must be an object")
        for key in ("enabled", "auto_collection", "auto_publish", "preserve_serial_order"):
            if type(account.get(key)) is not bool:
                raise ValueError(f"{route}: {key} must be boolean")
        folder = account.get("target_folder_id")
        if not isinstance(folder, str) or not FOLDER_ID.fullmatch(folder):
            raise ValueError(f"{route}: target_folder_id is invalid")
        collection_folder = account.get("collection_folder_id", "")
        if collection_folder and (not isinstance(collection_folder, str)
                                  or not FOLDER_ID.fullmatch(collection_folder)):
            raise ValueError(f"{route}: collection_folder_id is invalid")
        platforms = account.get("target_platforms")
        if (not isinstance(platforms, list) or not platforms
                or len(platforms) != len(set(platforms))
                or any(platform not in PLATFORMS for platform in platforms)):
            raise ValueError(f"{route}: target_platforms are invalid")
        for key in ("daily_new", "daily_archive"):
            if type(account.get(key)) is not int or account[key] < 0 or account[key] > 20:
                raise ValueError(f"{route}: {key} must be between 0 and 20")
        cap = account.get("max_per_source_per_day", 2)
        if type(cap) is not int or cap < 1 or cap > 6:
            raise ValueError(f"{route}: max_per_source_per_day must be between 1 and 6")
        keywords = account.get("content_keywords", [])
        if (not isinstance(keywords, list)
                or any(not isinstance(word, str) or not word.strip() or len(word) > 80
                       for word in keywords)):
            raise ValueError(f"{route}: content_keywords must be a list of short strings")
        times = account.get("publish_times")
        if (not isinstance(times, list) or len(times) != len(set(times))
                or any(not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value)
                       for value in times)):
            raise ValueError(f"{route}: publish_times must contain unique HH:MM values")
        try:
            publish_timezone = ZoneInfo(account.get("publish_timezone", payload["timezone"]))
        except (TypeError, ValueError):
            raise ValueError(f"{route}: invalid publish_timezone") from None
        if account["auto_publish"] and not account["enabled"]:
            raise ValueError(f"{route}: auto_publish requires enabled=true")
        if account["auto_collection"] and not account["enabled"]:
            raise ValueError(f"{route}: auto_collection requires enabled=true")
        if account["auto_collection"] and not collection_folder:
            raise ValueError(f"{route}: auto_collection requires an isolated collection_folder_id")
        if account["auto_publish"] and account["preserve_serial_order"]:
            raise ValueError(f"{route}: serial routes cannot auto-publish unslotted source videos")
        if account["auto_publish"] and not account["auto_collection"]:
            raise ValueError(f"{route}: auto_publish requires auto_collection=true")
        sources = account.get("source_accounts")
        account_errors = []
        if not isinstance(sources, list):
            account_errors.append("source_accounts_must_be_list")
            sources = []
        normalized = []
        for source_index, source in enumerate(sources):
            try:
                normalized.append(_validate_source(source, route))
            except ValueError:
                # One malformed source must not disable independent routes.
                account_errors.append(f"source_{source_index + 1}_invalid_or_unapproved")
        usernames = [source["username"] for source in normalized]
        if len(usernames) != len(set(usernames)):
            account_errors.append("duplicate_source_usernames")
            normalized = list({source["username"]: source for source in reversed(normalized)}.values())
        if account["auto_publish"] and not any(
                source["enabled"] and source["rights_approved"]
                and source["official_api_download_allowed"] for source in normalized):
            account_errors.append("auto_publish_has_no_authorized_sources")
        if account["auto_publish"] and any(platform not in {"facebook", "instagram"}
                                             for platform in platforms):
            account_errors.append("unsupported_target_platform_for_source_publisher")
        if collection_folder and collection_folder == folder:
            account_errors.append("collection_folder_not_isolated")
        if account["auto_collection"] and not any(
                source["enabled"] and source["rights_approved"]
                and source["official_api_download_allowed"] for source in normalized):
            account_errors.append("auto_collection_has_no_authorized_sources")
        result["accounts"][route] = {**account, "publish_timezone": str(publish_timezone),
                                     "source_accounts": normalized,
                                     "config_errors": sorted(set(account_errors))}
    collection_routes: dict[str, list[str]] = {}
    for route, account in result["accounts"].items():
        folder_id = account["collection_folder_id"]
        if isinstance(folder_id, str) and folder_id:
            collection_routes.setdefault(folder_id, []).append(route)
    for routes in collection_routes.values():
        if len(routes) > 1:
            for route in routes:
                account = result["accounts"][route]
                account["config_errors"] = sorted(set(account["config_errors"])
                                                   | {"collection_folder_reused_by_routes"})
    return result


def load_config(path: str | Path = CONFIG_PATH) -> dict:
    with Path(path).open(encoding="utf-8") as source:
        return validate_config(json.load(source))


def collection_targets(config: dict) -> dict[str, dict]:
    """Return only targets explicitly enabled at both account and collection levels."""
    return {
        route: account for route, account in config["accounts"].items()
        if account["enabled"] and account["auto_collection"] and not account.get("config_errors")
        and any(source["enabled"] and source["rights_approved"]
                and source["official_api_download_allowed"]
                for source in account["source_accounts"])
    }


def due_publish_routes(config: dict, now: datetime | None = None) -> list[str]:
    """Routes whose configured local publication time matches the given instant."""
    now = now or datetime.now(ZoneInfo("Europe/Istanbul"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Europe/Istanbul"))
    else:
        now = now.astimezone(ZoneInfo("Europe/Istanbul"))
    due = []
    for route, account in config["accounts"].items():
        local = now.astimezone(ZoneInfo(account["publish_timezone"]))
        slot = local.strftime("%H:%M")
        if (account["enabled"] and account["auto_collection"] and account["auto_publish"]
                and account["collection_folder_id"] and not account.get("config_errors")
                and any(source["enabled"] and source["rights_approved"]
                        and source["official_api_download_allowed"] for source in account["source_accounts"])
                and slot in account["publish_times"]):
            due.append(route)
    return due


def active_publish_account(route: str, *, config: dict | None = None) -> dict | None:
    if route not in ROUTES:
        return None
    config = config or load_config()
    account = config["accounts"][route]
    if (account["enabled"] and account["auto_collection"] and account["auto_publish"]
            and account["collection_folder_id"]
            and not account.get("config_errors")
            and any(source["enabled"] and source["rights_approved"]
                    and source["official_api_download_allowed"] for source in account["source_accounts"])
            and not account["preserve_serial_order"]):
        return account
    return None
