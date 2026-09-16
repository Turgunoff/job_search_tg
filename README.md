# Telegram IT-vakansiya filtri + menyuli bot

Ochiq IT kanallarni siz o'rningizga o'qiydi, faqat sizga mos vakansiyalarni
(**Flutter, native iOS/Android, Backend, Fullstack**) ajratadi va **o'z botingizga
yig'adi**. Botdagi menyudan yo'nalishni tanlasangiz, vakansiyalar ro'yxati
kanaldagi post havolasi (URL) bilan chiqadi.

```
t.me/s/<kanal> ochiq sahifalari          Sizning botingiz
  HTTP orqali o'qiladi  ──► filtr ──► baza ──► 💙 Flutter  🍏 iOS  🤖 Android
   (login kerak emas)     dublikat            ⚙️ Backend  🧩 Fullstack  📱 Barcha mobile
                          AI (ixt.)           🆕 Bugungi  🌍 Remote  📋 Hammasi
                                              📌 Mening  🔔 Sozlamalar
                                              + qidiruv va obunalar
```

**Akkauntga kirish talab qilinmaydi.** Kanallar Telegram'ning ochiq
`t.me/s/<kanal>` sahifasi orqali o'qiladi — telefon raqam, tasdiqlash kodi va
`.session` fayli kerak emas, akkauntingiz xavf ostida qolmaydi.

**Imkoniyatlari:**
- Rezyumelar va boshqa kasb vakansiyalarini tashlab yuboradi.
- **Dublikatlarni olib tashlaydi.** Bitta vakansiya 5 ta kanalda chiqsa ham, bir marta saqlanadi.
- Yo'nalish, daraja, remote va maoshni ajratadi.
- Botda sahifalash (◀️ ▶️) va so'z bo'yicha qidiruv bor, masalan `laravel remote`.
- **Belgilar:** ro'yxat tagidagi raqam tugmalari bilan vakansiyani 🙈 yashirasiz
  (odam olingan, mos kelmadi), ⭐ saqlaysiz yoki ✅ ariza berganingizni
  belgilaysiz. Hammasi **📌 Mening** bo'limida to'planadi, belgilar har
  foydalanuvchiga alohida.
- **Shaxsiy bildirishnoma:** **🔔 Sozlamalar** dan qaysi yo'nalishlar bo'yicha
  xabar kelishini tanlaysiz — keraksizi umuman kelmaydi. Faqat remote va
  minimal AI ball chegarasini ham qo'yish mumkin.
- **Qidiruv obunasi:** so'zni qidirib, natija ostidagi «🔔 Obuna» ni bossangiz —
  o'sha so'zga mos yangi vakansiya chiqishi bilan xabar keladi.
- **📦 Arxiv:** ro'yxatlar oxirgi 30 kunni ko'rsatadi (`LIST_DAYS`), eskisi
  arxivda qoladi — ro'yxat allaqachon yopilgan vakansiyalar bilan to'lib
  ketmaydi.
- Har soatda yangi postlarni tekshiradi.
- `.env` ga yangi kanal qo'shsangiz, 15 daqiqada o'zi ilg'aydi va uning 15 kunini ko'rib chiqadi — qayta ishga tushirish shart emas.
- **Kanalni botdan turib boshqarish:** admin `+@kanal_nomi` deb yozsa kanal
  qo'shiladi (avval o'qilishi tekshiriladi), `-@kanal_nomi` — chiqariladi.
- Yangi vakansiya bo'lsa, bot xabar beradi. 🔔 tugmasi bilan o'chirib qo'ysa bo'ladi.
- Bot hammaga ochiq: kim `/start` bossa vakansiyalarni ko'radi va xabar oladi. 🔔 sozlamasi har foydalanuvchiga alohida.
- Topilgan hamma vakansiyalar `vakansiyalar.csv` fayliga ham yoziladi.

> **Cheklov:** faqat **ochiq** kanallar o'qiladi. Kanal egasi ochiq ko'rinishni
> (preview) o'chirgan bo'lsa, u kanal loginsiz o'qilmaydi. Tekshirish oson:
> brauzerda `t.me/s/kanal_nomi` ochilsa — ishlaydi.

---

## 1-qadam. Telegram API kalitlari (2 daqiqa)

Bular **faqat bot uchun** kerak (Telethon bot tokeni bilan ulanadi).

1. https://my.telegram.org saytiga kiring. Tasdiqlash kodi Telegramga keladi.
2. **API development tools** → App title: `JobFilter`, Short name: `jobfilter`, Platform: `Desktop`.
3. Chiqqan **api_id** va **api_hash** ni saqlab qo'ying.

## 2-qadam. Bot tokeni va user ID

- Token: @BotFather → `/mybots` → botingiz → **API Token**
- Sizning user ID ingiz: @userinfobot ga yozing, u raqamni ko'rsatadi

> Bot hammaga ochiq — kim `/start` bossa foydalana oladi. `OWNER_ID` esa
> admin huquqlarini beradi: 🔄 qayta tekshirish, 📡 kanallar ro'yxati va
> texnik hisobotlar faqat sizga ko'rinadi.

