"""Telegram kanallarini LOGINSIZ o'qish — t.me/s/<kanal> ochiq sahifasi orqali.

Telethon userbot o'rniga ishlatiladi: akkauntga kirish, .session fayli va
api_id/api_hash kerak emas. Faqat ochiq (preview yoqilgan) kanallar o'qiladi.

Chiqadigan `WebPost` Telethon Message ning kerakli maydonlarini takrorlaydi
(`id`, `message`, `date`), shuning uchun main.py dagi qayta ishlash mantig'i
o'zgarishsiz ishlayveradi.

    posts = await iter_posts("dartuz_jobs", since=...)   # 15 kunlik backfill
    posts = await iter_posts("dartuz_jobs", min_id=257)  # faqat yangilari
"""
from __future__ import annotations

import asyncio
import html as html_mod
import logging
import re
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("tme_web")

BASE = "https://t.me/s"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

REQUEST_TIMEOUT = 30
MIN_INTERVAL = 1.5    # so'rovlar orasidagi eng kichik tanaffus (t.me ni charchatmaslik)
MAX_PAGES = 60        # bitta kanal uchun varaqlash chegarasi (~1200 post)

_throttle = asyncio.Lock()
_last_request = 0.0


class ChannelUnavailable(Exception):
    """Kanal topilmadi yoki ochiq preview'i yo'q."""


@dataclass
class WebPost:
    """Telethon Message o'rnini bosuvchi minimal post."""
    id: int
    message: str
    date: datetime


@dataclass
class ParsedPage:
    title: str
    posts: list[WebPost] = field(default_factory=list)
    next_before: int | None = None   # keyingi (eskiroq) sahifa kursori


# --------------------------------------------------------------------------- #
# Nom va havolalar
# --------------------------------------------------------------------------- #
def normalize(channel: str) -> str:
    """'https://t.me/s/kanal/', '@kanal', 'kanal' -> 'kanal'."""
    s = channel.strip()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^t\.me/", "", s)
    s = re.sub(r"^s/", "", s)
    return s.lstrip("@").strip("/").split("/")[0]


def post_link(channel: str, msg_id: int) -> str:
    return f"https://t.me/{normalize(channel)}/{msg_id}"


def chat_id_for(channel: str) -> int:
    """Kanal uchun barqaror manfiy ID.

    Haqiqiy Telegram chat_id sini loginsiz bilib bo'lmaydi, lekin storage.py ga
    bazada kalit sifatida ishlatish uchun barqaror son kerak. Username hech
    qachon o'zgarmasa, ID ham o'zgarmaydi — demak dublikat va "oxirgi ko'rilgan
    post" holati saqlanadi.
    """
    return -(zlib.crc32(normalize(channel).lower().encode()) & 0x7FFFFFFF)


# --------------------------------------------------------------------------- #
# HTML tahlili
# --------------------------------------------------------------------------- #
_WRAP_RE = re.compile(r'<div class="tgme_widget_message_wrap\b', re.S)
_POST_ID_RE = re.compile(r'data-post="[^"/]+/(\d+)"')
_TIME_RE = re.compile(r'<time datetime="([^"]+)"')
_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_BEFORE_RE = re.compile(r'data-before="(\d+)"')
_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]*)"')


def _clean(fragment: str) -> str:
    """Post HTML ini sof matnga aylantiradi: <br> -> qator, teglar olib tashlanadi."""
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"</?(?:p|div)\b[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)          # a, b, i, span, tg-emoji ...
    t = html_mod.unescape(t)
    t = t.replace("​", "").replace("\r", "")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _split_wraps(html: str) -> list[str]:
    starts = [m.start() for m in _WRAP_RE.finditer(html)]
    return [html[a:b] for a, b in zip(starts, starts[1:] + [len(html)])]


