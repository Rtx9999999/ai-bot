import asyncio
import base64
import aiohttp
from .config import Settings


class RunPodError(RuntimeError): pass


class RunPod:
    def __init__(self, cfg: Settings): self.cfg = cfg

    async def submit(self, endpoint: str, payload: dict) -> tuple[str, dict]:
        headers = {"Authorization": f"Bearer {self.cfg.runpod_api_key}", "Content-Type": "application/json"}
        base = f"https://api.runpod.ai/v2/{endpoint}"
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{base}/run", headers=headers, json={"input": payload}) as r:
                body = await r.json();
                if r.status >= 300: raise RunPodError(str(body))
                job = body["id"]
            deadline = asyncio.get_running_loop().time() + self.cfg.runpod_timeout_seconds
            delay = 1.5
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(delay); delay = min(delay * 1.25, 8)
                async with session.get(f"{base}/status/{job}", headers=headers) as r:
                    status = await r.json()
                if status.get("status") == "COMPLETED": return job, status.get("output") or {}
                if status.get("status") in {"FAILED", "CANCELLED", "TIMED_OUT"}: raise RunPodError(status.get("error") or str(status))
            async with session.post(f"{base}/cancel/{job}", headers=headers): pass
            raise RunPodError("Délai RunPod dépassé")

    @staticmethod
    async def output_bytes(output: dict) -> tuple[bytes, str]:
        value = output.get("image") or output.get("video") or output.get("result") or (output.get("images") or [None])[0]
        if not value: raise RunPodError("Le worker n'a retourné aucun média")
        if isinstance(value, dict): value = value.get("url") or value.get("base64")
        if str(value).startswith("http"):
            async with aiohttp.ClientSession() as s:
                async with s.get(value) as r: r.raise_for_status(); return await r.read(), r.headers.get("Content-Type", "application/octet-stream")
        raw = str(value).split(",", 1)[-1]
        return base64.b64decode(raw), str(output.get("content_type") or "application/octet-stream")