> ❗ Agar bu bot hozir boshqa kodda ishlayotgan bo'lsa (n8n, boshqa server,
> webhook), ikkalasi bir-biriga xalaqit beradi. Bunday holda @BotFather'da
> `/newbot` bilan alohida bot oching.

## 3-qadam. O'rnatish

```bash
cd job_search_tg
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` da to'ldiring: `API_ID`, `API_HASH`, `BOT_TOKEN`, `OWNER_ID`, `CHANNELS`.

## 4-qadam. Kanallarni tekshirish

```bash
python main.py --list
```

```
📢 SOZLANGAN KANALLAR: 3 ta  (✅ = o'qiladi, ❌ = loginsiz o'qib bo'lmaydi)

  ✅ @dartuz_jobs                 20 post   Jobs Dart | Flutter 🇺🇿
  ✅ @progjob                     20 post   Работа для программистов
  ❌ @yopiq_kanal                           Yopiq kanal

2 / 3 kanal o'qiladi.
```

❌ belgililarni `EXCLUDE_CHANNELS` ga qo'shsangiz, har safar tekshirilmaydi.

## 5-qadam. Botni ochib /start bosing

Telegramda botingizni oching va **/start** bosing, pastda menyu paydo bo'ladi.
Bu qadam shart, chunki usiz bot sizga birinchi bo'lib yoza olmaydi.

## 6-qadam. Ishga tushirish

```bash
python main.py
```

| Vaziyat | Nima bo'ladi |
|---|---|
| **Birinchi ishga tushish** | Har bir kanalning oxirgi **15 kuni** tekshiriladi. Botga alohida xabar yog'dirilmaydi, faqat **kanal reytingi** keladi |
| **Har soatda** | Har kanalda faqat oxirgi tekshiruvdan keyingi **yangi** postlar ko'riladi |
| **`.env` ga kanal qo'shdingiz** | 15 daqiqada aniqlanadi va shu kanalning **15 kuni** tekshiriladi |
| **Dublikat** | Bir xil vakansiya boshqa kanalda yoki qayta chiqsa ham, **bir marta** saqlanadi |
| **Skript qayta ishga tushdi** | Qayerda to'xtaganini eslaydi (`jobs.db`) va o'sha joydan davom etadi |

Botdagi **🔄 Hozir tekshirish** tugmasi soatni kutmasdan tekshiradi.
**📡 Kanallar** tugmasi qaysi kanallar kuzatilayotganini ko'rsatadi.

Jadvalni `.env` da o'zgartirish mumkin: `BACKFILL_DAYS`, `SCAN_INTERVAL_MIN`, `CHANNEL_CHECK_MIN`.

### 24/7 ishlashi uchun

**Linux server (systemd):**
```bash
sudo cp deploy/jobfilter.service.example /etc/systemd/system/jobfilter.service
sudo systemctl daemon-reload && sudo systemctl enable --now jobfilter
journalctl -u jobfilter -f
```

