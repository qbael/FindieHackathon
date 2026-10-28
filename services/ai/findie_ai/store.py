import asyncio
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from findie_ai.ranking import location_tokens, normalize_text, rank_candidates


class SnapshotConflict(ValueError):
    pass


class Store:
    def __init__(self, dsn, model_id, revision, dimensions, processing_profile="text-v1"):
        self.dsn = dsn
        self.identity = (model_id, revision, dimensions, processing_profile)
        self.dimensions = dimensions

    async def migrate(self):
        async with await psycopg.AsyncConnection.connect(self.dsn) as connection:
            await connection.execute(Path(__file__).with_name("schema.sql").read_text())

    async def check(self):
        async with await psycopg.AsyncConnection.connect(self.dsn) as connection:
            await connection.execute("""SELECT d.embedding <=> d.embedding, i.document_version
                                        FROM ai_documents d JOIN ai_items i USING (item_id) LIMIT 0""")

    def _vector(self, vector):
        if len(vector) != self.dimensions or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in vector
        ) or not any(vector):
            raise ValueError("Embedding must contain the configured number of finite, nonzero values.")
        return json.dumps(vector, allow_nan=False)

    async def upsert(self, snapshot, snapshot_hash, embedding, deadline, *, text_only=False):
        sources = snapshot["sources"]
        if not isinstance(embedding, dict):
            if len(sources) != 1 or sources[0]["kind"] != "text":
                raise ValueError("All snapshot sources require embeddings.")
            embedding = {str(sources[0]["id"]): embedding}
        expected = {str(source["id"]) for source in sources if not text_only or source["kind"] == "text"}
        if len({str(source["id"]) for source in sources}) != len(sources) or set(embedding) != expected:
            raise ValueError("Embedding sources must match the enabled projection of the complete manifest.")
        vectors = {source_id: self._vector(vector) for source_id, vector in embedding.items()}
        return await self._write(snapshot, snapshot_hash, vectors, deadline)

    async def remove(self, snapshot, snapshot_hash, deadline):
        return await self._write(snapshot, snapshot_hash, None, deadline)

    async def _write(self, snapshot, snapshot_hash, embedding, deadline):
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise TimeoutError("Index command deadline expired.")
        item_id, version = snapshot["itemId"], snapshot["documentVersion"]
        tombstone = embedding is None
        async with asyncio.timeout(remaining):
            async with await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row) as connection:
                await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(item_id),))
                cursor = await connection.execute(
                    "SELECT document_version, snapshot_sha256, tombstone FROM ai_items WHERE item_id = %s",
                    (item_id,),
                )
                current = await cursor.fetchone()
                if current and current["document_version"] > version:
                    return False
                if current and current["document_version"] == version:
                    if current["snapshot_sha256"] != snapshot_hash or current["tombstone"] != tombstone:
                        raise SnapshotConflict("Same document version has a different snapshot.")
                else:
                    await connection.execute(
                        """INSERT INTO ai_items (item_id, document_version, snapshot_sha256, tombstone)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (item_id) DO UPDATE SET document_version = EXCLUDED.document_version,
                           snapshot_sha256 = EXCLUDED.snapshot_sha256, tombstone = EXCLUDED.tombstone""",
                        (item_id, version, snapshot_hash, tombstone),
                    )
                    await connection.execute("DELETE FROM ai_documents WHERE item_id = %s", (item_id,))
                if not tombstone:
                    document = snapshot["document"]
                    # A replay may reindex a new model namespace, preserving other current namespaces.
                    await connection.execute(
                        "DELETE FROM ai_documents WHERE item_id = %s AND model_id = %s AND model_revision = %s AND dimensions = %s",
                        (item_id, *self.identity[:3]),
                    )
                    for source in snapshot["sources"]:
                        if (source["kind"], source["processingProfile"]) not in {
                            ("text", "text-v1"), ("image", "image-v1")
                        }:
                            raise ValueError("Invalid source modality.")
                        if str(source["id"]) not in embedding:
                            continue
                        await connection.execute(
                        """INSERT INTO ai_documents (item_id, model_id, model_revision, dimensions,
                           processing_profile, document_version, source_id, source_version, source_sha256,
                           found_area, found_on, found_from, found_until, search_terms, location_tokens, embedding)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           setweight(to_tsvector('simple', %s), 'A') ||
                           setweight(to_tsvector('simple', %s), 'B') ||
                           setweight(to_tsvector('simple', %s), 'C'), %s, %s::vector)
                           """,
                        (item_id, *self.identity[:3], source["processingProfile"], version,
                         source["id"], source["version"], source["sha256"],
                         document["foundArea"], document.get("foundOn"), document.get("foundFrom"),
                         document.get("foundUntil"),
                         normalize_text(document["title"]) if source["kind"] == "text" else "",
                         normalize_text(document["publicDescription"]) if source["kind"] == "text" else "",
                         normalize_text(document["foundArea"]) if source["kind"] == "text" else "",
                         location_tokens(document["title"] + " " + document["publicDescription"]) if source["kind"] == "text" else [],
                         embedding[str(source["id"])]),
                        )
                if datetime.now(timezone.utc) >= deadline:
                    raise TimeoutError("Index command deadline expired before commit.")
            return True

    async def search(self, text, vector, area=None, from_date=None, until=None, limit=200, *, strategy="hybrid", modality="text"):
        if not 1 <= limit <= 200:
            raise ValueError("Candidate limit must be between 1 and 200.")
        if strategy not in {"hybrid", "semantic", "lexical"}:
            raise ValueError("Unknown evaluation strategy.")
        if modality not in {"text", "image"}:
            raise ValueError("Unknown search modality.")
        vector = self._vector(vector)
        first = date.fromisoformat(from_date) if isinstance(from_date, str) else from_date
        last = date.fromisoformat(until) if isinstance(until, str) else until
        if first and last and first > last:
            raise ValueError("Invalid date filter.")
        local_timezone = timezone(timedelta(hours=7))
        start = datetime.combine(first, time.min, local_timezone) if first else None
        end = datetime.combine(last + timedelta(days=1), time.min, local_timezone) if last else None
        tokens = location_tokens(text) if modality == "text" else []
        lexical_query = " | ".join(dict.fromkeys(normalize_text(text).split())) if modality == "text" else ""
        # Retrieve a bounded pool before the requested output limit so fusion keeps both ranks.
        pool_limit = 200
        # shortcut: exact vector scan favors recall; add ANN only after measuring corpus size and recall.
        async with await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row) as connection:
            cursor = await connection.execute(
                """WITH eligible AS MATERIALIZED (
                    SELECT d.* FROM ai_documents d JOIN ai_items i USING (item_id)
                    WHERE NOT i.tombstone AND d.document_version = i.document_version
                      AND (d.model_id, d.model_revision, d.dimensions, d.processing_profile) = (%s, %s, %s, %s)
                      AND (%s::text IS NULL OR strpos(lower(d.found_area), lower(%s)) > 0)
                      AND (%s::date IS NULL OR d.found_on >= %s OR coalesce(d.found_until, d.found_from) >= %s)
                      AND (%s::date IS NULL OR d.found_on <= %s OR d.found_from < %s)
                ), nearest_source AS (
                    SELECT *, row_number() OVER (PARTITION BY item_id ORDER BY embedding <=> %s::vector, source_id) AS source_rank
                    FROM eligible
                ), semantic AS (
                    SELECT *, row_number() OVER (ORDER BY embedding <=> %s::vector, item_id) AS rank
                    FROM nearest_source WHERE source_rank = 1 ORDER BY rank LIMIT %s
                ), lexical AS (
                    SELECT *, row_number() OVER (ORDER BY ts_rank_cd(search_terms, to_tsquery('simple', %s)) DESC, item_id) AS rank
                    FROM eligible WHERE %s = 'text' AND search_terms @@ to_tsquery('simple', %s) ORDER BY rank LIMIT %s
                ), locations AS (
                    SELECT *, row_number() OVER (ORDER BY ts_rank_cd(search_terms, to_tsquery('simple', %s)) DESC, item_id) AS rank
                    FROM eligible WHERE %s = 'text' AND location_tokens && %s::text[] ORDER BY rank LIMIT %s
                )
                SELECT 'semantic' AS channel, item_id, document_version, source_id, source_version, source_sha256, location_tokens, rank FROM semantic
                UNION ALL
                SELECT 'lexical', item_id, document_version, source_id, source_version, source_sha256, location_tokens, rank FROM lexical
                UNION ALL
                SELECT 'locations', item_id, document_version, source_id, source_version, source_sha256, location_tokens, rank FROM locations
                ORDER BY channel, rank""",
                (*self.identity[:3], "text-v1" if modality == "text" else "image-v1",
                 area, area, first, first, start, last, last, end, vector, vector, pool_limit,
                 lexical_query, modality, lexical_query, pool_limit, lexical_query, modality, tokens, pool_limit),
            )
            channels = {"semantic": [], "lexical": [], "locations": []}
            for row in await cursor.fetchall():
                channels[row["channel"]].append(row)
        if modality == "image":
            return rank_candidates(channels["semantic"], [], [], [], limit)
        if strategy != "hybrid":
            return rank_candidates(channels[strategy], [], [], [], limit)
        return rank_candidates(channels["semantic"], channels["lexical"], channels["locations"], tokens, limit)
