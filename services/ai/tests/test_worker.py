import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image

from findie_ai.config import Settings
from findie_ai.contracts import ImageEmbeddingMetadata, Query, RedactMetadata, SearchMetadata, Snapshot
from findie_ai.ollama import EmbeddingInputRejected, ModelUnavailable
from findie_ai.worker import Worker


SETTINGS = Settings(service_token='test', revision='a' * 64, redaction_revision='b' * 64, dimensions=2)


def encode(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()


def metadata(**extra):
    return {'schemaVersion': 1, 'modelId': SETTINGS.model_id, 'modelRevision': SETTINGS.revision,
            'deadlineAt': (datetime.now(timezone.utc) + timedelta(seconds=25)).isoformat(), **extra}


def query_metadata(**extra):
    return metadata(processingProfile='text-v1', searchProfileId=SETTINGS.search_profile,
                    searchProfileVersion=1, mode='text', area=None, **{'from': None}, until=None,
                    limit=10, candidateLimit=200) | extra


def test_redaction_accepts_five_minute_deadlines_and_rejects_expired_or_excessive_ones():
    value = metadata(modelId=SETTINGS.redaction_model, modelRevision='b' * 64,
                     imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
                     sourceSha256='a' * 64, processingProfile='redact-v4')
    deadline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert 299 < RedactMetadata.model_validate(value | {'deadlineAt': deadline}).remaining() <= 300
    with pytest.raises(ValueError, match='processingProfile'):
        RedactMetadata.model_validate(value | {'processingProfile': 'redact-v2'})
    with pytest.raises(ValueError, match='deadline_too_long'):
        SearchMetadata.model_validate(query_metadata(deadlineAt=deadline)).remaining()
    for seconds, error, message in ((306, ValueError, 'deadline_too_long'), (-1, TimeoutError, 'deadline_expired')):
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        with pytest.raises(error, match=message):
            RedactMetadata.model_validate(value | {'deadlineAt': deadline}).remaining()


def test_ocr_image_operations_allow_five_minutes_but_text_and_index_budgets_stay_short():
    deadline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    image = metadata(imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
        sourceSha256="a" * 64, dimensions=2, processingProfile="image-v1", deadlineAt=deadline)
    assert 299 < ImageEmbeddingMetadata.model_validate(image).remaining() <= 300
    query = query_metadata(mode="image", processingProfile="image-v1", deadlineAt=deadline)
    assert 299 < SearchMetadata.model_validate(query).remaining() <= 300
    with pytest.raises(ValueError, match="deadline_too_long"):
        SearchMetadata.model_validate(query_metadata(deadlineAt=deadline)).remaining()


def snapshot():
    item_id = str(uuid4())
    title, description = 'Ví đen', 'Nhặt tại phòng E.205'
    return {'schemaVersion': 1, 'itemId': item_id, 'documentVersion': 1, 'kind': 'snapshot',
            'document': {'title': title, 'publicDescription': description, 'foundArea': 'Đại học Sài Gòn',
                         'foundTimePrecision': 'unknown', 'foundOn': None, 'foundFrom': None,
                         'foundUntil': None, 'foundTimezone': 'Asia/Ho_Chi_Minh',
                         'custody': {'kind': 'person', 'displayName': 'Người nhặt'}},
            'sources': [{'kind': 'text', 'id': item_id, 'version': 1,
                         'sha256': hashlib.sha256((title + '\n' + description).encode()).hexdigest(),
                         'processingProfile': 'text-v1'}]}


def index_metadata(value, body):
    return metadata(jobId=str(uuid4()), leaseToken=str(uuid4()), itemId=value['itemId'],
                    documentVersion=value['documentVersion'], snapshotSha256=hashlib.sha256(body).hexdigest(), dimensions=2)


class Message:
    def __init__(self, kind, meta, body, *, durable=False):
        self.type, self.body, self.content_type = kind, body, 'application/json'
        self.headers = {'metadata': encode(meta)}
        self.correlation_id = str(uuid4())
        self.reply_to = SETTINGS.result_queue if durable else 'amq.gen-unit-test'
        self.processed = False
        self.locked = False
        self.events = []

    async def ack(self):
        self.processed = True
        self.locked = True
        self.events.append('ack')

    async def reject(self, requeue=False):
        assert requeue is False
        self.processed = True
        self.locked = True
        self.events.append('reject')


def test_ack_after_commit_and_confirmed_receipt_and_unroutable_is_not_success():
    async def run():
        worker = Worker(SETTINGS)
        value = snapshot()
        body = encode(value)
        message = Message('index.upsert', index_metadata(value, body), body, durable=True)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])

        async def commit(*_args, **_kwargs):
            message.events.append('commit')
            return True

        async def publish(reply, **kwargs):
            assert not message.processed and kwargs['mandatory'] is True
            assert json.loads(reply.headers['metadata'])['committed'] is True
            message.events.append('confirmed')

        worker.store.upsert = commit
        worker.publisher = SimpleNamespace(default_exchange=SimpleNamespace(publish=publish))
        try:
            await worker.handle(message, 'index')
            assert message.events == ['commit', 'confirmed', 'ack']
            message.events.clear()
            message.processed = False
            message.locked = False
            message.body = body
            worker.publisher.default_exchange.publish = AsyncMock(side_effect=RuntimeError('unroutable'))
            await worker.handle(message, 'index')
            assert message.events == ['commit', 'reject']
        finally:
            await worker.close()
    asyncio.run(run())


