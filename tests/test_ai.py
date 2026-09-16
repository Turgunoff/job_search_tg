"""ai.py: model javobini tahlil qilish testlari (tarmoqqa chiqmaydi)."""
from __future__ import annotations

import pytest

from ai import parse_reply


def test_oddiy_json():
    d = parse_reply('{"is_vacancy": true, "score": 8, "title": "Flutter dev"}')
    assert d["score"] == 8
    assert d["is_vacancy"] is True
    assert d["title"] == "Flutter dev"


def test_markdown_bloki_ichida():
    """Modellar JSON ni ```json ... ``` ichida qaytarishi odatiy hol."""
    d = parse_reply('Mana natija:\n```json\n{"score": 7, "is_vacancy": true}\n```\nTayyor.')
    assert d["score"] == 7


def test_reasoning_bloki_tashlanadi():
    """DeepSeek <think>...</think> qo'shishi mumkin — u JSON emas."""
    raw = '<think>Hmm, bu Flutter vakansiyasi, {"score": 1} deb o\'ylayapman...</think>\n{"score": 9, "is_vacancy": true}'
    d = parse_reply(raw)
    assert d["score"] == 9


def test_score_matn_bolsa_songa_aylanadi():
    assert parse_reply('{"score": "8", "is_vacancy": true}')["score"] == 8


def test_score_yoq_bolsa_nol():
    assert parse_reply('{"is_vacancy": true}')["score"] == 0


def test_is_vacancy_default_true():
    """Model maydonni tushirib qoldirsa, vakansiyani yo'qotmaymiz."""
    assert parse_reply('{"score": 6}')["is_vacancy"] is True


def test_buzuq_javob_none():
    assert parse_reply("Kechirasiz, javob bera olmayman.") is None
    assert parse_reply("") is None
    assert parse_reply('{"score": ') is None


def test_ichma_ich_obyekt():
    d = parse_reply('{"score": 5, "is_vacancy": true, "meta": {"a": 1}}')
    assert d["score"] == 5
    assert d["meta"] == {"a": 1}


@pytest.mark.parametrize("qiymat,kutilgan", [
    ("12", 10),      # chegaradan yuqori
    ("-3", 0),       # manfiy
    ("7", 7),
])
def test_score_chegarada(qiymat, kutilgan):
    assert parse_reply(f'{{"score": {qiymat}}}')["score"] == kutilgan
