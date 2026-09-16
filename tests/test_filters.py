import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from filters import JobFilter, fingerprint

F = JobFilter()

FLUTTER_UZ = """#vakansiya
Lavozim: Flutter dasturchi (Middle)
Kompaniya: Uzum
Talablar: Dart, Bloc, REST API
Maosh: 1500-2500$
Manzil: Toshkent, gibrid"""

BACKEND_RU = """🔥 Вакансия: Backend-разработчик (Laravel)
Требования: PHP 8, MySQL, Redis
Зарплата: от 12 млн сум
Формат: удалённо"""

IOS_EN = """We are hiring! Senior iOS Engineer
Requirements: Swift, SwiftUI, 5+ years
Salary: $4000"""

RESUME = """#rezyume
Flutter dasturchi, 2 yil tajriba, ish qidiryapman. Tel: +998..."""

RESUME_HEADER = """Резюме: Android разработчик Kotlin
Опыт 3 года, ищу интересные проекты, требования к зарплате 1000$"""

DESIGNER = """#vakansiya
UI/UX dizayner kerak. Figma bilan ishlash. Maosh kelishiladi. Toshkent shahri."""

NO_MARKER = """Flutter 3.24 chiqdi! Yangi imkoniyatlar haqida maqolamizda o'qing, havola pastda."""

def test_flutter_uz():
    m = F.match(FLUTTER_UZ)
    assert m and "Flutter" in m.categories
    assert "Middle" in m.levels and m.remote
    assert m.salary and "1500" in m.salary

def test_backend_ru():
    m = F.match(BACKEND_RU)
    assert m and "Backend" in m.categories and m.remote
    assert "12 млн" in m.salary

def test_ios_en():
    m = F.match(IOS_EN)
    assert m and "iOS" in m.categories and "Senior" in m.levels

def test_resume_excluded():
    assert F.match(RESUME) is None
    assert F.match(RESUME_HEADER) is None

def test_resume_word_in_body_ok():
    text = FLUTTER_UZ + "\nRezyumeni @hr_bot ga yuboring"
    assert F.match(text) is not None

def test_irrelevant():
    assert F.match(DESIGNER) is None
    assert F.match(NO_MARKER) is None

def test_exclude_levels():
    f = JobFilter(exclude_levels=["Senior", "Lead"])
    assert f.match(IOS_EN) is None
    assert f.match(FLUTTER_UZ) is not None

def test_extra_keywords():
    f = JobFilter(include_extra=["1C"], exclude_extra=["Uzum"])
    assert f.match(FLUTTER_UZ) is None
    assert f.match("#vakansiya 1C dasturchi kerak, maosh yaxshi, Toshkent shahri ofis") is not None

def test_fullstack_and_go():
    m = F.match("Ищем Fullstack разработчика (React + Go developer), зарплата по договоренности")
    assert m and {"Fullstack", "Backend"} <= set(m.categories)
    assert F.match("Вакансия: go to the office every day, менеджер по продажам, зарплата") is None

def test_fingerprint_dedup():
    a = FLUTTER_UZ + "\n\nKanal: @it_jobs_uz https://t.me/it_jobs_uz #ishbor"
    b = FLUTTER_UZ + "\n@boshqa_kanal #vakansiya_uz"
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint(BACKEND_RU)