def test_expired_query_model_mismatch_and_disabled_image_query_do_not_call_model_or_store():
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        try:
            body = encode({'text': 'ví E.205', 'area': None, 'from': None, 'until': None})
            expired = query_metadata(deadlineAt=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
            await worker.handle(Message('search.hybrid', expired, body), 'query')
            await worker.handle(Message('search.hybrid', query_metadata(modelRevision='b' * 64), body), 'query')
            message = Message('search.hybrid.image', query_metadata(mode='image', processingProfile='image-v1',
                searchProfileId=SETTINGS.image_search_profile), png())
            message.content_type = 'image/png'
            await worker.handle(message, 'image')
            worker.ollama.embed.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
            assert all(call.args[2] is False for call in worker.reply.await_args_list)
        finally:
            await worker.close()
    asyncio.run(run())


def test_raw_failure_drops_body_and_never_routes_to_command_queue():
    async def run():
        worker = Worker(SETTINGS)
        worker.reply = AsyncMock(side_effect=RuntimeError('reply disappeared'))
        try:
            message = Message('image.redact', metadata(), b'raw')
            await worker.handle(message, 'image')
            assert message.events == ['ack']
            message = Message('search.hybrid', query_metadata(), b'{}')
            message.reply_to = SETTINGS.index_queue
            worker.reply.reset_mock()
            await worker.handle(message, 'query')
            assert message.events == ['ack']
            worker.reply.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_public_contract_rejects_private_fields_hash_mismatch_and_blank_query():
    value = snapshot()
    assert 'E.205' in Snapshot.model_validate(value).embedding_text()
    value['document']['privateAnswers'] = ['private']
    with pytest.raises(ValueError):
        Snapshot.model_validate(value)
    value = snapshot()
    value['sources'][0]['sha256'] = 'b' * 64
    with pytest.raises(ValueError):
        Snapshot.model_validate(value)
    with pytest.raises(ValueError):
        Query.model_validate({'text': '   '})
    value = snapshot()
    value['schemaVersion'] = True
    with pytest.raises(ValueError):
        Snapshot.model_validate(value)


def png():
    output = BytesIO()
    with Image.new("RGB", (12, 12), (255, 0, 0)) as image:
        image.save(output, format="PNG")
    return output.getvalue()


def image_job(*, image_count=2, seconds=25):
    value = snapshot()
    raw = png()
    sources = [{"kind": "image", "id": str(uuid4()), "version": 2,
                "sha256": hashlib.sha256(raw).hexdigest(), "processingProfile": "image-v1"}
               for _ in range(image_count)]
    value["sources"].extend(sources)
    body = encode(value)
    meta = index_metadata(value, body)
    meta["deadlineAt"] = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    manifest = Message("index.upsert", meta, body, durable=True)
    parts = []
    for source in sources:
        part = Message("index.source.image", meta | {
            "sourceId": source["id"], "sourceVersion": source["version"],
            "sourceSha256": source["sha256"], "processingProfile": "image-v1",
        }, raw, durable=True)
        part.content_type, part.correlation_id = "image/png", manifest.correlation_id
        parts.append(part)
    return value, manifest, parts


def vector_part(part, *, payload=None):
    meta = json.loads(part.headers["metadata"])
    cached = {"modelId": meta["modelId"], "modelRevision": meta["modelRevision"],
              "dimensions": meta["dimensions"], "sourceSha256": "c" * 64, "vector": [0, 1]}
    body = encode(cached if payload is None else payload)
    message = Message("index.source.vector", meta | {"payloadSha256": hashlib.sha256(body).hexdigest()}, body, durable=True)
    message.correlation_id = part.correlation_id
    return message


@pytest.mark.parametrize("enabled", [True, False])
def test_original_image_embedding_is_transient_and_never_uses_redacted_pixels(enabled):
    async def run():
        from findie_ai.images import normalize

        worker = Worker(replace(SETTINGS, image_search_enabled=enabled))
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.ollama.read_text = AsyncMock(return_value={"text": "MSSV 001234", "hasUnclearText": False})
        worker.ollama.detect_regions = AsyncMock()
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        raw = png()
        meta = metadata(imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
            sourceSha256=hashlib.sha256(raw).hexdigest(), dimensions=2, processingProfile="image-v1")
        message = Message("image.embed", meta, raw)
        message.content_type = "image/png"
        try:
            await worker.handle(message, "image")
            assert message.events == ["ack"] and message.body == b""
            result = worker.reply.await_args.args
            assert result[2] is True
            if enabled:
                normalized = await normalize(raw, "image/png")
                worker.ollama.read_text.assert_awaited_once_with(normalized)
                worker.ollama.embed_image.assert_awaited_once_with(normalized)
                assert result[3] == {"modelId": SETTINGS.model_id, "modelRevision": SETTINGS.revision,
                    "dimensions": 2, "sourceSha256": meta["sourceSha256"], "vector": [0, 1],
                    "ocr": {"text": "MSSV 001234", "hasUnclearText": False,
                        "modelId": SETTINGS.redaction_model, "modelRevision": SETTINGS.redaction_revision,
                        "processingProfile": "ocr-v1"}}
            else:
                worker.ollama.embed_image.assert_not_awaited()
                worker.ollama.read_text.assert_not_awaited()
                assert result[3] is None
            worker.ollama.detect_regions.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["hash", "dimensions", "model", "inference"])
