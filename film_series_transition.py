"""Owner-authorized Film Mağarası series transition, source selection only.

Bıçkın Part 8 must remain held because the present Drive source visually
duplicates Part 3. This module selects an intact DIFFERENT series without
altering any old post, source ID, saved intent or legacy platform receipt.
Selection alone never grants permission to publish.
"""
from __future__ import annotations

import re

SERIES_PREFIX = "En_Buyuk_Saban"
EXPECTED_PARTS = 32
ALLOWED_ROUTES = frozenset({"film", "film_second"})
EXACT_MP4 = re.compile(r"^En_Buyuk_Saban_Part_([1-9][0-9]*)\.mp4$")


def switch_film_source(route, videos, catalog):
    """Allow only canonical Part 1..32 after all paired TXT files are present.

    Publication still requires the original Meta preflight, remote-history
    checks, exact captions, source preparation, dedupe and durable post IDs.
    All previous Bıçkın and Yoksul ledger records remain unchanged.
    """
    if route not in ALLOWED_ROUTES:
        return list(videos)
    if not isinstance(catalog, dict) or not isinstance(videos, list):
        raise ValueError("film_source_inventory_invalid")
    expected_video_names = {
        f"{SERIES_PREFIX}_Part_{p}.mp4" for p in range(1, EXPECTED_PARTS + 1)}
    expected_txt_names = {
        f"{SERIES_PREFIX}_Part_{p}.txt" for p in range(1, EXPECTED_PARTS + 1)}
    if not expected_video_names.issubset(catalog) or not expected_txt_names.issubset(catalog):
        raise RuntimeError("new_film_source_or_txt_incomplete")
    selected = []
    parts = set()
    for v in videos:
        if not isinstance(v, dict) or not isinstance(v.get("name"), str):
            raise ValueError("film_source_row_invalid")
        match = EXACT_MP4.fullmatch(v["name"])
        if not match:
            continue
        part = int(match.group(1))
        if part > EXPECTED_PARTS or part in parts or not str(v.get("id") or ""):
            raise ValueError("new_film_source_part_invalid")
        parts.add(part)
        selected.append(v)
    if parts != set(range(1, EXPECTED_PARTS + 1)):
        raise RuntimeError("new_film_source_selection_incomplete")
    return selected
