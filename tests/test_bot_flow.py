import asyncio, os, sys, tempfile
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
tmp = tempfile.mkdtemp()

from telethon.extensions import html as th
import main
from bot import JobBot, PAGE
from test_filters import FLUTTER_UZ, BACKEND_RU, IOS_EN, RESUME


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeEvent:
    def __init__(self, text="", sender=42, data=None):
        self.raw_text, self.sender_id, self.data = text, sender, data
        self.out = []
    async def get_sender(self):
        return NS(username=f"u{self.sender_id}", first_name=f"User {self.sender_id}")
    async def respond(self, text, buttons=None, **kw):
        th.parse(text); self.out.append(("respond", text, buttons))
    async def edit(self, text, buttons=None, **kw):
        th.parse(text); self.out.append(("edit", text, buttons))
    async def answer(self, *a, **kw):
        self.out.append(("answer", a, kw))


def make_app(monkeypatch, db="t"):
    """Soxta bot + testga tegishli alohida baza (`db` — fayl nomi)."""
    # conftest xavfsiz qiymatlar beradi; bu testga soxta bot kerak.
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("DB_PATH", os.path.join(tmp, f"{db}.db"))
    monkeypatch.setenv("CSV_PATH", os.path.join(tmp, f"{db}.csv"))
    monkeypatch.setenv("BOT_SESSION_NAME", os.path.join(tmp, "b"))
    app = main.App()
    app.bot.owner_id = 42
    sent = []
    async def fake_send(text, link=None, force=False):
        th.parse(text); sent.append((text, link, force))
    app.send = fake_send
    ch1 = NS(title="IT Jobs UZ", username="itjobsuz", id=111)
    ch2 = NS(title="Private", username=None, usernames=None, id=222)
    app.entities = {-100111: ch1, -100222: ch2}
    return app, sent


def msg(i, t, hours_ago=0):
    return NS(id=i, message=t, date=datetime.now(timezone.utc) - timedelta(hours=hours_ago))


def test_full_flow(monkeypatch):
    app, sent = make_app(monkeypatch)
    async def go():
        assert await app.handle(msg(1, FLUTTER_UZ, 30), -100111)
        assert await app.handle(msg(2, RESUME, 30), -100111) is None
        assert await app.handle(msg(3, FLUTTER_UZ + "\n@x #y", 29), -100222) is None  # dublikat
        await app.handle(msg(4, BACKEND_RU, 28), -100222)
        item = await app.handle(msg(5, IOS_EN), -100111)
        assert item["link"] == "https://t.me/itjobsuz/5"
        th.parse(item["html"])
        assert sent == []  # handle o'zi hech narsa yubormaydi
        for i in range(10):  # sahifalash uchun
            await app.handle(msg(100 + i, BACKEND_RU + f"\nLoyiha raqami {i} uchun backend kerak"), -100222)
    run(go())
    rows, total = app.store.query("all")
    assert total == 13
    assert app.store.query("cat:Flutter")[1] == 1
    assert app.store.query("cat:Mobile")[1] == 2          # Flutter + iOS
    assert app.store.query("cat:Backend")[1] == 11
    assert app.store.query("remote")[1] >= 12
    assert app.store.query("today")[1] >= 11
    assert app.store.query("q:laravel")[1] == 11
    assert app.store.query("q:LARAVEL удалённо")[1] == 11  # kirill registri
    assert app.store.query("q:uzum")[1] == 1

    bot = app.bot
    async def ui():
        e = FakeEvent("⚙️ Backend"); await bot.on_message(e)
        kind, text, buttons = e.out[0]
        assert "11 ta vakansiya (1–8)" in text and "https://t.me/c/222/" in text
        # 8 ta 🙈 tugmasi (4 tadan 2 qator) + sahifalash qatori
        assert [len(r) for r in buttons] == [4, 4, 1]
        assert buttons[0][0].text == "🙈 1"
        assert buttons[-1][0].type.data == b"p|cat:Backend|8"
        e2 = FakeEvent(data=b"p|cat:Backend|8"); await bot.on_callback(e2)
        assert e2.out[0][0] == "edit" and "(9–11)" in e2.out[0][1]
        assert e2.out[0][2][0][0].text == "🙈 9"     # raqamlar ro'yxatdagidek
        assert e2.out[0][2][-1][0].type.data == b"p|cat:Backend|0"
        e3 = FakeEvent("💙 Flutter"); await bot.on_message(e3)
        assert "Flutter dasturchi (Middle)" in e3.out[0][1] and "t.me/itjobsuz/1" in e3.out[0][1]
        e4 = FakeEvent("uzum"); await bot.on_message(e4)
        assert "1 ta vakansiya" in e4.out[0][1]
        e5 = FakeEvent("📊 Statistika"); await bot.on_message(e5)
        assert "Bazada jami: <b>13</b>" in e5.out[0][1]
        e6 = FakeEvent("🔔 Bildirishnoma"); await bot.on_message(e6)
        assert app.store.notify_on(42) is False
        # bot ochiq: notanish foydalanuvchi ham menyu oladi, lekin admin tugmalarisiz
        e7 = FakeEvent("/start", sender=999); await bot.on_message(e7)
        begona_tugmalar = [b.button.text for row in e7.out[0][2] for b in row]
        assert "shaxsiy" not in e7.out[0][1].lower()
        assert "💙 Flutter" in begona_tugmalar
        assert "🔄 Hozir tekshirish" not in begona_tugmalar
        e8 = FakeEvent("/start"); await bot.on_message(e8)
        egasi_tugmalar = [b.button.text for row in e8.out[0][2] for b in row]
        assert "🔄 Hozir tekshirish" in egasi_tugmalar
        # ikkalasi ham users jadvaliga tushdi (42 ning 🔔 si e6 da o'chirilgan)
        assert app.store.user_count() == (2, 1)
        e9 = FakeEvent(data=b"p|q:77|0"); await bot.on_callback(e9)
        assert e9.out[0][0] == "answer"
    run(ui())
    rep = app.report([-100111, -100222], 7)
    th.parse(rep)
    assert "mos / jami" in rep


