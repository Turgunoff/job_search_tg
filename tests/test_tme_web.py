"""tme_web: t.me/s/<kanal> sahifasini tahlil qilish testlari.

Tarmoqqa chiqmaydi — tests/fixtures/dartuz_jobs.html haqiqiy namunasi ustida ishlaydi.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest

import tme_web

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "dartuz_jobs.html"
HTML = FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def page():
    return tme_web.parse_page(HTML, "dartuz_jobs")


def test_kanal_nomi(page):
    assert page.title == "Jobs Dart | Flutter 🇺🇿"


def test_hamma_postlar_topiladi(page):
    assert len(page.posts) == 20
    assert [p.id for p in page.posts] == [
        236, 237, 238, 239, 240, 241, 242, 243, 244, 245,
        246, 248, 249, 250, 251, 252, 253, 254, 255, 257,
    ]


def test_postlar_eskisidan_yangisiga(page):
    ids = [p.id for p in page.posts]
    assert ids == sorted(ids)


def test_sanalar_utc_va_aware(page):
    for p in page.posts:
        assert p.date.tzinfo is not None, f"{p.id} sanasi naive"
        assert p.date.utcoffset() == timezone.utc.utcoffset(None)
    assert page.posts[0].date == datetime(2025, 5, 13, 14, 54, 14, tzinfo=timezone.utc)
    assert page.posts[-1].date == datetime(2026, 9, 15, 6, 55, 21, tzinfo=timezone.utc)


def test_matn_toliq_kesilmaydi(page):
    """Eng uzun post oxirigacha olinishi kerak — filtr to'liq matnga tayanadi."""
    longest = max(page.posts, key=lambda p: len(p.message))
    assert longest.id == 252
    # Boshi va oxiri — kesilmaganning haqiqiy isboti.
    assert longest.message.startswith("Вакансия: Flutter Developer (Middle)")
    assert longest.message.endswith("Больше вакансии на канале: @dartuz_jobs")
    # Ortiqcha tozalab yubormaganini ham tekshiramiz (xom HTML ~3.7k belgi).
    assert len(longest.message) > 3200
    assert "Заработная вилка начинается от 1500-2000$" in longest.message


def test_html_belgilari_tozalanadi(page):
    birlashgan = "\n".join(p.message for p in page.posts)
    for qoldiq in ("<br", "<a ", "</div>", "&amp;", "&#39;", "&quot;"):
        assert qoldiq not in birlashgan, f"tozalanmagan: {qoldiq}"


def test_qatorlar_saqlanadi(page):
    """<br> yangi qatorga aylanadi — filters.py qatorma-qator qidiradi."""
    assert any("\n" in p.message for p in page.posts)


def test_matnsiz_post_bosh_satr(page):
    """Faqat rasm/fayl bo'lgan post — matn bo'sh, lekin post tashlab yuborilmaydi."""
    media = next(p for p in page.posts if p.id == 246)
    assert media.message == ""


def test_varaqlash_kursori(page):
    assert page.next_before == 236


def test_oxirgi_sahifada_kursor_yoq():
    page = tme_web.parse_page("<html><body></body></html>", "bosh_kanal")
    assert page.posts == []
    assert page.next_before is None


def test_yopiq_kanal_post_bermaydi():
    """Preview o'chirilgan kanal: sahifa keladi, lekin post yo'q."""
    page = tme_web.parse_page(
        '<html><meta property="og:title" content="Yopiq"></html>', "yopiq")
    assert page.posts == []


class TestChatId:
    def test_barqaror(self):
        assert tme_web.chat_id_for("dartuz_jobs") == tme_web.chat_id_for("dartuz_jobs")

    def test_registrga_bogliq_emas(self):
        assert tme_web.chat_id_for("DartUz_Jobs") == tme_web.chat_id_for("dartuz_jobs")

    def test_manfiy(self):
        """storage.py kanal ID sini Telegram uslubida manfiy deb kutadi."""
        assert tme_web.chat_id_for("dartuz_jobs") < 0

    def test_kanallar_toqnashmaydi(self):
        nomlar = ["dartuz_jobs", "progjob", "unilance", "flutterroles", "ayti_jobs"]
        assert len({tme_web.chat_id_for(n) for n in nomlar}) == len(nomlar)


class TestNormalize:
    @pytest.mark.parametrize("kiritma,kutilgan", [
        ("https://t.me/dartuz_jobs", "dartuz_jobs"),
        ("t.me/dartuz_jobs", "dartuz_jobs"),
        ("@dartuz_jobs", "dartuz_jobs"),
        ("dartuz_jobs", "dartuz_jobs"),
        ("https://t.me/s/dartuz_jobs", "dartuz_jobs"),
        ("https://t.me/dartuz_jobs/", "dartuz_jobs"),
    ])
    def test_turli_formatlar(self, kiritma, kutilgan):
        assert tme_web.normalize(kiritma) == kutilgan


def test_post_havolasi():
    assert tme_web.post_link("dartuz_jobs", 252) == "https://t.me/dartuz_jobs/252"
