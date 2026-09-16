"""Ixtiyoriy: Claude API orqali vakansiyani profilingizga mosligini baholash.

.env da ANTHROPIC_API_KEY bo'lmasa, bu modul ishlatilmaydi va faqat
kalit so'z filtri ishlaydi.
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("ai")

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


class AIScorer:
    def __init__(self, api_key: str, model: str, profile: str):
        from anthropic import AsyncAnthropic  # faqat kerak bo'lganda import

        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.profile = profile

    async def evaluate(self, text: str) -> dict | None:
        try:
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=400,
                messages=[{"role": "user", "content": PROMPT.format(
                    profile=self.profile, text=text[:4000])}],
            )
            raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                return None
            data = json.loads(m.group(0))
            data["score"] = int(data.get("score") or 0)
            data["is_vacancy"] = bool(data.get("is_vacancy", True))
            return data
        except Exception as e:  # AI xatosi vakansiyani yo'qotmasligi kerak
            log.warning("AI baholashda xato: %s", e)
            return None
