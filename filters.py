"""Vakansiya filtri: kalit so'zlar, istisnolar, teglar.

Kalit so'zlarni shu fayldagi CATEGORIES ichida o'zgartiring yoki .env dagi
INCLUDE_EXTRA / EXCLUDE_EXTRA orqali qo'shing.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# --- Yo'nalishlar (regex, katta-kichik harf farqi yo'q) -----------------------
CATEGORIES: dict[str, list[str]] = {
    "Flutter": [r"\bflutter\b", r"\bdart\b", r"флаттер"],
    "iOS": [r"\bios\b", r"\bswift\b", r"swiftui", r"objective[- ]?c\b", r"\buikit\b"],
    "Android": [r"\bandroid\b", r"\bkotlin\b", r"jetpack\s+compose", r"андроид"],
    "Mobile": [r"\bmobile\b", r"мобильн", r"\bmobil\b", r"react\s*native", r"mobile\s+app"],
    "Backend": [
        r"\bback[- ]?end\b", r"бэкенд", r"бекенд", r"\blaravel\b", r"\bphp\b",
        r"\bnode\.?js\b", r"\bnest\.?js\b", r"\bpython\b", r"\bdjango\b",
        r"\bfastapi\b", r"\bgolang\b", r"\bgo[- ](?:developer|dasturchi|разработчик)",
    ],
    "Fullstack": [r"\bfull[- ]?stack\b", r"фул+стек", r"фул+-стек"],
}

# --- Post haqiqatan vakansiya ekanini bildiruvchi belgilar --------------------
VACANCY_MARKERS = [
    r"vakansiya", r"ваканси", r"#vacanc", r"\bhiring\b", r"we are looking",
    r"looking for", r"ищем", r"требует", r"требуются", r"talab qilinadi",
    r"xodim kerak", r"ishchi kerak", r"ishga taklif", r"ish o['‘’`]?rni",
    r"maosh", r"ish haqi", r"зарплат", r"оклад", r"\bsalary\b", r"lavozim",
    r"должност", r"talablar", r"требования", r"requirements", r"\bjob\b",
    r"\bkerak\b", r"\bвакансия\b", r"\bopen position",
]

# --- Umuman o'tkazib yuboriladigan postlar (rezyume, ish qidiruvchilar) --------
GLOBAL_EXCLUDE = [
    r"#rezyume", r"#резюме", r"#resume\b", r"#cv\b", r"#ishqidir", r"#соискател",
    r"ищу работу", r"ish qidiryapman", r"ish izlayapman", r"looking for a job",
    r"#ish_qidiruvchi", r"#ishqidiruvchi",
]
# Faqat postning boshida (sarlavhada) tekshiriladi, chunki vakansiya matnida
# "rezyumeni yuboring" kabi iboralar ko'p uchraydi.
HEADER_EXCLUDE = [r"rezyume", r"резюме", r"\bresume\b", r"ish qidir", r"\bcv\b"]
HEADER_LEN = 80

LEVELS = {
    "Intern": [r"\bintern", r"стажер", r"стажёр", r"amaliyot"],
    "Junior": [r"\bjunior\b", r"джун"],
    "Middle": [r"\bmiddle\b", r"мидл"],
    "Senior": [r"\bsenior\b", r"сеньор", r"синьор"],
    "Lead": [r"team\s*lead", r"tech\s*lead", r"тимлид", r"техлид", r"\blead\b"],
}
REMOTE = [r"\bremote\b", r"удал[её]н", r"masofa", r"\bonline\b", r"гибрид", r"hybrid", r"gibrid"]
SALARY_LINE = re.compile(r"(maosh|ish haqi|зарплат|оклад|salary|з/п|💰|💵)", re.I)


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in patterns]


@dataclass
class Match:
    categories: list[str]
    levels: list[str] = field(default_factory=list)
    remote: bool = False
    salary: str | None = None


class JobFilter:
    def __init__(self, include_extra: list[str] | None = None,
                 exclude_extra: list[str] | None = None,
                 require_marker: bool = True,
                 exclude_levels: list[str] | None = None):
        self.cats = {k: _compile(v) for k, v in CATEGORIES.items()}
        if include_extra:
            self.cats["Boshqa"] = [re.compile(re.escape(w), re.I) for w in include_extra]
        self.markers = _compile(VACANCY_MARKERS)
        self.global_ex = _compile(GLOBAL_EXCLUDE) + [
            re.compile(re.escape(w), re.I) for w in (exclude_extra or [])
        ]
        self.header_ex = _compile(HEADER_EXCLUDE)
        self.levels = {k: _compile(v) for k, v in LEVELS.items()}
        self.remote = _compile(REMOTE)
        self.require_marker = require_marker
        self.exclude_levels = {l.strip().lower() for l in (exclude_levels or []) if l.strip()}

    @staticmethod
    def _any(pats: list[re.Pattern], text: str) -> bool:
        return any(p.search(text) for p in pats)

    def match(self, text: str) -> Match | None:
        if not text or len(text) < 40:
            return None
        if self._any(self.global_ex, text):
            return None
        if self._any(self.header_ex, text[:HEADER_LEN]):
            return None
        cats = [name for name, pats in self.cats.items() if self._any(pats, text)]
        if not cats:
            return None
        if self.require_marker and not self._any(self.markers, text):
            return None
        levels = [name for name, pats in self.levels.items() if self._any(pats, text)]
        # Faqat istisno qilingan darajalar topilsa (masalan faqat Senior) — o'tkazamiz
        if levels and self.exclude_levels and all(l.lower() in self.exclude_levels for l in levels):
            return None
        return Match(
            categories=cats,
            levels=levels,
            remote=self._any(self.remote, text),
            salary=extract_salary(text),
        )


def extract_salary(text: str) -> str | None:
    for line in text.splitlines():
        if SALARY_LINE.search(line):
            line = re.sub(r"\s+", " ", line).strip(" -•:*")
            return line[:90] if line else None
    return None


def fingerprint(text: str) -> str:
    """Bir xil vakansiya turli kanallarda qayta joylansa ham bir xil xesh beradi.

    Kanal futerlari (havola, @username, #teg bor qatorlar) va qisqa qatorlar
    tashlanadi, qolgan dastlabki mazmunli qatorlardan xesh olinadi.
    """
    parts = []
    for line in text.lower().splitlines():
        if re.search(r"https?://|t\.me/|@\w+", line):
            continue
        line = re.sub(r"#\w+", " ", line)
        line = re.sub(r"[^\w]+", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) >= 12:
            parts.append(line)
        if len(parts) >= 8:
            break
    norm = " ".join(parts) or re.sub(r"\W+", " ", text.lower()).strip()
    return hashlib.sha1(norm[:500].encode()).hexdigest()


_LABEL = re.compile(
    r"^(vakansiya|вакансия|vacancy|lavozim|должность|position|позиция|kerak|требуется|"
    r"we are hiring|hiring|ищем)\s*[:\-–—!]*\s*", re.I)


def guess_title(text: str) -> str:
    """Postdan vakansiya nomini taxmin qiladi (birinchi mazmunli qator)."""
    for line in text.splitlines():
        line = re.sub(r"#\w+|https?://\S+|@\w+", " ", line)
        line = re.sub(r"[^\w\s()+/.,&'’\-–—:]", " ", line)  # emoji va belgilar
        line = re.sub(r"\s+", " ", line).strip(" -–—:*.,")
        line = _LABEL.sub("", line).strip(" -–—:*.,")
        if len(line) >= 4:
            return line[:70] + ("…" if len(line) > 70 else "")
    return "Vakansiya"


# Kanal nomi/username bo'yicha vakansiya kanalini avtomatik aniqlash
JOB_CHANNEL_HINT = re.compile(
    r"vakans|вакан|job|\bish\b|ishbor|ishga|ish\s?o['‘’`]?rn|\bwork|remote|"
    r"\brabot|\bработ|\bhr\b|hiring|career|karyera|kadr|кадр|freelanc|фриланс|"
    r"dasturchi|developer|programmist|программист|rezyume|резюме",
    re.I,
)


def looks_like_job_channel(title: str | None, username: str | None) -> bool:
    hay = f"{title or ''} {(username or '').replace('_', ' ')}"
    return bool(JOB_CHANNEL_HINT.search(hay))
