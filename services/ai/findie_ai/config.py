"""Server-side model and transport configuration; no secrets in status output."""

from dataclasses import dataclass, field
import ipaddress
import os
import re
from urllib.parse import urlsplit


QUERY_INSTRUCTION = (
    "Given a Vietnamese lost-item description, retrieve matching found-item posts, "
    "preserving object details and precise finding locations."
)


def loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    service_token: str = field(repr=False)
    search_dsn: str = field(default="", repr=False)
    rabbitmq_url: str = field(default="", repr=False)
    ollama_base_url: str = field(default="http://127.0.0.1:11434", repr=False)
    ollama_api_key: str = field(default="", repr=False)
    model_id: str = "qwen3-embedding:4b"
    revision: str = ""
    dimensions: int = 2048
    query_instruction: str = QUERY_INSTRUCTION
    search_profile: str = "text-description-v1"
    index_queue: str = "findie.ai.commands"
    result_queue: str = "findie.api.results"
    query_queue: str = "findie.ai.query"
    image_queue: str = "findie.ai.image"
    image_search_enabled: bool = False
    image_search_profile: str = "image-only-v1"
    redaction_model: str = "qwen3-vl:4b-instruct"
    redaction_revision: str = ""

    def __post_init__(self):
        if not self.service_token:
            raise ValueError("AI_SERVICE_TOKEN must be configured.")
        if not 1 <= self.dimensions <= 16000:
            raise ValueError("AI_EMBEDDING_DIMENSIONS must be between 1 and 16000.")
        if self.revision and not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", self.revision):
            raise ValueError("AI_EMBEDDING_REVISION must pin the model fingerprint SHA-256.")
        if self.redaction_revision and not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", self.redaction_revision):
            raise ValueError("AI_REDACTION_REVISION must pin the Ollama manifest SHA-256.")
        if (not self.model_id or not self.search_profile or not self.image_search_profile
                or not self.redaction_model or len(self.query_instruction) > 2000):
            raise ValueError("Invalid model/search profile configuration.")
        endpoint = urlsplit(self.ollama_base_url)
        if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError("Invalid OLLAMA_BASE_URL.")
        if not loopback(endpoint.hostname) and (endpoint.scheme != "https" or not self.ollama_api_key):
            raise ValueError("Remote Ollama requires HTTPS and OLLAMA_API_KEY on an authenticated gateway.")
        if self.rabbitmq_url:
            broker = urlsplit(self.rabbitmq_url)
            if (broker.scheme not in {"amqp", "amqps"} or not broker.hostname
                    or broker.scheme == "amqp" and not loopback(broker.hostname)):
                raise ValueError("RabbitMQ requires AMQPS outside loopback.")
        queues = (self.index_queue, self.result_queue, self.query_queue, self.image_queue)
        if len(set(queues)) != 4 or any(not q or len(q.encode()) > 255 for q in queues):
            raise ValueError("AI queue names must be distinct and valid.")

    @property
    def enabled(self) -> bool:
        return bool(self.search_dsn and self.rabbitmq_url and self.revision)

    @classmethod
    def from_env(cls):
        image_search = os.environ.get("AI_IMAGE_SEARCH_ENABLED", "false").lower()
        if image_search not in {"true", "false"}:
            raise ValueError("AI_IMAGE_SEARCH_ENABLED must be true or false.")
        return cls(
            service_token=os.environ.get("AI_SERVICE_TOKEN", "").strip(),
            search_dsn=os.environ.get("AI_SEARCH_DSN", ""),
            rabbitmq_url=os.environ.get("AI_RABBITMQ_URL", os.environ.get("RabbitMq__Uri", "")),
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_api_key=os.environ.get("OLLAMA_API_KEY", ""),
            model_id=os.environ.get("AI_EMBEDDING_MODEL", "qwen3-embedding:4b"),
            revision=os.environ.get("AI_EMBEDDING_REVISION", ""),
            dimensions=int(os.environ.get("AI_EMBEDDING_DIMENSIONS", "2048")),
            query_instruction=os.environ.get("AI_EMBEDDING_QUERY_INSTRUCTION", QUERY_INSTRUCTION),
            search_profile=os.environ.get("AI_TEXT_SEARCH_PROFILE", "text-description-v1"),
            image_search_enabled=image_search == "true",
            image_search_profile=os.environ.get("AI_IMAGE_SEARCH_PROFILE", "image-only-v1"),
            redaction_model=os.environ.get("AI_REDACTION_MODEL", "qwen3-vl:4b-instruct"),
            redaction_revision=os.environ.get("AI_REDACTION_REVISION", ""),
            **{f"{kind}_queue": os.environ.get(f"AI_{kind.upper()}_QUEUE", default)
               for kind, default in (("index", "findie.ai.commands"), ("result", "findie.api.results"),
                                     ("query", "findie.ai.query"), ("image", "findie.ai.image"))},
        )
