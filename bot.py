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

from storage import PREF_CATS, Storage

log = logging.getLogger("bot")

MENU = [
    [("💙 Flutter", "cat:Flutter"), ("🍏 iOS", "cat:iOS"), ("🤖 Android", "cat:Android")],
    [("⚙️ Backend", "cat:Backend"), ("🧩 Fullstack", "cat:Fullstack"), ("📱 Barcha mobile", "cat:Mobile")],
    [("🆕 Bugungi", "today"), ("🌍 Remote", "remote"), ("📋 Hammasi", "all")],
    [("📌 Mening", "@my"), ("🔔 Sozlamalar", "@prefs"), ("❓ Yordam", "@help")],
    [("🔄 Hozir tekshirish", "@scan"), ("📡 Kanallar", "@channels")],
]
LABEL2KEY = {label: key for row in MENU for label, key in row}
# Ro'yxat sarlavhalari: menyudagilar + menyuda tugmasi bo'lmagan bo'limlar
TITLES = {key: label for label, key in LABEL2KEY.items()} | {
    "hidden": "🙈 Yashirilganlar",
    "saved": "⭐ Saqlangan",
    "applied": "✅ Ariza berilgan",
    "arxiv": "📦 Arxiv",
}

# Ro'yxatdagi raqam tugmasi qaysi belgini qo'yadi: kod -> (ikonka, belgi, harakat)
MODES = {
    "h": ("🙈", "hidden", "Yashirish"),
    "s": ("⭐", "saved", "Saqlash"),
    "a": ("✅", "applied", "Ariza berdim"),
}
MARK2MODE = {mark: code for code, (_, mark, _) in MODES.items()}
# Belgilar ro'yxatidan belgini olib tashlash tugmasi
UNMARK_ICON = {"hidden": "↩️", "saved": "✖️", "applied": "✖️"}
SCORES = [0, 6, 7, 8, 9]        # ⭐ Min ball tugmasi shu qiymatlar bo'ylab aylanadi

PAGE = 8
MARK_ROW = 4            # bitta qatorga nechta raqam tugmasi sig'adi
QUERY_CACHE = 20        # har foydalanuvchiga saqlanadigan qidiruvlar soni
BROADCAST_GAP = 0.05    # xabarlar orasidagi pauza (~20 xabar/sekund)

HELP = (
    "<b>Qanday ishlaydi</b>\n"
    "Bot IT kanallarni kuzatadi va saralangan vakansiyalarni shu yerga yig'adi. "
    "Har soatda yangi postlar tekshiriladi.\n\n"
    "<b>Ro'yxatlar</b>\n"
    "• Menyudan yo'nalishni tanlang — vakansiyalar va kanaldagi post havolasi chiqadi.\n"
    "• ◀️ ▶️ bilan sahifalarni almashtiring.\n"
    "• <b>Qidirish:</b> shunchaki so'z yozing, masalan <code>laravel remote</code>.\n\n"
    "<b>Belgilar</b> — ro'yxat ostidagi raqam tugmalari:\n"
    "• 🙈 — kerak bo'lmagan vakansiyani yashiradi (odam olingan, mos kelmadi).\n"
    "• ⭐ — keyin qaytib ko'rish uchun saqlaydi.\n"
    "• ✅ — ariza berganingizni belgilaydi.\n"
    "Tugmalar ostidagi qatordan belgini almashtirasiz. Hammasi "
    "<b>📌 Mening</b> bo'limida to'planadi.\n\n"
    "<b>🔔 Sozlamalar</b>\n"
    "• Qaysi yo'nalishlar bo'yicha xabar kelishini tanlang — keraksizi kelmaydi.\n"
    "• Faqat remote va minimal AI ballini qo'yish mumkin.\n"
    "• Qidiruv natijasi ostidagi «🔔 Obuna» — o'sha so'zga mos yangi vakansiya "
    "chiqsa, darhol xabar beradi."
)

