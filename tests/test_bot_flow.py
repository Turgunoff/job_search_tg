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
        # 8 ta raqam tugmasi (4 tadan 2 qator) + rejim qatori + sahifalash
        assert [len(r) for r in buttons] == [4, 4, 2, 1]
        assert buttons[0][0].text == "🙈 1"
        assert [b.text for b in buttons[2]] == ["⭐ Saqlash", "✅ Ariza berdim"]
        assert buttons[-1][0].type.data == b"p|cat:Backend|8|h"
        # eski format tugmasi (yangilanishdan oldingi xabarlar) ham ishlaydi
        e2 = FakeEvent(data=b"p|cat:Backend|8"); await bot.on_callback(e2)
        assert e2.out[0][0] == "edit" and "(9–11)" in e2.out[0][1]
        assert e2.out[0][2][0][0].text == "🙈 9"     # raqamlar ro'yxatdagidek
        assert e2.out[0][2][-1][0].type.data == b"p|cat:Backend|0|h"
        e3 = FakeEvent("💙 Flutter"); await bot.on_message(e3)
        assert "Flutter dasturchi (Middle)" in e3.out[0][1] and "t.me/itjobsuz/1" in e3.out[0][1]
        e4 = FakeEvent("uzum"); await bot.on_message(e4)
        assert "1 ta vakansiya" in e4.out[0][1]
        e5 = FakeEvent(data=b"g|stats"); await bot.on_callback(e5)
        assert "Bazada jami: <b>13</b>" in e5.out[0][1]
        e6 = FakeEvent(data=b"n|t|"); await bot.on_callback(e6)   # 🔔 ni o'chirish
        assert app.store.notify_on(42) is False
        # bot ochiq: notanish foydalanuvchi ham menyu oladi, lekin admin tugmalarisiz
        e7 = FakeEvent("/start", sender=999); await bot.on_message(e7)
        begona_tugmalar = [b.button.text for row in e7.out[0][2] for b in row]
        assert "shaxsiy" not in e7.out[0][1].lower()
        assert "💙 Flutter" in begona_tugmalar
        assert "🔄 Hozir tekshirish" not in begona_tugmalar
        assert "📌 Mening" in begona_tugmalar
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
        birinchi = e.out[0][2][0][0].type.data.decode()   # "m|<id>|h|cat:Backend|0"
        vid = int(birinchi.split("|")[1])
        assert birinchi == f"m|{vid}|h|cat:Backend|0"

        # 1) yashiramiz — ro'yxat darhol qayta chiziladi va vakansiya yo'qoladi
        e2 = FakeEvent(data=birinchi.encode()); await bot.on_callback(e2)
        turlar = [o[0] for o in e2.out]
        assert "answer" in turlar and "edit" in turlar
        matn = [o for o in e2.out if o[0] == "edit"][0][1]
        assert "2 ta vakansiya" in matn
        assert app.store.query("all", user_id=42)[1] == 2
        assert app.store.query("all", user_id=999)[1] == 3   # boshqaga ta'sir qilmaydi
        assert app.store.query("all")[1] == 3                # bazada turibdi
        assert app.store.mark_counts(42)["hidden"] == 1

        # 2) qayta bosilsa — ikkilanmaydi
        e3 = FakeEvent(data=birinchi.encode()); await bot.on_callback(e3)
        assert app.store.mark_counts(42)["hidden"] == 1

        # 3) 🙈 Yashirilganlar ro'yxati — ↩️ tugmalari bilan
        e4 = FakeEvent(data=b"p|hidden|0|h"); await bot.on_callback(e4)
        kind, text, buttons = e4.out[0]
        assert "1 ta vakansiya" in text and "↩️" in text
        qaytar = buttons[0][0]
        assert qaytar.text == "↩️ 1"
        assert qaytar.type.data == f"x|{vid}|hidden|0".encode()
        assert len(buttons) == 1      # belgilar ro'yxatida rejim qatori yo'q

        # 4) qaytaramiz
        e5 = FakeEvent(data=qaytar.type.data); await bot.on_callback(e5)
        assert app.store.mark_counts(42)["hidden"] == 0
        assert app.store.query("all", user_id=42)[1] == 3
        assert "Yashirilgan vakansiya yo'q" in [o for o in e5.out if o[0] == "edit"][0][1]

        # 5) bildirishnomadagi tugma (filtrsiz) — ro'yxat chizilmaydi
        e6 = FakeEvent(data=f"m|{vid}|h||0".encode()); await bot.on_callback(e6)
        assert app.store.mark_counts(42)["hidden"] == 1
        assert [o[0] for o in e6.out] == ["answer"]

        # 6) o'chirilgan vakansiya id si — xato bermaydi
        e7 = FakeEvent(data=b"m|999999|h|cat:Backend|0"); await bot.on_callback(e7)
        assert [o[0] for o in e7.out] == ["answer"]

        # 7) eski format tugmasi ham ishlaydi
        app.store.unmark(42, vid, "hidden")
        e8 = FakeEvent(data=f"h|{vid}|cat:Backend|0".encode()); await bot.on_callback(e8)
        assert app.store.mark_counts(42)["hidden"] == 1
        e9 = FakeEvent(data=f"u|{vid}|0".encode()); await bot.on_callback(e9)
        assert app.store.mark_counts(42)["hidden"] == 0

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


