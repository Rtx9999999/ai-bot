import asyncio
from collections import defaultdict, deque

import aiohttp

from .config import Settings


SYSTEM_PROMPT = """Tu es l'assistante conversationnelle d'un bot Telegram de création d'images et de vidéos.
Réponds en français naturel, chaleureux et concis. Aide aussi l'utilisateur à rédiger de bons prompts.
Ne prétends jamais avoir lancé une génération si l'utilisateur n'a pas utilisé les boutons du bot.
Les contenus impliquant des mineurs, l'absence de consentement ou une usurpation nuisible sont interdits.
N'invente ni prix, ni solde, ni état de paiement."""


class ChatAssistant:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._history: dict[int, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=10))
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    @property
    def ready(self) -> bool:
        return bool(self.cfg.openai_api_key.strip())

    async def reply(self, user_id: int, text: str) -> str:
        async with self._locks[user_id]:
            history = self._history[user_id]
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": text[:4000]}]
            headers = {"Authorization": f"Bearer {self.cfg.openai_api_key}", "Content-Type": "application/json"}
            payload = {"model": self.cfg.openai_chat_model, "messages": messages, "temperature": 0.7, "max_tokens": 700}
            timeout = aiohttp.ClientTimeout(total=45)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload) as response:
                    if response.status >= 400:
                        detail = (await response.text())[:300]
                        raise RuntimeError(f"OpenAI {response.status}: {detail}")
                    data = await response.json()
            answer = data["choices"][0]["message"]["content"].strip()
            history.append({"role": "user", "content": text[:4000]})
            history.append({"role": "assistant", "content": answer[:4000]})
            return answer
