"""Deterministic Vietnamese lexical and precise-location signals."""

import re
import unicodedata


def normalize_text(text: str) -> str:
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
        if not unicodedata.combining(char)
    )
    text = re.sub(r"\b([a-z]{1,3})[.\-]+(\d{1,4})\b", r"\1\2", text)
    text = re.sub(r"\b([a-z])\s+(\d{1,4})\b", r"\1\2", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def location_tokens(text: str) -> list[str]:
    text = normalize_text(text)
    rooms = re.findall(r"\b[a-z]{1,3}\d{1,4}\b", text)
    numbered_rooms = re.findall(r"\bphong(?: hoc)? (\d{1,4})\b", text)
    halls = re.findall(r"\bhoi truong ([a-z0-9]+)\b", text)
    return sorted({*("room:" + room for room in rooms + numbered_rooms),
                   *("hall:" + hall for hall in halls)})


def rank_candidates(semantic, lexical, locations, query_locations, limit=200):
    """Fuse exact cosine and lexical ranks with a bounded location tie-break."""
    candidates, scores = {}, {}
    # shortcut: location weight is a regression baseline; calibrate it on labelled Findie queries.
    for channel, weight in ((semantic, 1.0), (lexical, 1.0), (locations, 0.03)):
        for rank, candidate in enumerate(channel, 1):
            item_id = str(candidate["item_id"])
            candidates[item_id] = candidate
            scores[item_id] = scores.get(item_id, 0.0) + weight / (60 + rank)
    query_locations = set(query_locations)
    ordered = sorted(candidates, key=lambda item_id: (
        -scores[item_id],
        -len(query_locations.intersection(candidates[item_id]["location_tokens"])), item_id,
    ))
    return [{
        "itemId": item_id,
        "documentVersion": candidates[item_id]["document_version"],
        "sourceId": str(candidates[item_id]["source_id"]),
        "sourceVersion": candidates[item_id]["source_version"],
        "sourceSha256": candidates[item_id]["source_sha256"],
    } for item_id in ordered[:limit]]
