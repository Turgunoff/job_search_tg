# Ochiq bot: shaxsiydan ko'p foydalanuvchiliga

**Sana:** 2026-09-16
**Holat:** tasdiqlangan, implementatsiya kutilmoqda

## Maqsad

`@ishtopuvchibot_bot` hozir faqat egasiga va `ALLOWED_USERS` ro'yxatidagilarga
javob beradi. Maqsad — botni ochiq qilish: kim `/start` bossa, vakansiyalar
menyusidan foydalana olsin va yangi vakansiyalar haqida xabar olsin.

Kutilayotgan miqyos: **o'nlab foydalanuvchi** (sheriklar, tanishlar).

## Doiradan tashqarida

Quyidagilar bu ishga kirmaydi va o'zgarmaydi:

- **Vakansiya mazmuni.** Filtr va AI saralash hozirgicha qoladi — Flutter, iOS,
  Android, Backend, Fullstack. `PROFILE` va `AI_MIN_SCORE` tegilmaydi. Ya'ni
  bot "IT dasturchi vakansiyalari" boti bo'lib qoladi, umumiy IT emas.
- **Yo'nalish bo'yicha obuna.** Foydalanuvchi qaysi yo'nalishga obuna bo'lishini
  tanlay olmaydi — bildirishnoma yo hammasi, yo hech qaysi. Keyingi ish uchun.
- **Foydalanuvchini bloklash.** Kerak emas deb qaror qilindi.
- `filters.py`, `tme_web.py`, `ai.py`, `vacancies` jadvali sxemasi, skanerlash
  mantig'i.

## Hozirgi holat va muammolar

`bot.py` kodidan aniqlangan:

| Joy | Muammo |
|---|---|
| `on_message`, `on_callback` | `sender_id not in self.allowed` → `⛔ Bu shaxsiy bot` |
| `notify_on()` | `settings` jadvalidagi **bitta global** `notify` kaliti — bir foydalanuvchi o'chirsa, hammaga o'chadi |
| `self.queries` | umumiy `dict`, kalit — oddiy hisoblagich. Foydalanuvchilar orasida aralashadi va **cheksiz o'sadi** |
| `recipients()` | `settings` dagi `started:<id>` kalitlari bo'yicha yig'adi; throttling yo'q |
| `@scan` tugmasi | 46 kanalni qayta o'qiydi (~80s + AI so'rovlari). Ochiq botda suiiste'mol vektori |
| `@channels` tugmasi | kuzatilayotgan 46 kanal ro'yxatini ochib beradi |
| `HELP` matni | "IT **kanallaringizni** kuzatadi" — shaxsiy bot tili |

## Qarorlar

| Savol | Qaror |
|---|---|
| Mazmun | O'zgarmaydi (dasturchi vakansiyalari) |
| Bildirishnoma standarti | **Yoqilgan**, hamma yo'nalish bo'yicha |
| Miqyos | O'nlab foydalanuvchi — alohida navbat/worker qurilmaydi |
| 🔄 va 📡 tugmalari | **Faqat egasiga.** Boshqalarning menyusida ko'rinmaydi |
| Bloklash | Kerak emas |
| Foydalanuvchi holati | `settings` ga kalit yopishtirish emas, **alohida `users` jadvali** |

## Arxitektura

### 1. `storage.py` — `users` jadvali

```sql
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    joined     INTEGER,
    last_seen  INTEGER,
    notify     INTEGER DEFAULT 1,
    active     INTEGER DEFAULT 1
);
```

- `notify` — 🔔 sozlamasi, har foydalanuvchiga alohida.
- `active` — `0` bo'lsa foydalanuvchi botni bloklagan; unga xabar yuborilmaydi.

Metodlar:

| Metod | Vazifasi |
|---|---|
| `add_user(user_id, username, first_name)` | `/start` da. Mavjud bo'lsa `last_seen` va `active=1` yangilanadi, `joined` va `notify` saqlanadi |
| `touch_user(user_id)` | Har xabarda `last_seen` |
| `set_notify(user_id, on)` | 🔔 tugmasi |
| `notify_on(user_id)` | Foydalanuvchining 🔔 holati (yozuv yo'q bo'lsa `True`) |
| `subscribers()` | `active=1 AND notify=1` bo'lgan `user_id` lar |
| `deactivate(user_id)` | Bloklaganda `active=0` |
| `user_count()` | `(jami, obunachilar)` — statistika uchun |

Migratsiya kerak emas: `CREATE TABLE IF NOT EXISTS`, bazada hali foydalanuvchi yo'q.
Eski `settings` dagi `started:<id>` kalitlari ishlatilmay qoladi (o'chirilmaydi, zararsiz).

### 2. `bot.py` — ruxsat va menyu

- `self.allowed` olib tashlanadi. Kirish hammaga ochiq.
- `owner_id` qoladi — admin huquqlari uchun. `.env` dagi `OWNER_ID` dan.
- `ALLOWED_USERS` endi kerak emas; `.env` va README dan olib tashlanadi.
- `/start`: `store.add_user(...)`, salomlashuv, menyu.
- **Har qanday xabar** foydalanuvchini ro'yxatga oladi (`add_user`), nafaqat
  `/start`. Shunda `users` jadvalida yozuvi yo'q foydalanuvchi bo'lmaydi va
  `notify_on()` ning "yozuv yo'q" holati amalda uchramaydi.
- `keyboard(owner: bool)`:
  - oddiy foydalanuvchi — `MENU` ning birinchi 4 qatori
  - egasi — barcha 5 qator (🔄 va 📡 bilan)
- `@scan` / `@channels`: `sender_id != owner_id` bo'lsa
  `"Bu tugma faqat admin uchun."` javobi (menyudan bosib bo'lmaydi, lekin eski
  klaviatura yoki matn orqali kelishi mumkin).
- `@notify`: `store.set_notify(sender_id, ...)`.
- `render_stats(user_id)`: 🔔 holati shu foydalanuvchiniki. Egasi uchun qo'shimcha
  qator: foydalanuvchilar soni va obunachilar soni.

### 3. Qidiruv keshi

`self.queries: dict[int, OrderedDict[str, str]]` — foydalanuvchi bo'yicha
ajratilgan, har birida oxirgi **20** ta so'rov (`OrderedDict`, eng eskisi
chiqariladi). Kalit — foydalanuvchi ichida o'suvchi hisoblagich.

`on_callback` da so'rov `event.sender_id` ning keshidan izlanadi. Topilmasa —
`"Qidiruv eskirgan — so'zni qayta yozing."` (hozirgi xatti-harakat saqlanadi).

Bu bir vaqtning o'zida ikkita muammoni yopadi: foydalanuvchilar orasidagi
aralashuv va cheksiz o'sish.

### 4. Xabarlarni ikkiga ajratish

Hozir `main.py` hamma narsani `self.send()` orqali yuboradi. Ajratiladi:

| Xabar | Metod | Kimga |
|---|---|---|
| 🆕 Yangi vakansiya (`notify_new`) | `bot.broadcast()` | Barcha obunachilar |
| 📊 Kanal reytingi (15 kunlik hisobot) | `bot.send_to_owner()` | Faqat egasi |
| ➕ Yangi kanal qo'shildi | `bot.send_to_owner()` | Faqat egasi |
| ✅ 🔄 tugmasi javobi | `event.respond()` | Bosgan odamga (hozirgidek) |

`main.py` dagi `send()` egaga yuboradigan bo'lib qoladi; `notify_new()` esa
`broadcast()` ni chaqiradi.

Mavjud `recipients()` metodi olib tashlanadi — uning o'rnini `subscribers()`
(tarqatish uchun) va to'g'ridan-to'g'ri `owner_id` (hisobotlar uchun) egallaydi.
`send_to_owner()` endi nomiga mos ravishda **faqat** egasiga yuboradi.

