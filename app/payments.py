import json
import secrets
from decimal import Decimal
import aiohttp
from .config import Settings
from .db import Database, now


class CryptoPayments:
    def __init__(self, cfg: Settings, db: Database): self.cfg, self.db = cfg, db

    async def create(self, uid: int, provider: str, usd: float, credits: int, premium=False):
        if provider not in {"sol", "eth"}:
            raise ValueError("unsupported payment provider")
        unique = Decimal(secrets.randbelow(899) + 100) / Decimal(1_000_000)
        price = await self._usd_price(provider)
        amount = (Decimal(str(usd)) / Decimal(str(price)) + unique).quantize(Decimal("0.000001"))
        meta = json.dumps({"premium": premium, "usd": usd})
        txid = await self.db.execute("INSERT INTO transactions(user_id,provider,amount,currency,credits,status,metadata,created_at) VALUES(?,?,?,?,?,'pending',?,?)", (uid, provider, float(amount), provider.upper(), credits, meta, now()))
        return txid, amount

    async def _usd_price(self, provider: str) -> float:
        fallback = self.cfg.sol_usd_price if provider == "sol" else self.cfg.eth_usd_price
        asset = "solana" if provider == "sol" else "ethereum"
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": asset, "vs_currencies": "usd"}) as response:
                    response.raise_for_status(); value = float((await response.json())[asset]["usd"])
                    return value if value > 0 else fallback
        except Exception:
            return fallback

    async def verify(self, tx: dict) -> str | None:
        if tx["provider"] == "sol": return await self._sol(tx)
        if tx["provider"] == "eth": return await self._eth(tx)
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

    async def _eth(self, tx: dict) -> str | None:
        if not self.cfg.eth_wallet:
            return None
        payload = {"jsonrpc":"2.0","id":1,"method":"eth_getBalance","params":[self.cfg.eth_wallet, "latest"]}
        async with aiohttp.ClientSession() as session:
            async with session.post(self.cfg.eth_rpc_url, json=payload) as response:
                response.raise_for_status()
                body = await response.json()
        balance_hex = body.get("result")
        if not balance_hex:
            return None
        balance_eth = Decimal(int(balance_hex, 16)) / Decimal(10**18)
        if balance_eth >= Decimal(str(tx["amount"])):
            return "balance-confirmed"
        return None
