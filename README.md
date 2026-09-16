# Telegram IT-vakansiya filtri + menyuli bot

Obuna bo'lgan IT kanallaringizni siz o'rningizga o'qiydi, faqat sizga mos
vakansiyalarni (**Flutter, native iOS/Android, Backend, Fullstack**) ajratadi va
**o'z botingizga yig'adi**. Botdagi menyudan yo'nalishni tanlasangiz, vakansiyalar
ro'yxati kanaldagi post havolasi (URL) bilan chiqadi.

```
Sizning akkauntingiz (userbot)          Sizning botingiz
  kanallarni o'qiydi  ──► filtr ──► baza ──► 💙 Flutter  🍏 iOS  🤖 Android
                          dublikat          ⚙️ Backend  🧩 Fullstack  📱 Barcha mobile
                          AI (ixt.)         🆕 Bugungi  🌍 Remote  📋 Hammasi
                                            📊 Statistika  🔔 Bildirishnoma  + qidiruv
```

**Nima uchun ikki qism?** Telegram botlar boshqa odamlarning kanallarini o'qiy
olmaydi. Shuning uchun kanallarni sizning akkauntingiz orqali o'qiymiz
(Telethon userbot), natijani esa botingizga yuboramiz.

**Imkoniyatlari:**
- **Kanallarni qo'lda kiritish shart emas.** Obuna kanallaringiz ichidan vakansiya kanallarini nomi bo'yicha o'zi topadi. O'zingizning kanallaringiz hisobga olinmaydi.
- Rezyumelar va boshqa kasb vakansiyalarini tashlab yuboradi.
- **Dublikatlarni olib tashlaydi.** Bitta vakansiya 5 ta kanalda chiqsa ham, bir marta saqlanadi.
- Yo'nalish, daraja, remote va maoshni ajratadi.
- Botda sahifalash (◀️ ▶️) va so'z bo'yicha qidiruv bor, masalan `laravel remote`.
- Har soatda yangi postlarni tekshiradi, yangi kanalga qo'shilsangiz uning 15 kunini darhol ko'rib chiqadi.
- Yangi vakansiya bo'lsa, bot xabar beradi. 🔔 tugmasi bilan o'chirib qo'ysa bo'ladi.
- Bot faqat sizga javob beradi, begonalar "⛔ Bu shaxsiy bot" javobini oladi.
- Topilgan hamma vakansiyalar `vakansiyalar.csv` fayliga ham yoziladi.

---

## 1-qadam. Telegram API kalitlari (2 daqiqa)

1. https://my.telegram.org saytiga kiring. Tasdiqlash kodi Telegramga keladi.
2. **API development tools** → App title: `JobFilter`, Short name: `jobfilter`, Platform: `Desktop`.
3. Chiqqan **api_id** va **api_hash** ni saqlab qo'ying.

> ⚠️ `api_hash` va keyin paydo bo'ladigan `jobfilter.session` fayli akkauntingizga
> to'liq kirish huquqini beradi. Hech kimga bermang.

## 2-qadam. Bot tokeni

Sizda bot bor. Uning tokenini @BotFather → `/mybots` → botingiz → **API Token** orqali oling.

> ❗ Agar bu bot hozir boshqa kodda ishlayotgan bo'lsa (n8n, boshqa server, webhook),
> ikkalasi bir-biriga xalaqit beradi. Bunday holda @BotFather'da `/newbot` bilan
> alohida bot oching yoki shu funksiyani mavjud bot kodingizga qo'shish kerak bo'ladi.

## 3-qadam. O'rnatish (Mac)

```bash
cd ~/Projects/job_search_tg
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # (agar .env hali bo'lmasa)
open -e .env           # API_ID, API_HASH, BOT_TOKEN ni tekshiring
```

## 4-qadam. Kanallarni tekshirish

```bash
python main.py --list
```
Birinchi ishga tushirishda Telegram kod yuboradi, uni terminalga kiriting.
Ekranda kanallaringiz chiqadi:
```
  ✅ -1001234567890  kanal @it_jobs_uz           IT Jobs Uzbekistan    ← kuzatiladi
  ✅ -1009876543210  kanal @uzdev_vacancy        UzDev Vakansiya       ← kuzatiladi
     -1001111111111  kanal @kunuz                Kun.uz                ← yo'q
  👤 -1002222222222  kanal @ishbor_tashkentda    Ishbor Toshkent       ← o'zingizniki
```
- **Qaysidir kanal topilmadi:** `.env` da `CHANNELS=auto,@o'sha_kanal` deb yozing.
- **Keraksiz kanal tanlandi:** `EXCLUDE_CHANNELS=@kanal` ga qo'shing.
- **Hamma obunalarni kuzatish:** `CHANNELS=all` qo'ying. Vakansiya bo'lmagan postlarni filtr baribir tashlab yuboradi.

## 5-qadam. Botni ochib /start bosing

Telegramda botingizni oching va **/start** bosing, pastda menyu paydo bo'ladi.
Bu qadam shart, chunki usiz bot sizga birinchi bo'lib yoza olmaydi.

