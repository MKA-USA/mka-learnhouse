"""Tests for the MUAPI image vendor (fully mocked; no network, no real key)."""

import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from PIL import Image

import src.services.ai.image.generator as gen
import src.services.mka.image_muapi as mu
from src.services.ai.llm import AINotConfiguredError

pytestmark = pytest.mark.asyncio

KEY = "fake-muapi-test-key-not-real"
OUT = "https://cdn.muapi.ai/out/1.webp"


def _img(fmt="WEBP"):
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), (200, 10, 10)).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MKA_IMAGE_VENDOR", "muapi")
    monkeypatch.setenv("MUAPI_API_KEY", KEY)
    monkeypatch.setattr(mu, "POLL_INTERVAL_SECONDS", 0)


def _install(monkeypatch, handler):
    """Route every httpx.AsyncClient in the module through a MockTransport."""
    real = httpx.AsyncClient
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(wrapped)
        return real(*a, **kw)

    monkeypatch.setattr(mu.httpx, "AsyncClient", factory)
    return calls


def _api(outputs=(OUT,), status="completed", nsfw=None, image=None, out_status=200,
         out_headers=None, poll=None, upload_json=None):
    image = image if image is not None else _img()

    def handler(req):
        path = req.url.path
        if req.url.host == "api.muapi.ai":
            if path.endswith("/upload_file"):
                return httpx.Response(200, json=upload_json or {"url": "https://cdn.muapi.ai/up/a.png"})
            if "/predictions/" in path:
                if poll:
                    return httpx.Response(200, json=poll.pop(0) if len(poll) > 1 else poll[0])
                return httpx.Response(200, json={
                    "status": status, "outputs": list(outputs),
                    "has_nsfw_contents": nsfw if nsfw is not None else [False],
                })
            return httpx.Response(200, json={"request_id": "r1", "status": "queued"})
        return httpx.Response(out_status, content=image, headers=out_headers or {})

    return handler


# --- enablement ---

async def test_disabled_without_vendor(monkeypatch):
    monkeypatch.delenv("MKA_IMAGE_VENDOR")
    assert mu.is_muapi_enabled() is False


async def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("MUAPI_API_KEY")
    assert mu.is_muapi_enabled() is False


# --- generation ---

async def test_text_success_returns_png(monkeypatch):
    calls = _install(monkeypatch, _api())
    out = await mu.generate_image_muapi("a mosque")
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    submit = next(c for c in calls if c.url.path.endswith("bytedance-seedream-v4.5"))
    assert submit.headers["x-api-key"] == KEY
    assert b'"aspect_ratio":"4:3"' in submit.content.replace(b" ", b"")
    download = calls[-1]
    assert "x-api-key" not in download.headers  # key never sent to the CDN


async def test_edit_uploads_then_calls_edit_model(monkeypatch):
    calls = _install(monkeypatch, _api())
    await mu.generate_image_muapi("darker", input_images=[_img("PNG")])
    paths = [c.url.path for c in calls]
    assert paths[0].endswith("/upload_file")
    edit = next(c for c in calls if c.url.path.endswith("seedream-v4.5-edit"))
    assert b"https://cdn.muapi.ai/up/a.png" in edit.content
    assert b"images_list" in edit.content


async def test_upload_response_nested_data_key(monkeypatch):
    _install(monkeypatch, _api(upload_json={"data": {"url": "https://cdn.muapi.ai/x.png"}}))
    assert (await mu.generate_image_muapi("p", input_images=[_img("PNG")]))[:4] == b"\x89PNG"


async def test_polls_until_completed(monkeypatch):
    done = {"status": "completed", "outputs": [OUT], "has_nsfw_contents": [False]}
    _install(monkeypatch, _api(poll=[{"status": "queued"}, {"status": "processing"}, done]))
    assert (await mu.generate_image_muapi("p"))[:4] == b"\x89PNG"


@pytest.mark.parametrize("kwargs", [
    {"status": "failed"},
    {"status": "cancelled"},
    {"nsfw": [True]},
    {"outputs": ()},
    {"outputs": ("https://evil.com/a.png",)},
    {"outputs": ("http://cdn.muapi.ai/a.png",)},
    {"outputs": ("https://muapi.ai.evil.com/a.png",)},
    {"outputs": ("https://cdn.muapi.ai@evil.com/a.png",)},
    {"image": b"not an image"},
    {"out_status": 500},
])
async def test_failures_raise(monkeypatch, kwargs):
    _install(monkeypatch, _api(**kwargs))
    with pytest.raises(mu.MuapiError):
        await mu.generate_image_muapi("p")


async def test_oversize_rejected(monkeypatch):
    monkeypatch.setattr(mu, "MAX_OUTPUT_BYTES", 10)
    _install(monkeypatch, _api())
    with pytest.raises(mu.MuapiError):
        await mu.generate_image_muapi("p")


