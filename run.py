#!/usr/bin/env python3
"""
Запуск Сейчастье v3.0
"""
import os, sys, io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Настройте эти переменные перед запуском:
os.environ.setdefault('SECRET_KEY', 'замените-на-случайную-строку-минимум-32-символа')
os.environ.setdefault('PORT', '5000')

# Telegram уведомления (опционально):
# os.environ['TG_BOT_TOKEN'] = '123456789:ABCdef...'   # токен от @BotFather
# os.environ['TG_CHAT_ID']   = '-1001234567890'        # ID чата/канала/группы

# Автовыход из админки (минуты):
os.environ.setdefault('JWT_EXPIRE_MIN', '60')

sys.path.insert(0, os.path.dirname(__file__))
from server.app import app, init_db

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    print(f'\nСейчастье запущен: http://localhost:{port}')
    print(f'Логин по умолчанию: admin / admin123')
    print(f'База данных: data/seychasye.db')
    tg = os.environ.get('TG_BOT_TOKEN','')
    print(f'Telegram: {"подключён" if tg else "не настроен"}')
    print()
    app.run(host='0.0.0.0', port=port, debug=False)
