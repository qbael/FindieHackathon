"""Disposable worker/broker/PostgreSQL checks; no real model quality is measured.

Run from the repository root:
    uv run --project services/ai --locked python services/ai/tests/integration.py
"""

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import aio_pika
import psycopg
from PIL import Image, PngImagePlugin


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/ai"))
MODEL = "qwen3-embedding:4b"
REVISION = "a" * 64
DIMENSIONS = 8
REDACTION_MODEL = "qwen3-vl:4b-instruct"
REDACTION_REVISION = "b" * 64
CAMPUS = "Trường Đại học Sài Gòn"


class OllamaStub(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/api/tags":
            self.respond({"models": [{"name": model, "model": model, "digest": revision}
                for model, revision in ((MODEL, REVISION), (REDACTION_MODEL, REDACTION_REVISION))]})
        else:
            self.respond({}, 404)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            self.respond({"capabilities": ["embedding", "vision"] if payload["model"] == MODEL else ["completion", "vision"]})
            return
        if self.path == "/api/generate" and payload.get("model") == REDACTION_MODEL:
            image = base64.b64decode(payload["images"][0], validate=True)
            with Image.open(BytesIO(image)) as decoded:
                decoded.load()
            self.respond({"model": REDACTION_MODEL, "done": True, "done_reason": "stop",
                "response": json.dumps({"regions": [{"label": "face", "bbox": [100, 100, 600, 600]}]})})
            return
        if self.path != "/api/embed":
            self.respond({}, 404)
            return
        if payload.get("model") != MODEL:
            self.respond({"error": "unknown test model"}, 400)
            return
        inputs = payload["input"]
        if not isinstance(inputs, list):
            inputs = [inputs]
        vectors = []
        for value in inputs:
            # Keep text scores equal for lexical ranking, but isolate the image vector space.
            if isinstance(value, dict):
                with Image.open(BytesIO(base64.b64decode(value["image"], validate=True))) as image:
                    image.load()
                vectors.append([0.0, 1.0] + [0.0] * (DIMENSIONS - 2))
            else:
                vectors.append([1.0] + [0.0] * (DIMENSIONS - 1))
        self.respond({"model": MODEL, "embeddings": vectors})

    def respond(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def snapshot(item_id, description, area=CAMPUS, version=1, removed=False):
    title = "Ví da đen"
    document = {
        "title": title, "publicDescription": description, "foundArea": area,
        "foundTimePrecision": "date", "foundOn": "2026-10-24", "foundFrom": None,
        "foundUntil": None, "foundTimezone": "Asia/Ho_Chi_Minh",
        "custody": {"kind": "external", "displayName": None, "pointId": None,
                    "name": "Bàn tiếp nhận", "publicAddress": area, "instructions": None},
    }
    return {
        "schemaVersion": 1, "itemId": item_id, "documentVersion": version,
        "kind": "tombstone" if removed else "snapshot", "document": None if removed else document,
        "sources": [] if removed else [{"kind": "text", "id": item_id, "version": 1,
            "sha256": digest((title + "\n" + description).encode()), "processingProfile": "text-v1"}],
    }


async def checks(broker_url, dsn, ollama_url):
    connection = await aio_pika.connect(broker_url)
    async with connection:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        results = await channel.declare_queue("findie.api.results", durable=True, passive=True)
        replies = await channel.declare_queue("", exclusive=True, auto_delete=True,
            arguments={"x-message-ttl": 60000, "x-max-length": 64, "x-max-length-bytes": 33554432})
        waiters = {}

        async def receive(message):
            async with message.process(requeue=False):
                waiter = waiters.get(message.correlation_id)
                if waiter is not None and not waiter.done():
                    waiter.set_result((json.loads(message.headers["metadata"]), message.body))

        await results.consume(receive)
        await replies.consume(receive)

        async def request(kind, body, metadata, *, persistent=False, content_type="application/json", parts=(), parts_first=False):
            correlation = str(uuid4())
            waiter = asyncio.get_running_loop().create_future()
            waiters[correlation] = waiter
            header = {"schemaVersion": 1, "deadlineAt": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
                      "modelId": MODEL, "modelRevision": REVISION, **metadata}
            route = "findie.ai.commands" if persistent else (
                "findie.ai.image" if content_type.startswith("image/") else "findie.ai.query")
            try:
                async def publish(operation, payload, fields, mime):
                    await channel.default_exchange.publish(aio_pika.Message(
                        body=payload, headers={"metadata": encoded(header | fields).decode()}, type=operation,
                        correlation_id=correlation, reply_to=results.name if persistent else replies.name,
                        content_type=mime, expiration=timedelta(seconds=30),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT if persistent else aio_pika.DeliveryMode.NOT_PERSISTENT,
                    ), routing_key=route, mandatory=True)
                if parts_first and parts:
                    source, output = parts[0]
                    fields = {"sourceId": source["id"], "sourceVersion": source["version"],
                        "sourceSha256": source["sha256"], "processingProfile": "image-v1"}
                    await publish("index.source.image", output, fields, "image/png")
                    await publish("index.source.image", output, fields, "image/png")
                await publish(kind, body, {}, content_type)
                for source, output in (parts[1:] if parts_first else parts):
                    await publish("index.source.image", output, {"sourceId": source["id"], "sourceVersion": source["version"],
                        "sourceSha256": source["sha256"], "processingProfile": "image-v1"}, "image/png")
                response, response_body = await asyncio.wait_for(waiter, timeout=35)
                assert response["schemaVersion"] == 1 and response["kind"] == kind, "response envelope must identify the operation"
                return response, response_body
            finally:
                waiters.pop(correlation, None)

        async def index(value, *, expect_success=True, parts=(), parts_first=False):
            body = encoded(value)
            metadata = {"jobId": str(uuid4()), "leaseToken": str(uuid4()), "itemId": value["itemId"],
                        "documentVersion": value["documentVersion"], "snapshotSha256": digest(body), "dimensions": DIMENSIONS}
            kind = "index.remove" if value["kind"] == "tombstone" else "index.upsert"
            response, _ = await request(kind, body, metadata, persistent=True, parts=parts, parts_first=parts_first)
            if not expect_success:
                assert not response["succeeded"] and not response["committed"]
                return
            assert response["succeeded"] and response["committed"], "index receipt must report a committed transaction"
            for field, expected in metadata.items():
                assert response[field] == expected, f"index receipt must echo {field}"
            async with await psycopg.AsyncConnection.connect(dsn) as db:
                cursor = await db.execute("SELECT document_version, tombstone FROM ai_items WHERE item_id = %s", (UUID(value["itemId"]),))
                current = await cursor.fetchone()
                assert current and current[0] >= value["documentVersion"], "receipt must follow the durable watermark commit"
                if current[0] == value["documentVersion"]:
                    assert current[1] == (value["kind"] == "tombstone"), "receipt must reflect the committed snapshot"
                cursor = await db.execute("SELECT count(*) FROM ai_documents WHERE item_id = %s", (UUID(value["itemId"]),))
                assert (await cursor.fetchone())[0] == (0 if current[1] else len(value["sources"])), "all sources must commit with their watermark"

        search_metadata = {"processingProfile": "text-v1", "searchProfileId": "text-description-v1",
                           "searchProfileVersion": 1, "mode": "text", "area": CAMPUS,
                           "from": None, "until": None, "limit": 10, "candidateLimit": 200}

        async def search(text, **filters):
            metadata = search_metadata | filters
            body = encoded({"text": text, **{key: metadata[key] for key in ("area", "from", "until")}})
            response, body = await request("search.hybrid", body, metadata)
            assert response["succeeded"], "valid text search must succeed"
            for field in ("modelId", "modelRevision", "processingProfile", "searchProfileId", "searchProfileVersion"):
                assert response[field] == ({"modelId": MODEL, "modelRevision": REVISION} | metadata)[field]
            return json.loads(body)["candidates"]

        room_id, hall_id, other_id = (str(UUID(int=value)) for value in (3, 1, 2))
        room = snapshot(room_id, "Ví da đen nhặt được tại phòng học E.205.")
        hall = snapshot(hall_id, "Ví da đen nhặt được tại sảnh hội trường A.")
        other = snapshot(other_id, "Ví da đen nhặt được tại phòng học E.205.", "Trường Đại học Khác")
        for value in (hall, other, room):
            await index(value)

        candidates = await search("ví da đen tại phòng E.205")
        assert candidates and candidates[0]["itemId"] == room_id, "exact classroom must rank before a different location"
        assert all(hit["itemId"] != other_id for hit in candidates), "campus filter must exclude another university"
        for hit in candidates:
            source = room["sources"][0] if hit["itemId"] == room_id else hall["sources"][0]
            assert hit["documentVersion"] == 1 and hit["sourceId"] == hit["itemId"]
            assert hit["sourceVersion"] == source["version"] and hit["sourceSha256"] == source["sha256"]
        assert (await search("ví da đen tại sảnh hội trường A"))[0]["itemId"] == hall_id
        assert not await search("ví da đen", area="Khu vực không tồn tại"), "area filters must not be relaxed"
        assert not await search("ví da đen", **{"from": "2026-10-25"}), "date filters must run before candidate limits"

        from findie_ai.config import Settings
        from findie_ai.evaluate import Case, evaluate
        report = await evaluate([
            Case(text="ví đen phòng E.205", area=CAMPUS, relevantItemIds=[room_id]),
            Case(text="ví đen sảnh hội trường A", area=CAMPUS, relevantItemIds=[hall_id]),
            Case(text="mũ bảo hiểm", area="Khu vực không tồn tại", relevantItemIds=[]),
        ], Settings(service_token="test", search_dsn=dsn, ollama_base_url=ollama_url,
                    model_id=MODEL, revision=REVISION, dimensions=DIMENSIONS))
        assert set(report["results"]) == {"semantic", "lexical", "hybrid"}
        assert report["results"]["hybrid"]["hitAt10"] == 1
        assert report["results"]["hybrid"]["noMatchWithSuggestionsRate"] == 0

        response, _ = await request("search.hybrid", encoded({"text": "ví", "area": CAMPUS, "from": None, "until": None}),
            search_metadata | {"modelRevision": "b" * 64})
        assert not response["succeeded"], "different model revisions must fail instead of mixing vector spaces"

        # A private upload is normalized and masked in RAM before any persistent index part exists.
        private_note = "PRIVATE-ORIGINAL-METADATA-NOT-FOR-STORAGE"
        buffer = BytesIO()
        info = PngImagePlugin.PngInfo()
        info.add_text("private", private_note)
        with Image.new("RGB", (20, 20), "red") as image:
            image.save(buffer, format="PNG", pnginfo=info)
        raw_image = buffer.getvalue()
        response, output = await request("image.redact", raw_image,
            {"modelId": REDACTION_MODEL, "modelRevision": REDACTION_REVISION,
             "itemId": room_id, "imageId": str(uuid4()), "sourceVersion": 1,
             "sourceSha256": digest(raw_image), "processingProfile": "redact-v3"}, content_type="image/png")
        assert response["succeeded"] and response["sha256"] == digest(output)
        assert response["contentType"] == "image/png" and response["byteSize"] == len(output)
        assert output != raw_image and private_note.encode() not in output
        with Image.open(BytesIO(output)) as image:
            assert not image.info and image.getpixel((5, 5)) == (0, 0, 0)
        full = snapshot(room_id, room["document"]["publicDescription"], version=2)
        full["sources"].extend({"kind": "image", "id": str(uuid4()), "version": 1,
            "sha256": digest(output), "processingProfile": "image-v1"} for _ in range(2))
        parts = [(source, output) for source in full["sources"] if source["kind"] == "image"]
        await index(full, parts=parts, parts_first=True)
        await index(full, parts=parts)  # Exact replay remains a full, atomic manifest.
        assert (await search("ví E.205"))[0]["sourceId"] == room_id

        async def image_search(**filters):
            response, body = await request("search.hybrid.image", raw_image,
                search_metadata | {"mode": "image", "processingProfile": "image-v1",
                    "searchProfileId": "image-only-v1"} | filters, content_type="image/png")
            assert response["succeeded"]
            return json.loads(body)["candidates"]

        hits = await image_search()
        assert len(hits) == 1 and hits[0]["itemId"] == room_id
        assert hits[0]["sourceId"] in {source["id"] for source, _ in parts}
        assert hits[0]["sourceSha256"] == digest(output) and hits[0]["documentVersion"] == 2
        assert not await image_search(area="Other campus")
        assert not await image_search(**{"from": "2026-10-25"})
        async with await psycopg.AsyncConnection.connect(dsn) as db:
            cursor = await db.execute("SELECT data_type FROM information_schema.columns WHERE table_name IN ('ai_items', 'ai_documents')")
            assert all(row[0] != "bytea" for row in await cursor.fetchall()), "raw/output/query bytes have no persistence column"
            cursor = await db.execute("SELECT search_terms::text, location_tokens FROM ai_documents WHERE processing_profile = 'image-v1'")
            assert all(not terms and not tokens for terms, tokens in await cursor.fetchall()), "image retrieval must not invent OCR/lexical terms"

        await index(snapshot(room_id, "", version=3, removed=True))
        await index(room, expect_success=False)
        await index(full, parts=parts, expect_success=False)
        assert not await image_search(), "old image manifests cannot resurrect a tombstone"
        assert all(hit["itemId"] != room_id for hit in await search("ví da đen tại phòng E.205"))
        print("PASS: Python worker with real PostgreSQL/RabbitMQ: text ranking, full output-only image manifest/parts, atomic receipts, image provenance/dedupe, filters, model mismatch and tombstone replay")


def run():
    suffix = secrets.token_hex(6)
    database_name, broker_name = "findie-ai-test-" + suffix, "findie-ai-broker-" + suffix
    password, token = secrets.token_hex(24), secrets.token_hex(24)
    environment = os.environ | {"POSTGRES_DB": "findie_search", "POSTGRES_USER": "findie_test",
        "POSTGRES_PASSWORD": password, "RABBITMQ_DEFAULT_USER": "findie_test", "RABBITMQ_DEFAULT_PASS": password}
    server = ThreadingHTTPServer(("127.0.0.1", 0), OllamaStub)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    worker = None
    try:
        subprocess.run(["docker", "run", "--detach", "--rm", "--name", database_name,
            "--env", "POSTGRES_DB", "--env", "POSTGRES_USER", "--env", "POSTGRES_PASSWORD",
            "--publish", "127.0.0.1::5432", "pgvector/pgvector:0.8.2-pg17-trixie"], env=environment, check=True, capture_output=True)
        subprocess.run(["docker", "run", "--detach", "--rm", "--name", broker_name,
            "--env", "RABBITMQ_DEFAULT_USER", "--env", "RABBITMQ_DEFAULT_PASS",
            "--env", "RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS=+S 2:2", "--publish", "127.0.0.1::5672",
            "rabbitmq@sha256:76412b1ed2865b88ed01b4a504f72e888842f2089a7527743d325ce7c9d3a43b"],
            env=environment, check=True, capture_output=True)

        def port(name, container_port):
            return int(subprocess.check_output(["docker", "port", name, container_port], text=True).strip().rsplit(":", 1)[1])

        db_port, broker_port = port(database_name, "5432/tcp"), port(broker_name, "5672/tcp")
        dsn = f"postgresql://findie_test:{password}@127.0.0.1:{db_port}/findie_search"
        broker_url = f"amqp://findie_test:{password}@127.0.0.1:{broker_port}/"
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(dsn, connect_timeout=1):
                    pass
                with socket.create_connection(("127.0.0.1", broker_port), timeout=1) as probe:
                    probe.sendall(b"AMQP\x00\x00\x09\x01")
                    if not probe.recv(8):
                        raise OSError("Broker is starting")
                break
            except (OSError, psycopg.OperationalError):
                if time.monotonic() > deadline:
                    raise RuntimeError("Disposable PostgreSQL/RabbitMQ did not become ready.") from None
                time.sleep(0.25)

        async def provision():
            async with await aio_pika.connect(broker_url) as connection:
                channel = await connection.channel()
                for name in ("findie.ai.commands", "findie.api.results"):
                    await channel.declare_queue(name, durable=True)

        asyncio.run(provision())
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            worker_port = listener.getsockname()[1]
        environment |= {"AI_SERVICE_TOKEN": token, "AI_SEARCH_DSN": dsn, "AI_RABBITMQ_URL": broker_url,
            "OLLAMA_BASE_URL": f"http://127.0.0.1:{server.server_port}", "AI_EMBEDDING_MODEL": MODEL,
            "AI_EMBEDDING_REVISION": REVISION, "AI_EMBEDDING_DIMENSIONS": str(DIMENSIONS),
            "AI_INDEX_QUEUE": "findie.ai.commands", "AI_RESULT_QUEUE": "findie.api.results",
            "AI_QUERY_QUEUE": "findie.ai.query", "AI_IMAGE_QUEUE": "findie.ai.image",
            "AI_TEXT_SEARCH_PROFILE": "text-description-v1", "AI_IMAGE_SEARCH_ENABLED": "true",
            "AI_IMAGE_SEARCH_PROFILE": "image-only-v1", "AI_REDACTION_MODEL": REDACTION_MODEL,
            "AI_REDACTION_REVISION": REDACTION_REVISION,
            "PYTHONPATH": str(ROOT / "services/ai")}
        subprocess.run([sys.executable, "-m", "findie_ai.migrate"], cwd=ROOT,
            env=environment | {"AI_SEARCH_MIGRATION_DSN": dsn}, check=True)
        subprocess.run([sys.executable, "-m", "pytest", "services/ai/tests/test_store.py", "-q"], cwd=ROOT,
            env=environment | {"AI_TEST_DATABASE_URL": dsn}, check=True)
        worker = subprocess.Popen([sys.executable, "-m", "uvicorn", "findie_ai.main:app", "--host", "127.0.0.1",
            "--port", str(worker_port), "--log-level", "warning", "--no-access-log"], cwd=ROOT,
            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 45
        while True:
            if worker.poll() is not None:
                raise RuntimeError("Python worker exited before becoming ready.")
            try:
                request = Request(f"http://127.0.0.1:{worker_port}/v1/status", headers={"X-Service-Token": token})
                with urlopen(request, timeout=1) as response:
                    if json.load(response).get("inferenceReady") is True:
                        break
            except (HTTPError, URLError, TimeoutError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Python worker did not report inferenceReady.")
            time.sleep(0.25)
        asyncio.run(checks(broker_url, dsn, environment["OLLAMA_BASE_URL"]))
    finally:
        if worker is not None:
            worker.terminate()
            try:
                _, output = worker.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                _, output = worker.communicate(timeout=5)
            if output:
                print(output.decode(errors="replace").replace(password, "[redacted]").replace(token, "[redacted]")[-4000:], file=sys.stderr)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        for name in (broker_name, database_name):
            subprocess.run(["docker", "rm", "--force", name], capture_output=True)
        if worker is not None and b"Traceback" in output:
            raise RuntimeError("Worker emitted an unhandled exception; see sanitized stderr above.")


if __name__ == "__main__":
    run()
