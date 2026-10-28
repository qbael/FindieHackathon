"""Bounded in-memory decoding, metadata removal and solid privacy masks."""

import asyncio
from hashlib import sha256
from io import BytesIO
import math
from typing import Annotated, Literal

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_BYTES = 10 * 1024 * 1024
MIME_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
Coordinate = Annotated[float, Field(strict=True, ge=0, le=1000, allow_inf_nan=False)]


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["face", "identity_document", "payment_card", "phone", "address", "qr_code", "barcode"]
    bbox: tuple[Coordinate, Coordinate, Coordinate, Coordinate]

    @model_validator(mode="after")
    def ordered(self):
        if self.bbox[0] >= self.bbox[2] or self.bbox[1] >= self.bbox[3]:
            raise ValueError("invalid_region")
        return self


class Regions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regions: list[Region] = Field(max_length=32)


def _decode(body, content_type):
    if content_type not in MIME_FORMATS or not body or len(body) > MAX_BYTES:
        raise ValueError("invalid_image")
    try:
        with Image.open(BytesIO(body), formats=list(MIME_FORMATS.values())) as source:
            width, height = source.size
            if (source.format != MIME_FORMATS[content_type] or getattr(source, "n_frames", 1) != 1
                    or max(width, height) > 10000 or width * height > 40_000_000):
                raise ValueError("invalid_image")
            source.load()
            with ImageOps.exif_transpose(source) as oriented:
                # shortcut: 1600px bounds model payloads; evaluate small-region recall before increasing it.
                oriented.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                with oriented.convert("RGBA") as rgba, Image.new("RGB", rgba.size, "white") as image:
                    image.paste(rgba, mask=rgba.getchannel("A"))
                    return np.array(image)
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError):
        raise ValueError("invalid_image") from None


def _encode(image):
    output = BytesIO()
    with Image.fromarray(image) as clean:
        clean.save(output, format="PNG")
    data = output.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError("output_too_large")
    return data


async def normalize(body: bytes, content_type: str) -> bytes:
    return await asyncio.to_thread(lambda: _encode(_decode(body, content_type)))


def _mask(image, regions):
    height, width = image.shape[:2]
    padding = max(2, math.ceil(max(width, height) / 100))
    for region in regions:
        x1, y1, x2, y2 = region.bbox
        left, top = max(0, math.floor(x1 * width / 1000) - padding), max(0, math.floor(y1 * height / 1000) - padding)
        right, bottom = min(width - 1, math.ceil(x2 * width / 1000) + padding - 1), min(height - 1, math.ceil(y2 * height / 1000) + padding - 1)
        cv2.rectangle(image, (left, top), (right, bottom), (0, 0, 0), thickness=cv2.FILLED)
    return _encode(image)


async def redact(ollama, body: bytes, content_type: str) -> tuple[bytes, dict]:
    image = await asyncio.to_thread(_decode, body, content_type)
    clean = await asyncio.to_thread(_encode, image)
    regions = Regions(regions=await ollama.detect_regions(clean)).regions
    output = await asyncio.to_thread(_mask, image, regions)
    height, width = image.shape[:2]
    return output, {
        "contentType": "image/png", "sha256": sha256(output).hexdigest(), "byteSize": len(output),
        "width": width, "height": height, "sensitiveRegions": [region.model_dump(mode="json") for region in regions],
    }
