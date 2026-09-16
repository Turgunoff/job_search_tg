"""Telegram IT-vakansiya filtri (Telethon userbot + menyuli bot).

Ishlash tartibi:
  • Yangi (hali ko'rilmagan) kanal  -> oxirgi BACKFILL_DAYS (15) kun skanerlanadi.
  • Har SCAN_INTERVAL_MIN (60) daqiqada -> har kanalda faqat oxirgi skandan keyingi postlar.
  • Yangi kanalga qo'shilsangiz -> darhol (va har CHANNEL_CHECK_MIN daqiqada) aniqlanadi,
    shu kanal uchun 15 kunlik skan qilinadi.
  • Bir xil vakansiya faqat bir marta saqlanadi.

Foydalanish:
  python main.py --list      # kanallar ro'yxati (✅ = kuzatiladi)
  python main.py             # doimiy ishlash
  python main.py --once      # bir marta skanerlash va chiqish
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import html
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient, events, functions, types, utils
from telethon.errors import FloodWaitError

from filters import JobFilter, fingerprint, guess_title, looks_like_job_channel
from storage import Storage

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("telethon").setLevel(logging.WARNING)
log = logging.getLogger("jobfilter")

CAT_ICON = {"Flutter": "💙", "iOS": "🍏", "Android": "🤖", "Mobile": "📱",
            "Backend": "⚙️", "Fullstack": "🧩", "Boshqa": "🔹"}


def env_list(name: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]


def env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None or not v.strip() else v.strip().lower() in ("1", "true", "yes", "ha")


def is_own(entity) -> bool:
    """O'zingiz yaratgan yoki admin bo'lgan kanal (sizning kanallar portfeli)."""
    if getattr(entity, "creator", False):
        return True
    return bool(getattr(entity, "broadcast", False) and getattr(entity, "admin_rights", None))


# --------------------------------------------------------------------------- #
class App:
    def __init__(self):
        api_id = os.getenv("API_ID")
        api_hash = os.getenv("API_HASH")
        if not api_id or not api_hash:
            sys.exit("❌ .env faylida API_ID va API_HASH yo'q. README ni qarang.")
        self.api_id, self.api_hash = int(api_id), api_hash
        self.client = TelegramClient(os.getenv("SESSION_NAME", "jobfilter"),
                                     self.api_id, api_hash)
        self.phone = os.getenv("PHONE") or None
        self.filter = JobFilter(
            include_extra=env_list("INCLUDE_EXTRA"),
            exclude_extra=env_list("EXCLUDE_EXTRA"),
            require_marker=env_bool("REQUIRE_VACANCY_MARKER", True),
            exclude_levels=env_list("EXCLUDE_LEVELS"),
        )
        self.store = Storage(os.getenv("DB_PATH", "jobs.db"))
        self.csv_path = os.getenv("CSV_PATH", "vakansiyalar.csv")
        self.min_score = int(os.getenv("AI_MIN_SCORE", "6"))
        self.ai = None
        if os.getenv("ANTHROPIC_API_KEY"):
            from ai import AIScorer
            self.ai = AIScorer(
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                model=os.getenv("AI_MODEL", "claude-haiku-4-5"),
                profile=os.getenv("PROFILE", "IT dasturchi"),
            )
        self.bot = None
        if os.getenv("BOT_TOKEN"):
            from bot import JobBot
            self.bot = JobBot(self.store, self.api_id, api_hash, os.getenv("BOT_TOKEN"),
                              session=os.getenv("BOT_SESSION_NAME", "jobfilter_bot"))
        self.backfill_days = int(os.getenv("BACKFILL_DAYS", "15"))
        self.scan_interval = int(os.getenv("SCAN_INTERVAL_MIN", "60"))
        self.check_interval = int(os.getenv("CHANNEL_CHECK_MIN", "5"))
        self.realtime = env_bool("REALTIME", False)
        self.notify_max = int(os.getenv("NOTIFY_MAX", "5"))
        self.peers: list[int] = []
        self.lock: asyncio.Lock | None = None
        self._pending_refresh: asyncio.Task | None = None
        self.last_scan: datetime | None = None
        self.entities: dict[int, object] = {}
        self.stats: dict[int, Counter] = defaultdict(Counter)

    # ---------------- kanallarni aniqlash ---------------- #
    def _mode(self) -> str:
        ch = os.getenv("CHANNELS", "").strip().lower()
        if ch in ("all", "hammasi"):
            return "all"
        if os.getenv("FOLDER", "").strip() or (ch and ch != "auto"):
            return "manual"
        return "auto"

    @staticmethod
    def _auto_pick(d, mode: str) -> bool:
        if not d.is_channel or is_own(d.entity):
            return False
        if mode == "all":
            return True
        return looks_like_job_channel(d.name, getattr(d.entity, "username", None))

    async def list_all(self):
        folders = await self._folders()
        print("\n📂 PAPKALAR (FOLDER=... uchun):")
        for title, peers in folders.items():
            print(f"  • {title}  ({len(peers)} ta chat)")
        mode = self._mode()
        print(f"\n📢 KANAL VA GURUHLAR  (rejim: {mode};  ✅ = avtomatik tanlanadi, "
              f"👤 = o'zingizniki, e'tiborga olinmaydi)")
        n = 0
        async for d in self.client.iter_dialogs():
            if not d.is_channel:
                continue
            kind = "guruh" if d.is_group else "kanal"
            uname = getattr(d.entity, "username", None)
            if is_own(d.entity):
                mark = "👤"
            elif self._auto_pick(d, "all" if mode == "all" else "auto"):
                mark = "✅"
                n += 1
            else:
                mark = "  "
            print(f"  {mark} {d.id:>16}  {kind:5} @{uname or '-':25} {d.name}")
        if mode != "manual":
            print(f"\nAvtomatik rejimda {n} ta kanal kuzatiladi. Keraksizini EXCLUDE_CHANNELS ga, "
                  f"topilmaganini CHANNELS ga qo'shing (auto bilan birga: CHANNELS=auto,@kanal).")

    async def _folders(self) -> dict[str, list[int]]:
        res = await self.client(functions.messages.GetDialogFiltersRequest())
        items = getattr(res, "filters", res)
        out: dict[str, list[int]] = {}
        for f in items:
            title = getattr(f, "title", None)
            if title is None:  # "Barcha chatlar" papkasi
                continue
            title = str(getattr(title, "text", title))
            peers = list(getattr(f, "include_peers", []) or []) + \
                list(getattr(f, "pinned_peers", []) or [])
            out[title] = [utils.get_peer_id(p) for p in peers]
        return out

    async def _resolve_one(self, ch: str) -> int:
        ent = await self.client.get_entity(int(ch) if ch.lstrip("-").isdigit() else ch)
        return utils.get_peer_id(ent)

    async def compute_peers(self, strict: bool = True) -> list[int]:
        dialogs = await self.client.get_dialogs()  # entity keshini ham to'ldiradi
        channels = env_list("CHANNELS")
        mode = self._mode()
        ids: list[int] = []
        if mode == "all" or mode == "auto" or any(c.lower() == "auto" for c in channels):
            pick_mode = "all" if mode == "all" else "auto"
            ids += [d.id for d in dialogs if self._auto_pick(d, pick_mode)]
        folder = os.getenv("FOLDER", "").strip()
        if folder:
            folders = await self._folders()
            match = next((v for k, v in folders.items()
                          if k.strip().lower() == folder.lower()), None)
            if match is None:
                msg = f"'{folder}' papkasi topilmadi. Mavjud: {', '.join(folders) or '-'}"
                if strict:
                    sys.exit("❌ " + msg)
                log.warning(msg)
                match = []
            ids += match
        for ch in channels:
            if ch.lower() in ("auto", "all", "hammasi"):
                continue
            try:
                ids.append(await self._resolve_one(ch))
            except Exception as e:
                log.warning("Kanal topilmadi: %s (%s)", ch, e)

        excluded: set[int] = set()
        for ch in env_list("EXCLUDE_CHANNELS"):
            try:
                excluded.add(await self._resolve_one(ch))
            except Exception as e:
                log.warning("EXCLUDE_CHANNELS: topilmadi %s (%s)", ch, e)
        ids = [i for i in dict.fromkeys(ids) if i not in excluded]
        if not ids and strict:
            sys.exit("❌ Kuzatiladigan kanal topilmadi. `python main.py --list` ni ko'ring "
                     "va .env da CHANNELS yoki FOLDER ni to'ldiring.")
        ok = []
        for pid in ids:
            try:
                self.entities[pid] = await self.client.get_entity(pid)
                ok.append(pid)
            except Exception as e:
                log.warning("Entity olinmadi %s: %s", pid, e)
        return ok

    def title(self, pid: int) -> str:
        return str(getattr(self.entities.get(pid), "title", pid))

    # ---------------- yordamchilar ---------------- #
    @staticmethod
    def link(chat, msg_id: int) -> str:
        uname = getattr(chat, "username", None)
        if not uname and getattr(chat, "usernames", None):
            uname = chat.usernames[0].username
        if uname:
            return f"https://t.me/{uname}/{msg_id}"
        return f"https://t.me/c/{chat.id}/{msg_id}"

    @staticmethod
    def format_post(chat, text, link, m, ai, title) -> str:
        e = html.escape
        cats = " · ".join(f"{CAT_ICON.get(c, '')} {c}" for c in m.categories)
        tags = []
        level = (ai or {}).get("level") or (", ".join(m.levels) if m.levels else None)
        if level:
            tags.append(str(level))
        if m.remote:
            tags.append("Remote/Gibrid")
        company = (ai or {}).get("company")
        lines = [f"🆕 <b>{e(title)}</b>" + (f" — {e(str(company))}" if company else "")]
        lines.append(e(cats) + (f"  |  {e(' · '.join(tags))}" if tags else ""))
        if ai:
            lines.append(f"⭐ Moslik: {ai['score']}/10 — {e(str(ai.get('reason') or ''))}")
            if ai.get("location"):
                lines.append(f"📍 {e(str(ai['location']))}")
        salary = (ai or {}).get("salary") or m.salary
        if salary:
            lines.append(f"💰 {e(str(salary))}")
        lines.append(f"📢 {e(getattr(chat, 'title', '') or '')}")
        lines.append(f"🔗 {e(link)}")
        preview = text.strip()
        if len(preview) > 700:
            preview = preview[:700].rsplit(" ", 1)[0] + " …"
        lines.append(f"\n<blockquote>{e(preview)}</blockquote>")
        return "\n".join(lines)

    async def send(self, text_html: str, link: str | None = None, force: bool = False):
        if self.bot:
            await self.bot.send_to_owner(text_html, link, force=force)
            return
        while True:
            try:
                await self.client.send_message("me", text_html, parse_mode="html",
                                               link_preview=False)
                return
            except FloodWaitError as e:
                log.warning("FloodWait %ss", e.seconds)
                await asyncio.sleep(e.seconds + 1)

    def write_csv(self, row: dict):
        new = not os.path.exists(self.csv_path)
        with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)

    # ---------------- asosiy ishlov ---------------- #
    async def handle(self, msg, chat_id: int) -> dict | None:
        """Postni tekshiradi. Yangi mos vakansiya saqlansa — uning ma'lumotini qaytaradi."""
        chat = self.entities.get(chat_id) or await msg.get_chat()
        st = self.stats[chat_id]
        st["jami"] += 1
        text = getattr(msg, "message", None) or ""
        m = self.filter.match(text)
        if not m:
            self.store.mark_msg(chat_id, msg.id)
            return None
        link = self.link(chat, msg.id)
        h = fingerprint(text)
        prev = self.store.get_hash(h)
        if prev and prev[0] != link:  # boshqa joyda oldin chiqqan vakansiya
            st["dublikat"] += 1
            self.store.mark_msg(chat_id, msg.id)
            return
        if prev and not prev[1]:  # oldingi ishga tushishda AI rad etgan
            st["AI rad etdi"] += 1
            return
        if self.store.msg_seen(chat_id, msg.id):  # oldin saqlangan
            st["mos"] += 1
            for c in m.categories:
                self.stats[0][c] += 1
            return
        self.store.mark_msg(chat_id, msg.id)

        ai = None
        if self.ai:
            ai = await self.ai.evaluate(text)
            if ai and (not ai["is_vacancy"] or ai["score"] < self.min_score):
                st["AI rad etdi"] += 1
                self.store.mark_hash(h, chat_id, msg.id, link, sent=False)
                log.info("AI rad etdi (%s/10): %s", ai["score"], link)
                return

        title = str((ai or {}).get("title") or guess_title(text))
        levels = str((ai or {}).get("level") or ", ".join(m.levels))
        salary = (ai or {}).get("salary") or m.salary
        salary = str(salary) if salary else None
        company = (ai or {}).get("company")
        self.store.mark_hash(h, chat_id, msg.id, link, sent=True)
        self.store.add_vacancy(
            hash=h, posted=int(msg.date.timestamp()), chat_id=chat_id,
            chat_title=getattr(chat, "title", "") or "", link=link, cats=m.categories,
            levels=levels, remote=m.remote, salary=salary, title=title,
            company=str(company) if company else None,
            score=(ai or {}).get("score"), text=text,
        )
        st["mos"] += 1
        for c in m.categories:
            self.stats[0][c] += 1
        self.write_csv({
            "sana": msg.date.astimezone().strftime("%Y-%m-%d %H:%M"),
            "kanal": getattr(chat, "title", ""),
            "yo'nalish": ", ".join(m.categories),
            "daraja": levels,
            "lavozim": title,
            "kompaniya": company or "",
            "maosh": salary or "",
            "remote": "ha" if m.remote else "",
            "ai_ball": (ai or {}).get("score", ""),
            "havola": link,
            "matn": text[:300].replace("\n", " "),
        })
        log.info("✅ Saqlandi: %s [%s] %s", link, ", ".join(m.categories), title)
        return {
            "html": self.format_post(chat, text, link, m, ai, title),
            "link": link, "title": title, "chat": getattr(chat, "title", "") or "",
            "cats": m.categories,
        }

    async def scan_channel(self, pid: int) -> tuple[list[dict], bool]:
        """(yangi vakansiyalar, bu birinchi — 15 kunlik skanmi)"""
        last_id = self.store.channel_last_id(pid)
        first = last_id is None
        msgs = []
        if first:
            since = datetime.now(timezone.utc) - timedelta(days=self.backfill_days)
            async for msg in self.client.iter_messages(pid, limit=5000):
                if msg.date < since:
                    break
                msgs.append(msg)
        else:
            async for msg in self.client.iter_messages(pid, min_id=last_id, limit=3000):
                msgs.append(msg)
        new: list[dict] = []
        max_id = last_id or 0
        for msg in reversed(msgs):  # eskisidan yangisiga
            max_id = max(max_id, msg.id)
            item = await self.handle(msg, pid)
            if item:
                new.append(item)
        if first and not msgs:  # 15 kunda post bo'lmagan kanal: oxirgi ID ni eslab qolamiz
            async for msg in self.client.iter_messages(pid, limit=1):
                max_id = msg.id
        self.store.set_channel(pid, self.title(pid), max_id)
        log.info("%s %s — %d post, %d yangi vakansiya",
                 "🆕 15 kunlik skan:" if first else "Skan:", self.title(pid), len(msgs), len(new))
        return new, first

    async def _scan_safe(self, pid: int) -> tuple[list[dict], bool]:
        for _ in range(2):
            try:
                return await self.scan_channel(pid)
            except FloodWaitError as e:
                log.warning("FloodWait %ss (%s)", e.seconds, self.title(pid))
                await asyncio.sleep(e.seconds + 1)
            except Exception as e:
                log.warning("Kanalni o'qib bo'lmadi %s: %s", self.title(pid), e)
                return [], False
        return [], False

    async def scan_all(self) -> int:
        """Barcha kanallarni tekshiradi. Yangi vakansiyalar sonini qaytaradi."""
        async with self.lock:
            self.stats = defaultdict(Counter)
            fresh: list[dict] = []
            first_scanned: list[int] = []
            for pid in list(self.peers):
                new, first = await self._scan_safe(pid)
                if first:
                    first_scanned.append(pid)
                else:
                    fresh += new
            self.last_scan = datetime.now()
            if fresh:
                await self.notify_new(fresh)
            if first_scanned:
                await self.send(self.report(first_scanned, self.backfill_days), force=True)
            total = sum(self.stats[p]["mos"] for p in first_scanned) + len(fresh)
            log.info("Skan tugadi: %d ta yangi vakansiya", total)
            return total

    async def refresh_channels(self) -> None:
        """Obunalarni qayta ko'rib chiqadi; yangi kanal bo'lsa — darhol 15 kunlik skan."""
        async with self.lock:
            try:
                peers = await self.compute_peers(strict=False)
            except Exception as e:
                log.warning("Kanallar ro'yxatini yangilab bo'lmadi: %s", e)
                return
            added = [p for p in peers if p not in self.peers]
            removed = [p for p in self.peers if p not in peers]
            self.peers = peers
            if self.bot:
                self.bot.channels_count = len(peers)
            for p in removed:
                log.info("➖ Kanal kuzatuvdan chiqdi: %s", self.title(p))
            for p in added:
                log.info("➕ Yangi kanal: %s", self.title(p))
                self.stats = defaultdict(Counter)
                new, first = await self._scan_safe(p)
                e = html.escape
                if first:
                    await self.send(
                        f"➕ <b>Yangi kanal:</b> {e(self.title(p))}\n"
                        f"Oxirgi {self.backfill_days} kun tekshirildi — "
                        f"<b>{self.stats[p]['mos']}</b> ta mos vakansiya topildi "
                        f"({self.stats[p]['jami']} post, {self.stats[p]['dublikat']} dublikat).\n"
                        f"Menyudan ko'ring 👇", force=True)
                elif new:
                    await self.notify_new(new)

    def refresh_soon(self, delay: int = 10) -> None:
        """Kanalga qo'shilish/chiqish hodisasida bir necha soniyadan keyin tekshirish."""
        if self._pending_refresh and not self._pending_refresh.done():
            return

        async def later():
            await asyncio.sleep(delay)
            await self.refresh_channels()

        self._pending_refresh = asyncio.ensure_future(later())

    async def notify_new(self, items: list[dict]) -> None:
        if len(items) <= self.notify_max:
            for it in items:
                await self.send(it["html"], it["link"])
            return
        e = html.escape
        lines = [f"🆕 <b>{len(items)} ta yangi vakansiya</b>\n"]
        for it in items[:15]:
            lines.append(f"• <a href=\"{e(it['link'])}\">{e(it['title'])}</a> — {e(it['chat'])}")
        if len(items) > 15:
            lines.append(f"… va yana {len(items) - 15} ta")
        lines.append("\nBarchasi menyuda: 🆕 Bugungi / 📋 Hammasi 👇")
        await self.send("\n".join(lines))

    async def loop_every(self, minutes: int, fn) -> None:
        while True:
            await asyncio.sleep(minutes * 60)
            try:
                await fn()
            except Exception:
                log.exception("Rejali vazifada xato")

    # ---------------- bot uchun ---------------- #
    async def bot_scan(self) -> str:
        if self.lock.locked():
            return "⏳ Tekshiruv allaqachon ketmoqda, birozdan so'ng natija keladi."
        await self.refresh_channels()
        n = await self.scan_all()
        return (f"✅ Tekshiruv tugadi. Yangi vakansiyalar: <b>{n}</b>\n"
                f"Keyingi avtomatik tekshiruv {self.scan_interval} daqiqadan so'ng.")

    def bot_channels(self) -> str:
        e = html.escape
        counts = self.store.channel_counts()
        rows = sorted(self.peers, key=lambda p: -counts.get(p, 0))
        lines = [f"<b>📡 Kuzatilayotgan kanallar: {len(rows)}</b>",
                 "<i>saqlangan vakansiyalar soni</i>\n"]
        for p in rows:
            lines.append(f"{counts.get(p, 0):>3} · {e(self.title(p))}")
        if self.last_scan:
            lines.append(f"\nOxirgi tekshiruv: {self.last_scan.strftime('%d.%m %H:%M')}")
        text = "\n".join(lines)
        return text if len(text) < 4000 else text[:3900].rsplit("\n", 1)[0] + "\n…"

    def report(self, peers: list[int], days: int) -> str:
        e = html.escape
        rows = []
        for pid in peers:
            s = self.stats.get(pid, Counter())
            title = getattr(self.entities.get(pid), "title", str(pid))
            rows.append((s["mos"], s["jami"], s["dublikat"], title))
        rows.sort(key=lambda r: (-r[0], -r[1]))
        total = sum(r[0] for r in rows)
        lines = [f"<b>📊 Kanal reytingi — oxirgi {days} kun</b>",
                 f"Sizga mos vakansiyalar (dublikatsiz): <b>{total}</b>"]
        if self.bot:
            lines.append("Ularni pastdagi menyu tugmalari orqali ko'ring 👇")
        lines.append("\n<i>mos / jami post (dublikat)</i>")
        for mos, jami, dup, title in rows:
            mark = "🟢" if mos >= 3 else ("🟡" if mos else "🔴")
            lines.append(f"{mark} {mos} / {jami} ({dup})  {e(str(title))}")
        cats = self.stats.get(0, Counter())
        if cats:
            lines.append("\n<b>Yo'nalishlar bo'yicha:</b> " +
                         ", ".join(f"{k}: {v}" for k, v in cats.most_common()))
        lines.append("\n🔴 — sizga mos post bermagan kanallar. Ularni EXCLUDE_CHANNELS ga "
                     "qo'shish yoki obunadan chiqish mumkin.")
        text = "\n".join(lines)
        plain = text
        for tag in ("<b>", "</b>", "<i>", "</i>"):
            plain = plain.replace(tag, "")
        print("\n" + html.unescape(plain))
        return text

    # ---------------- ishga tushirish ---------------- #
    async def run(self, args):
        # PHONE bo'sh bo'lsa — Telethon terminalda so'rasin (None uzatilsa xato beradi).
        await self.client.start(
            phone=self.phone or (lambda: input("Telefon raqamingiz (+998...): ")))
        me = await self.client.get_me()
        log.info("Kirildi: %s (id=%s)", me.first_name, me.id)

        if args.list:
            await self.list_all()
            return

        if self.bot:
            extra = [int(x) for x in env_list("ALLOWED_USERS") if x.lstrip("-").isdigit()]
            await self.bot.start(owner_id=me.id, extra_allowed=extra)
            if not self.store.get_setting(f"started:{me.id}"):
                log.warning("👉 Telegramda @%s botini oching va /start bosing — "
                            "aks holda bot sizga yoza olmaydi.", self.bot.username)
        else:
            log.info("BOT_TOKEN yo'q — natijalar Saved Messages ga yuboriladi.")
        if self.ai:
            log.info("AI baholash yoqilgan (model=%s, min=%s)", self.ai.model, self.min_score)

        self.lock = asyncio.Lock()
        self.peers = await self.compute_peers(strict=True)
        log.info("Kuzatilmoqda %d ta kanal: %s", len(self.peers),
                 ", ".join(self.title(p) for p in self.peers))
        if self.bot:
            self.bot.channels_count = len(self.peers)
            self.bot.scan_callback = self.bot_scan
            self.bot.channels_callback = self.bot_channels

        await self.scan_all()
        if args.once:
            return

        # Kanalga qo'shilish / chiqish hodisasi -> darhol tekshirish
        @self.client.on(events.Raw(types.UpdateChannel))
        async def _on_channel_update(update):
            self.refresh_soon()

        if self.realtime:
            @self.client.on(events.NewMessage())
            async def _on_new(event):
                if event.chat_id not in self.peers:
                    return
                try:
                    item = await self.handle(event.message, event.chat_id)
                    if item:
                        await self.notify_new([item])
                except Exception:
                    log.exception("Postni qayta ishlashda xato")

        asyncio.ensure_future(self.loop_every(self.scan_interval, self.scan_all))
        asyncio.ensure_future(self.loop_every(self.check_interval, self.refresh_channels))
        log.info("👀 Ishlayapti: har %d daqiqada yangi postlar, har %d daqiqada yangi kanallar "
                 "tekshiriladi%s. To'xtatish: Ctrl+C", self.scan_interval, self.check_interval,
                 " (+ real vaqt)" if self.realtime else "")
        await self.client.run_until_disconnected()

    async def close(self):
        await self.client.disconnect()
        if self.bot:
            await self.bot.client.disconnect()


def main():
    p = argparse.ArgumentParser(description="Telegram IT-vakansiya filtri")
    p.add_argument("--list", action="store_true", help="kanallar va papkalarni ko'rsatish")
    p.add_argument("--days", type=int, default=0, metavar="KUN",
                   help="yangi kanallar uchun necha kun orqaga qarash (standart: BACKFILL_DAYS=15)")
    p.add_argument("--once", action="store_true", help="bir marta skanerlab chiqish")
    args = p.parse_args()
    app = App()
    if args.days:
        app.backfill_days = args.days
    loop = app.client.loop
    try:
        loop.run_until_complete(app.run(args))
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")
    finally:
        loop.run_until_complete(app.close())


if __name__ == "__main__":
    main()
