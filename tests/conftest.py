"""Testlar uchun umumiy izolyatsiya.

main.py import qilinganda `load_dotenv()` ishlaydi va yonidagi .env faylini
os.environ ga yuklaydi. Serverda (yoki .env bor istalgan mashinada) bu testlarga
haqiqiy BOT_TOKEN va AI kalitini berib yuboradi — natijada testlar tarmoqqa
chiqib, tashqi xizmatga so'rov yuboradi. Quyidagi fixture har bir testdan oldin
muhitni xavfsiz qiymatlarga qaytaradi.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Testlar uchun xavfsiz qiymatlar: tashqi xizmat yo'q, haqiqiy kanal yo'q.
XAVFSIZ = {
    "API_ID": "1",
    "API_HASH": "test",
    "BOT_TOKEN": "",          # bot ulanmaydi
    "AI_API_KEY": "",         # AI chaqirilmaydi
    "AI_ENDPOINT": "",
    "AI_MODEL": "",
    "CHANNELS": "",
    "EXCLUDE_CHANNELS": "",
    "OWNER_ID": "0",
    "ALLOWED_USERS": "",
    "INCLUDE_EXTRA": "",
    "EXCLUDE_EXTRA": "",
    "EXCLUDE_LEVELS": "",
    "REQUIRE_VACANCY_MARKER": "true",
    "BACKFILL_DAYS": "15",
    "NOTIFY_MAX": "5",
}


@pytest.fixture(autouse=True)
def toza_muhit(monkeypatch):
    for key, value in XAVFSIZ.items():
        monkeypatch.setenv(key, value)
    # Ish davomida .env qayta o'qilmasin (refresh_channels uni chaqiradi).
    import main
    monkeypatch.setattr(main, "load_dotenv", lambda *a, **k: None)
