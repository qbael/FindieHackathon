import asyncio
from hashlib import sha256
from io import BytesIO
import struct
import zlib

import numpy as np
from PIL import Image, PngImagePlugin
import pytest

from findie_ai.images import MAX_BYTES, Regions, normalize, redact


def encoded(format="PNG", *, size=(80, 60), **options):
    buffer = BytesIO()
    with Image.new("RGB", size, "white") as image:
        image.save(buffer, format=format, **options)
    return buffer.getvalue()


class Detector:
    def __init__(self, regions):
        self.regions = regions
        self.input = None

    async def detect_regions(self, image):
        self.input = image
        return self.regions


def test_redaction_masks_real_pixels_and_returns_matching_clean_metadata():
    body = encoded()
    detector = Detector([{"label": "phone", "bbox": [250, 250, 750, 750]}])
    output, metadata = asyncio.run(redact(detector, body, "image/png"))
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[15:45, 20:60] == 0).all()
        assert (pixels[0, 0] == 255).all()
        assert image.size == (80, 60) and not image.getexif() and not image.info
    assert detector.input == body
    assert metadata == {"contentType": "image/png", "sha256": sha256(output).hexdigest(),
                        "byteSize": len(output), "width": 80, "height": 60,
                        "sensitiveRegions": [{"label": "phone", "bbox": [250.0, 250.0, 750.0, 750.0]}]}
    assert output != body


def test_no_pii_still_reencodes_strips_metadata_and_applies_exif_orientation():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private input"
    body = encoded("JPEG", size=(80, 60), exif=exif, comment=b"private comment")
    output, metadata = asyncio.run(redact(Detector([]), body, "image/jpeg"))
    assert output != body and b"private" not in output and metadata["sensitiveRegions"] == []
    with Image.open(BytesIO(output)) as image:
        assert image.size == (60, 80) and image.format == "PNG"
        assert not image.getexif() and not image.info


def test_normalization_bounds_size_removes_text_chunks_and_flattens_hidden_pixels():
    chunks = PngImagePlugin.PngInfo()
    chunks.add_text("note", "private input")
    output = asyncio.run(normalize(encoded(size=(3200, 100), pnginfo=chunks), "image/png"))
    with Image.open(BytesIO(output)) as image:
        assert image.size == (1600, 50) and not image.info
    assert b"private" not in output
    buffer = BytesIO()
    with Image.new("RGBA", (2, 2), (255, 0, 0, 0)) as image:
        image.save(buffer, format="PNG")
    output = asyncio.run(normalize(buffer.getvalue(), "image/png"))
    with Image.open(BytesIO(output)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("body,mime", [
    (b"", "image/png"), (b"not an image", "image/png"), (encoded(), "image/jpeg"),
    (encoded("GIF"), "image/png"), (encoded(), "image/gif"),
    (encoded()[:40], "image/png"), (b"x" * (MAX_BYTES + 1), "image/png"),
])
def test_invalid_input_fails_before_model_call(body, mime):
    detector = Detector([])
    with pytest.raises(ValueError):
        asyncio.run(redact(detector, body, mime))
    assert detector.input is None


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_supported_image_formats_normalize_to_clean_png(format, mime):
    output = asyncio.run(normalize(encoded(format), mime))
    with Image.open(BytesIO(output)) as image:
        assert image.format == "PNG" and image.size == (80, 60) and not image.info


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("WEBP", "image/webp")])
def test_animation_is_rejected_before_decode(format, mime):
    buffer = BytesIO()
    with Image.new("RGB", (5, 5), "white") as first, Image.new("RGB", (5, 5), "black") as second:
        first.save(buffer, format=format, save_all=True, append_images=[second], duration=100, loop=0)
    with pytest.raises(ValueError):
        asyncio.run(normalize(buffer.getvalue(), mime))


def test_pixel_axis_limits_are_rejected_before_decode():
    for width, height in ((10001, 1), (7000, 6000)):
        body = bytearray(encoded())
        body[16:24] = struct.pack(">II", width, height)
        body[29:33] = struct.pack(">I", zlib.crc32(body[12:29]))
        with pytest.raises(ValueError):
            asyncio.run(normalize(bytes(body), "image/png"))


@pytest.mark.parametrize("region", [
    {"label": "face", "bbox": [0, 0, float("nan"), 100]},
    {"label": "face", "bbox": [0, 0, float("inf"), 100]},
    {"label": "face", "bbox": [0, 0, 1001, 100]},
    {"label": "face", "bbox": [50, 0, 40, 100]},
    {"label": "face", "bbox": [0, 20, 100, 20]},
    {"label": "face", "bbox": [False, 0, 100, 100]},
    {"label": "face", "bbox": ["0", 0, 100, 100]},
    {"label": "unknown", "bbox": [0, 0, 100, 100]},
    {"label": "face", "bbox": [0, 0, 100, 100], "text": "private input"},
])
def test_untrusted_regions_fail_closed(region):
    with pytest.raises(ValueError):
        asyncio.run(redact(Detector([region]), encoded(), "image/png"))


def test_region_count_is_bounded():
    with pytest.raises(ValueError):
        Regions(regions=[{"label": "face", "bbox": [0, 0, 100, 100]}] * 33)


def test_model_error_does_not_return_raw_input_as_output():
    class BrokenDetector:
        async def detect_regions(self, _image):
            raise RuntimeError("model_unavailable")

    with pytest.raises(RuntimeError, match="model_unavailable"):
        asyncio.run(redact(BrokenDetector(), encoded(), "image/png"))