## 6-qadam. Ishga tushirish

```bash
python main.py
```
Ishlash tartibi:

| Vaziyat | Nima bo'ladi |
|---|---|
| **Birinchi ishga tushish** | Har bir kanalning oxirgi **15 kuni** tekshiriladi. Botga alohida xabar yog'dirilmaydi, faqat **kanal reytingi** keladi. Vakansiyalarni menyudan ko'rasiz |
| **Har soatda** | Har kanalda faqat oxirgi tekshiruvdan keyingi **yangi** postlar ko'riladi. Yangi vakansiya bo'lsa, bot xabar beradi |
| **Yangi kanalga qo'shildingiz** | Bir necha soniya ichida aniqlanadi (zaxira tekshiruv har 5 daqiqada) va shu kanalning **15 kuni** tekshiriladi. Bot "➕ Yangi kanal: … N ta vakansiya" deb yozadi |
| **Dublikat** | Bir xil vakansiya boshqa kanalda yoki qayta chiqsa ham, **bir marta** saqlanadi |
| **Skript qayta ishga tushdi** | Qayerda to'xtaganini eslaydi (`jobs.db`) va o'sha joydan davom etadi |

Botdagi **🔄 Hozir tekshirish** tugmasi soatni kutmasdan tekshiradi.
**📡 Kanallar** tugmasi qaysi kanallar kuzatilayotganini ko'rsatadi.

Jadvalni `.env` da o'zgartirish mumkin: `BACKFILL_DAYS`, `SCAN_INTERVAL_MIN`, `CHANNEL_CHECK_MIN`, `REALTIME`.

Mac yoqilganda o'zi ishga tushishi uchun:
```bash
bash scripts/install_mac.sh
```
To'xtatish: `launchctl bootout gui/$(id -u)/uz.zettacode.jobfilter`

> Mac uxlab qolsa skript ham to'xtaydi. 24/7 ishlashi kerak bo'lsa, papkani
> (`.session` fayllari bilan birga) VPS serverga ko'chirib, `systemd` yoki `pm2` bilan ishga tushiring.

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
| 🔄 Hozir tekshirish | Soatni kutmasdan yangi postlar va yangi kanallarni tekshirish |
| 📡 Kanallar | Kuzatilayotgan kanallar va har biridan saqlangan vakansiyalar soni |
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
| `CHANNELS` | bo'sh = avto · `all` = hammasi · `auto,@kanal` · `@k1,@k2` |
| `FOLDER` | Telegram papkasi nomi (ixtiyoriy) |
| `EXCLUDE_CHANNELS` | Kuzatilmaydigan kanallar |
| `INCLUDE_EXTRA` / `EXCLUDE_EXTRA` | Qo'shimcha / taqiqlangan kalit so'zlar |
| `EXCLUDE_LEVELS` | Masalan `Intern,Lead`. Postda faqat shu darajalar bo'lsa, u tashlab yuboriladi |
| `BOT_TOKEN` | Botingiz tokeni |
| `ALLOWED_USERS` | Botdan yana kim foydalana oladi (user ID) |
| `ANTHROPIC_API_KEY` | AI baholashni yoqadi (ixtiyoriy) |
| `AI_MIN_SCORE`, `PROFILE` | AI uchun minimal ball va profilingiz tavsifi |

Kalit so'zlarning to'liq ro'yxati `filters.py` fayli boshida (`CATEGORIES`).
Vakansiya kanalini nomi bo'yicha aniqlash qoidasi `JOB_CHANNEL_HINT` da.

### AI bilan aqlli saralash (ixtiyoriy)
https://console.anthropic.com saytidan kalit oling va `.env` da `ANTHROPIC_API_KEY` bilan `PROFILE` ni to'ldiring.
Shunda har bir vakansiya 0–10 ball bilan baholanadi va botda ⭐ bilan ko'rinadi.
Dublikatlar va rezyumelar AI'ga yuborilmaydi. AI ishlamay qolsa, vakansiya kalit so'z bo'yicha baribir saqlanadi.

## Muammolar

| Belgi | Yechim |
|---|---|
| Bot javob bermayapti | Skript ishlab turganini tekshiring. Token boshqa joyda ishlatilmayotganiga ishonch hosil qiling |
| "Bot sizga yoza olmadi" logi | Botni oching va /start bosing |
| Kerakli kanal kuzatilmayapti | `python main.py --list`, keyin `CHANNELS=auto,@kanal` |
| Kerakli vakansiya kelmadi | Postda "vakansiya/maosh/talablar" kabi so'z yo'q bo'lishi mumkin → `REQUIRE_VACANCY_MARKER=false` |
| Keraksiz vakansiyalar ko'p | `EXCLUDE_EXTRA` ga so'z qo'shing yoki AI'ni yoqing |
| Hammasini boshidan skanerlash (15 kun) | Skriptni to'xtating va `jobs.db` faylini o'chiring |

Testlar: `pip install pytest && pytest -q tests`
