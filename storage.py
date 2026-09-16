"""SQLite: ko'rilgan postlar, dublikatlar, saralangan vakansiyalar va sozlamalar."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime

MOBILE_GROUP = ["Flutter", "iOS", "Android", "Mobile"]


class Storage:
    def __init__(self, path: str = "jobs.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen_msg (
                chat_id INTEGER, msg_id INTEGER, ts INTEGER,
                PRIMARY KEY (chat_id, msg_id));
            CREATE TABLE IF NOT EXISTS seen_hash (
                hash TEXT PRIMARY KEY, ts INTEGER, chat_id INTEGER,
                msg_id INTEGER, link TEXT, sent INTEGER);
            CREATE TABLE IF NOT EXISTS vacancies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE, posted INTEGER, chat_id INTEGER, chat_title TEXT,
                link TEXT, cats TEXT, levels TEXT, remote INTEGER, salary TEXT,
                title TEXT, company TEXT, score INTEGER, text TEXT, search TEXT);
            CREATE INDEX IF NOT EXISTS idx_vac_posted ON vacancies(posted);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS channels (
                chat_id INTEGER PRIMARY KEY, title TEXT, last_msg_id INTEGER,
                first_scan INTEGER, last_scan INTEGER);
            """
        )
        self.db.commit()

    # ---------- ko'rilgan postlar / dublikatlar ----------
    def msg_seen(self, chat_id: int, msg_id: int) -> bool:
        cur = self.db.execute(
            "SELECT 1 FROM seen_msg WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))
        return cur.fetchone() is not None

    def mark_msg(self, chat_id: int, msg_id: int) -> None:
        self.db.execute("INSERT OR IGNORE INTO seen_msg VALUES (?,?,?)",
                        (chat_id, msg_id, int(time.time())))
        self.db.commit()

    def get_hash(self, h: str) -> tuple[str, bool] | None:
        """Xesh oldin ko'rilgan bo'lsa: (birinchi post havolasi, yuborilganmi)."""
        row = self.db.execute("SELECT link, sent FROM seen_hash WHERE hash=?", (h,)).fetchone()
        return (row[0], bool(row[1])) if row else None

    def mark_hash(self, h: str, chat_id: int, msg_id: int, link: str, sent: bool) -> None:
        self.db.execute("INSERT OR IGNORE INTO seen_hash VALUES (?,?,?,?,?,?)",
                        (h, int(time.time()), chat_id, msg_id, link, int(sent)))
        self.db.commit()

    # ---------- vakansiyalar ----------
    def add_vacancy(self, *, hash: str, posted: int, chat_id: int, chat_title: str,
                    link: str, cats: list[str], levels: list[str] | str, remote: bool,
                    salary: str | None, title: str | None, company: str | None,
                    score: int | None, text: str) -> None:
        if isinstance(levels, list):
            levels = ", ".join(levels)
        self.db.execute(
            """INSERT OR IGNORE INTO vacancies
               (hash, posted, chat_id, chat_title, link, cats, levels, remote, salary,
                title, company, score, text, search)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (hash, posted, chat_id, chat_title, link, "," + ",".join(cats) + ",",
             levels or "", int(remote), salary, title, company, score, text,
             f"{title or ''} {company or ''} {text}".lower()),
        )
        self.db.commit()

    @staticmethod
    def _where(flt: str) -> tuple[str, list]:
        """flt: all | today | remote | cat:<Nomi> | q:<qidiruv matni>"""
        kind, _, arg = flt.partition(":")
        if kind == "cat":
            cats = MOBILE_GROUP if arg == "Mobile" else [arg]
            return ("(" + " OR ".join("cats LIKE ?" for _ in cats) + ")",
                    [f"%,{c},%" for c in cats])
        if kind == "today":
            midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            return "posted >= ?", [int(midnight.timestamp())]
        if kind == "remote":
            return "remote = 1", []
        if kind == "q":
            words = [w for w in arg.lower().split() if w]
            if not words:
                return "1=1", []
            return " AND ".join("search LIKE ?" for _ in words), [f"%{w}%" for w in words]
        return "1=1", []

    def query(self, flt: str, offset: int = 0, limit: int = 8) -> tuple[list[sqlite3.Row], int]:
        where, params = self._where(flt)
        total = self.db.execute(f"SELECT COUNT(*) FROM vacancies WHERE {where}", params).fetchone()[0]
        rows = self.db.execute(
            f"SELECT * FROM vacancies WHERE {where} ORDER BY posted DESC LIMIT ? OFFSET ?",
            params + [limit, offset]).fetchall()
        return rows, total

    def stats(self, days: int = 7) -> dict:
        since = int(time.time()) - days * 86400
        midnight = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        one = lambda sql, p=(): self.db.execute(sql, p).fetchone()[0]
        cats: dict[str, int] = {}
        for (c,) in self.db.execute("SELECT cats FROM vacancies WHERE posted >= ?", (since,)):
            for name in filter(None, c.split(",")):
                cats[name] = cats.get(name, 0) + 1
        top = self.db.execute(
            """SELECT chat_title, COUNT(*) n FROM vacancies WHERE posted >= ?
               GROUP BY chat_id ORDER BY n DESC LIMIT 5""", (since,)).fetchall()
        return {
            "total": one("SELECT COUNT(*) FROM vacancies"),
            "today": one("SELECT COUNT(*) FROM vacancies WHERE posted >= ?", (midnight,)),
            "week": one("SELECT COUNT(*) FROM vacancies WHERE posted >= ?", (since,)),
            "cats": dict(sorted(cats.items(), key=lambda x: -x[1])),
            "top": [(r[0], r[1]) for r in top],
        }

    # ---------- kanal holati ----------
    def channel_last_id(self, chat_id: int) -> int | None:
        """None — kanal hali skanerlanmagan (demak 15 kunlik skan kerak)."""
        row = self.db.execute("SELECT last_msg_id FROM channels WHERE chat_id=?",
                              (chat_id,)).fetchone()
        return None if row is None else int(row[0] or 0)

    def set_channel(self, chat_id: int, title: str, last_msg_id: int) -> None:
        now = int(time.time())
        self.db.execute(
            """INSERT INTO channels (chat_id, title, last_msg_id, first_scan, last_scan)
               VALUES (?,?,?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,
                 last_msg_id=MAX(channels.last_msg_id, excluded.last_msg_id),
                 last_scan=excluded.last_scan""",
            (chat_id, title, last_msg_id, now, now))
        self.db.commit()

    def channel_counts(self) -> dict[int, int]:
        return {r[0]: r[1] for r in self.db.execute(
            "SELECT chat_id, COUNT(*) FROM vacancies GROUP BY chat_id")}

    # ---------- sozlamalar ----------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
        self.db.commit()