def rejim_qatori(buttons):
    """Tugmalar orasidan rejim almashtirgich qatorini topadi."""
    return next(row for row in buttons if any("Saqlash" in b.text or "Yashirish" in b.text
                                              for b in row))


def test_belgilar_rejimi(monkeypatch):
    """⭐ va ✅ — rejim almashtirgich, ro'yxatda ko'rinishi, 🙈 bilan zidligi."""
    app, _ = make_app(monkeypatch, db="belgi")
    bot, st = app.bot, app.store

    async def go():
        for i in range(3):
            await app.handle(msg(400 + i, BACKEND_RU + f"\nBelgi testi {i} backend"), -100111)
        e = FakeEvent("📋 Hammasi"); await bot.on_message(e)
        rejim = rejim_qatori(e.out[0][2])
        assert [b.text for b in rejim] == ["⭐ Saqlash", "✅ Ariza berdim"]

        # ⭐ rejimiga o'tamiz — raqamlar yulduzchaga aylanadi
        e2 = FakeEvent(data=rejim[0].type.data); await bot.on_callback(e2)
        tugmalar = e2.out[0][2]
        assert tugmalar[0][0].text == "⭐ 1"
        assert [b.text for b in rejim_qatori(tugmalar)] == ["🙈 Yashirish", "✅ Ariza berdim"]

        # ⭐ 1 ni bosamiz
        saqla = tugmalar[0][0].type.data
        vid = int(saqla.decode().split("|")[1])
        e3 = FakeEvent(data=saqla); await bot.on_callback(e3)
        assert st.mark_counts(42)["saved"] == 1
        # saqlangan vakansiya ro'yxatda ⭐ bilan belgilanadi va yo'qolmaydi
        matn = [o for o in e3.out if o[0] == "edit"][0][1]
        assert "3 ta vakansiya" in matn and "⭐</b>" not in matn
        assert st.query("all", user_id=42)[1] == 3

        # ✅ ham qo'shamiz — ikkalasi birga tura oladi
        e4 = FakeEvent(data=f"m|{vid}|a|all|0".encode()); await bot.on_callback(e4)
        assert st.marks_of(42, [vid])[vid] == {"saved", "applied"}
        matn = [o for o in e4.out if o[0] == "edit"][0][1]
        assert "⭐✅" in matn                      # ro'yxatda ikkala belgi

        # 🙈 qo'ysak — ⭐ olib tashlanadi (zid belgilar)
        e5 = FakeEvent(data=f"m|{vid}|h|all|0".encode()); await bot.on_callback(e5)
        assert st.marks_of(42, [vid])[vid] == {"hidden", "applied"}
        assert st.query("all", user_id=42)[1] == 2

        # ⭐ Saqlangan ro'yxati bo'shab qoldi, ✅ ro'yxatida turibdi
        assert st.query("saved", user_id=42)[1] == 0
        assert st.query("applied", user_id=42)[1] == 1

        # 📌 Mening — sanoqlar to'g'ri
        e6 = FakeEvent("📌 Mening"); await bot.on_message(e6)
        assert "✅ Ariza berilgan: <b>1</b>" in e6.out[0][1]
        assert "🙈 Yashirilganlar: <b>1</b>" in e6.out[0][1]

    run(go())


