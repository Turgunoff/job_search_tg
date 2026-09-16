"""Menyuli Telegram bot: saralangan IT vakansiyalarni yo'nalish bo'yicha ko'rsatadi.

Bot hammaga ochiq — kim /start bossa foydalana oladi. OWNER_ID esa admin
huquqlariga ega: 🔄 qayta tekshirish, 📡 kanallar ro'yxati va texnik hisobotlar.
"""
from __future__ import annotations

import asyncio
import html
import logging
from collections import OrderedDict, defaultdict
from datetime import datetime

from telethon import Button, TelegramClient, events
from telethon.errors import (FloodWaitError, InputUserDeactivatedError,
                             UserIsBlockedError)

from storage import Storage

log = logging.getLogger("bot")

MENU = [
    [("💙 Flutter", "cat:Flutter"), ("🍏 iOS", "cat:iOS"), ("🤖 Android", "cat:Android")],
    [("⚙️ Backend", "cat:Backend"), ("🧩 Fullstack", "cat:Fullstack"), ("📱 Barcha mobile", "cat:Mobile")],
    [("🆕 Bugungi", "today"), ("🌍 Remote", "remote"), ("📋 Hammasi", "all")],
    [("📊 Statistika", "@stats"), ("🔔 Bildirishnoma", "@notify"), ("❓ Yordam", "@help")],
    [("🔄 Hozir tekshirish", "@scan"), ("📡 Kanallar", "@channels")],
]
LABEL2KEY = {label: key for row in MENU for label, key in row}
KEY2LABEL = {key: label for label, key in LABEL2KEY.items()}
PAGE = 8
QUERY_CACHE = 20        # har foydalanuvchiga saqlanadigan qidiruvlar soni
BROADCAST_GAP = 0.05    # xabarlar orasidagi pauza (~20 xabar/sekund)

HELP = (
    "<b>Qanday ishlaydi</b>\n"
    "Bot IT kanallarni kuzatadi va saralangan vakansiyalarni shu yerga yig'adi.\n"
    "• Har soatda yangi postlar tekshiriladi.\n\n"
    "• Pastdagi menyudan yo'nalishni tanlang — vakansiyalar ro'yxati va kanaldagi post havolasi chiqadi.\n"
    "• ◀️ ▶️ tugmalari bilan sahifalarni almashtiring.\n"
    "• <b>Qidirish:</b> shunchaki so'z yozing, masalan <code>laravel remote</code> yoki <code>uzum</code>.\n"
    "• 🔔 — yangi vakansiyalar haqida xabar berishni yoqish/o'chirish."
)


