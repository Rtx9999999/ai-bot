import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from cryptography.fernet import Fernet, InvalidToken

from .chat import ChatAssistant
from .config import get_settings
from .db import Database, now
from .handlers import create_router
from .payments import CryptoPayments
from .runpod import RunPod
from .security import RateLimiter
from .storage import Storage


async def main():
    cfg = get_settings()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db = Database(cfg.database_path)
    await db.init()
    cipher = Fernet(cfg.clone_encryption_key.encode()) if cfg.clone_encryption_key else None
    running: dict[int, tuple[Bot, asyncio.Task]] = {}
    primary_id: int | None = None

    def make_dispatcher(start_clone, stop_clone):
        dp = Dispatcher()
        dp.include_router(create_router(
            cfg, db, RunPod(cfg), Storage(cfg), CryptoPayments(cfg, db),
            RateLimiter(cfg.rate_limit_seconds), ChatAssistant(cfg, db), start_clone, stop_clone,
        ))
        return dp

    async def launch(token: str) -> tuple[Bot, str]:
        bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            me = await bot.get_me()
        except Exception as exc:
            await bot.session.close()
            raise ValueError("Token Telegram invalide ou révoqué.") from exc
        if me.id in running:
            await bot.session.close()
            return running[me.id][0], f"@{me.username} est déjà actif."
        await bot.delete_webhook(drop_pending_updates=False)
        dp = make_dispatcher(start_clone, stop_clone)

        async def poll():
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            finally:
                await bot.session.close()

        task = asyncio.create_task(poll(), name=f"clone-{me.id}")
        running[me.id] = (bot, task)
        return bot, f"@{me.username} est connecté et actif."

    async def start_clone(owner_id: int, token: str) -> str:
        if cipher is None:
            raise ValueError("Le chiffrement des clones n'est pas configuré.")
        if token in {cfg.telegram_token, cfg.backup_telegram_token}:
            raise ValueError("Ce token appartient déjà à un bot du service.")
        count = await db.one("SELECT COUNT(*) total FROM clone_bots WHERE owner_id=? AND active=1", (owner_id,))
        if count["total"] >= cfg.max_clones_per_user:
            raise ValueError("Vous avez atteint la limite de clones actifs.")
        bot, result = await launch(token)
        me = await bot.get_me()
        if me.id == primary_id:
            raise ValueError("Ce token appartient déjà au bot principal.")
        encrypted = cipher.encrypt(token.encode()).decode()
        await db.execute(
            "INSERT INTO clone_bots(owner_id,bot_id,username,token_encrypted,active,created_at) VALUES(?,?,?,?,1,?) "
            "ON CONFLICT(bot_id) DO UPDATE SET owner_id=excluded.owner_id,username=excluded.username,token_encrypted=excluded.token_encrypted,active=1",
            (owner_id, me.id, me.username or str(me.id), encrypted, now()),
        )
        return result

    async def stop_clone(owner_id: int, bot_id: int) -> bool:
        row = await db.one("SELECT id FROM clone_bots WHERE owner_id=? AND bot_id=? AND active=1", (owner_id, bot_id))
        if not row:
            return False
        await db.execute("UPDATE clone_bots SET active=0,token_encrypted='' WHERE id=?", (row["id"],))
        active = running.pop(bot_id, None)
        if active:
            active[1].cancel()
        return True

    primary, _ = await launch(cfg.telegram_token)
    primary_id = (await primary.get_me()).id

    async def promo_loop():
        chat = cfg.promo_chat.strip() or (f"@{cfg.required_channel_username}" if cfg.required_channel_username else "")
        if not chat or cfg.promo_interval_minutes <= 0:
            return
        while True:
            try:
                state = await db.one("SELECT value FROM bot_state WHERE key='last_promo'")
                last = datetime.fromisoformat(state["value"]) if state else None
                elapsed = (datetime.now(timezone.utc) - last).total_seconds() if last else cfg.promo_interval_minutes * 60
                if elapsed >= cfg.promo_interval_minutes * 60:
                    me = await primary.get_me()
                    text = (
                        "🚀 <b>Transforme tes idées en images et vidéos avec l'IA !</b>\n\n"
                        "🔥 Images uniques · ⭐ Haute qualité\n"
                        "🎬 Vidéos IA · 👗 Changement de tenue\n"
                        "🔄 Face swap consenti · 🤖 Clone du bot\n\n"
                        "🎁 <b>Des crédits gratuits t'attendent pour essayer.</b>\n\n"
                        "🔞 Service réservé aux personnes majeures."
                    )
                    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Lancer le bot", url=f"https://t.me/{me.username}?start=community")]])
                    await primary.send_message(chat, text, reply_markup=markup)
                    stamp = datetime.now(timezone.utc).isoformat()
                    await db.execute("INSERT INTO bot_state(key,value,updated_at) VALUES('last_promo',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (stamp, stamp))
            except Exception:
                logging.exception("Unable to publish scheduled promo")
            await asyncio.sleep(60)

    promo_task = asyncio.create_task(promo_loop(), name="hourly-promo")
    if cfg.backup_telegram_token and cfg.backup_telegram_token != cfg.telegram_token:
        await launch(cfg.backup_telegram_token)

    if cipher:
        for clone in await db.all("SELECT * FROM clone_bots WHERE active=1"):
            try:
                token = cipher.decrypt(clone["token_encrypted"].encode()).decode()
                await launch(token)
            except Exception:
                logging.exception("Unable to restore clone %s", clone["bot_id"])

    try:
        await asyncio.gather(*(task for _, task in running.values()))
    finally:
        promo_task.cancel()
        for _, task in running.values():
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
