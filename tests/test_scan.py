"""Soatlik skan, 15 kunlik backfill va yangi kanal qo'shilishi (soxta Telegram client bilan)."""
import asyncio, os, sys, tempfile
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from telethon.extensions import html as th
import main
from test_filters import FLUTTER_UZ, BACKEND_RU, IOS_EN, RESUME

NOW = datetime.now(timezone.utc)


def m(i, text, days_ago):
    return NS(id=i, message=text, date=NOW - timedelta(days=days_ago))


class FakeClient:
    def __init__(self):
        self.posts = {}      # pid -> [msg, ...] (ID bo'yicha o'sib boradi)
        self.dialogs = []    # [NS(id, name, is_channel, is_group, entity)]
        self.calls = []

    def add_channel(self, pid, title, username, posts):
        ent = NS(id=abs(pid) - 1000000000000, title=title, username=username)
        self.dialogs.append(NS(id=pid, name=title, is_channel=True, is_group=False, entity=ent))
        self.posts[pid] = posts

    async def get_dialogs(self):
        return self.dialogs

    async def get_entity(self, pid):
        return next(d.entity for d in self.dialogs if d.id == pid)

    async def iter_messages(self, pid, limit=None, min_id=0):
        self.calls.append((pid, min_id))
        for msg in sorted(self.posts[pid], key=lambda x: -x.id)[:limit]:
            if msg.id > min_id:
                yield msg


def make_app(tmp):
    os.environ.update(API_ID="1", API_HASH="x", BOT_TOKEN="", CHANNELS="", FOLDER="",
                      EXCLUDE_CHANNELS="", BACKFILL_DAYS="15",
                      DB_PATH=os.path.join(tmp, "t.db"), CSV_PATH=os.path.join(tmp, "t.csv"),
                      SESSION_NAME=os.path.join(tmp, "u"))
    app = main.App()
    app.client = FakeClient()
    app.sent = []

    async def fake_send(text, link=None, force=False):
        th.parse(text)
        app.sent.append((text, link, force))
    app.send = fake_send
    app.lock = asyncio.Lock()
    return app


def run(c):
    return asyncio.run(c)


def test_backfill_hourly_and_new_channel():
    tmp = tempfile.mkdtemp()
    app = make_app(tmp)
    c = app.client
    c.add_channel(-1000000000111, "IT Vakansiyalar", "itvak", [
        m(1, FLUTTER_UZ, 20),          # 15 kundan eski -> olinmaydi
        m(2, BACKEND_RU, 10),
        m(3, RESUME, 5),
        m(4, IOS_EN, 1),
    ])
    c.add_channel(-1000000000222, "Kun.uz", "kunuz", [m(1, BACKEND_RU, 1)])  # job kanal emas

    async def go():
        app.peers = await app.compute_peers()
        assert app.peers == [-1000000000111]

        # 1) birinchi ishga tushish: 15 kunlik skan, alohida xabar yo'q, faqat hisobot
        n = await app.scan_all()
        assert n == 2
        assert len(app.sent) == 1 and "Kanal reytingi" in app.sent[0][0]
        assert app.store.query("all")[1] == 2
        assert app.store.channel_last_id(-1000000000111) == 4

        # 2) soatlik skan: yangi post yo'q -> hech narsa
        app.sent.clear()
        assert await app.scan_all() == 0
        assert app.sent == []
        assert c.calls[-1] == (-1000000000111, 4)   # min_id bilan faqat yangilari so'raladi

        # 3) yangi post + boshqa kanalning dublikati
        c.posts[-1000000000111] += [m(5, FLUTTER_UZ + "\nYangi loyiha uchun", 0),
                                    m(6, BACKEND_RU + "\n@boshqa", 0)]   # 6 = dublikat
        assert await app.scan_all() == 1
        assert len(app.sent) == 1 and app.sent[0][1] == "https://t.me/itvak/5"

        # 4) foydalanuvchi yangi kanalga qo'shildi -> darhol 15 kunlik skan
        app.sent.clear()
        c.add_channel(-1000000000333, "Remote Jobs UZ", "remotejobsuz", [
            m(10, IOS_EN, 3),                                  # dublikat (1-kanalda bor)
            m(11, "#vakansiya\nAndroid dasturchi (Kotlin) kerak\nMaosh: 2000$", 7),
            m(9, "#vakansiya\nFullstack developer kerak, maosh 1500$", 30),   # eski
        ])
        await app.refresh_channels()
        assert -1000000000333 in app.peers
        assert len(app.sent) == 1 and "Yangi kanal" in app.sent[0][0]
        assert "<b>1</b> ta mos vakansiya" in app.sent[0][0]
        assert app.store.query("cat:Android")[1] == 1
        assert app.store.query("cat:Fullstack")[1] == 0

        # 5) qayta tekshirish — hech narsa takrorlanmaydi
        app.sent.clear()
        await app.refresh_channels()
        assert await app.scan_all() == 0
        assert app.sent == []
        assert app.store.query("all")[1] == 4

        # 6) ko'p yangi vakansiya -> bitta umumiy xabar
        c.posts[-1000000000111] += [
            m(100 + i, f"#vakansiya\nLaravel backend dasturchi kerak — loyiha raqami {i}\nMaosh kelishiladi", 0)
            for i in range(8)]
        assert await app.scan_all() == 8
        assert len(app.sent) == 1 and "8 ta yangi vakansiya" in app.sent[0][0]

        # 7) bot uchun matnlar
        th.parse(app.bot_channels())
        assert "Remote Jobs UZ" in app.bot_channels()

    run(go())


def test_empty_new_channel_remembers_last_id():
    tmp = tempfile.mkdtemp()
    app = make_app(tmp)
    app.client.add_channel(-1000000000444, "Old Jobs", "oldjobs", [m(50, BACKEND_RU, 40)])

    async def go():
        app.peers = await app.compute_peers()
        assert await app.scan_all() == 0
        assert app.store.channel_last_id(-1000000000444) == 50
    run(go())
