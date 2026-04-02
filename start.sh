#!/bin/bash
# ──────────────────────────────────────────────
#  Сейчастье — скрипт запуска
# ──────────────────────────────────────────────
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# ── Зависимости ──────────────────────────────
echo "📦 Проверяю зависимости Python..."
pip install flask pyjwt --break-system-packages -q 2>/dev/null || \
pip install flask pyjwt -q 2>/dev/null || \
pip3 install flask pyjwt -q 2>/dev/null || true

# ── Конфигурация ─────────────────────────────
export PORT="${PORT:-5000}"
export SECRET_KEY="${SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   🍕  СЕЙЧАСТЬЕ — Запуск сервера    ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  🌐  http://localhost:${PORT}"
echo ""

if [ -n "${TG_BOT_TOKEN}" ] && [ -n "${TG_CHAT_ID}" ]; then
  echo "  📱  Telegram-уведомления: ✅ подключены"
else
  echo "  📱  Telegram: не настроен"
  echo "      Для включения задайте переменные:"
  echo "      TG_BOT_TOKEN=<токен>  TG_CHAT_ID=<chat_id>"
fi
echo ""
echo "  🔑  Вход по умолчанию: admin / admin123"
echo "      (смените пароль после первого входа!)"
echo ""
echo "  Нажмите Ctrl+C для остановки"
echo "────────────────────────────────────────"
echo ""

python3 server/app.py
