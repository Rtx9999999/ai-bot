import asyncio
import tempfile
from pathlib import Path
from app.db import Database
from app.security import validate_prompt
from app.config import Settings


def test_prompt_filter():
    assert validate_prompt("portrait sensuel de deux adultes consentants")[0]
    assert not validate_prompt("underage schoolgirl")[0]
    assert not validate_prompt("forced sex scene")[0]


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
