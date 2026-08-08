import asyncio
import base64
import binascii

import aiohttp

from .config import Settings


class RunPodError(RuntimeError):
    pass


class RunPod:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._max_submit_attempts = 3
        self._max_status_failures = 3

    @staticmethod
    async def _json(response: aiohttp.ClientResponse) -> dict:
        try:
            value = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            value = {"error": (await response.text())[:1000]}
        return value if isinstance(value, dict) else {"result": value}

    async def submit(self, endpoint: str, payload: dict) -> tuple[str, dict]:
        headers = {
            "Authorization": f"Bearer {self.cfg.runpod_api_key}",
            "Content-Type": "application/json",
        }
        base = f"https://api.runpod.ai/v2/{endpoint}"
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            job = None
            submit_error: Exception | None = None
            for attempt in range(1, self._max_submit_attempts + 1):
                try:
                    async with session.post(f"{base}/run", headers=headers, json={"input": payload}) as response:
                        body = await self._json(response)
                        if response.status >= 300:
                            raise RunPodError(f"RunPod submit HTTP {response.status}: {body}")
                        job = body.get("id")
                        if not job:
                            raise RunPodError(f"RunPod n'a pas retourné d'identifiant de tâche: {body}")
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError, RunPodError) as exc:
                    submit_error = exc
                    if attempt >= self._max_submit_attempts:
                        raise RunPodError(f"RunPod submit failed after {attempt} attempts: {exc}") from exc
                    await asyncio.sleep(1.5 * attempt)

            if job is None:
                raise RunPodError(f"RunPod submit failed: {submit_error}")

            deadline = asyncio.get_running_loop().time() + self.cfg.runpod_timeout_seconds
            delay = 1.5
            consecutive_errors = 0
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(delay)
                delay = min(delay * 1.25, 8)
                try:
                    async with session.get(f"{base}/status/{job}", headers=headers) as response:
                        status = await self._json(response)
                        if response.status >= 500:
                            raise RunPodError(f"RunPod status HTTP {response.status}: {status}")
                        if response.status >= 300:
                            raise RunPodError(f"RunPod status HTTP {response.status}: {status}")
                    consecutive_errors = 0
                except (aiohttp.ClientError, asyncio.TimeoutError, RunPodError):
                    consecutive_errors += 1
                    if consecutive_errors >= self._max_status_failures:
                        raise RunPodError("RunPod status unavailable after repeated failures")
                    continue
                if status.get("status") == "COMPLETED":
                    return job, status.get("output") or {}
                if status.get("status") in {"FAILED", "CANCELLED", "TIMED_OUT"}:
                    raise RunPodError(status.get("error") or str(status))

            try:
                async with session.post(f"{base}/cancel/{job}", headers=headers):
                    pass
            except aiohttp.ClientError:
                pass
            raise RunPodError("Délai RunPod dépassé")

    @staticmethod
    async def output_bytes(output: dict) -> tuple[bytes, str]:
        value = output.get("image") or output.get("video") or output.get("result") or (output.get("images") or [None])[0]
        if not value:
            raise RunPodError("Le worker n'a retourné aucun média")
        if isinstance(value, dict):
            value = value.get("url") or value.get("base64")
        if str(value).startswith("http"):
            timeout = aiohttp.ClientTimeout(total=120, connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(value) as response:
                    response.raise_for_status()
                    return await response.read(), response.headers.get("Content-Type", "application/octet-stream")
        raw = str(value).split(",", 1)[-1]
        try:
            decoded = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RunPodError("Le worker a retourné un média base64 invalide") from exc
        return decoded, str(output.get("content_type") or "application/octet-stream")
