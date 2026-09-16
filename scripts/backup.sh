#!/usr/bin/env bash
# jobs.db ning kunlik zaxirasi (rotatsiya bilan).
#
#   chmod +x scripts/backup.sh
#   crontab -e  ->  0 3 * * * /home/azureuser/Projects/job_search_tg/scripts/backup.sh
#
# Sozlash (.env dan yoki muhit o'zgaruvchisi sifatida):
#   DB_PATH      — baza fayli (standart: jobs.db)
#   BACKUP_DIR   — zaxira papkasi (standart: backups)
#   BACKUP_KEEP  — nechta nusxa saqlansin (standart: 14)
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

DB="${DB_PATH:-jobs.db}"
DIR="${BACKUP_DIR:-backups}"
KEEP="${BACKUP_KEEP:-14}"

if [ ! -f "$DB" ]; then
    echo "❌ Baza topilmadi: $DB" >&2
    exit 1
fi
if ! command -v sqlite3 >/dev/null; then
    echo "❌ sqlite3 o'rnatilmagan: sudo apt install sqlite3" >&2
    exit 1
fi

mkdir -p "$DIR"
out="$DIR/jobs-$(date +%F-%H%M).db"

# .backup — bot ishlab turganda ham xavfsiz (oddiy cp emas: yozuv o'rtasida
# qolgan fayl buzilgan bo'lishi mumkin).
sqlite3 "$DB" ".backup '$out'"
gzip -f "$out"

# Eskilarini o'chirish
ls -1t "$DIR"/jobs-*.db.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "✅ Zaxira: ${out}.gz  ($(ls -1 "$DIR"/jobs-*.db.gz | wc -l) ta nusxa saqlanmoqda)"
