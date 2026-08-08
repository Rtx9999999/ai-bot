import asyncio
import tempfile
from pathlib import Path
from app.db import Database
from app.security import validate_prompt, validate_real_photo_edit
from app.config import Settings
from app.storage import Storage
from app.runpod import RunPod, RunPodError


def test_prompt_filter():
    assert validate_prompt("portrait sensuel de deux adultes consentants")[0]
    assert not validate_prompt("underage schoolgirl")[0]
    assert not validate_prompt("forced sex scene")[0]
    assert not validate_real_photo_edit("make the real person topless")[0]
    assert validate_real_photo_edit("replace the shirt with a red evening dress")[0]


def test_atomic_credit_flow():
    async def run():
        with tempfile.TemporaryDirectory() as d:
            db=Database(str(Path(d)/"test.db")); await db.init(); await db.ensure_user(1,"alice",2)
            assert await db.debit(1,1); assert not await db.debit(1,2)
            await db.credit(1,3); u=await db.one("SELECT * FROM users WHERE id=1"); assert u["credits"]==4
    asyncio.run(run())


def test_optional_generation_backends():
    cfg = Settings(telegram_token="123456:test")
    assert not cfg.media_backend_ready
    assert not cfg.generation_backend_ready("gen")
    assert not cfg.faceswap_backend_ready


def test_common_telegram_token_aliases(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123456:alias")
    assert Settings().telegram_token == "123456:alias"


def test_example_placeholders_do_not_initialize_s3():
    cfg = Settings(
        telegram_token="999999:real",
        s3_endpoint_url="https://ACCOUNT_ID.r2.cloudflarestorage.com",
        s3_access_key="replace_me",
        s3_secret_key="replace_me",
        s3_bucket="adult-art-bot",
        s3_public_url="https://media.example.com",
    )
    assert not cfg.media_backend_ready
    assert Storage(cfg).client is None


def test_private_s3_does_not_require_public_url():
    cfg = Settings(
        telegram_token="999999:real",
        s3_endpoint_url="https://account.r2.cloudflarestorage.com",
        s3_access_key="access-key",
        s3_secret_key="secret-key",
        s3_bucket="ai-bot-media",
        s3_region="auto",
        s3_public_url="https://media.example.com",
    )
    assert cfg.media_backend_ready


def test_main_menu_includes_safe_faceswap():
    from app.keyboards import main
    labels = [button.text for row in main().inline_keyboard for button in row]
    callbacks = [button.callback_data for row in main().inline_keyboard for button in row]
    assert "ðŸ”„ Face swap consenti" in labels
    assert "ðŸ‘— Changer tenue (photo)" in labels
    assert "swap" in callbacks


def test_runpod_decodes_base64_output():
    async def run():
        raw, content_type = await RunPod.output_bytes({"image": "aGVsbG8=", "content_type": "image/png"})
        assert raw == b"hello"
        assert content_type == "image/png"

    asyncio.run(run())


def test_runpod_rejects_invalid_base64_output():
    async def run():
        try:
            await RunPod.output_bytes({"result": "not-valid-base64"})
        except RunPodError:
            return
        raise AssertionError("invalid base64 should raise RunPodError")

    asyncio.run(run())