**Mac (launchd):**
```bash
bash scripts/install_mac.sh
```
To'xtatish: `launchctl bootout gui/$(id -u)/uz.zettacode.jobfilter`
(Mac uxlab qolsa skript ham to'xtaydi — doimiy ishlashi kerak bo'lsa serverga qo'ying.)

---

## Botdan foydalanish

| Tugma | Nima ko'rsatadi |
|---|---|
| 💙 Flutter / 🍏 iOS / 🤖 Android | Shu yo'nalishdagi vakansiyalar, yangilari birinchi |
| 📱 Barcha mobile | Flutter + iOS + Android + boshqa mobile |
| ⚙️ Backend / 🧩 Fullstack | Laravel, Node.js, Python, Go, fullstack |
| 🆕 Bugungi | Bugun chiqqan vakansiyalar |
| 🌍 Remote | Masofaviy yoki gibrid ish |
| 📋 Hammasi | Hamma saqlangan vakansiyalar |
| 📊 Statistika | Bugun / 7 kun, yo'nalishlar, eng foydali kanallar |
| 🔄 Hozir tekshirish | *(faqat admin)* Soatni kutmasdan yangi postlarni tekshirish |
| 📡 Kanallar | *(faqat admin)* Kuzatilayotgan kanallar va saqlangan vakansiyalar soni |
| 🔔 Bildirishnoma | Yangi vakansiya xabarlarini yoqish/o'chirish |
| *istalgan so'z* | Qidiruv: `uzum`, `laravel remote`, `senior flutter` |

Ro'yxatdagi har bir vakansiya shunday ko'rinadi:
```
1. Flutter dasturchi (Middle)
Flutter · Middle · Remote
💰 Maosh: 1500-2500$
📢 IT Jobs UZ · 16.09 14:30
🔗 https://t.me/it_jobs_uz/4521
```

## Sozlamalar (`.env`)

| O'zgaruvchi | Nima qiladi |
|---|---|
| `CHANNELS` | Kuzatiladigan kanallar, vergul bilan. `@kanal`, `t.me/kanal`, `https://t.me/kanal` — hammasi bo'ladi |
| `EXCLUDE_CHANNELS` | Ro'yxatdan chiqariladigan kanallar |
| `INCLUDE_EXTRA` / `EXCLUDE_EXTRA` | Qo'shimcha / taqiqlangan kalit so'zlar |
| `EXCLUDE_LEVELS` | Masalan `Intern,Lead`. Postda faqat shu darajalar bo'lsa, u tashlab yuboriladi |
| `BOT_TOKEN` | Botingiz tokeni |
| `OWNER_ID` | Sizning Telegram user ID ingiz — admin huquqlari (🔄, 📡, hisobotlar) |
| `AI_ENDPOINT` / `AI_API_KEY` / `AI_MODEL` | AI baholashni yoqadi (ixtiyoriy) |
| `AI_MIN_SCORE`, `PROFILE` | AI uchun minimal ball va profilingiz tavsifi |

Kalit so'zlarning to'liq ro'yxati `filters.py` fayli boshida (`CATEGORIES`).

### AI bilan aqlli saralash (ixtiyoriy)

OpenAI-mos istalgan `chat/completions` endpoint ishlaydi — Azure AI Foundry,
OpenAI, OpenRouter va h.k. `.env` da `AI_ENDPOINT`, `AI_API_KEY`, `AI_MODEL` va
`PROFILE` ni to'ldiring. Shunda har bir vakansiya 0–10 ball bilan baholanadi va
botda ⭐ bilan ko'rinadi. Dublikatlar va rezyumelar AI'ga yuborilmaydi.
AI ishlamay qolsa, vakansiya kalit so'z bo'yicha baribir saqlanadi.

## Muammolar

| Belgi | Yechim |
|---|---|
| Bot javob bermayapti | Skript ishlab turganini tekshiring. Token boshqa joyda ishlatilmayotganiga ishonch hosil qiling |
| "Bot sizga yoza olmadi" logi | Botni oching va /start bosing |
| Kerakli kanal o'qilmayapti | `python main.py --list` — ❌ bo'lsa kanal yopiq, loginsiz o'qib bo'lmaydi |
| Kerakli vakansiya kelmadi | Postda "vakansiya/maosh/talablar" kabi so'z yo'q bo'lishi mumkin → `REQUIRE_VACANCY_MARKER=false` |
| Keraksiz vakansiyalar ko'p | `EXCLUDE_EXTRA` ga so'z qo'shing yoki AI'ni yoqing |
| Hammasini boshidan skanerlash (15 kun) | Skriptni to'xtating va `jobs.db` faylini o'chiring |

Testlar: `pip install pytest && pytest -q tests`

---

## Baza zaxirasi

`jobs.db` — yig'ilgan hamma vakansiya, foydalanuvchilar va ularning belgilari.
Fayl buzilsa yoki server yo'qolsa, hammasi ketadi. Kunlik zaxira uchun:

```bash
sudo apt install sqlite3          # bir marta
chmod +x scripts/backup.sh
crontab -e
# quyidagini qo'shing (har kuni soat 3:00 da):
0 3 * * * /home/azureuser/Projects/job_search_tg/scripts/backup.sh
```

Nusxalar `backups/` papkasiga `jobs-2026-09-16-0300.db.gz` ko'rinishida tushadi,
oxirgi 14 tasi saqlanadi (`BACKUP_KEEP`). Skript `sqlite3 .backup` dan
foydalanadi — bot ishlab turganda ham xavfsiz (oddiy `cp` yozuv o'rtasida
buzilgan fayl berishi mumkin).

Tiklash: `gunzip -c backups/jobs-....db.gz > jobs.db` va servisni qayta ishga
tushiring.

## Testlar

```bash
pip install pytest
python -m pytest tests/ -q
```

Har `git push` da GitHub Actions ham shu testlarni ishga tushiradi
(`.github/workflows/tests.yml`).

## Loyiha tuzilishi

| Fayl | Vazifasi |
|---|---|
| `tme_web.py` | `t.me/s/<kanal>` sahifasini o'qish va tahlil qilish (loginsiz) |
| `filters.py` | Kalit so'z filtri, yo'nalish/daraja/maosh ajratish, dublikat fingerprint |
| `storage.py` | SQLite: ko'rilgan postlar, vakansiyalar, kanal holati, sozlamalar |
| `ai.py` | Ixtiyoriy AI baholash (OpenAI-mos endpoint) |
| `bot.py` | Telegram bot menyusi, sahifalash, qidiruv |
| `main.py` | Hammasini bog'laydi: skan jadvali, xabarlar, hisobot |
| `scripts/backup.sh` | `jobs.db` ning kunlik zaxirasi (cron uchun) |
| `.github/workflows/tests.yml` | Har push da testlarni ishga tushiradi |

> Ilgari kanallar userbot (akkauntga kirish) orqali o'qilardi. U variant git
> tarixida saqlangan — `git log` dagi birinchi commit.