### 5. `broadcast()`

```
async def broadcast(text_html, link=None):
    for uid in store.subscribers():
        await self._send(uid, text_html, buttons)
        await asyncio.sleep(0.05)      # ~20 xabar/sekund
```

`_send()` da mavjud xatolik mantig'i kengaytiriladi:

| Xato | Harakat |
|---|---|
| `FloodWaitError` | `e.seconds + 1` kutib, qayta urinish (mavjud kod) |
| `UserIsBlockedError`, `ValueError`, `InputUserDeactivatedError` | `store.deactivate(uid)`, keyingisiga o'tish |
| Boshqa | Log, keyingisiga o'tish — bitta foydalanuvchi butun tarqatishni to'xtatmaydi |

Miqyos hisobi: 50 obunachi × `NOTIFY_MAX=5` cheklovi = bir skanda ko'pi bilan
~250 xabar, 50 ms oralik bilan ~13 soniya. Alohida navbat yoki worker kerak emas.

### 6. Matnlar

- `HELP`: "IT kanallaringizni kuzatadi" → "IT kanallarni kuzatadi".
- `bot.py` modul docstring'i yangilanadi.
- `⛔ Bu shaxsiy bot.` javobi olib tashlanadi.
- `/start` salomlashuvi ochiq bot uchun moslanadi.

## Testlar

TDD: har bir xatti-harakat uchun avval test.

**Yangi `tests/test_users.py`:**
- `add_user` yozadi; takroriy `/start` dublikat yaratmaydi va `joined` ni saqlaydi
- `set_notify` / `notify_on` — foydalanuvchilar bir-biriga ta'sir qilmaydi
- `subscribers()` — `notify=0` va `active=0` bo'lganlar chiqmaydi
- `deactivate` — `active=0`, qayta `/start` da `active=1`
- `user_count()` — jami va obunachilar

**`tests/test_bot_flow.py` ga qo'shimcha:**
- Notanish foydalanuvchi `/start` bosadi → menyu oladi (⛔ yo'q)
- Oddiy foydalanuvchi menyusida 🔄 va 📡 tugmalari yo'q; matn orqali bosishga
  urinsa — "faqat admin uchun"
- Egasining menyusida ikkalasi ham bor
- 🔔 — A o'chiradi, B ning sozlamasi o'zgarmaydi
- Qidiruv: A ning sahifalash tugmasi B ning qidiruviga tushmaydi
- Qidiruv keshi 20 tadan oshmaydi
- `broadcast`: 3 foydalanuvchi, o'rtadagisi bloklagan → qolgan ikkitasi xabar
  oladi, bloklagani `active=0` ga o'tadi
- Hisobot (`send_to_owner`) faqat egasiga boradi, obunachilarga bormaydi

## Xavflar

| Xavf | Yumshatish |
|---|---|
| Telegram tarqatishda `FloodWait` beradi | 50 ms oralik + mavjud `FloodWait` kutish mantig'i |
| Foydalanuvchi botni bloklaydi, har skanda xato | `active=0` bilan ro'yxatdan chiqariladi |
| Ochiq bot spam qabul qiladi | Miqyos kichik; kerak bo'lsa keyin bloklash qo'shiladi |
| 🔄 suiiste'mol qilinadi | Egasidan boshqaga berilmaydi |

## Muvaffaqiyat mezoni

1. Notanish odam `/start` bosadi → menyu ishlaydi, vakansiyalarni ko'radi.
2. Yangi vakansiya chiqqanda hamma obunachi xabar oladi, egasi esa qo'shimcha
   texnik hisobotlarni ham oladi.
3. Bir foydalanuvchining 🔔 sozlamasi boshqalarga ta'sir qilmaydi.
4. Botni bloklagan foydalanuvchi tarqatishni to'xtatmaydi.
5. 🔄 va 📡 egasidan boshqaga ochiq emas.
6. Barcha mavjud testlar + yangilari o'tadi.