def test_original_embedding_failure_drops_raw_bytes_without_persisting_or_redacting(failure):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed_image = AsyncMock(side_effect=RuntimeError("unavailable"))
        worker.ollama.read_text = AsyncMock(return_value={"text": "", "hasUnclearText": False})
        worker.reply = AsyncMock(side_effect=RuntimeError("reply unavailable"))
        raw = png()
        meta = metadata(imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
            sourceSha256=hashlib.sha256(raw).hexdigest(), dimensions=2, processingProfile="image-v1")
        if failure == "hash":
            meta["sourceSha256"] = "a" * 64
        elif failure == "dimensions":
            meta["dimensions"] = 3
        elif failure == "model":
            meta["modelRevision"] = "b" * 64
        message = Message("image.embed", meta, raw)
        message.content_type = "image/png"
        try:
            await worker.handle(message, "image")
            assert message.events == ["ack"] and message.body == b""
            assert not worker.pending
            if failure != "inference":
                worker.ollama.embed_image.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_ocr_failure_does_not_silently_lose_searchable_text_on_upload():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.read_text = AsyncMock(side_effect=RuntimeError("invalid transcription"))
        worker.ollama.embed_image = AsyncMock()
        worker.reply = AsyncMock()
        raw = png()
        meta = metadata(imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
            sourceSha256=hashlib.sha256(raw).hexdigest(), dimensions=2, processingProfile="image-v1")
        message = Message("image.embed", meta, raw)
        message.content_type = "image/png"
        try:
            await worker.handle(message, "image")
            assert message.events == ["ack"] and message.body == b""
            assert worker.reply.await_args.args[2] is False
            worker.ollama.embed_image.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("corruption", [None, "profile", "model", "revision", "length", "unclear", "extra"])
