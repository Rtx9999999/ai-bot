import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import aiosqlite


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
            PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY, username TEXT, credits INTEGER NOT NULL DEFAULT 0,
              premium_until TEXT, age_verified INTEGER NOT NULL DEFAULT 0,
              banned INTEGER NOT NULL DEFAULT 0, referrer_id INTEGER,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS generations(
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
              prompt TEXT, settings TEXT NOT NULL, runpod_job_id TEXT, status TEXT NOT NULL,
              source_url TEXT, result_url TEXT, error TEXT, created_at TEXT NOT NULL,
              FOREIGN KEY(user_id) REFERENCES users(id));
            CREATE TABLE IF NOT EXISTS transactions(
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, provider TEXT NOT NULL,
              external_id TEXT UNIQUE, amount REAL NOT NULL, currency TEXT NOT NULL, credits INTEGER NOT NULL,
              status TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
              FOREIGN KEY(user_id) REFERENCES users(id));
            CREATE TABLE IF NOT EXISTS referrals(
              id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL, referred_id INTEGER UNIQUE NOT NULL,
              bonus_credits INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_gen_user ON generations(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, created_at DESC);
            """)
            await db.commit()

    async def execute(self, sql: str, params=()) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(sql, params); await db.commit(); return cur.lastrowid or 0

    async def one(self, sql: str, params=()):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur:
                row = await cur.fetchone(); return dict(row) if row else None

    async def all(self, sql: str, params=()):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur: return [dict(r) for r in await cur.fetchall()]

    async def ensure_user(self, uid: int, username: str | None, free: int, referrer: int | None = None):
        existing = await self.one("SELECT * FROM users WHERE id=?", (uid,))
        if existing:
            await self.execute("UPDATE users SET username=?,updated_at=? WHERE id=?", (username, now(), uid)); return existing
        valid_ref = referrer if referrer and referrer != uid and await self.one("SELECT id FROM users WHERE id=?", (referrer,)) else None
        await self.execute("INSERT INTO users(id,username,credits,referrer_id,created_at,updated_at) VALUES(?,?,?,?,?,?)", (uid, username, free, valid_ref, now(), now()))
        if valid_ref: await self.execute("INSERT OR IGNORE INTO referrals(referrer_id,referred_id,created_at) VALUES(?,?,?)", (valid_ref, uid, now()))
        return await self.one("SELECT * FROM users WHERE id=?", (uid,))

    async def debit(self, uid: int, cost: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("UPDATE users SET credits=credits-?,updated_at=? WHERE id=? AND credits>=? AND banned=0", (cost, now(), uid, cost)); await db.commit(); return cur.rowcount == 1

    async def credit(self, uid: int, amount: int):
        await self.execute("UPDATE users SET credits=credits+?,updated_at=? WHERE id=?", (amount, now(), uid))

    async def complete_payment(self, txid: int, external: str, premium_days: int, referral_pct: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row; await db.execute("BEGIN IMMEDIATE")
            tx = await (await db.execute("SELECT * FROM transactions WHERE id=?", (txid,))).fetchone()
            if not tx or tx["status"] != "pending": await db.rollback(); return False
            user = await (await db.execute("SELECT * FROM users WHERE id=?", (tx["user_id"],))).fetchone()
            try:
                await db.execute("UPDATE transactions SET status='paid',external_id=? WHERE id=?", (external, txid))
                meta = json.loads(tx["metadata"]); credits = tx["credits"]
                if meta.get("premium"):
                    base = datetime.now(timezone.utc)
                    if user["premium_until"]:
                        old = datetime.fromisoformat(user["premium_until"])
                        if old > base: base = old
                    await db.execute("UPDATE users SET premium_until=?,credits=credits+?,updated_at=? WHERE id=?", ((base + timedelta(days=premium_days)).isoformat(), credits, now(), tx["user_id"]))
                else: await db.execute("UPDATE users SET credits=credits+?,updated_at=? WHERE id=?", (credits, now(), tx["user_id"]))
                if user["referrer_id"]:
                    bonus = max(1, credits * referral_pct // 100)
                    await db.execute("UPDATE users SET credits=credits+? WHERE id=?", (bonus, user["referrer_id"]))
                    await db.execute("UPDATE referrals SET bonus_credits=bonus_credits+? WHERE referred_id=?", (bonus, tx["user_id"]))
                await db.commit(); return True
            except Exception: await db.rollback(); raise

    async def new_generation(self, uid: int, kind: str, prompt: str, settings: dict) -> int:
        return await self.execute("INSERT INTO generations(user_id,kind,prompt,settings,status,created_at) VALUES(?,?,?,?,?,?)", (uid, kind, prompt, json.dumps(settings), "queued", now()))