def test_bildirishnoma_sozlamalari(monkeypatch):
    """Har foydalanuvchi o'z yo'nalishiga obuna: kimga nima ketishini tekshiradi."""
    app, _ = make_app(monkeypatch, db="prefs")
    bot, st = app.bot, app.store

    async def go():
        for uid in (1, 2, 3):
            st.add_user(uid)
        st.toggle_cat(1, "Flutter")                  # 1 — faqat Flutter
        st.toggle_cat(2, "Backend")                  # 2 — Backend + faqat remote
        st.set_pref(2, "remote_only", 1)
        st.set_pref(3, "min_score", 8)               # 3 — hammasi, lekin ⭐8+

        flutter = {"cats": ["Flutter"], "remote": False, "score": 9}
        backend = {"cats": ["Backend"], "remote": True, "score": 7}
        assert st.recipients(**flutter) == [1, 3]
        assert st.recipients(**backend) == [2]       # 3 ga ball yetmadi
        # remote emas -> 2 ga bormaydi
        assert st.recipients(cats=["Backend"], remote=False, score=9) == [3]
        # ball yo'q (AI o'chirilgan) -> ball filtri qo'llanmaydi
        assert st.recipients(cats=["Flutter"], remote=False, score=None) == [1, 3]
        # 📱 Mobile tanlovi butun mobil guruhni qamraydi
        st.toggle_cat(1, "Flutter"); st.toggle_cat(1, "Mobile")
        assert 1 in st.recipients(cats=["iOS"], remote=False, score=9)
        # bildirishnomani o'chirgan odam ro'yxatdan chiqadi
        st.set_notify(3, False)
        assert st.recipients(**flutter) == [1]

        # UI: tugmalar holatni ko'rsatadi
        e = FakeEvent("🔔 Sozlamalar"); await bot.on_message(e)
        text, buttons = e.out[0][1], e.out[0][2]
        assert "Yo'nalishlar: <b>hammasi</b>" in text
        assert buttons[0][0].text == "⬜ Flutter"
        e2 = FakeEvent(data=b"n|c|Flutter"); await bot.on_callback(e2)
        assert st.prefs(42)["cats"] == ["Flutter"]
        assert e2.out[0][2][0][0].text == "✅ Flutter"
        # ⭐ Min ball tugmasi aylanadi: 0 -> 6 -> 7
        for kutilgan in (6, 7):
            e3 = FakeEvent(data=b"n|s|"); await bot.on_callback(e3)
            assert st.prefs(42)["min_score"] == kutilgan
        e4 = FakeEvent(data=b"n|r|"); await bot.on_callback(e4)
        assert st.prefs(42)["remote_only"] is True

    run(go())


