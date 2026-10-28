import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from findie_ai.store import SnapshotConflict, Store


@pytest.fixture
def store():
    dsn = os.environ.get("AI_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set AI_TEST_DATABASE_URL to run PostgreSQL/pgvector integration checks.")
    schema = "ai_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema},public")
    result = Store(scoped_dsn, "test-embedding", "revision-1", 3)
    try:
        asyncio.run(result.migrate())
        yield result
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def snapshot(description="Ví đen, nhặt tại phòng học E.205", *, item_id=None, version=1,
             area="Trường đại học Sài Gòn", found_on="2026-10-25", found_from=None, found_until=None,
             title="Ví màu đen"):
    item_id = item_id or str(uuid4())
    return {
        "schemaVersion": 1, "itemId": item_id, "documentVersion": version, "kind": "snapshot",
        "document": {
            "title": title, "publicDescription": description, "foundArea": area,
            "foundTimePrecision": "date", "foundOn": found_on, "foundFrom": found_from,
            "foundUntil": found_until, "foundTimezone": "Asia/Ho_Chi_Minh", "custody": {},
        },
        "sources": [{"kind": "text", "id": item_id, "version": version,
                     "sha256": hashlib.sha256((title + "\n" + description).encode()).hexdigest(),
                     "processingProfile": "text-v1"}],
    }


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def deadline():
    return datetime.now(timezone.utc) + timedelta(seconds=30)


async def put(store, value, vector=(1.0, 0.0, 0.0)):
    return await store.upsert(value, checksum(value), list(vector), deadline())


def test_room_hall_retrieval_and_hard_filters_precede_candidate_limit(store):
    async def run():
        room = snapshot()
        hall = snapshot("Ví màu đen nhặt được tại sảnh hội trường A")
        wrong_room = snapshot("Ví màu đen nhặt tại phòng E.206")
        for value, vector in [(room, [0.8, 0.2, 0]), (hall, [0.8, 0.1, 0.1]), (wrong_room, [1, 0, 0])]:
            await put(store, value, vector)
        for _ in range(5):
            await put(store, snapshot(area="Đại học khác"))
            await put(store, snapshot(found_on="2026-10-23"))
        result = await store.search("vi den phong E205", [1, 0, 0], "SÀI GÒN", "2026-10-25", "2026-10-25", 2)
        assert result[0]["itemId"] == room["itemId"]
        assert len(result) == 2
        result = await store.search("vi den sanh hoi truong A", [1, 0, 0], "Sài Gòn", "2026-10-25", None, 2)
        assert result[0]["itemId"] == hall["itemId"]
        assert result[0]["sourceSha256"] == hall["sources"][0]["sha256"]
    asyncio.run(run())


def test_filter_date_overlap_matches_vietnam_timezone_and_excludes_unknown(store):
    async def run():
        inside = snapshot(found_on=None, found_from="2026-10-24T17:00:00Z")
        interval = snapshot(found_on=None, found_from="2026-10-24T10:00:00Z", found_until="2026-10-24T18:00:00Z")
        outside_before = snapshot(found_on=None, found_from="2026-10-24T16:59:59Z")
        outside_after = snapshot(found_on=None, found_from="2026-10-25T17:00:00Z")
        unknown = snapshot(found_on=None)
        for value in [inside, interval, outside_before, outside_after, unknown]:
            await put(store, value)
        result = await store.search("ví", [1, 0, 0], from_date="2026-10-25", until="2026-10-25")
        assert {row["itemId"] for row in result} == {inside["itemId"], interval["itemId"]}
    asyncio.run(run())


def test_wrong_object_in_matching_room_and_punctuation_only_query(store):
    async def run():
        wallet = snapshot("Ví màu đen nhặt tại phòng E.206")
        laptop = snapshot("Máy tính xách tay tại phòng E.205", title="Máy tính xách tay")
        await put(store, wallet)
        await put(store, laptop, [0.1, 0.9, 0])
        result = await store.search("ví màu đen phòng E.205", [1, 0, 0])
        assert result[0]["itemId"] == wallet["itemId"]
        assert len(await store.search("...!?", [1, 0, 0])) == 2
    asyncio.run(run())