def test_cached_ocr_is_bound_to_approved_image_and_validated_before_indexing(corruption):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.ollama.read_text = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job(image_count=1)
        payload = json.loads(vector_part(parts[0]).body)
        ocr = {"text": "MSSV 001234", "hasUnclearText": False, "modelId": SETTINGS.redaction_model,
               "modelRevision": SETTINGS.redaction_revision, "processingProfile": "ocr-v1"}
        if corruption == "profile":
            ocr["processingProfile"] = "unknown"
        elif corruption == "model":
            ocr["modelId"] = "other"
        elif corruption == "revision":
            ocr["modelRevision"] = "c" * 64
        elif corruption == "length":
            ocr["text"] = "x" * 3001
        elif corruption == "unclear":
            ocr["hasUnclearText"] = "false"
        elif corruption == "extra":
            ocr["privateInstructions"] = "unexpected"
        part = vector_part(parts[0], payload=payload | {"ocr": ocr})
        try:
            await worker.handle(manifest, "index")
            worker.ollama.embed.assert_not_awaited()
            await worker.handle(part, "index")
            worker.ollama.embed_image.assert_not_awaited()
            worker.ollama.read_text.assert_not_awaited()
            assert worker.reply.await_args.args[2] is (corruption is None)
            if corruption is None:
                assert worker.store.upsert.await_args.kwargs == {"text_only": False,
                    "ocr": {value["sources"][1]["id"]: "MSSV 001234"}}
                worker.ollama.embed.assert_awaited_once_with(
                    Snapshot.model_validate(value).embedding_text() + "\nOCR ảnh:\nMSSV 001234")
            else:
                worker.ollama.embed.assert_not_awaited()
                worker.store.upsert.assert_not_awaited()
            assert not worker.pending and part.body == b""
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("error", [None, EmbeddingInputRejected, ModelUnavailable])
def test_index_combines_ocr_in_manifest_order_and_retries_only_rejected_input(error):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(side_effect=[error("test"), [1, 0]] if error else None, return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job()
        texts = ["MSSV 001234", "CCCD 00008765"]
        for index, part in enumerate(parts):
            payload = json.loads(vector_part(part).body)
            payload["ocr"] = {"text": texts[index], "hasUnclearText": False,
                              "modelId": SETTINGS.redaction_model, "modelRevision": SETTINGS.redaction_revision,
                              "processingProfile": "ocr-v1"}
            parts[index] = vector_part(part, payload=payload)
        try:
            await worker.handle(parts[1], "index")
            await worker.handle(manifest, "index")
            worker.ollama.embed.assert_not_awaited()
            await worker.handle(parts[0], "index")
            public_text = Snapshot.model_validate(value).embedding_text()
            expected_inputs = [public_text + "\nOCR ảnh:\n" + "\n".join(texts)]
            if error is EmbeddingInputRejected:
                expected_inputs.append(public_text)
            assert [call.args[0] for call in worker.ollama.embed.await_args_list] == expected_inputs
            worker.ollama.embed_image.assert_not_awaited()
            if error is ModelUnavailable:
                worker.store.upsert.assert_not_awaited()
                assert worker.reply.await_args.args[2] is False
            else:
                worker.store.upsert.assert_awaited_once()
                assert list(worker.store.upsert.await_args.kwargs["ocr"].values()) == texts
                assert worker.store.upsert.await_args.args[2] == {
                    value["itemId"]: [1, 0], **{source["id"]: [0, 1] for source in value["sources"][1:]},
                }
                assert worker.reply.await_args.args[2] is True
        finally:
            await worker.close()
    asyncio.run(run())


def test_index_caps_only_the_appended_ocr_at_the_gateway_character_limit():
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        public_text = "mô tả " * 850
        document = SimpleNamespace(embedding_text=lambda: public_text)
        ocr = {str(uuid4()): "a" * 3000 for _ in range(5)}
        try:
            await worker.embed_index_text(document, ocr)
            combined = worker.ollama.embed.await_args.args[0]
            assert combined.startswith(public_text + "\nOCR ảnh:\n")
            assert len(combined) == 20000 and sum(map(len, ocr.values())) == 15000
        finally:
            await worker.close()
    asyncio.run(run())


def test_text_query_includes_image_vector_sources_only_when_image_capability_is_enabled():
    async def run():
        for enabled in (False, True):
            worker = Worker(replace(SETTINGS, image_search_enabled=enabled))
            worker.ollama.embed = AsyncMock(return_value=[1, 0])
            worker.store.search = AsyncMock(return_value=[])
            try:
                await worker.execute("search.hybrid", SearchMetadata.model_validate(query_metadata()),
                    encode({"text": "MSSV 001234"}))
                kwargs = worker.store.search.await_args.kwargs
                assert kwargs["include_images"] is enabled
                worker.ollama.embed.assert_not_awaited()
                assert await kwargs["embed"]() == [1, 0]
                worker.ollama.embed.assert_awaited_once_with("MSSV 001234", query=True)
            finally:
                await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("enabled", [True, False])
def test_index_reuses_original_vectors_and_binds_them_to_approved_display_sources(enabled):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=enabled))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job(image_count=1)
        part = vector_part(parts[0])
        duplicate = vector_part(parts[0])
        try:
            await worker.handle(part, "index")
            await worker.handle(duplicate, "index")
            assert part.body == duplicate.body == b"" and not part.processed
            await worker.handle(manifest, "index")
            worker.ollama.embed_image.assert_not_awaited()
            embeddings = worker.store.upsert.await_args.args[2]
            assert embeddings[value["itemId"]] == [1, 0]
            if enabled:
                assert embeddings[value["sources"][1]["id"]] == [0, 1]
            else:
                assert len(embeddings) == 1
            assert worker.store.upsert.await_args.kwargs == {"text_only": not enabled}
            assert worker.reply.await_args.args[2] is True
            assert manifest.events == part.events == duplicate.events == ["ack"]
            assert not worker.pending
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("corruption", ["checksum", "source", "model", "dimensions", "nan", "zero", "bool", "extra"])
def test_invalid_cached_vector_parts_never_commit_a_projection(corruption):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        _, manifest, parts = image_job(image_count=1)
        part = vector_part(parts[0])
        payload = json.loads(part.body)
        if corruption == "model":
            payload["modelRevision"] = "b" * 64
        elif corruption == "dimensions":
            payload["dimensions"] = 3
        elif corruption == "nan":
            payload["vector"] = [float("nan"), 1]
        elif corruption == "zero":
            payload["vector"] = [0, 0]
        elif corruption == "bool":
            payload["vector"] = [True, 1]
        elif corruption == "extra":
            payload["privateText"] = "not allowed"
        part = vector_part(parts[0], payload=payload)
        if corruption == "checksum":
            part.body += b" "
        elif corruption == "source":
            meta = json.loads(part.headers["metadata"])
            part.headers["metadata"] = encode(meta | {"sourceSha256": "d" * 64})
        try:
            await worker.handle(manifest, "index")
            await worker.handle(part, "index")
            worker.store.upsert.assert_not_awaited()
            worker.ollama.embed_image.assert_not_awaited()
            assert worker.reply.await_args.args[2] is False
            assert manifest.events == part.events == ["ack"]
            assert not worker.pending and part.body == b""
        finally:
            await worker.close()
    asyncio.run(run())


