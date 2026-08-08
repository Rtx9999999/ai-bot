import re
import time
import unicodedata
from collections import defaultdict, deque

ILLEGAL = re.compile(
    r"\b(child|children|kid|minor|underage|preteen|teen(?:ager)?|schoolgirl|schoolboy|"
    r"loli|lolita|shota|young[- ]looking|rape|raping|forced sex|non[- ]?consensual|"
    r"unconscious|drugged|incest|bestiality|zoophilia|enfant|mineur|mineure|adolescent|"
    r"adolescente|viol|forcee?|sans consentement|inconscient|droguee?|inceste|zoophilie)\b", re.I
)
REAL_PHOTO_SEXUAL = re.compile(r"\b(nude|naked|nudity|topless|see[- ]?through|transparent|explicit|hardcore|genitals?|breasts?)\b", re.I)


def validate_prompt(prompt: str) -> tuple[bool, str]:
    text = prompt.strip()
    if len(text) < 3 or len(text) > 1500: return False, "Le prompt doit contenir entre 3 et 1500 caractères."
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().translate(str.maketrans({"0":"o","1":"i","3":"e","4":"a","5":"s","7":"t","@":"a","$":"s"}))
    if ILLEGAL.search(normalized): return False, "Demande refusée : contenu illégal ou non consenti détecté."
    return True, ""


def validate_real_photo_edit(prompt: str) -> tuple[bool, str]:
    ok, reason = validate_prompt(prompt)
    if not ok: return ok, reason
    if REAL_PHOTO_SEXUAL.search(prompt): return False, "Les modifications sexuelles ou nues d'une personne réelle sont refusées."
    return True, ""


class RateLimiter:
    def __init__(self, interval: int, burst: int = 8):
        self.interval, self.burst = interval, burst
        self.last: dict[int, float] = {}; self.events: dict[int, deque] = defaultdict(deque)

    def allowed(self, uid: int) -> bool:
        current = time.monotonic(); q = self.events[uid]
        while q and current - q[0] > 60: q.popleft()
        if current - self.last.get(uid, 0) < self.interval or len(q) >= self.burst: return False
        self.last[uid] = current; q.append(current); return True
