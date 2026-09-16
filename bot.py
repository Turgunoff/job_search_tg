"""Menyuli Telegram bot: saralangan vakansiyalarni yo'nalish bo'yicha ko'rsatadi.

Bot faqat egasiga (skript ulangan akkaunt) va ALLOWED_USERS dagilarga javob beradi.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime

from telethon import Button, TelegramClient, events
from telethon.errors import FloodWaitError

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

HELP = (
    "<b>Qanday ishlaydi</b>\n"
    "Skript IT kanallaringizni kuzatadi va sizga mos vakansiyalarni shu botga yig'adi.\n"
    "• Yangi kanal — oxirgi 15 kun tekshiriladi, keyin har soatda faqat yangi postlar.\n"
    "• Yangi kanalga qo'shilsangiz — bir necha daqiqada o'zi topib, 15 kunini tekshiradi.\n\n"
    "• Pastdagi menyudan yo'nalishni tanlang — vakansiyalar ro'yxati va kanaldagi post havolasi chiqadi.\n"
    "• ◀️ ▶️ tugmalari bilan sahifalarni almashtiring.\n"
    "• <b>Qidirish:</b> shunchaki so'z yozing, masalan <code>laravel remote</code> yoki <code>uzum</code>.\n"
    "• 🔔 — yangi vakansiyalar haqida xabar berishni yoqish/o'chirish.\n"
    "• 🔄 — soatni kutmasdan hozir tekshirish.  📡 — kuzatilayotgan kanallar."
)


class JobBot:
    def __init__(self, store: Storage, api_id: int, api_hash: str, token: str,
                 session: str = "jobfilter_bot"):
        self.store = store
        self.token = token
        self.client = TelegramClient(session, api_id, api_hash)
        self.allowed: set[int] = set()
        self.owner_id: int | None = None
        self.queries: dict[str, str] = {}
        self.channels_count = 0
        self.username = ""
        # App tomonidan ulanadi:
        self.scan_callback = None       # async () -> str
        self.channels_callback = None   # () -> str

    async def start(self, owner_id: int, extra_allowed: list[int]):
        await self.client.start(bot_token=self.token)
        self.client.parse_mode = "html"
        self.owner_id = owner_id
        self.allowed = {owner_id, *extra_allowed}
        self.client.add_event_handler(
            self.on_message, events.NewMessage(incoming=True, func=lambda e: e.is_private))
        self.client.add_event_handler(self.on_callback, events.CallbackQuery())
        me = await self.client.get_me()
        self.username = me.username or ""
        log.info("Bot ishga tushdi: @%s", self.username)

    # ------------------------------------------------------------------ #
    @staticmethod
    def keyboard():
        return [[Button.text(label, resize=True, persistent=True) for label, _ in row]
                for row in MENU]

    def notify_on(self) -> bool:
        return self.store.get_setting("notify", "1") == "1"

    async def on_message(self, event):
        if event.sender_id not in self.allowed:
            await event.respond("⛔ Bu shaxsiy bot.")
            return
        text = (event.raw_text or "").strip()
        if text in ("/start", "/menu"):
            self.store.set_setting(f"started:{event.sender_id}", "1")
            await event.respond(
                "👋 Salom! Saralangan IT vakansiyalar shu yerda.\n"
                "Pastdagi menyudan yo'nalishni tanlang.\n\n" + HELP,
                buttons=self.keyboard())
            return
        if text == "/help":
            await event.respond(HELP, buttons=self.keyboard())
            return
        key = LABEL2KEY.get(text)
        if key == "@stats":
            await event.respond(self.render_stats())
        elif key == "@notify":
            new = "0" if self.notify_on() else "1"
            self.store.set_setting("notify", new)
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
            await self.show_page(event, key, 0, edit=False)
        elif text.startswith("/"):
            await event.respond("Noma'lum buyruq. /menu ni bosing.", buttons=self.keyboard())
        elif len(text) >= 2:
            qid = str(len(self.queries) + 1)
            self.queries[qid] = text[:100]
            await self.show_page(event, f"q:{qid}", 0, edit=False)

    async def on_callback(self, event):
        if event.sender_id not in self.allowed:
            await event.answer("⛔")
            return
        data = event.data.decode()
        if not data.startswith("p|"):
            await event.answer()
            return
        _, flt, off = data.split("|", 2)
        if flt.startswith("q:") and flt[2:] not in self.queries:
            await event.answer("Qidiruv eskirgan — so'zni qayta yozing.", alert=True)
            return
        await self.show_page(event, flt, int(off), edit=True)
        await event.answer()

    # ------------------------------------------------------------------ #
    def _resolve(self, flt: str) -> tuple[str, str]:
        """(bazaga beriladigan filtr, sarlavha)"""
        if flt.startswith("q:"):
            q = self.queries.get(flt[2:], "")
            return f"q:{q}", f"🔎 «{html.escape(q)}»"
        return flt, KEY2LABEL.get(flt, "📋 Hammasi")

    async def show_page(self, event, flt: str, offset: int, edit: bool):
        db_flt, header = self._resolve(flt)
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

    def render_stats(self) -> str:
        s = self.store.stats(7)
        e = html.escape
        lines = [
            "<b>📊 Statistika</b>",
            f"Bazada jami: <b>{s['total']}</b>",
            f"Bugun: <b>{s['today']}</b>  |  Oxirgi 7 kun: <b>{s['week']}</b>",
            f"Kuzatilayotgan kanallar: {self.channels_count}",
            f"Bildirishnoma: {'🔔 yoqilgan' if self.notify_on() else '🔕 o‘chirilgan'}",
        ]
        if s["cats"]:
            lines.append("\n<b>Yo'nalishlar (7 kun):</b>")
            lines += [f"• {e(k)}: {v}" for k, v in s["cats"].items()]
        if s["top"]:
            lines.append("\n<b>Eng foydali kanallar (7 kun):</b>")
            lines += [f"{i}. {e(t or '-')} — {n}" for i, (t, n) in enumerate(s["top"], 1)]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    def recipients(self) -> list[int]:
        """Egasi + /start bosgan ruxsatli foydalanuvchilar."""
        out = [self.owner_id] if self.owner_id else []
        out += [u for u in self.allowed
                if u != self.owner_id and self.store.get_setting(f"started:{u}")]
        return out

    async def send_to_owner(self, text_html: str, link: str | None = None,
                            force: bool = False) -> None:
        """Yangi vakansiya yoki hisobotni egasiga (va ruxsatli foydalanuvchilarga) yuborish."""
        if not force and not self.notify_on():
            return
        buttons = [Button.url("🔗 Kanaldagi postni ochish", link)] if link else None
        for uid in self.recipients():
            await self._send(uid, text_html, buttons)

    async def _send(self, uid: int, text_html: str, buttons) -> None:
        for _ in range(3):
            try:
                await self.client.send_message(uid, text_html, buttons=buttons,
                                               link_preview=False)
                return
            except FloodWaitError as e:
                log.warning("Bot FloodWait %ss", e.seconds)
                await asyncio.sleep(e.seconds + 1)
            except ValueError:
                log.warning("Bot %s ga yoza olmadi: @%s botini oching va /start bosing",
                            uid, self.username)
                return
            except Exception as e:
                log.error("Bot xabar yubora olmadi (%s): %s", uid, e)
                return