def test_conflicting_original_vector_duplicate_fails_instead_of_replacing_first_vector():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        _, manifest, parts = image_job(image_count=2)
        first = vector_part(parts[0])
        payload = json.loads(first.body)
        second = vector_part(parts[0], payload=payload | {"vector": [1, 0]})
        try:
            await worker.handle(manifest, "index")
            await worker.handle(first, "index")
            await worker.handle(second, "index")
            worker.store.upsert.assert_not_awaited()
            assert worker.reply.await_args.args[2] is False
            assert manifest.events == first.events == second.events == ["ack"]
            assert not worker.pending
        finally:
            await worker.close()
    asyncio.run(run())


def test_max_dimension_original_vectors_fit_reply_and_index_parts():
    async def run():
        settings = replace(SETTINGS, dimensions=16000, image_search_enabled=True)
        worker = Worker(settings)
        vector = [0.0078125] * settings.dimensions
        worker.ollama.embed = AsyncMock(return_value=vector)
        worker.store.upsert = AsyncMock(return_value=True)
        worker.publisher = SimpleNamespace(default_exchange=SimpleNamespace(publish=AsyncMock()))
        value, manifest, parts = image_job(image_count=1)
        meta = json.loads(manifest.headers["metadata"]) | {"dimensions": settings.dimensions}
        manifest.headers["metadata"] = encode(meta)
        part_meta = json.loads(parts[0].headers["metadata"]) | {"dimensions": settings.dimensions}
        parts[0].headers["metadata"] = encode(part_meta)
        payload = {"modelId": settings.model_id, "modelRevision": settings.revision,
                   "dimensions": settings.dimensions, "sourceSha256": "c" * 64, "vector": vector}
        part = vector_part(parts[0], payload=payload)
        assert 65536 < len(part.body) < 1024 * 1024
        try:
            request = Message("image.embed", {}, png())
            await worker.reply(request, {}, True, payload)
            published = worker.publisher.default_exchange.publish.await_args.args[0]
            assert json.loads(published.body) == payload
            await worker.handle(manifest, "index")
            await worker.handle(part, "index")
            assert worker.store.upsert.await_args.args[2][value["sources"][1]["id"]] == vector
            assert manifest.events == part.events == ["ack"]
        finally:
            await worker.close()
    asyncio.run(run())