def parse_page(html: str, channel: str) -> ParsedPage:
    """Bitta t.me/s/ sahifasini tahlil qiladi. Postlar eskisidan yangisiga."""
    title_m = _TITLE_RE.search(html)
    page = ParsedPage(title=html_mod.unescape(title_m.group(1)) if title_m else normalize(channel))

    for wrap in _split_wraps(html):
        pid = _POST_ID_RE.search(wrap)
        when = _TIME_RE.search(wrap)
        if not pid or not when:
            continue                      # xizmat bloklari (reklama, "more" tugmasi)
        text_m = _TEXT_RE.search(wrap)
        try:
            date = datetime.fromisoformat(when.group(1)).astimezone(timezone.utc)
        except ValueError:
            continue
        page.posts.append(WebPost(
            id=int(pid.group(1)),
            message=_clean(text_m.group(1)) if text_m else "",
            date=date,
        ))

    page.posts.sort(key=lambda p: p.id)
    before = _BEFORE_RE.search(html)
    page.next_before = int(before.group(1)) if before else None
    return page


# --------------------------------------------------------------------------- #
# Tarmoq
# --------------------------------------------------------------------------- #
def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "en,ru;q=0.9,uz;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


async def fetch_page(channel: str, before: int | None = None) -> ParsedPage:
    """Sahifani yuklab, tahlil qilib qaytaradi. So'rovlar sekinlashtiriladi."""
    global _last_request
    ch = normalize(channel)
    url = f"{BASE}/{ch}" + (f"?before={before}" if before else "")

    async with _throttle:
        pause = MIN_INTERVAL - (asyncio.get_event_loop().time() - _last_request)
        if pause > 0:
            await asyncio.sleep(pause)
        try:
            html = await asyncio.to_thread(_get, url)
        except urllib.error.HTTPError as e:
            raise ChannelUnavailable(f"{ch}: HTTP {e.code}") from e
        except Exception as e:
            raise ChannelUnavailable(f"{ch}: {e}") from e
        finally:
            _last_request = asyncio.get_event_loop().time()

    return parse_page(html, ch)


async def iter_posts(channel: str, *, min_id: int | None = None,
                     since: datetime | None = None,
                     max_pages: int = MAX_PAGES) -> tuple[str, list[WebPost]]:
    """Kanal postlarini yig'adi (eskisidan yangisiga).

    min_id — shu ID dan keyingi postlar (odatdagi soatlik tekshiruv).
    since  — shu sanadan keyingi postlar (birinchi marta, 15 kunlik backfill).
    Ikkalasi ham berilmasa — faqat birinchi sahifa (oxirgi ~20 post).
    """
    ch = normalize(channel)
    first = await fetch_page(ch)
    title, collected = first.title, list(first.posts)
    before = first.next_before

    def yetarli() -> bool:
        if not collected:
            return True
        oldest = collected[0]
        if min_id is not None and oldest.id <= min_id:
            return True
        if since is not None and oldest.date < since:
            return True
        return min_id is None and since is None   # chegara yo'q -> bitta sahifa

    pages = 1
    while not yetarli() and before and pages < max_pages:
        try:
            page = await fetch_page(ch, before=before)
        except ChannelUnavailable as e:
            log.warning("Varaqlash to'xtadi (%s)", e)
            break
        if not page.posts:
            break
        collected = page.posts + collected
        before, pages = page.next_before, pages + 1

    if min_id is not None:
        collected = [p for p in collected if p.id > min_id]
    if since is not None:
        collected = [p for p in collected if p.date >= since]
    if pages >= max_pages:
        log.warning("%s: %d sahifa chegarasiga yetildi, eskiroq postlar o'tkazib yuborildi",
                    ch, max_pages)
    return title, collected


async def probe(channel: str) -> tuple[bool, str, int]:
    """Kanal loginsiz o'qiladimi? -> (ochiqmi, nomi, sahifadagi post soni)."""
    try:
        page = await fetch_page(channel)
    except ChannelUnavailable as e:
        return False, str(e), 0
    return bool(page.posts), page.title, len(page.posts)
