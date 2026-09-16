"""Soatlik skan, 15 kunlik backfill va kanal qo'shilishi (soxta tme_web manbai bilan)."""
import asyncio, os, sys, tempfile
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from telethon.extensions import html as th
import main
import tme_web
from test_filters import FLUTTER_UZ, BACKEND_RU, IOS_EN, RESUME

NOW = datetime.now(timezone.utc)


def m(i, text, days_ago):
    return tme_web.WebPost(id=i, message=text, date=NOW - timedelta(days=days_ago))


class FakeTme:
    """tme_web ning tarmoqsiz o'rnini bosuvchisi — shartnomasi bir xil."""

    def __init__(self):
        self.posts: dict[str, list] = {}
        self.titles: dict[str, str] = {}
        self.calls: list[tuple] = []

    def add_channel(self, username, title, posts):
        self.titles[username] = title
        self.posts[username] = list(posts)

    async def probe(self, channel):
        name = tme_web.normalize(channel)
        if name not in self.posts:
            return False, f"{name}: HTTP 404", 0
        return True, self.titles[name], len(self.posts[name])

    async def iter_posts(self, channel, *, min_id=None, since=None, max_pages=60):
        name = tme_web.normalize(channel)
        self.calls.append((name, min_id, since is not None))
        posts = sorted(self.posts[name], key=lambda p: p.id)
        if min_id is not None:
            posts = [p for p in posts if p.id > min_id]
        if since is not None:
            posts = [p for p in posts if p.date >= since]
        return self.titles[name], posts