def test_kanal_royxati(monkeypatch):
    """Avtomatik topish o'rniga .env dagi ro'yxat — turli formatlar qabul qilinadi."""
    monkeypatch.setenv("CHANNELS", "https://t.me/itvakansiya,@uzdev_jobs, t.me/kunuz ")
    monkeypatch.setenv("EXCLUDE_CHANNELS", "@kunuz")
    assert main.App.wanted() == ["itvakansiya", "uzdev_jobs"]


def test_yashirish(monkeypatch):
    """🙈 — vakansiya shu foydalanuvchining ro'yxatlaridan chiqadi, boshqalarnikida qoladi."""
    app, _ = make_app(monkeypatch, db="yashir")
    bot = app.bot

    async def go():
        for i in range(3):
            await app.handle(msg(200 + i, BACKEND_RU + f"\nLoyiha {i} uchun backend"), -100111)
        e = FakeEvent("⚙️ Backend"); await bot.on_message(e)
        birinchi = e.out[0][2][0][0].type.data.decode()   # "h|<id>|cat:Backend|0"
        vid = int(birinchi.split("|")[1])
        assert birinchi == f"h|{vid}|cat:Backend|0"

        # 1) yashiramiz — ro'yxat darhol qayta chiziladi va vakansiya yo'qoladi
        e2 = FakeEvent(data=birinchi.encode()); await bot.on_callback(e2)
        turlar = [o[0] for o in e2.out]
        assert "answer" in turlar and "edit" in turlar
        matn = [o for o in e2.out if o[0] == "edit"][0][1]
        assert "2 ta vakansiya" in matn
        assert app.store.query("all", user_id=42)[1] == 2
        assert app.store.query("all", user_id=999)[1] == 3   # boshqaga ta'sir qilmaydi
        assert app.store.query("all")[1] == 3                # bazada turibdi
        assert app.store.hidden_count(42) == 1

        # 2) qayta bosilsa — ikkilanmaydi
        e3 = FakeEvent(data=birinchi.encode()); await bot.on_callback(e3)
        assert app.store.hidden_count(42) == 1

        # 3) 🙈 Yashirilganlar ro'yxati — ↩️ tugmalari bilan
        e4 = FakeEvent("🙈 Yashirilganlar"); await bot.on_message(e4)
        kind, text, buttons = e4.out[0]
        assert "1 ta vakansiya" in text and "↩️" in text
        qaytar = buttons[0][0]
        assert qaytar.text == "↩️ 1"
        assert qaytar.type.data == f"u|{vid}|0".encode()

        # 4) qaytaramiz
        e5 = FakeEvent(data=qaytar.type.data); await bot.on_callback(e5)
        assert app.store.hidden_count(42) == 0
        assert app.store.query("all", user_id=42)[1] == 3
        assert "Yashirilgan vakansiya yo'q" in [o for o in e5.out if o[0] == "edit"][0][1]

        # 5) bildirishnomadagi tugma (filtrsiz) — ro'yxat chizilmaydi
        e6 = FakeEvent(data=f"h|{vid}||0".encode()); await bot.on_callback(e6)
        assert app.store.hidden_count(42) == 1
        assert [o[0] for o in e6.out] == ["answer"]

        # 6) o'chirilgan vakansiya id si — xato bermaydi
        e7 = FakeEvent(data=b"h|999999|cat:Backend|0"); await bot.on_callback(e7)
        assert [o[0] for o in e7.out] == ["answer"]

    run(go())


def test_oxirgi_sahifa_bosh_qolsa(monkeypatch):
    """Sahifadagi yagona vakansiya yashirilsa — oldingi sahifaga tushadi."""
    app, _ = make_app(monkeypatch, db="sahifa")
    bot = app.bot

    async def go():
        for i in range(PAGE + 1):
            await app.handle(msg(300 + i, BACKEND_RU + f"\nSahifa testi {i} backend"), -100111)
        e = FakeEvent(data=f"p|all|{PAGE}".encode()); await bot.on_callback(e)
        text = e.out[0][1]
        assert f"({PAGE + 1}–{PAGE + 1})" in text
        hide = e.out[0][2][0][0].type.data
        e2 = FakeEvent(data=hide); await bot.on_callback(e2)
        matn = [o for o in e2.out if o[0] == "edit"][0][1]
        assert f"{PAGE} ta vakansiya (1–{PAGE})" in matn   # 1-sahifaga qaytdi

    run(go())
