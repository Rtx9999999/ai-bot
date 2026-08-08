import json
import secrets
from decimal import Decimal
import aiohttp
from .config import Settings
from .db import Database, now


class CryptoPayments:
    def __init__(self, cfg: Settings, db: Database): self.cfg, self.db = cfg, db

    async def create(self, uid: int, provider: str, usd: float, credits: int, premium=False):
        if provider not in {"sol", "ton"}:
            raise ValueError("unsupported payment provider")
        unique = Decimal(secrets.randbelow(899) + 100) / Decimal(1_000_000)
        price = self.cfg.sol_usd_price if provider == "sol" else self.cfg.ton_usd_price
        amount = (Decimal(str(usd)) / Decimal(str(price)) + unique).quantize(Decimal("0.000001"))
        meta = json.dumps({"premium": premium, "usd": usd})
        txid = await self.db.execute("INSERT INTO transactions(user_id,provider,amount,currency,credits,status,metadata,created_at) VALUES(?,?,?,?,?,'pending',?,?)", (uid, provider, float(amount), provider.upper(), credits, meta, now()))
        return txid, amount

    async def verify(self, tx: dict) -> str | None:
        if tx["provider"] == "sol": return await self._sol(tx)
        if tx["provider"] == "ton": return await self._ton(tx)
        return None

    async def _sol(self, tx: dict) -> str | None:
        payload = {"jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress","params":[self.cfg.solana_wallet,{"limit":50}]}
        async with aiohttp.ClientSession() as s:
            async with s.post(self.cfg.solana_rpc_url, json=payload) as r: signatures = (await r.json()).get("result", [])
            for item in signatures:
                sig = item["signature"]
                p = {"jsonrpc":"2.0","id":1,"method":"getTransaction","params":[sig,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]}
                async with s.post(self.cfg.solana_rpc_url, json=p) as r: result = (await r.json()).get("result")
                if not result or result.get("meta",{}).get("err"): continue
                keys = result["transaction"]["message"]["accountKeys"]
                ids = [x.get("pubkey") if isinstance(x,dict) else x for x in keys]
                if self.cfg.solana_wallet in ids:
                    i=ids.index(self.cfg.solana_wallet); delta=(result["meta"]["postBalances"][i]-result["meta"]["preBalances"][i])/1e9
                    if abs(delta-float(tx["amount"])) < 0.0000005: return sig
        return None

    async def _ton(self, tx: dict) -> str | None:
        headers = {"X-API-Key": self.cfg.toncenter_api_key} if self.cfg.toncenter_api_key else {}
        params = {"address": self.cfg.ton_wallet, "limit": 100, "archival": "false"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.cfg.toncenter_api_url}/getTransactions", params=params, headers=headers) as response:
                response.raise_for_status()
                body = await response.json()
        expected_comment = f"BOT-{tx['id']}"
        for item in body.get("result", []):
            incoming = item.get("in_msg") or {}
            value = Decimal(str(incoming.get("value", "0"))) / Decimal(1_000_000_000)
            if abs(value - Decimal(str(tx["amount"]))) > Decimal("0.0000005"):
                continue
            if str(incoming.get("message", "")).strip() != expected_comment:
                continue
            return (item.get("transaction_id") or {}).get("hash")
        return None