def test_tarqatish(monkeypatch):
    """deliver_new: kimga nechta xabar ketadi, ko'p bo'lsa — bitta umumiy."""
    app, _ = make_app(monkeypatch, db="tarqat")
    bot, st = app.bot, app.store
    yuborilgan = []

    async def fake_send(uid, text, buttons):
        th.parse(text); yuborilgan.append((uid, text, buttons)); return True
    bot._send = fake_send

    def item(i, cats, remote=False, score=9, text="flutter dasturchi kerak"):
        return {"id": i, "html": f"<b>Vakansiya {i}</b>", "link": f"https://t.me/x/{i}",
                "title": f"Vakansiya {i}", "chat": "Kanal", "cats": cats,
                "remote": remote, "score": score, "search": text}

    async def go():
        st.add_user(1); st.toggle_cat(1, "Flutter")
        st.add_user(2); st.toggle_cat(2, "Backend")

        n = await bot.deliver_new([item(1, ["Flutter"]), item(2, ["Backend"])], notify_max=5)
        assert n == 2
        assert {u for u, _, _ in yuborilgan} == {1, 2}
        assert len(yuborilgan) == 2                  # har biriga faqat o'ziniki
        # xabarda 🙈 va ⭐ tugmalari bor
        tugmalar = [b.text for row in yuborilgan[0][2] for b in row]
        assert "🙈 Yashirish" in tugmalar and "⭐ Saqlash" in tugmalar

        # ko'p vakansiya -> bitta umumiy xabar
        yuborilgan.clear()
        await bot.deliver_new([item(10 + i, ["Flutter"]) for i in range(8)], notify_max=5)
        faqat1 = [x for x in yuborilgan if x[0] == 1]
        assert len(faqat1) == 1 and "8 ta yangi vakansiya" in faqat1[0][1]

    run(go())


def test_qidiruv_obunasi(monkeypatch):
    """🔔 Obuna: sozlama mos kelmasa ham, obuna bo'yicha xabar keladi."""
    app, _ = make_app(monkeypatch, db="obuna")
    bot, st = app.bot, app.store
    yuborilgan = []

    async def fake_send(uid, text, buttons):
        th.parse(text); yuborilgan.append((uid, text)); return True
    bot._send = fake_send

    async def go():
        await app.handle(msg(500, BACKEND_RU + "\nUzum Market uchun backend"), -100111)
        e = FakeEvent("uzum"); await bot.on_message(e)
        obuna = e.out[0][2][-1][0]           # "🔔 Shu qidiruvga obuna"
        assert obuna.text == "🔔 Shu qidiruvga obuna"
        e2 = FakeEvent(data=obuna.type.data); await bot.on_callback(e2)
        assert [r["query"] for r in st.alerts(42)] == ["uzum"]
        # ikkinchi marta — takrorlanmaydi
        e3 = FakeEvent(data=obuna.type.data); await bot.on_callback(e3)
        assert len(st.alerts(42)) == 1

        # 42 faqat Flutter ga obuna, lekin "uzum" qidiruvi mos keladi
        st.toggle_cat(42, "Flutter")
        it = {"id": 99, "html": "<b>Backend</b>", "link": "https://t.me/x/9",
              "title": "Backend", "chat": "Kanal", "cats": ["Backend"],
              "remote": False, "score": 9, "search": "uzum market backend kerak"}
        await bot.deliver_new([it], notify_max=5)
        meniki = [t for u, t in yuborilgan if u == 42]
        assert len(meniki) == 1 and "«uzum» obunangiz bo'yicha" in meniki[0]

        # obunani o'chirish
        e4 = FakeEvent(data=b"g|alerts"); await bot.on_callback(e4)
        ochir = e4.out[0][2][0][0]
        assert ochir.text == "🗑 1"
        e5 = FakeEvent(data=ochir.type.data); await bot.on_callback(e5)
        assert st.alerts(42) == []

    run(go())


def test_arxiv_va_tozalash(monkeypatch):
    """Ro'yxatlar oxirgi 30 kunni, 📦 Arxiv eskisini ko'rsatadi."""
    app, _ = make_app(monkeypatch, db="arxiv")
    st = app.store

    async def go():
        await app.handle(msg(600, BACKEND_RU + "\nYangi backend"), -100111)
        await app.handle(msg(601, FLUTTER_UZ + "\nEski flutter", 24 * 45), -100111)
    run(go())

    assert st.query("all")[1] == 1                # 45 kunlik oynadan tashqarida
    assert st.query("arxiv")[1] == 1
    assert st.query("cat:Flutter")[1] == 0
    assert st.query("q:flutter")[1] == 1          # qidiruv oynaga bo'ysunmaydi

    bot = app.bot
    async def ui():
        e = FakeEvent(data=b"p|arxiv|0|h"); await bot.on_callback(e)
        assert "📦 Arxiv</b> — 1 ta" in e.out[0][1]
    run(ui())

    # tozalash: eski xizmat yozuvlari ketadi, vakansiyalar qoladi
    st.db.execute("UPDATE seen_msg SET ts = ts - 100*86400")
    st.db.execute("UPDATE seen_hash SET ts = ts - 100*86400")
    st.db.commit()
    assert st.purge(60) > 0
    assert st.db.execute("SELECT COUNT(*) FROM seen_msg").fetchone()[0] == 0
    assert st.query("all")[1] + st.query("arxiv")[1] == 2