async def test_redirect_to_other_host_rejected(monkeypatch):
    _install(monkeypatch, _api(out_status=302, out_headers={"location": "https://evil.com/x"}))
    with pytest.raises(mu.MuapiError):
        await mu.generate_image_muapi("p")


async def test_timeout_raises(monkeypatch):
    monkeypatch.setenv("MUAPI_TIMEOUT_SECONDS", "0.001")
    monkeypatch.setattr(mu, "POLL_INTERVAL_SECONDS", 1)
    _install(monkeypatch, _api(poll=[{"status": "processing"}]))
    with pytest.raises(mu.MuapiError):
        await mu.generate_image_muapi("p")


async def test_transport_error_wrapped(monkeypatch):
    def boom(req):
        raise httpx.ConnectError("conn to https://api.muapi.ai?k=secret")
    _install(monkeypatch, boom)
    with pytest.raises(mu.MuapiError) as ei:
        await mu.generate_image_muapi("p")
    assert "secret" not in str(ei.value)


# --- generator hook ---

def _gemini_cfg(key="gk"):
    return SimpleNamespace(ai_config=SimpleNamespace(
        provider="google", api_key=key, gemini_api_key=None, image_model=None))


def _gemini_client():
    part = SimpleNamespace(inline_data=SimpleNamespace(data=b"GEMINI"))
    resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=resp)
    return client


def _patch_gen(cfg):
    return (
        patch.object(gen, "get_learnhouse_config", return_value=cfg),
        patch.object(gen.mka_brand, "brand_image_prompt", AsyncMock(side_effect=lambda p, **k: p)),
    )


async def test_hook_disabled_uses_gemini_only(monkeypatch):
    monkeypatch.delenv("MKA_IMAGE_VENDOR")
    spy = AsyncMock()
    monkeypatch.setattr(mu, "generate_image_muapi", spy)
    p1, p2 = _patch_gen(_gemini_cfg())
    with p1, p2, patch("google.genai.Client", return_value=_gemini_client()):
        assert await gen.generate_image("x") == b"GEMINI"
    spy.assert_not_called()


async def test_hook_vendor_without_key_uses_gemini(monkeypatch):
    monkeypatch.delenv("MUAPI_API_KEY")
    spy = AsyncMock()
    monkeypatch.setattr(mu, "generate_image_muapi", spy)
    p1, p2 = _patch_gen(_gemini_cfg())
    with p1, p2, patch("google.genai.Client", return_value=_gemini_client()):
        assert await gen.generate_image("x") == b"GEMINI"
    spy.assert_not_called()


async def test_hook_muapi_success_skips_gemini(monkeypatch):
    _install(monkeypatch, _api())
    client_cls = MagicMock()
    p1, p2 = _patch_gen(_gemini_cfg())
    with p1, p2, patch("google.genai.Client", client_cls):
        out = await gen.generate_image("x")
    assert out[:4] == b"\x89PNG"
    client_cls.assert_not_called()


@pytest.mark.parametrize("kwargs", [{"status": "failed"}, {"nsfw": [True]}])
async def test_hook_failure_falls_back_to_gemini(monkeypatch, kwargs):
    _install(monkeypatch, _api(**kwargs))
    p1, p2 = _patch_gen(_gemini_cfg())
    with p1, p2, patch("google.genai.Client", return_value=_gemini_client()):
        assert await gen.generate_image("x") == b"GEMINI"


async def test_hook_timeout_falls_back_to_gemini(monkeypatch):
    monkeypatch.setenv("MUAPI_TIMEOUT_SECONDS", "0.001")
    monkeypatch.setattr(mu, "POLL_INTERVAL_SECONDS", 1)
    _install(monkeypatch, _api(poll=[{"status": "processing"}]))
    p1, p2 = _patch_gen(_gemini_cfg())
    with p1, p2, patch("google.genai.Client", return_value=_gemini_client()):
        assert await gen.generate_image("x") == b"GEMINI"


async def test_hook_muapi_fails_and_no_gemini_key_is_generic(monkeypatch):
    _install(monkeypatch, _api(status="failed"))
    p1, p2 = _patch_gen(_gemini_cfg(key=None))
    with p1, p2:
        with pytest.raises(RuntimeError) as ei:
            await gen.generate_image("x")
    assert not isinstance(ei.value, AINotConfiguredError)


async def test_hook_disabled_and_no_gemini_key_still_not_configured(monkeypatch):
    monkeypatch.delenv("MKA_IMAGE_VENDOR")
    p1, p2 = _patch_gen(_gemini_cfg(key=None))
    with p1, p2:
        with pytest.raises(AINotConfiguredError):
            await gen.generate_image("x")


