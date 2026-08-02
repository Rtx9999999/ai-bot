import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from .config import get_settings
from .db import Database
from .handlers import create_router
from .payments import CryptoPayments
from .runpod import RunPod
from .security import RateLimiter
from .storage import Storage


async def main():
    cfg=get_settings(); logging.basicConfig(level=cfg.log_level,format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db=Database(cfg.database_path); await db.init()
    bot=Bot(cfg.telegram_token,default=DefaultBotProperties(parse_mode=ParseMode.HTML)); dp=Dispatcher()
    dp.include_router(create_router(cfg,db,RunPod(cfg),Storage(cfg),CryptoPayments(cfg,db),RateLimiter(cfg.rate_limit_seconds)))
    await bot.delete_webhook(drop_pending_updates=False)
    try: await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally: await bot.session.close()


if __name__=="__main__": asyncio.run(main())