def test_complete_image_manifest_is_atomic_with_out_of_order_parts_and_duplicate_parts():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job()
        duplicate = Message("index.source.image", json.loads(parts[0].headers["metadata"]), png(), durable=True)
        duplicate.content_type, duplicate.correlation_id = "image/png", manifest.correlation_id
        try:
            await worker.handle(parts[0], "index")
            await worker.handle(duplicate, "index")
            assert not parts[0].processed and not duplicate.processed
            assert parts[0].body == duplicate.body == b""
            await worker.handle(manifest, "index")
            worker.store.upsert.assert_not_awaited()
            worker.reply.assert_not_awaited()
            await worker.handle(parts[1], "index")
            worker.store.upsert.assert_awaited_once()
            embeddings = worker.store.upsert.await_args.args[2]
            assert set(embeddings) == {source["id"] for source in value["sources"]}
            assert worker.ollama.embed_image.await_count == 2
            worker.reply.assert_awaited_once()
            assert worker.reply.await_args.args[2] is True
            assert all(message.events == ["ack"] for message in [manifest, duplicate, *parts])
            assert not worker.pending and worker.pending_bytes == 0
        finally:
            await worker.close()
    asyncio.run(run())


def test_text_only_projection_validates_full_manifest_without_image_inference():
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job()
        expected_hash = hashlib.sha256(manifest.body).hexdigest()
        try:
            await worker.handle(parts[0], 'index')
            await worker.handle(manifest, 'index')
            worker.store.upsert.assert_not_awaited()
            worker.reply.assert_not_awaited()
            await worker.handle(parts[1], 'index')
            worker.ollama.embed_image.assert_not_awaited()
            worker.store.upsert.assert_awaited_once()
            committed = worker.store.upsert.await_args
            assert committed.args[:3] == (Snapshot.model_validate(value).model_dump(mode='json'),
                                         expected_hash, {value['itemId']: [1, 0]})
            assert committed.kwargs == {'text_only': True}
            assert worker.reply.await_args.args[1]['snapshotSha256'] == expected_hash
            assert worker.reply.await_args.args[2] is True
            assert all(message.events == ['ack'] and message.body == b'' for message in [manifest, *parts])
            assert not worker.pending and worker.pending_bytes == 0
        finally:
            await worker.close()
    asyncio.run(run())


