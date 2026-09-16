"""Ixtiyoriy: vakansiyani profilingizga mosligini AI bilan baholash.

OpenAI-mos chat/completions endpoint'i bilan ishlaydi (Azure AI Foundry,
OpenAI, OpenRouter va h.k.). .env da AI_API_KEY bo'lmasa, bu modul umuman
ishlatilmaydi va faqat kalit so'z filtri qoladi.

    AI_ENDPOINT=https://<resurs>.services.ai.azure.com/openai/v1
    AI_API_KEY=...
    AI_MODEL=DeepSeek-V4-Flash-0731

Qo'shimcha paket talab qilinmaydi — sof urllib.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request

log = logging.getLogger("ai")

TIMEOUT = 60
RETRIES = 2

PROMPT = """Sen IT vakansiyalarni saralovchi yordamchisan.

Nomzod profili:
{profile}

Quyidagi Telegram postini o'qi va FAQAT JSON qaytar (boshqa matn yo'q):
{{
  "is_vacancy": true/false,        // bu ish beruvchining vakansiyasimi (rezyume/reklama emas)
  "score": 0-10,                    // nomzodga qanchalik mos
  "title": "lavozim nomi",
  "company": "kompaniya yoki null",
  "salary": "maosh yoki null",
  "location": "shahar/format yoki null",
  "level": "Junior/Middle/Senior/Lead yoki null",
  "reason": "o'zbekcha, 1 qisqa gap: nega mos/mos emas"
}}

Post:
\"\"\"
{text}
\"\"\"
"""

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_reply(raw: str) -> dict | None:
    """Model javobidan JSON ni ajratadi. Tushunarsiz javobda None.

    Modellar JSON ni ```json blokiga o'rashi yoki oldidan izoh yozishi mumkin,
    DeepSeek esa <think>...</think> qo'shadi — hammasi hisobga olingan.
    """
    if not raw:
        return None
    text = _THINK_RE.sub("", raw)
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        score = int(float(data.get("score") or 0))
    except (TypeError, ValueError):
        score = 0
    data["score"] = max(0, min(10, score))
    data["is_vacancy"] = bool(data.get("is_vacancy", True))
    return data


class AIScorer:
    def __init__(self, endpoint: str, api_key: str, model: str, profile: str):
        if not endpoint or not model:
            raise ValueError("AI uchun .env da AI_ENDPOINT va AI_MODEL to'ldirilishi kerak")
        self.url = endpoint.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.profile = profile

    def _call(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0,
        }).encode()
        req = urllib.request.Request(self.url, data=body, headers={
            "Content-Type": "application/json",
            "api-key": self.api_key,                       # Azure AI Foundry
            "Authorization": f"Bearer {self.api_key}",      # OpenAI-mos boshqa xizmatlar
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return data["choices"][0]["message"]["content"] or ""

    async def evaluate(self, text: str) -> dict | None:
        """Postni baholaydi. Xato bo'lsa None — vakansiya kalit so'z bo'yicha saqlanaveradi."""
        prompt = PROMPT.format(profile=self.profile, text=text[:4000])
        for urinish in range(RETRIES):
            try:
                return parse_reply(await asyncio.to_thread(self._call, prompt))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:200]
                if e.code == 429 and urinish + 1 < RETRIES:
                    log.warning("AI band (429), 20s kutamiz")
                    await asyncio.sleep(20)
                    continue
                log.warning("AI xatosi HTTP %s: %s", e.code, detail)
                return None
            except Exception as e:  # AI xatosi vakansiyani yo'qotmasligi kerak
                if urinish + 1 < RETRIES:
                    await asyncio.sleep(5)
                    continue
                log.warning("AI baholashda xato: %s", e)
                return None
        return None