def test_versions_conflicts_tombstones_and_deadline_rollback(store):
    async def run():
        value = snapshot()
        assert await put(store, value)
        assert await put(store, value)
        conflicting = snapshot("Mô tả khác", item_id=value["itemId"])
        with pytest.raises(SnapshotConflict):
            await put(store, conflicting)
        tombstone = {"schemaVersion": 1, "itemId": value["itemId"], "documentVersion": 2,
                     "kind": "tombstone", "document": None, "sources": []}
        assert await store.remove(tombstone, checksum(tombstone), deadline())
        assert await store.remove(tombstone, checksum(tombstone), deadline())
        assert not await put(store, value)
        assert not await store.search("ví", [1, 0, 0])
        expired = snapshot()
        with pytest.raises(TimeoutError):
            await store.upsert(expired, checksum(expired), [1, 0, 0], datetime.now(timezone.utc) - timedelta(seconds=1))
        assert not await store.search("ví", [1, 0, 0])
    asyncio.run(run())


def test_model_namespaces_do_not_mix_vectors_and_new_revision_can_reindex(store):
    async def run():
        value = snapshot()
        await put(store, value)
        other = Store(store.dsn, "other-embedding", "revision-2", 2)
        assert await other.search("ví", [1, 0]) == []
        assert await other.upsert(value, checksum(value), [1, 0], deadline())
        assert len(await other.search("ví", [1, 0])) == 1
        assert len(await store.search("ví", [1, 0, 0])) == 1
        newer = snapshot(item_id=value["itemId"], version=2)
        assert await other.upsert(newer, checksum(newer), [1, 0], deadline())
        assert await store.search("ví", [1, 0, 0]) == []
    asyncio.run(run())


def test_concurrent_versions_keep_newest_and_reject_invalid_vectors(store):
    async def run():
        old = snapshot()
        new = snapshot(item_id=old["itemId"], version=2)
        await asyncio.gather(put(store, new), put(store, old))
        result = await store.search("ví", [1, 0, 0])
        assert result[0]["documentVersion"] == 2
        for vector in ([1, 0], [0, 0, 0], [float("nan"), 0, 0], [True, 0, 0]):
            with pytest.raises(ValueError):
                await put(store, snapshot(), vector)
    asyncio.run(run())


def with_images(value, count=2):
    value["sources"].extend({"kind": "image", "id": str(uuid4()), "version": 2,
        "sha256": str(index + 1) * 64, "processingProfile": "image-v1"} for index in range(count))
    return value


def test_multisource_snapshot_is_atomic_and_image_search_deduplicates_with_provenance(store):
    async def run():
        value = with_images(snapshot())
        sources = value["sources"]
        vectors = {sources[0]["id"]: [1, 0, 0], sources[1]["id"]: [0, 1, 0], sources[2]["id"]: [0, 0.8, 0.2]}
        with pytest.raises(ValueError):
            await store.upsert(value, checksum(value), {sources[0]["id"]: [1, 0, 0]}, deadline())
        assert await store.search("ví", [1, 0, 0]) == []
        assert await store.upsert(value, checksum(value), vectors, deadline())
        text = await store.search("ví", [1, 0, 0])
        images = await store.search("room E206 MUST NOT ADD LEXICAL SCORE", [0, 1, 0], modality="image")
        assert len(text) == len(images) == 1
        assert text[0]["sourceId"] == sources[0]["id"]
        assert images[0]["sourceId"] == sources[1]["id"]
        assert images[0]["sourceVersion"] == 2 and images[0]["sourceSha256"] == sources[1]["sha256"]
        assert await store.search("", [0, 1, 0], area="other", limit=1, modality="image") == []
        assert await store.search("", [0, 1, 0], from_date="2026-10-26", limit=1, modality="image") == []
        async with await psycopg.AsyncConnection.connect(store.dsn) as db:
            rows = await (await db.execute("SELECT processing_profile, search_terms::text, location_tokens FROM ai_documents")).fetchall()
            assert len(rows) == 3
            assert all(not terms and not locations for profile, terms, locations in rows if profile == "image-v1")
        # Same snapshot is replayable and an independent model revision may reindex every source.
        await store.upsert(value, checksum(value), vectors, deadline())
        other = Store(store.dsn, "new", "revision", 2)
        await other.upsert(value, checksum(value), {source["id"]: [1, 0] for source in sources}, deadline())
        assert len(await other.search("", [1, 0], modality="image")) == 1
        newer = snapshot(item_id=value["itemId"], version=2)
        await put(store, newer)
        assert await other.search("", [1, 0], modality="image") == []
        assert await store.search("", [0, 1, 0], modality="image") == []
    asyncio.run(run())


