import json
import secrets
from decimal import Decimal
import aiohttp
from .config import Settings
from .db import Database, now


class CryptoPayments:
    def __init__(self, cfg: Settings, db: Database): self.cfg, self.db = cfg, db

    async def create(self, uid: int, provider: str, usd: float, credits: int, premium=False):
        unique = Decimal(secrets.randbelow(899) + 100) / Decimal(1_000_000)
        amount = (Decimal(str(usd)) / Decimal(str(self.cfg.sol_usd_price)) + unique).quantize(Decimal("0.000001")) if provider == "sol" else (Decimal(str(usd)) + unique).quantize(Decimal("0.000001"))
        meta = json.dumps({"premium": premium, "usd": usd})
        txid = await self.db.execute("INSERT INTO transactions(user_id,provider,amount,currency,credits,status,metadata,created_at) VALUES(?,?,?,?,?,'pending',?,?)", (uid, provider, float(amount), "SOL" if provider == "sol" else "USDT", credits, meta, now()))
        return txid, amount

    async def verify(self, tx: dict) -> str | None:
        return await (self._sol(tx) if tx["provider"] == "sol" else self._tron(tx))

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

    async def _tron(self, tx: dict) -> str | None:
        url=f"{self.cfg.trongrid_api_url}/v1/accounts/{self.cfg.tron_wallet}/transactions/trc20?only_confirmed=true&contract_address={self.cfg.usdt_trc20_contract}&limit=100"
        headers={"TRON-PRO-API-KEY":self.cfg.trongrid_api_key} if self.cfg.trongrid_api_key else {}
        async with aiohttp.ClientSession() as s:
            async with s.get(url,headers=headers) as r: data=(await r.json()).get("data",[])
        for item in data:
            if item.get("to") == self.cfg.tron_wallet and abs(int(item["value"])/1e6-float(tx["amount"])) < 0.0000005: return item["transaction_id"]
        return None