def test_eski_bazani_kochirish(monkeypatch):
    """Eski `hidden` jadvali user_vacancy ga ko'chiriladi."""
    import sqlite3
    from storage import Storage
    yol = os.path.join(tmp, "eski.db")
    db = sqlite3.connect(yol)
    db.executescript("""
        CREATE TABLE users (user_id INTEGER PRIMARY KEY, username TEXT,
            first_name TEXT, joined INTEGER, last_seen INTEGER,
            notify INTEGER DEFAULT 1, active INTEGER DEFAULT 1);
        CREATE TABLE hidden (user_id INTEGER, vacancy_id INTEGER, ts INTEGER,
            PRIMARY KEY (user_id, vacancy_id));
        INSERT INTO users VALUES (7, 'u', 'U', 1, 1, 1, 1);
        INSERT INTO hidden VALUES (7, 123, 1700000000);
    """)
    db.commit(); db.close()

    st = Storage(yol)
    assert tuple(st.db.execute(
        "SELECT mark, ts FROM user_vacancy WHERE user_id=7 AND vacancy_id=123"
    ).fetchone()) == ("hidden", 1700000000)
    assert st.db.execute(
        "SELECT name FROM sqlite_master WHERE name='hidden'").fetchone() is None
    assert st.prefs(7) == {"notify": True, "cats": [], "remote_only": False,
                           "min_score": 0}
    Storage(yol)          # ikkinchi marta ochish ham xatosiz


def test_kanal_boshqaruvi(monkeypatch):
    """Admin +@kanal / -@kanal bilan ro'yxatni o'zgartiradi."""
    app, _ = make_app(monkeypatch, db="kanal")
    bot, st = app.bot, app.store
    app.lock = asyncio.Lock()
    monkeypatch.setenv("CHANNELS", "@asosiy")

    async def fake_probe(name):
        return (True, f"Kanal {name}", 5) if name != "yopiq" else (False, "HTTP 404", 0)
    monkeypatch.setattr(main.tme_web, "probe", fake_probe)
    async def fake_iter(name, **kw):
        return f"Kanal {name}", []
    monkeypatch.setattr(main.tme_web, "iter_posts", fake_iter)
    bot.channel_edit_callback = app.bot_edit_channel

    async def go():
        app.peers = await app.compute_peers()
        assert app.wanted_now() == ["asosiy"]

        # qo'shish
        javob = await app.bot_edit_channel("@yangi", add=True)
        await app.pending_refresh
        assert "Qo'shildi" in javob
        assert st.get_list("extra_channels") == ["yangi"]
        assert app.wanted_now() == ["asosiy", "yangi"]

        # o'qilmaydigan kanal qo'shilmaydi
        javob = await app.bot_edit_channel("@yopiq", add=True)
        assert "o'qilmadi" in javob
        assert st.get_list("extra_channels") == ["yangi"]

        # .env dagi kanalni ham o'chirish mumkin
        javob = await app.bot_edit_channel("@asosiy", add=False)
        await app.pending_refresh
        assert "Kuzatuvdan chiqarildi" in javob
        assert app.wanted_now() == ["yangi"]

        # admin xabari orqali
        e = FakeEvent("+@boshqa"); await bot.on_message(e)
        await app.pending_refresh
        assert "Qo'shildi" in e.out[-1][1]
        assert "boshqa" in app.wanted_now()
        # oddiy foydalanuvchida bu qidiruv bo'lib qoladi
        e2 = FakeEvent("+@boshqa", sender=999); await bot.on_message(e2)
        assert "vakansiya yo'q" in e2.out[0][1]

    run(go())
