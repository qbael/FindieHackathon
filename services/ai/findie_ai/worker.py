"""Bounded AMQP indexing, image processing and search; input images stay in RAM."""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import random
import ssl
import time
from uuid import UUID

import aio_pika

from . import images
from .contracts import IndexImageMetadata, IndexMetadata, Query, RedactMetadata, SearchMetadata, Snapshot
from .ollama import ModelUnavailable, Ollama
from .store import Store


log = logging.getLogger(__name__)
MIMES = {"image/jpeg", "image/png", "image/webp"}


class Worker:
    def __init__(self, settings):
        self.settings = settings
        self.ollama = Ollama(settings)
        self.store = Store(settings.search_dsn, settings.model_id, settings.revision, settings.dimensions)
        self.connection = self.publisher = self.consumer = None
        self.capacity = asyncio.Semaphore(1)
        self.pending = {}
        self.pending_bytes = 0
        self.last_embedding_success = None

    @property
    def connected(self):
        return bool(self.connection and not self.connection.is_closed and self.publisher
                    and not self.publisher.is_closed and self.consumer and not self.consumer.is_closed)

    async def close(self):
        self.clear_pending()
        if self.connection:
            await self.connection.close()
        await self.ollama.close()

    @staticmethod
    def drop_body(message):
        if not getattr(message, "locked", False):
            message.body = b""

    def clear_pending(self):
        for state in self.pending.values():
            state["timer"].cancel()
            for message in state["messages"]:
                self.drop_body(message)
        self.pending.clear()
        # In-flight callbacks still own their byte reservations until their finally blocks run.

    async def probe(self):
        if not self.connected:
            return False
        try:
            async with asyncio.timeout(4):
                await self.store.check()
                await self.ollama.verify_models()
                needs_probe = self.last_embedding_success is None or time.monotonic() - self.last_embedding_success > 15
                if needs_probe and not self.ollama.lock.locked():
                    await self.ollama.embed("Kiểm tra kết nối tìm đồ thất lạc.", query=True)
                    self.last_embedding_success = time.monotonic()
            return self.last_embedding_success is not None
        except Exception:
            return False

    async def run(self):
        delay = 1
        while True:
            try:
                self.connection = await aio_pika.connect(
                    self.settings.rabbitmq_url, timeout=5, heartbeat=30,
                    ssl_context=ssl.create_default_context() if self.settings.rabbitmq_url.startswith("amqps:") else None,
                )
                async with self.connection:
                    self.publisher = await self.connection.channel(publisher_confirms=True, on_return_raises=True)
                    self.consumer = await self.connection.channel()
                    # Two manifests plus their five image parts must fit without waiting for ACKs.
                    await self.consumer.set_qos(prefetch_count=12)
                    index = await self.consumer.declare_queue(self.settings.index_queue, passive=True)
                    await self.consumer.declare_queue(self.settings.result_queue, passive=True)
                    query = await self.consumer.declare_queue(
                        self.settings.query_queue, exclusive=True, auto_delete=True,
                        arguments={"x-message-ttl": 30000, "x-max-length": 32, "x-max-length-bytes": 2 * 1024 * 1024},
                    )
                    image = await self.consumer.declare_queue(
                        self.settings.image_queue, exclusive=True, auto_delete=True,
                        arguments={"x-message-ttl": 300000, "x-max-length": 4, "x-max-length-bytes": 32 * 1024 * 1024},
                    )
                    await index.consume(lambda message: self.handle(message, "index"))
                    await query.consume(lambda message: self.handle(message, "query"))
                    await image.consume(lambda message: self.handle(message, "image"))
                    delay = 1
                    while self.connected:
                        await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Broker exceptions may contain credentials; never log exception or message bodies.
                log.warning("AI broker unavailable; reconnecting.")
            finally:
                self.clear_pending()
                if self.connection and not self.connection.is_closed:
                    await self.connection.close()
                self.connection = self.publisher = self.consumer = None
            await asyncio.sleep(delay + random.random() / 4)
            delay = min(delay * 2, 30)

    def identity(self, metadata):
        redaction = isinstance(metadata, RedactMetadata)
        model = self.settings.redaction_model if redaction else self.settings.model_id
        revision = self.settings.redaction_revision if redaction else self.settings.revision
        if metadata.modelId != model or metadata.modelRevision != revision:
            raise ValueError("model_configuration_mismatch")
        if isinstance(metadata, IndexMetadata) and metadata.dimensions != self.settings.dimensions:
            raise ValueError("dimension_configuration_mismatch")
        if isinstance(metadata, SearchMetadata):
            profile = self.settings.search_profile if metadata.mode == "text" else self.settings.image_search_profile
            if metadata.searchProfileId != profile:
                raise ValueError("search_profile_mismatch")
        if isinstance(metadata, SearchMetadata) and metadata.mode == "image" and not self.settings.image_search_enabled:
            raise ModelUnavailable("image_search_disabled")

    async def execute(self, kind, metadata, body, content_type="application/json"):
        self.identity(metadata)
        if kind == "image.redact":
            if sha256(body).hexdigest() != metadata.sourceSha256:
                raise ValueError("source_hash_mismatch")
            return await images.redact(self.ollama, body, content_type)
        if kind in {"search.hybrid", "search.hybrid.image"}:
            if kind == "search.hybrid":
                query = Query.model_validate_json(body)
                if metadata.mode != "text" or (query.area, query.from_, query.until) != (metadata.area, metadata.from_, metadata.until):
                    raise ValueError("filter_mismatch")
                vector = await self.ollama.embed(query.text, query=True)
                self.last_embedding_success = time.monotonic()
                candidates = await self.store.search(query.text, vector, query.area, query.from_, query.until, metadata.candidateLimit)
            else:
                if metadata.mode != "image":
                    raise ValueError("search_modality_mismatch")
                normalized = await images.normalize(body, content_type)
                vector = await self.ollama.embed_image(normalized)
                self.last_embedding_success = time.monotonic()
                candidates = await self.store.search("", vector, metadata.area, metadata.from_, metadata.until,
                                                     metadata.candidateLimit, modality="image")
            metadata.remaining()
            return {"candidates": candidates}
        snapshot = self.snapshot(kind, metadata, body)
        if kind == "index.upsert":
            if any(source.kind == "image" for source in snapshot.sources):
                raise ValueError("image_parts_required")
            vector = await self.ollama.embed(snapshot.embedding_text())
            committed = await self.store.upsert(snapshot.model_dump(mode="json"), metadata.snapshotSha256, vector, metadata.deadlineAt)
        else:
            committed = await self.store.remove(snapshot.model_dump(mode="json"), metadata.snapshotSha256, metadata.deadlineAt)
        if not committed:
            raise ValueError("snapshot_superseded")
        return {}

    @staticmethod
    def snapshot(kind, metadata, body):
        if sha256(body).hexdigest() != metadata.snapshotSha256:
            raise ValueError("snapshot_hash_mismatch")
        snapshot = Snapshot.model_validate_json(body)
        if (snapshot.itemId, snapshot.documentVersion, snapshot.kind) != (
                metadata.itemId, metadata.documentVersion, "snapshot" if kind == "index.upsert" else "tombstone"):
            raise ValueError("snapshot_identity_mismatch")
        return snapshot

    async def expire(self, key, state):
        await asyncio.sleep(max(0, (state["deadline"] - datetime.now(timezone.utc)).total_seconds()))
        await self.finish(key, state, TimeoutError("parts_deadline_expired"))

    async def collect(self, message, metadata):
        """Retain only bounded public metadata/vectors and ACK handles between parts."""
        key = (metadata.jobId, metadata.leaseToken)
        if self.pending_bytes + len(message.body) > 60 * 1024 * 1024:
            raise ValueError("index_capacity_exhausted")
        common = metadata.model_dump(exclude={"deadlineAt", "sourceId", "sourceVersion", "sourceSha256", "processingProfile"})
        state = self.pending.get(key)
        if state is None:
            if len(self.pending) >= 2:
                raise ValueError("index_capacity_exhausted")
            state = {"common": common, "deadline": metadata.deadlineAt, "manifest": None,
                     "metadata": None, "parts": {}, "validated_parts": set(), "vectors": {}, "messages": [], "finishing": False,
                     "correlation": message.correlation_id, "reply_to": message.reply_to}
            self.pending[key] = state
            state["timer"] = asyncio.create_task(self.expire(key, state))
        if state["common"] != common or state["correlation"] != message.correlation_id or state["reply_to"] != message.reply_to:
            raise ValueError("index_part_identity_mismatch")
        if len(state["messages"]) >= 12:
            raise ValueError("index_capacity_exhausted")
        state["messages"].append(message)
        size = len(message.body)
        self.pending_bytes += size
        if metadata.deadlineAt < state["deadline"]:
            state["deadline"] = metadata.deadlineAt
            state["timer"].cancel()
            state["timer"] = asyncio.create_task(self.expire(key, state))
        try:
            if isinstance(metadata, IndexImageMetadata):
                source_id = str(metadata.sourceId)
                identity = (metadata.sourceVersion, metadata.sourceSha256, metadata.processingProfile)
                if sha256(message.body).hexdigest() != metadata.sourceSha256:
                    raise ValueError("source_hash_mismatch")
                if source_id in state["parts"]:
                    if state["parts"][source_id] != identity:
                        raise ValueError("source_conflict")
                    return
                if len(state["parts"]) >= 5:
                    raise ValueError("too_many_image_parts")
                state["parts"][source_id] = identity
                self.validate_parts(state)
                async with self.capacity:
                    metadata.remaining()
                    normalized = await images.normalize(message.body, message.content_type)
                    if self.settings.image_search_enabled:
                        state["vectors"][source_id] = await self.ollama.embed_image(normalized)
                        self.last_embedding_success = time.monotonic()
                state["validated_parts"].add(source_id)
            else:
                snapshot = self.snapshot("index.upsert", metadata, message.body)
                if state["manifest"] is not None:
                    return
                state["manifest"], state["metadata"] = snapshot, metadata
                self.validate_parts(state)
                async with self.capacity:
                    metadata.remaining()
                    vector = await self.ollama.embed(snapshot.embedding_text())
                self.last_embedding_success = time.monotonic()
                state["vectors"][str(snapshot.itemId)] = vector
            if self.pending.get(key) is state:
                await self.finish(key, state)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self.finish(key, state, error)
        finally:
            self.drop_body(message)
            self.pending_bytes = max(0, self.pending_bytes - size)

    @staticmethod
    def validate_parts(state):
        if state["manifest"] is None:
            return
        expected = {str(source.id): (source.version, source.sha256, source.processingProfile)
                    for source in state["manifest"].sources if source.kind == "image"}
        if any(expected.get(source_id) != identity for source_id, identity in state["parts"].items()):
            raise ValueError("image_manifest_mismatch")

    async def finish(self, key, state, error=None):
        if self.pending.get(key) is not state or state["finishing"]:
            return
        snapshot = state["manifest"]
        if error is None:
            if snapshot is None:
                return
            images = {str(source.id) for source in snapshot.sources if source.kind == "image"}
            vectors = {str(source.id) for source in snapshot.sources
                       if source.kind == "text" or self.settings.image_search_enabled}
            if state["validated_parts"] != images or set(state["vectors"]) != vectors:
                return
        state["finishing"] = True
        if state["timer"] is not asyncio.current_task():
            state["timer"].cancel()
        manifest = next((message for message in state["messages"] if message.type == "index.upsert"), None)
        try:
            if error is None:
                try:
                    remaining = (state["deadline"] - datetime.now(timezone.utc)).total_seconds()
                    async with asyncio.timeout(max(0, remaining)):
                        committed = await self.store.upsert(snapshot.model_dump(mode="json"),
                            state["metadata"].snapshotSha256, dict(state["vectors"]), state["deadline"],
                            text_only=not self.settings.image_search_enabled)
                        if not committed:
                            raise ValueError("snapshot_superseded")
                except Exception as failure:
                    error = failure
            if manifest is None:
                raise ValueError("manifest_missing")
            code = "model_unavailable" if isinstance(error, ModelUnavailable) else "processing_failed" if error else None
            await self.reply(manifest, state["metadata"].model_dump(mode="json", by_alias=True), error is None, {}, code)
            for message in state["messages"]:
                if not message.processed:
                    self.drop_body(message)
                    await message.ack()
        except asyncio.CancelledError:
            raise
        except Exception:
            for message in state["messages"]:
                if not message.processed:
                    try:
                        self.drop_body(message)
                        await message.reject(requeue=False)
                    except Exception:
                        pass
        finally:
            self.pending.pop(key, None)
            state["vectors"].clear()
            for message in state["messages"]:
                self.drop_body(message)

    async def handle(self, message, lane):
        kind = message.type
        durable = lane == "index" and kind in {"index.upsert", "index.remove", "index.source.image"}
        metadata = None
        failure_reply_allowed = True
        try:
            header = message.headers.get("metadata")
            if isinstance(header, str):
                header = header.encode("utf-8")
            if not isinstance(header, (bytes, bytearray)) or len(header) > 16384 or not 0 < len(message.body) <= 10 * 1024 * 1024:
                raise ValueError("invalid_message_size")
            UUID(message.correlation_id)
            if durable:
                if message.reply_to != self.settings.result_queue:
                    raise ValueError("invalid_reply_route")
            elif not message.reply_to or not message.reply_to.startswith("amq.gen-") or len(message.reply_to) > 255:
                raise ValueError("invalid_reply_route")
            image = kind in {"index.source.image", "image.redact", "search.hybrid.image"}
            if not ((durable and (image or message.content_type == "application/json"))
                    or lane == "query" and kind == "search.hybrid" and message.content_type == "application/json"
                    or lane == "image" and kind in {"image.redact", "search.hybrid.image"}):
                raise ValueError("unsupported_operation")
            if image and message.content_type not in MIMES or not image and len(message.body) > 65536:
                raise ValueError("invalid_content_type_or_size")
            model = IndexImageMetadata if kind == "index.source.image" else IndexMetadata if durable else RedactMetadata if kind == "image.redact" else SearchMetadata
            metadata = model.model_validate_json(header)
            self.identity(metadata)
            async with asyncio.timeout(metadata.remaining()):
                if kind in {"index.upsert", "index.source.image"}:
                    await self.collect(message, metadata)
                    return
                async with self.capacity:
                    metadata.remaining()
                    result = await self.execute(kind, metadata, message.body, message.content_type)
            response_metadata = metadata.model_dump(mode="json", by_alias=True)
            if kind == "image.redact":
                result, output_metadata = result
                response_metadata.update(output_metadata)
            failure_reply_allowed = False
            await self.reply(message, response_metadata, True, result)
            self.drop_body(message)
            await message.ack()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if message.processed:
                return
            if isinstance(metadata, IndexMetadata):
                key = (metadata.jobId, metadata.leaseToken)
                state = self.pending.get(key)
                if state is not None:
                    if message in state["messages"]:
                        await self.finish(key, state, error)
                        return
                    failure_reply_allowed = False
            if metadata is not None and kind != "index.source.image" and failure_reply_allowed:
                code = "model_unavailable" if isinstance(error, ModelUnavailable) else "processing_failed"
                try:
                    await self.reply(message, metadata.model_dump(mode="json", by_alias=True), False, {}, code)
                    self.drop_body(message)
                    await message.ack()
                    return
                except Exception:
                    pass
            if not message.processed:
                try:
                    if durable:
                        self.drop_body(message)
                        await message.reject(requeue=False)
                    else:
                        self.drop_body(message)
                        await message.ack()  # Private raw/query bytes must never enter a DLQ.
                except Exception:
                    pass
        finally:
            self.drop_body(message)

    async def reply(self, message, metadata, succeeded, result, error_code=None):
        durable = message.type in {"index.upsert", "index.remove"}
        response = {**metadata, "kind": message.type, "succeeded": succeeded}
        if durable:
            response["committed"] = succeeded
        if error_code:
            response["errorCode"] = error_code
        binary = isinstance(result, bytes)
        payload = result if binary else json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        if len(payload) > (10 * 1024 * 1024 if binary else 262144):
            raise ValueError("response_too_large")
        header = json.dumps(response, separators=(",", ":"))
        if len(header.encode()) > 16384:
            raise ValueError("response_metadata_too_large")
        await self.publisher.default_exchange.publish(
            aio_pika.Message(
                payload, type=message.type, correlation_id=message.correlation_id,
                content_type=metadata["contentType"] if binary else "application/json", headers={"metadata": header},
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT if durable else aio_pika.DeliveryMode.NOT_PERSISTENT,
                expiration=60,
            ), routing_key=message.reply_to, mandatory=True, timeout=3,
        )