def test_text_only_projection_still_decodes_hash_matching_image_parts():
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, _, _ = image_job(image_count=1)
        raw = b'not an image'
        source = value['sources'][1]
        source['sha256'] = hashlib.sha256(raw).hexdigest()
        body = encode(value)
        meta = index_metadata(value, body)
        manifest = Message('index.upsert', meta, body, durable=True)
        part = Message('index.source.image', meta | {'sourceId': source['id'], 'sourceVersion': source['version'],
            'sourceSha256': source['sha256'], 'processingProfile': 'image-v1'}, raw, durable=True)
        part.content_type, part.correlation_id = 'image/png', manifest.correlation_id
        try:
            await worker.handle(manifest, 'index')
            await worker.handle(part, 'index')
            worker.store.upsert.assert_not_awaited()
            worker.ollama.embed_image.assert_not_awaited()
            assert worker.reply.await_args.args[2] is False
            assert manifest.events == part.events == ['ack']
            assert not worker.pending and worker.pending_bytes == 0
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize('image_search_enabled', [False, True])
def test_missing_or_corrupt_image_parts_never_commit_and_expire_without_retained_bodies(image_search_enabled):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=image_search_enabled))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        try:
            _, manifest, parts = image_job(image_count=1, seconds=0.04)
            await worker.handle(manifest, "index")
            assert manifest.body == b"" and not manifest.processed
            await asyncio.sleep(0.07)
            assert manifest.events == ["ack"] and not worker.pending
            assert worker.reply.await_args.args[2] is False
            worker.store.upsert.assert_not_awaited()
            _, manifest, parts = image_job(image_count=1)
            await worker.handle(manifest, "index")
            parts[0].body = b"corrupted output"
            await worker.handle(parts[0], "index")
            worker.store.upsert.assert_not_awaited()
            worker.ollama.embed_image.assert_not_awaited()
            assert manifest.events == parts[0].events == ["ack"]
            assert worker.reply.await_args.args[2] is False
            assert not worker.pending
        finally:
            await worker.close()
    asyncio.run(run())


def test_index_assembly_has_bounded_capacity_and_rejects_cross_correlation_parts():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        try:
            jobs = [image_job(image_count=1) for _ in range(3)]
            for _, manifest, _ in jobs:
                await worker.handle(manifest, "index")
            assert len(worker.pending) == 2
            assert jobs[2][1].events == ["ack"]  # A failed receipt releases a bounded outbox retry.
            part = jobs[0][2][0]
            part.correlation_id = str(uuid4())
            receipts_before = worker.reply.await_count
            await worker.handle(part, "index")
            assert part.events == ["reject"]
            assert worker.reply.await_count == receipts_before
            worker.ollama.embed_image.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_image_query_keeps_raw_bytes_out_of_storage_and_redaction_returns_only_output():
    async def run():
        settings = replace(SETTINGS, image_search_enabled=True, redaction_revision="b" * 64)
        worker = Worker(settings)
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.ollama.read_text = AsyncMock()
        worker.ollama.detect_regions = AsyncMock(return_value=[{"label": "face", "bbox": [0, 0, 500, 500]}])
        worker.store.search = AsyncMock(return_value=[])
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        try:
            raw = png()
            meta = query_metadata(mode="image", processingProfile="image-v1", searchProfileId=settings.image_search_profile)
            message = Message("search.hybrid.image", meta, raw)
            message.content_type = "image/png"
            await worker.handle(message, "image")
            assert message.events == ["ack"] and message.body == b""
            assert worker.store.search.await_args.args[0] == ""
            assert worker.store.search.await_args.kwargs == {"modality": "image"}
            assert worker.ollama.embed_image.await_args.kwargs == {}
            worker.ollama.read_text.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
            message = Message("image.redact", metadata(modelId=settings.redaction_model,
                modelRevision=settings.redaction_revision, imageId=str(uuid4()), itemId=str(uuid4()),
                sourceVersion=1, sourceSha256=hashlib.sha256(raw).hexdigest(), processingProfile="redact-v4"), raw)
            message.content_type = "image/png"
            await worker.handle(message, "image")
            response = worker.reply.await_args
            assert response.args[2] is True and response.args[3] != raw
            assert response.args[1]["sha256"] == hashlib.sha256(response.args[3]).hexdigest()
            assert message.events == ["ack"] and message.body == b""
            worker.store.upsert.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_deadline_during_inference_and_orphan_parts_release_each_delivery_once():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        async def slow(*_args):
            await asyncio.sleep(0.2)
            return [1, 0]
        worker.ollama.embed = AsyncMock(side_effect=slow)
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        try:
            _, manifest, parts = image_job(image_count=1, seconds=0.04)
            await worker.handle(manifest, "index")
            await worker.handle(parts[0], "index")
            worker.ollama.embed.assert_awaited_once()
            assert manifest.events == parts[0].events == ["ack"] and not worker.pending
            assert worker.reply.await_count == 1 and worker.reply.await_args.args[2] is False
            worker.reply.reset_mock()
            _, _, parts = image_job(image_count=1, seconds=0.02)
            await worker.handle(parts[0], "index")
            await asyncio.sleep(0.04)
            assert parts[0].events == ["reject"] and not worker.pending
            worker.reply.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_cold_readiness_allows_remote_dependencies_to_complete_within_twelve_seconds(monkeypatch):
    async def run():
        worker = Worker(SETTINGS)
        worker.connection = worker.publisher = worker.consumer = SimpleNamespace(is_closed=False)
        worker.connection.close = AsyncMock()
        loop = asyncio.get_running_loop()
        clock = [loop.time()]
        completed = []

        async def dependency(name, seconds, result=None):
            clock[0] += seconds
            await asyncio.sleep(0)
            completed.append(name)
            return result

        worker.store.check = lambda: dependency("database", 1.25)
        worker.ollama.verify_models = lambda: dependency("models", 4)
        worker.ollama.embed = lambda *_args, **_kwargs: dependency("embedding", 3.25, [1, 0])
        try:
            with monkeypatch.context() as patch:
                patch.setattr(loop, "time", lambda: clock[0])
                assert await worker.probe()
            assert completed == ["database", "models", "embedding"]
            assert worker.last_embedding_success is not None
        finally:
            await worker.close()
    asyncio.run(run())