ADMIN_HELP = (
    "\n\n<b>Admin uchun</b>\n"
    "• <code>+@kanal_nomi</code> — kanal qo'shish (darhol 15 kunlik skan qilinadi).\n"
    "• <code>-@kanal_nomi</code> — kanalni kuzatuvdan chiqarish."
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
        self.channel_edit_callback = None   # async (name: str, add: bool) -> str

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
        help_text = HELP + (ADMIN_HELP if owner else "")
        if text in ("/start", "/menu"):
            await event.respond(
                "👋 Salom! Saralangan IT vakansiyalar shu yerda.\n"
                "Pastdagi menyudan yo'nalishni tanlang.\n\n" + help_text,
                buttons=self.keyboard(owner))
            return
        if text == "/help":
            await event.respond(help_text, buttons=self.keyboard(owner))
            return
        if owner and self.is_channel_command(text):
            await self.edit_channel(event, text)
            return
        key = LABEL2KEY.get(text)
        if key in ("@scan", "@channels") and not owner:
            await event.respond("Bu tugma faqat admin uchun.", buttons=self.keyboard(owner))
            return
        if key == "@my":
            await self.show_my(event, uid, edit=False)
        elif key == "@prefs":
            await self.show_prefs(event, uid, edit=False)
        elif key == "@help":
            await event.respond(help_text)
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

    @staticmethod
    def is_channel_command(text: str) -> bool:
        """Admin yozgan `+@kanal` / `-@kanal`. Oddiy qidiruvdan ajratish uchun
        ikkinchi belgi `@` yoki harf bo'lishi shart."""
        return len(text) > 2 and text[0] in "+-" and (text[1] == "@" or text[1].isalpha())

    async def edit_channel(self, event, text: str):
        """Admin: +@kanal / -@kanal."""
        if not self.channel_edit_callback:
            await event.respond("Kanal boshqaruvi hali tayyor emas.")
            return
        add, name = text[0] == "+", text[1:].strip()
        await event.respond("⏳ Tekshirilmoqda..." if add else "⏳ Bajarilmoqda...")
        await event.respond(await self.channel_edit_callback(name, add))

    # ------------------------------------------------------------------ #
    async def on_callback(self, event):
        uid = event.sender_id
        kind, _, rest = event.data.decode().partition("|")
        if kind == "p":
            # Eski xabarlarda rejimsiz format uchraydi: "p|<filtr>|<offset>"
            parts = rest.split("|")
            flt, off = parts[0], parts[1]
            mode = parts[2] if len(parts) > 2 else "h"
            if not await self.check_query(event, uid, flt):
                return
            await self.show_page(event, flt, int(off), edit=True, user_id=uid, mode=mode)
            await event.answer()
        elif kind == "m":
            await self.on_mark(event, uid, rest)
        elif kind == "x":
            await self.on_unmark(event, uid, rest)
        elif kind == "h":       # eski 🙈 tugmasi: "h|<id>|<filtr>|<offset>"
            vid, flt, off = rest.split("|", 2)
            await self.on_mark(event, uid, f"{vid}|h|{flt}|{off}")
        elif kind == "u":       # eski ↩️ tugmasi: "u|<id>|<offset>"
            vid, _, off = rest.partition("|")
            await self.on_unmark(event, uid, f"{vid}|hidden|{off}")
        elif kind == "g":
            await self.on_goto(event, uid, rest)
        elif kind == "n":
            await self.on_pref(event, uid, rest)
        elif kind == "s":
            await self.on_subscribe(event, uid, rest)
        elif kind == "d":
            await self.on_del_alert(event, uid, rest)
        else:
            await event.answer()

    async def check_query(self, event, uid: int, flt: str) -> bool:
        """Qidiruv tugmasi eskirgan bo'lsa (bot qayta ishga tushgan) — ogohlantiradi."""
        if flt.startswith("q:") and self.get_query(uid, flt[2:]) is None:
            await event.answer("Qidiruv eskirgan — so'zni qayta yozing.", alert=True)
            return False
        return True

    async def on_mark(self, event, uid: int, rest: str):
        """Raqam tugmasi: vakansiyaga 🙈 / ⭐ / ✅ belgisini qo'yadi.

        rest: "<id>|<rejim>|<filtr>|<offset>". Filtr bo'sh bo'lsa, tugma
        bildirishnoma xabaridan bosilgan — qayta chizadigan ro'yxat yo'q.
        """
        vid, mode, flt, off = rest.split("|", 3)
        icon, mark, harakat = MODES.get(mode, MODES["h"])
        row = self.store.vacancy(int(vid))
        if row is None:
            await event.answer("Vakansiya topilmadi.", alert=True)
            return
        yangi = self.store.mark(uid, int(vid), mark)
        title = (row["title"] or "Vakansiya")[:60]
        joy = TITLES[mark]
        await event.answer(f"{icon} {harakat}: {title}\n«📌 Mening» → {joy}" if yangi
                           else f"{icon} «{title}» allaqachon {joy} ro'yxatida.")
        # Eskirgan qidiruvni qayta chiza olmaymiz, lekin belgi baribir qo'yildi.
        if flt.startswith("q:") and self.get_query(uid, flt[2:]) is None:
            return
        if flt:
            await self.show_page(event, flt, int(off), edit=True, user_id=uid, mode=mode)

    async def on_unmark(self, event, uid: int, rest: str):
        """Belgilar ro'yxatidagi ↩️ / ✖️ — belgini olib tashlaydi."""
        vid, flt, off = rest.split("|", 2)
        self.store.unmark(uid, int(vid), flt)
        await event.answer("↩️ Qaytarildi — ro'yxatlarda yana ko'rinadi." if flt == "hidden"
                           else f"✖️ {TITLES[flt]} ro'yxatidan olib tashlandi.")
        await self.show_page(event, flt, int(off), edit=True, user_id=uid)

    async def on_goto(self, event, uid: int, page: str):
        if page == "my":
            await self.show_my(event, uid, edit=True)
        elif page == "prefs":
            await self.show_prefs(event, uid, edit=True)
        elif page == "alerts":
            await self.show_alerts(event, uid, edit=True)
        elif page == "stats":
            await event.edit(self.render_stats(uid, self.is_owner(uid)),
                             buttons=[[Button.inline("◀️ Orqaga", "g|my")]])
        await event.answer()

    # ------------------------------------------------------------------ #
    def _resolve(self, flt: str, user_id: int) -> tuple[str, str]:
        """(bazaga beriladigan filtr, sarlavha)"""
        if flt.startswith("q:"):
            q = self.get_query(user_id, flt[2:]) or ""
            return f"q:{q}", f"🔎 «{html.escape(q)}»"
        return flt, TITLES.get(flt, "📋 Hammasi")

    async def show_page(self, event, flt: str, offset: int, edit: bool, user_id: int,
                        mode: str = "h"):
        mode = mode if mode in MODES else "h"
        db_flt, header = self._resolve(flt, user_id)
        rows, total = self.store.query(db_flt, offset, PAGE, user_id=user_id)
        if offset and offset >= total:      # sahifadagi oxirgi vakansiya belgilandi
            offset = max(0, ((total - 1) // PAGE) * PAGE)
            rows, total = self.store.query(db_flt, offset, PAGE, user_id=user_id)
        marks = self.store.marks_of(user_id, [r["id"] for r in rows])
        text = self.render_page(header, rows, total, offset, flt, marks, mode)
        buttons = self.page_buttons(rows, flt, offset, total, mode)
        if edit:
            await event.edit(text, buttons=buttons, link_preview=False)
        else:
            await event.respond(text, buttons=buttons, link_preview=False)

    @staticmethod
    def page_buttons(rows, flt: str, offset: int, total: int, mode: str = "h"):
        """Raqam tugmalari + rejim almashtirgich + sahifalash.

        Tugmadagi raqam ro'yxatdagi raqam bilan bir xil — foydalanuvchi qaysi
        vakansiyani belgilayotganini ko'rib turadi.
        """
        keys: list[list] = []
        if flt in MARK2MODE:                      # belgilar ro'yxati: belgini olib tashlash
            icon = UNMARK_ICON[flt]
            marks = [Button.inline(f"{icon} {i}", f"x|{r['id']}|{flt}|{offset}")
                     for i, r in enumerate(rows, start=offset + 1)]
        else:
            icon = MODES.get(mode, MODES["h"])[0]
            marks = [Button.inline(f"{icon} {i}", f"m|{r['id']}|{mode}|{flt}|{offset}")
                     for i, r in enumerate(rows, start=offset + 1)]
        keys += [marks[i:i + MARK_ROW] for i in range(0, len(marks), MARK_ROW)]
        if rows and flt not in MARK2MODE:         # boshqa rejimga o'tish
            keys.append([Button.inline(f"{ic} {harakat}", f"p|{flt}|{offset}|{code}")
                         for code, (ic, _, harakat) in MODES.items() if code != mode])
        if flt.startswith("q:"):
            keys.append([Button.inline("🔔 Shu qidiruvga obuna", f"s|{flt[2:]}")])
        nav = []
        if offset > 0:
            nav.append(Button.inline("◀️ Oldingi", f"p|{flt}|{max(0, offset - PAGE)}|{mode}"))
        if offset + PAGE < total:
            nav.append(Button.inline("Keyingi ▶️", f"p|{flt}|{offset + PAGE}|{mode}"))
        if nav:
            keys.append(nav)
        return keys or None

    @staticmethod
    def render_page(header: str, rows, total: int, offset: int, flt: str = "all",
                    marks: dict[int, set[str]] | None = None, mode: str = "h") -> str:
        e = html.escape
        marks = marks or {}
        if not total:
            bosh = {
                "hidden": "Yashirilgan vakansiya yo'q.",
                "saved": "Saqlangan vakansiya yo'q.",
                "applied": "Hali hech qaysisiga ariza bermagansiz.",
                "arxiv": "Arxivda vakansiya yo'q.",
            }.get(flt, "Hozircha vakansiya yo'q. 🙂")
            return f"<b>{header}</b>\n\n{bosh}"
        end = min(offset + PAGE, total)
        bosh = f"<b>{header}</b> — {total} ta vakansiya ({offset + 1}–{end})"
        if flt in MARK2MODE:
            bosh += (f"\n<i>{UNMARK_ICON[flt]} raqamini bossangiz, ro'yxatdan chiqadi.</i>")
        else:
            icon, _, harakat = MODES.get(mode, MODES["h"])
            bosh += f"\n<i>{icon} raqamini bosing — {harakat.lower()}.</i>"
        out = [bosh]
        for i, r in enumerate(rows, start=offset + 1):
            bor = marks.get(r["id"], set())
            belgi = "".join(MODES[MARK2MODE[m]][0] for m in ("saved", "applied") if m in bor)
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
            block = [f"\n<b>{i}. {title}</b>{comp}" + (f" {belgi}" if belgi else ""),
                     e(" · ".join(meta))]
            if r["salary"]:
                block.append(f"💰 {e(r['salary'][:70])}")
            block.append(f"📢 {e(r['chat_title'] or '')} · {date}")
            block.append(f"🔗 {e(r['link'])}")
            out.append("\n".join(block))
        return "\n".join(out)  # 8 ta qisqa blok — 4096 belgi limitidan ancha kam

    # ------------------------------------------------------------------ #
    async def show_my(self, event, uid: int, edit: bool):
        """📌 Mening — shaxsiy ro'yxatlar to'plami."""
        c = self.store.mark_counts(uid)
        n_alert = len(self.store.alerts(uid))
        text = "\n".join([
            "<b>📌 Mening ro'yxatlarim</b>\n",
            f"⭐ Saqlangan: <b>{c['saved']}</b>",
            f"✅ Ariza berilgan: <b>{c['applied']}</b>",
            f"🙈 Yashirilganlar: <b>{c['hidden']}</b>",
            f"🔔 Qidiruv obunalari: <b>{n_alert}</b>",
        ])
        buttons = [
            [Button.inline(f"⭐ Saqlangan ({c['saved']})", "p|saved|0|h"),
             Button.inline(f"✅ Ariza berilgan ({c['applied']})", "p|applied|0|h")],
            [Button.inline(f"🙈 Yashirilganlar ({c['hidden']})", "p|hidden|0|h"),
             Button.inline(f"🔔 Obunalar ({n_alert})", "g|alerts")],
            [Button.inline("📦 Arxiv", "p|arxiv|0|h"),
             Button.inline("📊 Statistika", "g|stats")],
        ]
        if edit:
            await event.edit(text, buttons=buttons, link_preview=False)
        else:
            await event.respond(text, buttons=buttons, link_preview=False)

    async def show_prefs(self, event, uid: int, edit: bool):
        """🔔 Sozlamalar — qaysi vakansiyalar haqida xabar kelishi."""
        p = self.store.prefs(uid)
        tanlangan = ", ".join(p["cats"]) if p["cats"] else "hammasi"
        ball = f"{p['min_score']}/10" if p["min_score"] else "chegara yo'q"
        text = "\n".join([
            "<b>🔔 Bildirishnoma sozlamalari</b>\n",
            f"Holat: {'🔔 yoqilgan' if p['notify'] else '🔕 o‘chirilgan'}",
            f"Yo'nalishlar: <b>{html.escape(tanlangan)}</b>",
            f"Faqat remote: <b>{'ha' if p['remote_only'] else 'yo‘q'}</b>",
            f"Minimal AI ball: <b>{ball}</b>",
            "\n<i>Bu sozlamalar faqat kelib turadigan xabarlarga ta'sir qiladi — "
            "menyudagi ro'yxatlarda hamma vakansiya ko'rinaveradi.</i>",
        ])
        cat_rows = [PREF_CATS[:3], PREF_CATS[3:]]
        buttons = [[Button.inline(f"{'✅' if c in p['cats'] else '⬜'} {c}", f"n|c|{c}")
                    for c in row] for row in cat_rows]
        buttons.append([Button.inline(
            f"🌍 Faqat remote: {'✅' if p['remote_only'] else '⬜'}", "n|r|")])
        buttons.append([Button.inline(f"⭐ Minimal ball: {ball}", "n|s|")])
        buttons.append([Button.inline(
            "🔕 Bildirishnomani o'chirish" if p["notify"] else "🔔 Bildirishnomani yoqish",
            "n|t|")])
        if edit:
            await event.edit(text, buttons=buttons, link_preview=False)
        else:
            await event.respond(text, buttons=buttons, link_preview=False)

    async def on_pref(self, event, uid: int, rest: str):
        what, _, arg = rest.partition("|")
        p = self.store.prefs(uid)
        if what == "c":
            self.store.toggle_cat(uid, arg)
        elif what == "r":
            self.store.set_pref(uid, "remote_only", not p["remote_only"])
        elif what == "s":
            joriy = p["min_score"] if p["min_score"] in SCORES else 0
            self.store.set_pref(uid, "min_score", SCORES[(SCORES.index(joriy) + 1) % len(SCORES)])
        elif what == "t":
            self.store.set_notify(uid, not p["notify"])
        await self.show_prefs(event, uid, edit=True)
        await event.answer()

    # ------------------------------------------------------------------ #
    async def show_alerts(self, event, uid: int, edit: bool):
        rows = self.store.alerts(uid)
        e = html.escape
        lines = [f"<b>🔔 Qidiruv obunalari</b> — {len(rows)} ta\n"]
        if rows:
            lines += [f"{i}. <code>{e(r['query'])}</code>" for i, r in enumerate(rows, 1)]
            lines.append("\n<i>Shu so'zlarga mos yangi vakansiya chiqsa, darhol "
                         "xabar beraman.</i>")
        else:
            lines.append("Obuna yo'q.")
        lines.append("\n<b>Qo'shish:</b> qidiruv so'zini yozing, natija ostidagi "
                     "«🔔 Shu qidiruvga obuna» tugmasini bosing.")
        oching = [Button.inline(f"🗑 {i}", f"d|{r['id']}") for i, r in enumerate(rows, 1)]
        buttons = [oching[i:i + MARK_ROW] for i in range(0, len(oching), MARK_ROW)]
        buttons.append([Button.inline("◀️ Orqaga", "g|my")])
        text = "\n".join(lines)
        if edit:
            await event.edit(text, buttons=buttons, link_preview=False)
        else:
            await event.respond(text, buttons=buttons, link_preview=False)

    async def on_subscribe(self, event, uid: int, qid: str):
        q = self.get_query(uid, qid)
        if q is None:
            await event.answer("Qidiruv eskirgan — so'zni qayta yozing.", alert=True)
            return
        if self.store.add_alert(uid, q):
            await event.answer(f"🔔 Obuna bo'ldingiz: «{q[:50]}»\n"
                               "Mos vakansiya chiqsa, xabar beraman.", alert=True)
        else:
            await event.answer(f"🔔 «{q[:50]}» obunasi allaqachon bor.", alert=True)

    async def on_del_alert(self, event, uid: int, alert_id: str):
        self.store.del_alert(uid, int(alert_id))
        await event.answer("🗑 Obuna o'chirildi.")
        await self.show_alerts(event, uid, edit=True)

    # ------------------------------------------------------------------ #
    def render_stats(self, user_id: int, owner: bool = False) -> str:
        s = self.store.stats(7)
        c = self.store.mark_counts(user_id)
        p = self.store.prefs(user_id)
        e = html.escape
        lines = [
            "<b>📊 Statistika</b>",
            f"Bazada jami: <b>{s['total']}</b>",
            f"Bugun: <b>{s['today']}</b>  |  Oxirgi 7 kun: <b>{s['week']}</b>",
            f"Kuzatilayotgan kanallar: {self.channels_count}",
            f"Bildirishnoma: {'🔔 yoqilgan' if p['notify'] else '🔕 o‘chirilgan'}"
            + (f" ({', '.join(p['cats'])})" if p["cats"] else ""),
            f"Sizda: ⭐ {c['saved']}  ·  ✅ {c['applied']}  ·  🙈 {c['hidden']}",
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
        buttons = [[Button.url("🔗 Kanaldagi postni ochish", link)]] if link else None
        await self._send(self.owner_id, text_html, buttons)

    @staticmethod
    def vacancy_buttons(link: str | None, vacancy_id: int | None):
        """Bildirishnoma xabarining tugmalari."""
        rows = []
        if link:
            rows.append([Button.url("🔗 Kanaldagi postni ochish", link)])
        if vacancy_id:
            rows.append([Button.inline("🙈 Yashirish", f"m|{vacancy_id}|h||0"),
                         Button.inline("⭐ Saqlash", f"m|{vacancy_id}|s||0")])
        return rows or None

    async def deliver_new(self, items: list[dict], notify_max: int = 5) -> int:
        """Yangi vakansiyalarni har kimning sozlamasiga qarab tarqatadi.

        Foydalanuvchi qaysi yo'nalishni tanlagan bo'lsa, o'shalar keladi.
        Qidiruv obunasiga mos kelgani esa sozlamadan qat'i nazar yuboriladi —
        bu ataylab so'ralgan narsa.

        Nechta foydalanuvchiga xabar ketganini qaytaradi.
        """
        per_user: dict[int, dict[int, dict]] = {}
        alert_hits: dict[int, dict[int, list[str]]] = {}
        for it in items:
            for uid in self.store.recipients(it["cats"], it["remote"], it["score"]):
                per_user.setdefault(uid, {})[it["id"]] = it
            for uid, queries in self.store.alert_matches(it["search"]).items():
                per_user.setdefault(uid, {})[it["id"]] = it
                alert_hits.setdefault(uid, {})[it["id"]] = queries
        yuborildi = 0
        for uid, byid in per_user.items():
            mine = list(byid.values())
            if await self._deliver_one(uid, mine, alert_hits.get(uid, {}), notify_max):
                yuborildi += 1
        log.info("Tarqatildi: %d ta yangi vakansiya -> %d foydalanuvchi",
                 len(items), yuborildi)
        return yuborildi

    async def _deliver_one(self, uid: int, items: list[dict],
                           hits: dict[int, list[str]], notify_max: int) -> bool:
        e = html.escape
        ok = False
        if len(items) <= notify_max:
            for it in items:
                text = it["html"]
                if it["id"] in hits:
                    text = (f"🔔 <i>«{e(hits[it['id']][0])}» obunangiz bo'yicha</i>\n\n"
                            + text)
                if await self._send(uid, text, self.vacancy_buttons(it["link"], it["id"])):
                    ok = True
                await asyncio.sleep(BROADCAST_GAP)
            return ok
        lines = [f"🆕 <b>{len(items)} ta yangi vakansiya</b>\n"]
        for it in items[:15]:
            nishon = " 🔔" if it["id"] in hits else ""
            lines.append(f"• <a href=\"{e(it['link'])}\">{e(it['title'])}</a> "
                         f"— {e(it['chat'])}{nishon}")
        if len(items) > 15:
            lines.append(f"… va yana {len(items) - 15} ta")
        lines.append("\nBarchasi menyuda: 🆕 Bugungi / 📋 Hammasi 👇")
        ok = await self._send(uid, "\n".join(lines), None)
        await asyncio.sleep(BROADCAST_GAP)
        return ok

    async def broadcast(self, text_html: str, link: str | None = None) -> int:
        """Hamma obunachiga bir xil xabar (e'lon). Yuborilganlar sonini qaytaradi."""
        buttons = [[Button.url("🔗 Ochish", link)]] if link else None
        yuborildi = 0
        for uid in self.store.subscribers():
            if await self._send(uid, text_html, buttons):
                yuborildi += 1
            await asyncio.sleep(BROADCAST_GAP)
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
