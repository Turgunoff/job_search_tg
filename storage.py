"""SQLite: ko'rilgan postlar, dublikatlar, saralangan vakansiyalar va sozlamalar."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime

MOBILE_GROUP = ["Flutter", "iOS", "Android", "Mobile"]
# Foydalanuvchi vakansiyaga qo'yadigan belgilar (user_vacancy.mark)
MARKS = ("hidden", "saved", "applied")
# Bildirishnoma sozlamalarida tanlanadigan yo'nalishlar
PREF_CATS = ["Flutter", "iOS", "Android", "Mobile", "Backend", "Fullstack"]


class Storage:
    def __init__(self, path: str = "jobs.db", list_days: int = 30):
        """`list_days` — ro'yxatlar necha kunlik oynani ko'rsatadi (0 = cheksiz)."""
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.list_days = list_days
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
            CREATE TABLE IF NOT EXISTS user_vacancy (
                user_id INTEGER, vacancy_id INTEGER, mark TEXT, ts INTEGER,
                PRIMARY KEY (user_id, vacancy_id, mark));
            CREATE INDEX IF NOT EXISTS idx_uv_mark ON user_vacancy(user_id, mark, ts);
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, query TEXT, ts INTEGER);
            CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id);
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                joined INTEGER, last_seen INTEGER,
                notify INTEGER DEFAULT 1, active INTEGER DEFAULT 1);
            """
        )
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """Eski bazani yangi sxemaga moslaydi (har ishga tushishda xavfsiz)."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(users)")}
        for name, decl in (("cats", "TEXT DEFAULT ''"),          # bo'sh = hammasi
                           ("remote_only", "INTEGER DEFAULT 0"),
                           ("min_score", "INTEGER DEFAULT 0")):
            if name not in cols:
                self.db.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
        # 🙈 belgilarining eski uyi — user_vacancy ga ko'chiramiz
        old = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hidden'").fetchone()
        if old:
            self.db.execute(
                "INSERT OR IGNORE INTO user_vacancy (user_id, vacancy_id, mark, ts) "
                "SELECT user_id, vacancy_id, 'hidden', ts FROM hidden")
            self.db.execute("DROP TABLE hidden")

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

    def purge(self, days: int = 60) -> int:
        """Eski xizmat yozuvlarini o'chiradi. Vakansiyalarga tegilmaydi.

        `channels.last_msg_id` eski postlarni qayta o'qishdan saqlaydi, shuning
        uchun bu yozuvlar keraksiz — faqat baza hajmini o'stiradi.
        """
        cutoff = int(time.time()) - days * 86400
        n = 0
        for table in ("seen_msg", "seen_hash"):
            n += self.db.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,)).rowcount
        self.db.commit()
        return n

    # ---------- vakansiyalar ----------
    def add_vacancy(self, *, hash: str, posted: int, chat_id: int, chat_title: str,
                    link: str, cats: list[str], levels: list[str] | str, remote: bool,
                    salary: str | None, title: str | None, company: str | None,
                    score: int | None, text: str) -> int:
        """Vakansiyani saqlaydi va uning id sini qaytaradi (dublikatda — mavjudi)."""
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
        return self.db.execute("SELECT id FROM vacancies WHERE hash=?", (hash,)).fetchone()[0]

    def _where(self, flt: str) -> tuple[str, list]:
        """flt: all | today | remote | arxiv | cat:<Nomi> | q:<qidiruv matni>

        Ro'yxatlar oxirgi `list_days` kunni ko'rsatadi. Qidiruv va 📦 Arxiv —
        istisno: ular ataylab eski vakansiyalarga ham qaraydi.
        """
        kind, _, arg = flt.partition(":")
        cutoff = int(time.time()) - self.list_days * 86400
        parts: list[str] = []
        params: list = []
        if kind == "cat":
            cats = MOBILE_GROUP if arg == "Mobile" else [arg]
            parts.append("(" + " OR ".join("cats LIKE ?" for _ in cats) + ")")
            params += [f"%,{c},%" for c in cats]
        elif kind == "today":
            midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            parts.append("posted >= ?")
            params.append(int(midnight.timestamp()))
        elif kind == "remote":
            parts.append("remote = 1")
        elif kind == "arxiv":
            if self.list_days:
                parts.append("posted < ?")
                params.append(cutoff)
            else:                                  # oyna yo'q -> arxiv ham bo'sh
                parts.append("0")
        elif kind == "q":
            words = [w for w in arg.lower().split() if w]
            parts += ["search LIKE ?" for _ in words]
            params += [f"%{w}%" for w in words]
        if self.list_days and kind not in ("q", "arxiv", "today"):
            parts.append("posted >= ?")
            params.append(cutoff)
        return " AND ".join(parts) or "1=1", params

    def query(self, flt: str, offset: int = 0, limit: int = 8,
              user_id: int | None = None) -> tuple[list[sqlite3.Row], int]:
        """Vakansiyalar sahifasi va umumiy soni.

        `user_id` berilsa, o'sha foydalanuvchi yashirganlari chiqmaydi.
        `flt` belgi nomi bo'lsa (hidden/saved/applied) — faqat o'sha belgililar,
        belgilangan vaqti bo'yicha.
        """
        if flt in MARKS:
            if user_id is None:
                return [], 0
            total = self.db.execute(
                "SELECT COUNT(*) FROM user_vacancy m JOIN vacancies v ON v.id=m.vacancy_id "
                "WHERE m.user_id=? AND m.mark=?", (user_id, flt)).fetchone()[0]
            rows = self.db.execute(
                "SELECT v.* FROM user_vacancy m JOIN vacancies v ON v.id=m.vacancy_id "
                "WHERE m.user_id=? AND m.mark=? ORDER BY m.ts DESC LIMIT ? OFFSET ?",
                (user_id, flt, limit, offset)).fetchall()
            return rows, total
        where, params = self._where(flt)
        if user_id is not None:
            where += (" AND id NOT IN (SELECT vacancy_id FROM user_vacancy "
                      "WHERE user_id=? AND mark='hidden')")
            params = params + [user_id]
        total = self.db.execute(f"SELECT COUNT(*) FROM vacancies WHERE {where}", params).fetchone()[0]
        rows = self.db.execute(
            f"SELECT * FROM vacancies WHERE {where} ORDER BY posted DESC LIMIT ? OFFSET ?",
            params + [limit, offset]).fetchall()
        return rows, total

    # ---------- foydalanuvchi belgilari (🙈 / ⭐ / ✅) ----------
    def vacancy(self, vacancy_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM vacancies WHERE id=?", (vacancy_id,)).fetchone()

    def mark(self, user_id: int, vacancy_id: int, mark: str) -> bool:
        """Belgi qo'yadi. Yangi qo'yilgan bo'lsa True.

        🙈 va ⭐ bir-biriga zid: biri qo'yilsa, ikkinchisi olib tashlanadi.
        ✅ mustaqil — ariza bergan vakansiyani keyin yashirsa ham bo'ladi.
        """
        if mark not in MARKS:
            raise ValueError(f"noma'lum belgi: {mark}")
        zid = {"hidden": "saved", "saved": "hidden"}.get(mark)
        if zid:
            self.db.execute("DELETE FROM user_vacancy WHERE user_id=? AND vacancy_id=? AND mark=?",
                            (user_id, vacancy_id, zid))
        cur = self.db.execute("INSERT OR IGNORE INTO user_vacancy VALUES (?,?,?,?)",
                              (user_id, vacancy_id, mark, int(time.time())))
        self.db.commit()
        return cur.rowcount > 0

    def unmark(self, user_id: int, vacancy_id: int, mark: str) -> bool:
        """Belgini olib tashlaydi. Haqiqatan turgan bo'lsa True."""
        cur = self.db.execute(
            "DELETE FROM user_vacancy WHERE user_id=? AND vacancy_id=? AND mark=?",
            (user_id, vacancy_id, mark))
        self.db.commit()
        return cur.rowcount > 0

    def marks_of(self, user_id: int, vacancy_ids: list[int]) -> dict[int, set[str]]:
        """Sahifadagi vakansiyalarning belgilari — ro'yxatda ⭐/✅ ko'rsatish uchun."""
        if not vacancy_ids:
            return {}
        holes = ",".join("?" * len(vacancy_ids))
        out: dict[int, set[str]] = {}
        for vid, mark in self.db.execute(
                f"SELECT vacancy_id, mark FROM user_vacancy "
                f"WHERE user_id=? AND vacancy_id IN ({holes})", [user_id] + vacancy_ids):
            out.setdefault(vid, set()).add(mark)
        return out

    def mark_counts(self, user_id: int) -> dict[str, int]:
        counts = {m: 0 for m in MARKS}
        for mark, n in self.db.execute(
                "SELECT mark, COUNT(*) FROM user_vacancy WHERE user_id=? GROUP BY mark",
                (user_id,)):
            counts[mark] = n
        return counts

    # ---------- statistika ----------
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

    def get_list(self, key: str) -> list[str]:
        """Vergul bilan saqlangan ro'yxat (bot orqali qo'shilgan kanallar kabi)."""
        return [x for x in (self.get_setting(key, "") or "").split(",") if x]

    def add_to_list(self, key: str, value: str) -> bool:
        items = self.get_list(key)
        if value in items:
            return False
        self.set_setting(key, ",".join(items + [value]))
        return True

    def remove_from_list(self, key: str, value: str) -> bool:
        items = self.get_list(key)
        if value not in items:
            return False
        self.set_setting(key, ",".join(x for x in items if x != value))
        return True

    # ---------- foydalanuvchilar ----------
    def add_user(self, user_id: int, username: str | None = None,
                 first_name: str | None = None) -> None:
        """Ro'yxatga oladi. Mavjud bo'lsa: ismni yangilaydi, qayta faollashtiradi.

        `joined`, `notify` va bildirishnoma sozlamalari ataylab saqlanadi —
        qayta /start bosgani foydalanuvchi tanlovini bekor qilmaydi.
        """
        now = int(time.time())
        self.db.execute(
            """INSERT INTO users (user_id, username, first_name, joined, last_seen,
                                  notify, active)
               VALUES (?,?,?,?,?,1,1)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username,
                 first_name=excluded.first_name,
                 last_seen=excluded.last_seen,
                 active=1""",
            (user_id, username, first_name, now, now))
        self.db.commit()

    def set_notify(self, user_id: int, on: bool) -> None:
        self.db.execute("UPDATE users SET notify=? WHERE user_id=?", (int(on), user_id))
        self.db.commit()

    def notify_on(self, user_id: int) -> bool:
        """Yozuv yo'q bo'lsa True — standart holat yoqilgan."""
        row = self.db.execute("SELECT notify FROM users WHERE user_id=?",
                              (user_id,)).fetchone()
        return True if row is None else bool(row[0])

    # ---------- bildirishnoma sozlamalari ----------
    def prefs(self, user_id: int) -> dict:
        """Foydalanuvchining bildirishnoma tanlovi (yozuv yo'q bo'lsa — standart)."""
        row = self.db.execute(
            "SELECT notify, cats, remote_only, min_score FROM users WHERE user_id=?",
            (user_id,)).fetchone()
        if row is None:
            return {"notify": True, "cats": [], "remote_only": False, "min_score": 0}
        return {
            "notify": bool(row["notify"]),
            "cats": [c for c in (row["cats"] or "").split(",") if c],
            "remote_only": bool(row["remote_only"]),
            "min_score": int(row["min_score"] or 0),
        }

    def toggle_cat(self, user_id: int, cat: str) -> list[str]:
        """Yo'nalishni yoqadi/o'chiradi va yangi ro'yxatni qaytaradi."""
        cats = self.prefs(user_id)["cats"]
        cats = [c for c in cats if c != cat] if cat in cats else cats + [cat]
        self.db.execute("UPDATE users SET cats=? WHERE user_id=?",
                        (",".join(cats), user_id))
        self.db.commit()
        return cats

    def set_pref(self, user_id: int, key: str, value: int) -> None:
        if key not in ("remote_only", "min_score"):
            raise ValueError(f"noma'lum sozlama: {key}")
        self.db.execute(f"UPDATE users SET {key}=? WHERE user_id=?", (int(value), user_id))
        self.db.commit()

    @staticmethod
    def _cats_match(want: list[str], have: list[str]) -> bool:
        """Bo'sh tanlov — hammasi mos. 'Mobile' butun mobil guruhni qamraydi."""
        if not want:
            return True
        kengaytirilgan = set()
        for c in want:
            kengaytirilgan.update(MOBILE_GROUP if c == "Mobile" else [c])
        return bool(kengaytirilgan & set(have))

    def recipients(self, cats: list[str], remote: bool, score: int | None) -> list[int]:
        """Shu vakansiya kimning sozlamalariga mos kelsa — o'shalar.

        Ball berilmagan bo'lsa (AI o'chirilgan) minimal ball filtri qo'llanmaydi:
        ma'lumot yo'qligi uchun vakansiyani tashlab yuborish noto'g'ri bo'lardi.
        """
        out = []
        for r in self.db.execute(
                "SELECT user_id, cats, remote_only, min_score FROM users "
                "WHERE active=1 AND notify=1 ORDER BY user_id"):
            want = [c for c in (r["cats"] or "").split(",") if c]
            if not self._cats_match(want, cats):
                continue
            if r["remote_only"] and not remote:
                continue
            if score is not None and score < int(r["min_score"] or 0):
                continue
            out.append(r["user_id"])
        return out

    def subscribers(self) -> list[int]:
        """Xabar yuboriladiganlar: bildirishnoma yoqilgan va botni bloklamaganlar."""
        return [r[0] for r in self.db.execute(
            "SELECT user_id FROM users WHERE active=1 AND notify=1 ORDER BY user_id")]

    def deactivate(self, user_id: int) -> None:
        """Botni bloklagan foydalanuvchi — boshqa urinmaymiz."""
        self.db.execute("UPDATE users SET active=0 WHERE user_id=?", (user_id,))
        self.db.commit()

    def user_count(self) -> tuple[int, int]:
        """(jami, obunachilar)"""
        one = lambda sql: self.db.execute(sql).fetchone()[0]
        return (one("SELECT COUNT(*) FROM users"),
                one("SELECT COUNT(*) FROM users WHERE active=1 AND notify=1"))

    # ---------- qidiruv obunalari ----------
    def add_alert(self, user_id: int, query: str) -> bool:
        """Obuna qo'shadi. Allaqachon bor bo'lsa False."""
        query = " ".join(query.lower().split())[:100]
        if not query or self.db.execute(
                "SELECT 1 FROM alerts WHERE user_id=? AND query=?",
                (user_id, query)).fetchone():
            return False
        self.db.execute("INSERT INTO alerts (user_id, query, ts) VALUES (?,?,?)",
                        (user_id, query, int(time.time())))
        self.db.commit()
        return True

    def alerts(self, user_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT id, query FROM alerts WHERE user_id=? ORDER BY id", (user_id,)).fetchall()

    def del_alert(self, user_id: int, alert_id: int) -> bool:
        cur = self.db.execute("DELETE FROM alerts WHERE id=? AND user_id=?",
                              (alert_id, user_id))
        self.db.commit()
        return cur.rowcount > 0

    def alert_matches(self, search: str) -> dict[int, list[str]]:
        """Shu vakansiyaga mos obunalar: {user_id: [qidiruv so'zlari, ...]}.

        Faqat faol va bildirishnomasi yoqilgan foydalanuvchilar olinadi.
        """
        search = search.lower()
        out: dict[int, list[str]] = {}
        for r in self.db.execute(
                "SELECT a.user_id, a.query FROM alerts a JOIN users u ON u.user_id=a.user_id "
                "WHERE u.active=1 AND u.notify=1"):
            if all(w in search for w in r["query"].split()):
                out.setdefault(r["user_id"], []).append(r["query"])
        return out