async def test_key_never_logged(monkeypatch, caplog):
    _install(monkeypatch, _api(status="failed"))
    p1, p2 = _patch_gen(_gemini_cfg())
    with caplog.at_level(logging.DEBUG), p1, p2, \
            patch("google.genai.Client", return_value=_gemini_client()):
        await gen.generate_image("x")
    assert KEY not in caplog.text


# --- configurable output hosts ---

async def test_output_hosts_env_allows_custom_host(monkeypatch):
    monkeypatch.setenv("MUAPI_OUTPUT_HOSTS", "cdn.example.net")
    _install(monkeypatch, _api(outputs=("https://cdn.example.net/a.webp",)))
    assert (await mu.generate_image_muapi("p"))[:4] == b"\x89PNG"


async def test_output_hosts_env_rejects_muapi_when_overridden(monkeypatch):
    monkeypatch.setenv("MUAPI_OUTPUT_HOSTS", "cdn.example.net")
    _install(monkeypatch, _api(outputs=(OUT,)))
    with pytest.raises(mu.MuapiError):
        await mu.generate_image_muapi("p")


async def test_output_hosts_env_keeps_https_and_port_rules(monkeypatch):
    monkeypatch.setenv("MUAPI_OUTPUT_HOSTS", "cdn.example.net, other.org")
    assert mu._is_allowed_output_url("https://sub.other.org/x")
    assert not mu._is_allowed_output_url("http://cdn.example.net/x")
    assert not mu._is_allowed_output_url("https://cdn.example.net:8443/x")
    assert not mu._is_allowed_output_url("https://u:p@cdn.example.net/x")


# --- overall deadline ---

async def test_default_timeout_is_60(monkeypatch):
    monkeypatch.delenv("MUAPI_TIMEOUT_SECONDS", raising=False)
    assert mu._timeout_seconds() == 60.0


async def test_call_timeout_is_min_remaining_and_30(monkeypatch):
    monkeypatch.setattr(mu.time, "monotonic", lambda: 100.0)
    assert mu._remaining(200.0) == 30.0
    assert mu._remaining(110.0) == 10.0
    with pytest.raises(mu.MuapiError):
        mu._remaining(100.0)


async def test_download_respects_remaining_deadline(monkeypatch):
    # Clock advances 0 during submit/poll, then jumps past the deadline before download.
    now = {"t": 0.0}
    monkeypatch.setattr(mu.time, "monotonic", lambda: now["t"])
    monkeypatch.setenv("MUAPI_TIMEOUT_SECONDS", "60")

    def handler(req):
        if req.url.host != "api.muapi.ai":
            raise AssertionError("download must not start after the deadline")
        resp = _api()(req)
        if "/predictions/" in req.url.path:
            now["t"] = 61.0
        return resp

    _install(monkeypatch, handler)
    with pytest.raises(mu.MuapiError):
        await mu.generate_image_muapi("p")


# --- size handling ---

def _png(size, mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, (10, 20, 30, 128) if mode == "RGBA" else (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


async def test_large_output_downscaled_keeping_aspect():
    out = Image.open(io.BytesIO(mu._to_png(_png((4000, 3000)))))
    assert out.size == (1536, 1152)


async def test_small_output_not_upscaled():
    out = Image.open(io.BytesIO(mu._to_png(_png((800, 600)))))
    assert out.size == (800, 600)


async def test_max_output_side_env(monkeypatch):
    monkeypatch.setenv("MUAPI_MAX_OUTPUT_SIDE", "512")
    out = Image.open(io.BytesIO(mu._to_png(_png((2000, 1000)))))
    assert out.size == (512, 256)


async def test_upload_is_jpeg_and_at_most_2048(monkeypatch):
    calls = _install(monkeypatch, _api())
    await mu.generate_image_muapi("p", input_images=[_png((4000, 3000))])
    up = next(c for c in calls if c.url.path.endswith("/upload_file"))
    assert b'filename="source.jpg"' in up.content and b"image/jpeg" in up.content
    start = up.content.index(b"\xff\xd8\xff")
    end = up.content.rindex(b"\r\n--")
    sent = Image.open(io.BytesIO(up.content[start:end]))
    assert sent.format == "JPEG" and max(sent.size) == 2048 and sent.mode == "RGB"


async def test_rgba_upload_flattened_onto_white():
    buf = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buf, format="PNG")  # fully transparent
    sent = Image.open(io.BytesIO(mu._prepare_upload(buf.getvalue())))
    assert sent.mode == "RGB" and sent.getpixel((5, 5))[0] > 240


async def test_undecodable_upload_raises():
    with pytest.raises(mu.MuapiError):
        mu._prepare_upload(b"nope")
