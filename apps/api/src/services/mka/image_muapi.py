"""MUAPI as the primary AI image vendor (Gemini stays the fallback).

Fork-owned. Enabled per deployment with ``MKA_IMAGE_VENDOR=muapi`` plus
``MUAPI_API_KEY``; anything else leaves the upstream Gemini path untouched. The
single upstream hook lives in ``services/ai/image/generator.py::generate_image``.

Flow: submit ``POST /{model}`` -> poll ``GET /predictions/{id}/result`` -> download
the hosted output (SSRF-guarded; hosts from ``MUAPI_OUTPUT_HOSTS``, default ``muapi.ai``) -> normalise to PNG (the router stores ``.png``).
Refine uploads the source image(s) to MUAPI first (``POST /upload_file``).

Outputs are downscaled (LANCZOS, never upscaled) to ``MUAPI_MAX_OUTPUT_SIDE`` (default 1536)
and saved as optimized PNG; uploaded source images are re-encoded to RGB JPEG q90, <=2048px.

One overall deadline (``MUAPI_TIMEOUT_SECONDS``, default 60) spans upload, submit, poll
and download; each HTTP call gets min(remaining, 30s).

Logging: exception type and HTTP status only. Never the key, URLs or prompts.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from typing import Any, Callable, Optional, TypeVar
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

# Mirrors upstream generator.MAX_PROMPT_CHARS (not imported: generator imports this module).
MAX_PROMPT_CHARS = 4000

DEFAULT_BASE_URL = "https://api.muapi.ai/api/v1"
DEFAULT_MODEL = "bytedance-seedream-v4.5"
DEFAULT_EDIT_MODEL = "bytedance-seedream-v4.5-edit"
DEFAULT_ASPECT_RATIO = "4:3"
DEFAULT_TIMEOUT_SECONDS = 60.0  # one overall deadline; leaves room for Gemini under a ~100s proxy limit
MAX_CALL_TIMEOUT_SECONDS = 30.0
DEFAULT_OUTPUT_HOSTS = "muapi.ai"

MAX_OUTPUT_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_PIXELS = 64_000_000
DEFAULT_MAX_OUTPUT_SIDE = 1536
MAX_UPLOAD_SIDE = 2048
MAX_REDIRECTS = 3
POLL_INTERVAL_SECONDS = 2.0

_PENDING = {"queued", "pending", "processing", "starting", "running", "in_progress"}
_FAILED = {"failed", "cancelled", "canceled", "error"}

T = TypeVar("T")


class MuapiError(Exception):
    """Any MUAPI failure; callers fall back to Gemini."""


def is_muapi_enabled() -> bool:
    """True when the vendor flag is ``muapi`` and a key is present (read at call time)."""
    vendor = os.environ.get("MKA_IMAGE_VENDOR", "").strip().lower()
    return vendor == "muapi" and bool(os.environ.get("MUAPI_API_KEY", "").strip())


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or "").strip() or default


def _timeout_seconds() -> float:
    try:
        value = float(_env("MUAPI_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def _sniff_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"


def _output_hosts() -> list[str]:
    raw = _env("MUAPI_OUTPUT_HOSTS", DEFAULT_OUTPUT_HOSTS)
    hosts = [h.strip().lower().strip(".") for h in raw.split(",")]
    return [h for h in hosts if h and "/" not in h and ":" not in h and "@" not in h]


def _remaining(deadline: float) -> float:
    """Per-call timeout: min(time left, 30s). Raises when the budget is spent."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise MuapiError("time budget exhausted")
    return min(left, MAX_CALL_TIMEOUT_SECONDS)


