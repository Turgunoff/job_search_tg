"""Telegram IT-vakansiya filtri (loginsiz o'qish + menyuli bot).

Kanallar t.me/s/<kanal> ochiq sahifasi orqali o'qiladi — akkauntga kirish,
.session fayli va userbot kerak emas. Faqat ochiq (preview yoqilgan) kanallar.
Natijalar sizning botingizga tushadi (bot tokeni uchun login talab qilinmaydi).

Ishlash tartibi:
  • Yangi (hali ko'rilmagan) kanal  -> oxirgi BACKFILL_DAYS (15) kun skanerlanadi.
  • Har SCAN_INTERVAL_MIN (60) daqiqada -> har kanalda faqat oxirgi skandan keyingi postlar.
  • .env dagi CHANNELS ro'yxatiga kanal qo'shsangiz -> CHANNEL_CHECK_MIN daqiqada
    aniqlanadi va shu kanal uchun 15 kunlik skan qilinadi (qayta ishga tushirish shart emas).
  • Bir xil vakansiya faqat bir marta saqlanadi.

Foydalanish:
  python main.py --list      # sozlangan kanallarni tekshirish (ochiq/yopiq)
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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

import tme_web
from filters import JobFilter, fingerprint, guess_title
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


@dataclass
class Channel:
    """Kuzatiladigan kanal.

    Telethon entity o'rnini bosadi — `link()`, `format_post()` va `report()`
    undan faqat `.id`, `.username`, `.title` ni oladi.
    """
    id: int          # tme_web.chat_id_for() bergan barqaror manfiy ID
    username: str    # t.me dagi nomi, masalan "dartuz_jobs"
    title: str       # ko'rinadigan nomi, masalan "Jobs Dart | Flutter"


# --------------------------------------------------------------------------- #
class App:
    def __init__(self):
        api_id = os.getenv("API_ID")
        api_hash = os.getenv("API_HASH")
        if not api_id or not api_hash:
            sys.exit("❌ .env faylida API_ID va API_HASH yo'q. README ni qarang.")
        self.api_id, self.api_hash = int(api_id), api_hash
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
        if os.getenv("AI_API_KEY"):
            from ai import AIScorer
            self.ai = AIScorer(
                endpoint=os.getenv("AI_ENDPOINT", ""),
                api_key=os.getenv("AI_API_KEY"),
                model=os.getenv("AI_MODEL", ""),
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
        self.notify_max = int(os.getenv("NOTIFY_MAX", "5"))
        self.owner_id = int(os.getenv("OWNER_ID", "0") or 0)
        self.peers: list[int] = []
        self.lock: asyncio.Lock | None = None
        self.last_scan: datetime | None = None
        self.entities: dict[int, Channel] = {}
        self.stats: dict[int, Counter] = defaultdict(Counter)

    # ---------------- kanallarni aniqlash ---------------- #
    @staticmethod
    def wanted() -> list[str]:
        """.env dagi CHANNELS dan kuzatiladigan kanal nomlari (EXCLUDE_CHANNELS chegirilgan)."""
        skip = {tme_web.normalize(c).lower() for c in env_list("EXCLUDE_CHANNELS")}
        names: list[str] = []
        for raw in env_list("CHANNELS"):
            name = tme_web.normalize(raw)
            if name and name.lower() not in skip and name not in names:
                names.append(name)
        return names

    async def compute_peers(self, strict: bool = True) -> list[int]:
        """Kanal ro'yxatini o'qiydi va har birining ochiqligini tekshiradi."""
        names = self.wanted()
        if not names and strict:
            sys.exit("❌ .env da CHANNELS bo'sh. Kuzatiladigan kanallarni vergul bilan "
                     "yozing, masalan: CHANNELS=@dartuz_jobs,@progjob")
        ok: list[int] = []
        for name in names:
            pid = tme_web.chat_id_for(name)
            if pid in self.entities:          # oldin tekshirilgan — qayta so'ramaymiz
                ok.append(pid)
                continue
            opened, title, _ = await tme_web.probe(name)
            if not opened:
                log.warning("Kanal o'qilmadi (yopiq yoki mavjud emas): @%s — %s", name, title)
                continue
            self.entities[pid] = Channel(id=pid, username=name, title=title)
            ok.append(pid)
        if not ok and strict:
            sys.exit("❌ Birorta kanal o'qilmadi. `python main.py --list` bilan tekshiring.")
        return ok

    async def list_all(self):
        """Sozlangan kanallarni tekshirib, ochiq/yopiqligini ko'rsatadi."""
        names = self.wanted()
        if not names:
            print("\n❌ .env da CHANNELS bo'sh.\n"
                  "   Masalan: CHANNELS=@dartuz_jobs,@progjob,@uzdev_jobs")
            return
        print(f"\n📢 SOZLANGAN KANALLAR: {len(names)} ta  "
              f"(✅ = o'qiladi, ❌ = loginsiz o'qib bo'lmaydi)\n")
        ochiq = 0
        for name in names:
            opened, title, count = await tme_web.probe(name)
            if opened:
                ochiq += 1
                print(f"  ✅ @{name:<28} {count:>2} post   {title}")
            else:
                print(f"  ❌ @{name:<28}          {title}")
        print(f"\n{ochiq} / {len(names)} kanal o'qiladi.")
        if ochiq < len(names):
            print("❌ belgililarda kanal egasi ochiq ko'rinishni (preview) o'chirgan — "
                  "ularni loginsiz o'qib bo'lmaydi. EXCLUDE_CHANNELS ga qo'shsangiz, "
                  "har safar tekshirilmaydi.")

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
        """Texnik xabar — faqat botning egasiga (hisobot, yangi kanal)."""
        if not self.bot:
            log.info("BOT_TOKEN yo'q, xabar yuborilmadi (natijalar bazada saqlangan).")
            return
        await self.bot.send_to_owner(text_html, link, force=force)

    async def broadcast(self, text_html: str, link: str | None = None):
        """Yangi vakansiya — barcha obunachilarga."""
        if not self.bot:
            log.info("BOT_TOKEN yo'q, tarqatilmadi (natijalar bazada saqlangan).")
            return
        await self.bot.broadcast(text_html, link)

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
        chat = self.entities[chat_id]
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
        chat = self.entities[pid]
        last_id = self.store.channel_last_id(pid)
        first = last_id is None
        if first:
            since = datetime.now(timezone.utc) - timedelta(days=self.backfill_days)
            title, msgs = await tme_web.iter_posts(chat.username, since=since)
        else:
            title, msgs = await tme_web.iter_posts(chat.username, min_id=last_id)
        if title and title != chat.title:      # kanal nomini yangilab turamiz
            chat.title = title
        new: list[dict] = []
        max_id = last_id or 0
        for msg in msgs:  # tme_web eskisidan yangisiga qaytaradi
            max_id = max(max_id, msg.id)
            item = await self.handle(msg, pid)
            if item:
                new.append(item)
        if first and not msgs:  # 15 kunda post bo'lmagan kanal: oxirgi ID ni eslab qolamiz
            _, oxirgi = await tme_web.iter_posts(chat.username)
            if oxirgi:
                max_id = oxirgi[-1].id
        self.store.set_channel(pid, self.title(pid), max_id)
        log.info("%s %s — %d post, %d yangi vakansiya",
                 "🆕 15 kunlik skan:" if first else "Skan:", self.title(pid), len(msgs), len(new))
        return new, first

    async def _scan_safe(self, pid: int) -> tuple[list[dict], bool]:
        for urinish in range(2):
            try:
                return await self.scan_channel(pid)
            except tme_web.ChannelUnavailable as e:
                # Vaqtincha tarmoq muammosi bo'lishi mumkin — bir marta qayta urinamiz.
                if urinish == 0:
                    log.warning("Kanal javob bermadi (%s), qayta urinaman", e)
                    await asyncio.sleep(10)
                    continue
                log.warning("Kanal o'qilmadi: %s", e)
                return [], False
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
        """.env dagi CHANNELS ni qayta o'qiydi; yangi kanal bo'lsa — darhol 15 kunlik skan."""
        async with self.lock:
            try:
                load_dotenv(override=True)   # fayl qo'lda tahrirlangan bo'lishi mumkin
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

    async def notify_new(self, items: list[dict]) -> None:
        if len(items) <= self.notify_max:
            for it in items:
                await self.broadcast(it["html"], it["link"])
            return
        e = html.escape
        lines = [f"🆕 <b>{len(items)} ta yangi vakansiya</b>\n"]
        for it in items[:15]:
            lines.append(f"• <a href=\"{e(it['link'])}\">{e(it['title'])}</a> — {e(it['chat'])}")
        if len(items) > 15:
            lines.append(f"… va yana {len(items) - 15} ta")
        lines.append("\nBarchasi menyuda: 🆕 Bugungi / 📋 Hammasi 👇")
        await self.broadcast("\n".join(lines))

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
        lines.append("\n🔴 — sizga mos post bermagan kanallar. Ularni .env dagi CHANNELS "
                     "ro'yxatidan olib tashlash mumkin.")
        text = "\n".join(lines)
        plain = text
        for tag in ("<b>", "</b>", "<i>", "</i>"):
            plain = plain.replace(tag, "")
        print("\n" + html.unescape(plain))
        return text

    # ---------------- ishga tushirish ---------------- #
    async def run(self, args):
        if args.list:
            await self.list_all()
            return

        if self.bot:
            if not self.owner_id:
                sys.exit("❌ .env da OWNER_ID yo'q. Botdan kim foydalanishini bilish uchun "
                         "Telegram user ID ingizni yozing (@userinfobot ko'rsatadi).")
            await self.bot.start(owner_id=self.owner_id)
            if self.owner_id not in self.store.subscribers():
                log.warning("👉 Telegramda @%s botini oching va /start bosing — "
                            "aks holda bot sizga yoza olmaydi.", self.bot.username)
        else:
            log.info("BOT_TOKEN yo'q — natijalar faqat bazaga va CSV ga yoziladi.")
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

        asyncio.ensure_future(self.loop_every(self.scan_interval, self.scan_all))
        asyncio.ensure_future(self.loop_every(self.check_interval, self.refresh_channels))
        log.info("👀 Ishlayapti: har %d daqiqada yangi postlar, har %d daqiqada .env dagi "
                 "kanallar ro'yxati tekshiriladi. To'xtatish: Ctrl+C",
                 self.scan_interval, self.check_interval)
        if self.bot:
            await self.bot.client.run_until_disconnected()
        else:
            while True:                      # bot yo'q — shunchaki rejadagi vazifalarni kutamiz
                await asyncio.sleep(3600)

    async def close(self):
        if self.bot:
            await self.bot.client.disconnect()


def main():
    p = argparse.ArgumentParser(description="Telegram IT-vakansiya filtri (loginsiz)")
    p.add_argument("--list", action="store_true",
                   help="sozlangan kanallarni tekshirish (ochiq/yopiq)")
    p.add_argument("--days", type=int, default=0, metavar="KUN",
                   help="yangi kanallar uchun necha kun orqaga qarash (standart: BACKFILL_DAYS=15)")
    p.add_argument("--once", action="store_true", help="bir marta skanerlab chiqish")
    args = p.parse_args()
    app = App()
    if args.days:
        app.backfill_days = args.days
    try:
        asyncio.run(app.run(args))
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")


if __name__ == "__main__":
    main()