class JobBot:
    def __init__(self, store: Storage, api_id: int, api_hash: str, token: str,
                 session: str = "jobfilter_bot"):
        self.store = store
        self.token = token
        self.client = TelegramClient(session, api_id, api_hash)
        self.owner_id: int | None = None
        # Har foydalanuvchining oxirgi qidiruvlari — sahifalash tugmalari uchun.
        # Foydalanuvchi bo'yicha ajratilgan va chegaralangan: xotira cheksiz o'smaydi.
        self.queries: dict[int, OrderedDict] = defaultdict(OrderedDict)
        self.query_seq: dict[int, int] = defaultdict(int)
        self.channels_count = 0
        self.username = ""
        # App tomonidan ulanadi:
        self.scan_callback = None       # async () -> str
        self.channels_callback = None   # () -> str

    async def start(self, owner_id: int):
        await self.client.start(bot_token=self.token)
        self.client.parse_mode = "html"
        self.owner_id = owner_id
        self.client.add_event_handler(
            self.on_message, events.NewMessage(incoming=True, func=lambda e: e.is_private))
        self.client.add_event_handler(self.on_callback, events.CallbackQuery())
        me = await self.client.get_me()
        self.username = me.username or ""
        log.info("Bot ishga tushdi: @%s (ochiq, admin=%s)", self.username, owner_id)

    def is_owner(self, user_id: int) -> bool:
        return bool(self.owner_id) and user_id == self.owner_id

    def remember_query(self, user_id: int, text: str) -> str:
        self.query_seq[user_id] += 1
        qid = str(self.query_seq[user_id])
        cache = self.queries[user_id]
        cache[qid] = text[:100]
        while len(cache) > QUERY_CACHE:
            cache.popitem(last=False)
        return qid

    def get_query(self, user_id: int, qid: str) -> str | None:
        return self.queries[user_id].get(qid)

    # ------------------------------------------------------------------ #
    @staticmethod
    def keyboard(owner: bool = False):
        """Oddiy foydalanuvchiga admin qatori (🔄, 📡) ko'rsatilmaydi."""
        rows = MENU if owner else MENU[:-1]
        return [[Button.text(label, resize=True, persistent=True) for label, _ in row]
                for row in rows]

    async def on_message(self, event):
        uid = event.sender_id
        sender = await event.get_sender()
        self.store.add_user(uid, getattr(sender, "username", None),
                            getattr(sender, "first_name", None))
        owner = self.is_owner(uid)
        text = (event.raw_text or "").strip()
        if text in ("/start", "/menu"):
            await event.respond(
                "👋 Salom! Saralangan IT vakansiyalar shu yerda.\n"
                "Pastdagi menyudan yo'nalishni tanlang.\n\n" + HELP,
                buttons=self.keyboard(owner))
            return
        if text == "/help":
            await event.respond(HELP, buttons=self.keyboard(owner))
            return
        key = LABEL2KEY.get(text)
        if key in ("@scan", "@channels") and not owner:
            await event.respond("Bu tugma faqat admin uchun.", buttons=self.keyboard(owner))
            return
        if key == "@stats":
            await event.respond(self.render_stats(uid, owner))
        elif key == "@notify":
            new = "0" if self.store.notify_on(uid) else "1"
            self.store.set_notify(uid, new == "1")
            await event.respond("🔔 Bildirishnoma yoqildi: yangi vakansiyalar darhol keladi."
                                if new == "1" else
                                "🔕 Bildirishnoma o'chirildi. Vakansiyalar menyuda saqlanib boradi.")
        elif key == "@help":
            await event.respond(HELP)
        elif key == "@scan":
            if not self.scan_callback:
                await event.respond("Skaner hali tayyor emas.")
                return
            await event.respond("⏳ Tekshirilmoqda... (kanallar soniga qarab 1-3 daqiqa)")
            await event.respond(await self.scan_callback())
        elif key == "@channels":
            await event.respond(self.channels_callback() if self.channels_callback
                                else "Ma'lumot yo'q.")
        elif key:
            await self.show_page(event, key, 0, edit=False, user_id=uid)
        elif text.startswith("/"):
            await event.respond("Noma'lum buyruq. /menu ni bosing.",
                                buttons=self.keyboard(owner))
        elif len(text) >= 2:
            qid = self.remember_query(uid, text)
            await self.show_page(event, f"q:{qid}", 0, edit=False, user_id=uid)

    async def on_callback(self, event):
        uid = event.sender_id
        data = event.data.decode()
        if not data.startswith("p|"):
            await event.answer()
            return
        _, flt, off = data.split("|", 2)
        if flt.startswith("q:") and self.get_query(uid, flt[2:]) is None:
            await event.answer("Qidiruv eskirgan — so'zni qayta yozing.", alert=True)
            return
        await self.show_page(event, flt, int(off), edit=True, user_id=uid)
        await event.answer()

    # ------------------------------------------------------------------ #
    def _resolve(self, flt: str, user_id: int) -> tuple[str, str]:
        """(bazaga beriladigan filtr, sarlavha)"""
        if flt.startswith("q:"):
            q = self.get_query(user_id, flt[2:]) or ""
            return f"q:{q}", f"🔎 «{html.escape(q)}»"
        return flt, KEY2LABEL.get(flt, "📋 Hammasi")

    async def show_page(self, event, flt: str, offset: int, edit: bool, user_id: int):
        db_flt, header = self._resolve(flt, user_id)
        rows, total = self.store.query(db_flt, offset, PAGE)
        text = self.render_page(header, rows, total, offset)
        nav = []
        if offset > 0:
            nav.append(Button.inline("◀️ Oldingi", f"p|{flt}|{max(0, offset - PAGE)}"))
        if offset + PAGE < total:
            nav.append(Button.inline("Keyingi ▶️", f"p|{flt}|{offset + PAGE}"))
        buttons = [nav] if nav else None
        if edit:
            await event.edit(text, buttons=buttons, link_preview=False)
        else:
            await event.respond(text, buttons=buttons, link_preview=False)

    @staticmethod
    def render_page(header: str, rows, total: int, offset: int) -> str:
        e = html.escape
        if not total:
            return f"<b>{header}</b>\n\nHozircha vakansiya yo'q. 🙂"
        end = min(offset + PAGE, total)
        out = [f"<b>{header}</b> — {total} ta vakansiya ({offset + 1}–{end})"]
        for i, r in enumerate(rows, start=offset + 1):
            title = e(r["title"] or "Vakansiya")
            comp = f" — {e(r['company'])}" if r["company"] else ""
            meta = [c for c in (r["cats"] or "").split(",") if c]
            if r["levels"]:
                meta.append(r["levels"])
            if r["remote"]:
                meta.append("Remote")
            if r["score"] is not None:
                meta.append(f"⭐{r['score']}/10")
            date = datetime.fromtimestamp(r["posted"]).strftime("%d.%m %H:%M")
            block = [f"\n<b>{i}. {title}</b>{comp}", e(" · ".join(meta))]
            if r["salary"]:
                block.append(f"💰 {e(r['salary'][:70])}")
            block.append(f"📢 {e(r['chat_title'] or '')} · {date}")
            block.append(f"🔗 {e(r['link'])}")
            out.append("\n".join(block))
        return "\n".join(out)  # 8 ta qisqa blok — 4096 belgi limitidan ancha kam

    def render_stats(self, user_id: int, owner: bool = False) -> str:
        s = self.store.stats(7)
        e = html.escape
        lines = [
            "<b>📊 Statistika</b>",
            f"Bazada jami: <b>{s['total']}</b>",
            f"Bugun: <b>{s['today']}</b>  |  Oxirgi 7 kun: <b>{s['week']}</b>",
            f"Kuzatilayotgan kanallar: {self.channels_count}",
            f"Bildirishnoma: {'🔔 yoqilgan' if self.store.notify_on(user_id) else '🔕 o‘chirilgan'}",
        ]
        if owner:
            jami, obuna = self.store.user_count()
            lines.append(f"Foydalanuvchilar: <b>{jami}</b>  |  obunachilar: <b>{obuna}</b>")
        if s["cats"]:
            lines.append("\n<b>Yo'nalishlar (7 kun):</b>")
            lines += [f"• {e(k)}: {v}" for k, v in s["cats"].items()]
        if s["top"]:
            lines.append("\n<b>Eng foydali kanallar (7 kun):</b>")
            lines += [f"{i}. {e(t or '-')} — {n}" for i, (t, n) in enumerate(s["top"], 1)]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    async def send_to_owner(self, text_html: str, link: str | None = None,
                            force: bool = False) -> None:
        """Texnik hisobotlar va admin xabarlari — faqat botning egasiga."""
        if not self.owner_id:
            return
        if not force and not self.store.notify_on(self.owner_id):
            return
        buttons = [Button.url("🔗 Kanaldagi postni ochish", link)] if link else None
        await self._send(self.owner_id, text_html, buttons)

    async def broadcast(self, text_html: str, link: str | None = None) -> int:
        """Yangi vakansiyani barcha obunachilarga yuboradi. Yuborilganlar sonini qaytaradi."""
        buttons = [Button.url("🔗 Kanaldagi postni ochish", link)] if link else None
        yuborildi = 0
        for uid in self.store.subscribers():
            if await self._send(uid, text_html, buttons):
                yuborildi += 1
            await asyncio.sleep(BROADCAST_GAP)
        log.info("Tarqatildi: %d obunachi", yuborildi)
        return yuborildi

    async def _send(self, uid: int, text_html: str, buttons) -> bool:
        """Bitta foydalanuvchiga yuborish. Muvaffaqiyatli bo'lsa True.

        Bitta foydalanuvchining xatosi butun tarqatishni to'xtatmaydi.
        """
        for _ in range(3):
            try:
                await self.client.send_message(uid, text_html, buttons=buttons,
                                               link_preview=False)
                return True
            except FloodWaitError as e:
                log.warning("Bot FloodWait %ss", e.seconds)
                await asyncio.sleep(e.seconds + 1)
            except (UserIsBlockedError, InputUserDeactivatedError, ValueError):
                log.info("Foydalanuvchi %s ga yozib bo'lmadi — ro'yxatdan chiqarildi", uid)
                self.store.deactivate(uid)
                return False
            except Exception as e:
                log.error("Bot xabar yubora olmadi (%s): %s", uid, e)
                return False
        return False