def test_readiness_does_not_queue_inference_behind_a_busy_model_after_warmup():
    async def run():
        worker = Worker(SETTINGS)
        worker.connection = worker.publisher = worker.consumer = SimpleNamespace(is_closed=False)
        worker.connection.close = AsyncMock()
        worker.store.check = AsyncMock()
        worker.ollama.verify_models = AsyncMock()
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        try:
            assert await worker.probe()
            worker.ollama.embed.assert_awaited_once()
            worker.last_embedding_success = time.monotonic() - 20
            async with worker.ollama.lock:
                assert await asyncio.wait_for(worker.probe(), timeout=0.1)
            worker.ollama.embed.assert_awaited_once()
            worker.store.check.assert_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_tombstone_commit_with_unconfirmed_receipt_rejects_without_false_commit_receipt():
    async def run():
        worker = Worker(SETTINGS)
        value = snapshot()
        value.update(kind="tombstone", document=None, sources=[])
        body = encode(value)
        message = Message("index.remove", index_metadata(value, body), body, durable=True)
        worker.store.remove = AsyncMock(return_value=True)
        worker.reply = AsyncMock(side_effect=[RuntimeError("unroutable"), None])
        try:
            await worker.handle(message, "index")
            worker.store.remove.assert_awaited_once()
            worker.reply.assert_awaited_once()
            assert worker.reply.await_args.args[2] is True
            assert message.events == ["reject"] and message.body == b""
        finally:
            await worker.close()
    asyncio.run(run())


def test_reconnect_keeps_inflight_byte_reservations_until_each_callback_finishes():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        started, release_first, release_second = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = 0
        async def blocked(_body):
            nonlocal calls
            calls += 1
            started.set()
            await (release_first if calls == 1 else release_second).wait()
            return [0, 1]
        worker.ollama.embed_image = blocked
        tasks = []
        try:
            _, _, parts = image_job(image_count=1)
            first = asyncio.create_task(worker.handle(parts[0], "index"))
            tasks.append(first)
            await started.wait()
            worker.clear_pending()
            _, _, later_parts = image_job(image_count=1)
            second = asyncio.create_task(worker.handle(later_parts[0], "index"))
            tasks.append(second)
            await asyncio.sleep(0)
            retained_size = len(later_parts[0].body)
            assert retained_size > 0
            release_first.set()
            await first
            assert worker.pending_bytes == retained_size
            release_second.set()
            await second
            assert worker.pending_bytes == 0
        finally:
            release_first.set()
            release_second.set()
            await asyncio.gather(*tasks)
            await worker.close()
    asyncio.run(run())