@pytest.fixture
def app(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("API_ID", "1")
    monkeypatch.setenv("API_HASH", "x")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("CHANNELS", "")
    monkeypatch.setenv("EXCLUDE_CHANNELS", "")
    monkeypatch.setenv("BACKFILL_DAYS", "15")
    monkeypatch.setenv("DB_PATH", os.path.join(tmp, "t.db"))
    monkeypatch.setenv("CSV_PATH", os.path.join(tmp, "t.csv"))
    monkeypatch.setattr(main, "load_dotenv", lambda *a, **k: None)  # .env ni o'qimasin

    fake = FakeTme()
    monkeypatch.setattr(main.tme_web, "probe", fake.probe)
    monkeypatch.setattr(main.tme_web, "iter_posts", fake.iter_posts)

    a = main.App()
    a.tme = fake
    a.sent = []           # egaga ketgan xabarlar (hisobotlar)
    a.broadcasted = []    # obunachilarga tarqatilgan vakansiyalar

    async def fake_send(text, link=None, force=False):
        th.parse(text)                       # HTML yaroqliligini tekshiradi
        a.sent.append((text, link, force))

    async def fake_broadcast(text, link=None):
        th.parse(text)
        a.broadcasted.append((text, link))

    a.send = fake_send
    a.broadcast = fake_broadcast
    a.lock = asyncio.Lock()
    return a


def pid_of(username):
    return tme_web.chat_id_for(username)


def test_backfill_hourly_and_new_channel(app, monkeypatch):
    itvak, kunuz = pid_of("itvak"), pid_of("kunuz")
    app.tme.add_channel("itvak", "IT Vakansiyalar", [
        m(1, FLUTTER_UZ, 20),          # 15 kundan eski -> olinmaydi
        m(2, BACKEND_RU, 10),
        m(3, RESUME, 5),
        m(4, IOS_EN, 1),
    ])
    app.tme.add_channel("kunuz", "Kun.uz", [m(1, BACKEND_RU, 1)])
    monkeypatch.setenv("CHANNELS", "@itvak")   # kunuz ro'yxatda yo'q

    async def go():
        app.peers = await app.compute_peers()
        assert app.peers == [itvak]
        assert kunuz not in app.peers

        # 1) birinchi ishga tushish: 15 kunlik skan, alohida xabar yo'q, faqat hisobot
        n = await app.scan_all()
        assert n == 2
        assert len(app.sent) == 1 and "Kanal reytingi" in app.sent[0][0]
        assert app.store.query("all")[1] == 2
        assert app.store.channel_last_id(itvak) == 4
        assert app.tme.calls[0][2] is True         # birinchi marta -> since bilan

        # 2) soatlik skan: yangi post yo'q -> hech narsa
        app.sent.clear()
        assert await app.scan_all() == 0
        assert app.sent == [] and app.broadcasted == []
        assert app.tme.calls[-1] == ("itvak", 4, False)   # faqat min_id dan keyingilari

        # 3) yangi post + boshqa kanalning dublikati
        app.tme.posts["itvak"] += [m(5, FLUTTER_UZ + "\nYangi loyiha uchun", 0),
                                   m(6, BACKEND_RU + "\n@boshqa", 0)]   # 6 = dublikat
        assert await app.scan_all() == 1
        # yangi vakansiya endi barcha obunachilarga tarqatiladi, egaga alohida emas
        assert len(app.broadcasted) == 1
        assert app.broadcasted[0][1] == "https://t.me/itvak/5"
        assert app.sent == []

        # 4) .env ga yangi kanal qo'shildi -> darhol 15 kunlik skan
        app.sent.clear()
        app.broadcasted.clear()
        app.tme.add_channel("remotejobsuz", "Remote Jobs UZ", [
            m(10, IOS_EN, 3),                                  # dublikat (itvak da bor)
            m(11, "#vakansiya\nAndroid dasturchi (Kotlin) kerak\nMaosh: 2000$", 7),
            m(9, "#vakansiya\nFullstack developer kerak, maosh 1500$", 30),   # eski
        ])
        monkeypatch.setenv("CHANNELS", "@itvak,@remotejobsuz")
        await app.refresh_channels()
        assert pid_of("remotejobsuz") in app.peers
        assert len(app.sent) == 1 and "Yangi kanal" in app.sent[0][0]
        assert "<b>1</b> ta mos vakansiya" in app.sent[0][0]
        assert app.store.query("cat:Android")[1] == 1
        assert app.store.query("cat:Fullstack")[1] == 0

        # 5) qayta tekshirish — hech narsa takrorlanmaydi
        app.sent.clear()
        app.broadcasted.clear()
        await app.refresh_channels()
        assert await app.scan_all() == 0
        assert app.sent == [] and app.broadcasted == []
        assert app.store.query("all")[1] == 4

        # 6) ko'p yangi vakansiya -> bitta umumiy xabar
        app.tme.posts["itvak"] += [
            m(100 + i, f"#vakansiya\nLaravel backend dasturchi kerak — loyiha raqami {i}\n"
                       f"Maosh kelishiladi", 0)
            for i in range(8)]
        assert await app.scan_all() == 8
        assert len(app.broadcasted) == 1
        assert "8 ta yangi vakansiya" in app.broadcasted[0][0]

        # 7) bot uchun matnlar
        th.parse(app.bot_channels())
        assert "Remote Jobs UZ" in app.bot_channels()

    asyncio.run(go())


def test_empty_new_channel_remembers_last_id(app, monkeypatch):
    """15 kunda post bo'lmagan kanal: oxirgi ID eslab qolinadi, qayta skanerlanmaydi."""
    app.tme.add_channel("oldjobs", "Old Jobs", [m(50, BACKEND_RU, 40)])
    monkeypatch.setenv("CHANNELS", "@oldjobs")

    async def go():
        app.peers = await app.compute_peers()
        assert await app.scan_all() == 0
        assert app.store.channel_last_id(pid_of("oldjobs")) == 50

    asyncio.run(go())


def test_yopiq_kanal_otkazib_yuboriladi(app, monkeypatch):
    """Preview o'chirilgan kanal ro'yxatda bo'lsa ham, ishni to'xtatmaydi."""
    app.tme.add_channel("ochiq", "Ochiq kanal", [m(1, FLUTTER_UZ, 1)])
    monkeypatch.setenv("CHANNELS", "@ochiq,@yopiq_kanal")

    async def go():
        peers = await app.compute_peers()
        assert peers == [pid_of("ochiq")]

    asyncio.run(go())


class TestWanted:
    def test_turli_formatlar(self, monkeypatch):
        monkeypatch.setenv("CHANNELS", "https://t.me/a, @b ,t.me/c,d")
        monkeypatch.setenv("EXCLUDE_CHANNELS", "")
        assert main.App.wanted() == ["a", "b", "c", "d"]

    def test_exclude_ishlaydi(self, monkeypatch):
        monkeypatch.setenv("CHANNELS", "@a,@b,@c")
        monkeypatch.setenv("EXCLUDE_CHANNELS", "https://t.me/B")
        assert main.App.wanted() == ["a", "c"]

    def test_takror_tashlanadi(self, monkeypatch):
        monkeypatch.setenv("CHANNELS", "@a,t.me/a,https://t.me/a/123")
        monkeypatch.setenv("EXCLUDE_CHANNELS", "")
        assert main.App.wanted() == ["a"]

    def test_bosh_royxat(self, monkeypatch):
        monkeypatch.setenv("CHANNELS", "")
        monkeypatch.setenv("EXCLUDE_CHANNELS", "")
        assert main.App.wanted() == []