def test_existing_primary_key_upgrade_preserves_text_data_and_is_repeatable(store):
    async def run():
        value = snapshot()
        await put(store, value)
        async with await psycopg.AsyncConnection.connect(store.dsn) as db:
            await db.execute("ALTER TABLE ai_documents DROP CONSTRAINT ai_documents_pkey")
            await db.execute("ALTER TABLE ai_documents ADD PRIMARY KEY (model_id, model_revision, dimensions, processing_profile, item_id)")
        await store.migrate()
        await store.migrate()
        assert (await store.search("ví", [1, 0, 0]))[0]["itemId"] == value["itemId"]
        full = with_images(snapshot(item_id=value["itemId"], version=2))
        await store.upsert(full, checksum(full), {source["id"]: [1, 0, 0] for source in full["sources"]}, deadline())
        assert len(await store.search("", [1, 0, 0], modality="image")) == 1
    asyncio.run(run())


def test_text_only_projection_advances_full_snapshot_and_can_replay_with_image_vectors(store):
    async def run():
        old = snapshot()
        await put(store, old)
        full = with_images(snapshot(item_id=old['itemId'], version=2))
        snapshot_hash = checksum(full)
        text_vectors = {full['itemId']: [1, 0, 0]}
        assert await store.upsert(full, snapshot_hash, text_vectors, deadline(), text_only=True)
        hits = await store.search('ví', [1, 0, 0])
        assert len(hits) == 1 and hits[0]['documentVersion'] == 2
        assert hits[0]['sourceId'] == full['itemId'] and hits[0]['sourceVersion'] == 2
        assert hits[0]['sourceSha256'] == full['sources'][0]['sha256']
        assert await store.search('', [1, 0, 0], modality='image') == []
        async with await psycopg.AsyncConnection.connect(store.dsn) as db:
            row = await (await db.execute('SELECT document_version, snapshot_sha256 FROM ai_items WHERE item_id = %s',
                (full['itemId'],))).fetchone()
            assert row == (2, snapshot_hash)
        vectors = {source['id']: [1, 0, 0] for source in full['sources']}
        assert await store.upsert(full, snapshot_hash, vectors, deadline())
        assert len(await store.search('', [1, 0, 0], modality='image')) == 1
        tombstone = {'itemId': full['itemId'], 'documentVersion': 3, 'sources': [], 'document': None, 'kind': 'tombstone'}
        assert await store.remove(tombstone, checksum(tombstone), deadline())
        assert not await store.upsert(full, snapshot_hash, text_vectors, deadline(), text_only=True)
        assert not await store.upsert(full, snapshot_hash, vectors, deadline())
        assert await store.search('ví', [1, 0, 0]) == []
        assert await store.search('', [1, 0, 0], modality='image') == []
    asyncio.run(run())


@pytest.mark.parametrize('text_only', [False, True])
def test_bad_later_source_rolls_back_watermark_and_keeps_previous_projection(store, text_only):
    async def run():
        old = snapshot()
        await put(store, old)
        invalid = with_images(snapshot(item_id=old["itemId"], version=2), count=1)
        invalid["sources"][1]["processingProfile"] = "unknown-profile"
        with pytest.raises(ValueError):
            await store.upsert(invalid, checksum(invalid), {source["id"]: [1, 0, 0] for source in invalid["sources"]
                if not text_only or source["kind"] == "text"}, deadline(), text_only=text_only)
        result = await store.search("ví", [1, 0, 0])
        assert len(result) == 1 and result[0]["documentVersion"] == 1
        assert result[0]["sourceSha256"] == old["sources"][0]["sha256"]
    asyncio.run(run())