def _is_allowed_output_url(url: str) -> bool:
    """https only; host equals or is a subdomain of a ``MUAPI_OUTPUT_HOSTS`` entry; port 443 only."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if port not in (None, 443):
        return False
    return any(host == h or host.endswith("." + h) for h in _output_hosts())


def _extract_url(payload: Any) -> Optional[str]:
    """Find the hosted URL in an upload response (key name varies by deployment)."""
    if isinstance(payload, str):
        return payload if payload.startswith("http") else None
    if isinstance(payload, dict):
        for key in ("url", "file_url", "hosted_url", "download_url", "output"):
            found = _extract_url(payload.get(key))
            if found:
                return found
        return _extract_url(payload.get("data"))
    return None


def _prepare_upload(data: bytes) -> bytes:
    """Re-encode a source image for upload: <=2048px longest side, RGB JPEG q90 (alpha onto white).

    MUAPI's /upload_file rejects large files (HTTP 400 on an ~11 MB PNG).
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > MAX_OUTPUT_PIXELS:
                raise MuapiError("source image too large")
            img.load()
            if "A" in img.getbands() or img.mode == "P":
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                img = flat
            elif img.mode != "RGB":
                img = img.convert("RGB")
            longest = max(img.size)
            if longest > MAX_UPLOAD_SIDE:
                scale = MAX_UPLOAD_SIDE / longest
                img = img.resize(
                    (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=90)
            return out.getvalue()
    except MuapiError:
        raise
    except Exception as e:  # noqa: BLE001
        raise MuapiError("source image is not decodable") from e


async def _upload(client: httpx.AsyncClient, base: str, data: bytes, deadline: float) -> str:
    jpeg = await asyncio.to_thread(_prepare_upload, data)
    resp = await client.post(
        f"{base}/upload_file", files={"file": ("source.jpg", jpeg, "image/jpeg")},
        timeout=_remaining(deadline),
    )
    if resp.status_code >= 400:
        raise MuapiError(f"upload failed with HTTP {resp.status_code}")
    url = _extract_url(resp.json())
    if not url:
        raise MuapiError("upload response had no hosted URL")
    return url


async def _submit(
    client: httpx.AsyncClient, base: str, model: str, body: dict, deadline: float
) -> str:
    resp = await client.post(f"{base}/{model}", json=body, timeout=_remaining(deadline))
    if resp.status_code >= 400:
        raise MuapiError(f"submit failed with HTTP {resp.status_code}")
    request_id = resp.json().get("request_id")
    if not request_id:
        raise MuapiError("submit response had no request_id")
    return str(request_id)


async def _poll(client: httpx.AsyncClient, base: str, request_id: str, deadline: float) -> str:
    """Poll until completed; return the first output URL."""
    while True:
        resp = await client.get(
            f"{base}/predictions/{request_id}/result", timeout=_remaining(deadline)
        )
        if resp.status_code >= 400:
            raise MuapiError(f"poll failed with HTTP {resp.status_code}")
        data = resp.json()
        status = str(data.get("status", "")).lower()
        if status == "completed":
            if any(data.get("has_nsfw_contents") or []):
                raise MuapiError("output flagged by content filter")
            outputs = data.get("outputs") or []
            if not outputs or not isinstance(outputs[0], str):
                raise MuapiError("completed without outputs")
            return outputs[0]
        if status in _FAILED:
            raise MuapiError(f"prediction ended with status {status}")
        if status not in _PENDING:
            raise MuapiError("unknown prediction status")
        if time.monotonic() + POLL_INTERVAL_SECONDS > deadline:
            raise MuapiError("timed out waiting for prediction")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _download(url: str, deadline: float) -> bytes:
    """Fetch the output with the SSRF guard: allowed host on every hop, size capped."""
    # A fresh client without the API key header: the key must never reach a CDN.
    async with httpx.AsyncClient(follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if not _is_allowed_output_url(url):
                raise MuapiError("output URL rejected")
            async with client.stream("GET", url, timeout=_remaining(deadline)) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise MuapiError("redirect without location")
                    url = urljoin(url, location)
                    continue
                if resp.status_code >= 400:
                    raise MuapiError(f"download failed with HTTP {resp.status_code}")
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_OUTPUT_BYTES:
                    raise MuapiError("output too large")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    _remaining(deadline)
                    buf.extend(chunk)
                    if len(buf) > MAX_OUTPUT_BYTES:
                        raise MuapiError("output too large")
                return bytes(buf)
    raise MuapiError("too many redirects")


def _max_output_side() -> int:
    try:
        value = int(_env("MUAPI_MAX_OUTPUT_SIDE", str(DEFAULT_MAX_OUTPUT_SIDE)))
    except ValueError:
        return DEFAULT_MAX_OUTPUT_SIDE
    return value if value > 0 else DEFAULT_MAX_OUTPUT_SIDE


def _to_png(data: bytes) -> bytes:
    max_side = _max_output_side()
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width * height > MAX_OUTPUT_PIXELS:
                raise MuapiError("output image too large")
            img.load()
            if img.mode not in ("RGB", "RGBA", "L", "LA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            longest = max(img.size)
            if longest > max_side:  # downscale only, never upscale
                scale = max_side / longest
                img = img.resize(
                    (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except MuapiError:
        raise
    except Exception as e:  # noqa: BLE001
        raise MuapiError("output is not a decodable image") from e


async def generate_image_muapi(
    prompt: str, *, input_images: Optional[list[bytes]] = None
) -> bytes:
    """Generate (or edit) an image through MUAPI. Returns PNG bytes or raises ``MuapiError``."""
    api_key = (os.environ.get("MUAPI_API_KEY") or "").strip()
    if not api_key:
        raise MuapiError("MUAPI key not configured")
    prompt = (prompt or "").strip()[:MAX_PROMPT_CHARS]
    if not prompt:
        raise MuapiError("empty prompt")

    base = _env("MUAPI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    deadline = time.monotonic() + _timeout_seconds()
    imgs = [img for img in (input_images or []) if img]

    body: dict[str, Any] = {
        "prompt": prompt,
        "aspect_ratio": _env("MUAPI_IMAGE_ASPECT_RATIO", DEFAULT_ASPECT_RATIO),
        "quality": "high",
    }
    try:
        async with httpx.AsyncClient(
            timeout=MAX_CALL_TIMEOUT_SECONDS, headers={"x-api-key": api_key}, follow_redirects=False
        ) as client:
            if imgs:
                body["images_list"] = [await _upload(client, base, img, deadline) for img in imgs]
                model = _env("MUAPI_IMAGE_EDIT_MODEL", DEFAULT_EDIT_MODEL)
            else:
                model = _env("MUAPI_IMAGE_MODEL", DEFAULT_MODEL)
            request_id = await _submit(client, base, model, body, deadline)
            output_url = await _poll(client, base, request_id, deadline)
        raw = await _download(output_url, deadline)
    except MuapiError:
        raise
    except (httpx.HTTPError, ValueError) as e:
        # Type only: httpx messages can embed request URLs.
        raise MuapiError(f"transport error: {type(e).__name__}") from None
    return await asyncio.to_thread(_to_png, raw)


async def attempt(
    prompt: str, input_images: Optional[list[bytes]]
) -> tuple[Optional[bytes], bool]:
    """Try MUAPI when enabled. Returns ``(png_bytes_or_None, muapi_was_tried)``."""
    if not is_muapi_enabled():
        return None, False
    try:
        return await generate_image_muapi(prompt, input_images=input_images), True
    except MuapiError as e:
        logger.warning("MUAPI image generation failed, falling back: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "MUAPI image generation failed, falling back: %s", type(e).__name__
        )
    return None, True


def fallback_config(resolve: Callable[[], T], muapi_tried: bool) -> T:
    """Resolve the Gemini config; if MUAPI was tried and Gemini has no key, fail generically.

    Without this the router would answer 403 "needs a Gemini key" for what is really
    a MUAPI outage; a plain error yields 502 plus the credit refund instead.
    """
    from src.services.ai.llm import AINotConfiguredError

    try:
        return resolve()
    except AINotConfiguredError:
        if muapi_tried:
            raise RuntimeError("Image generation failed") from None
        raise
