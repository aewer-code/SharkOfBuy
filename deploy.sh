#!/bin/bash
# Скрипт для быстрого деплоя бота

cd /home/ecronx/Загрузки/coding

echo "🔄 Добавляем изменения..."
git add bot.py requirements.txt .gitignore Procfile start.sh session_manager.py SESSIONS_README.md

echo "💾 Коммит..."
git commit -m "🚀 Обновление бота $(date '+%Y-%m-%d %H:%M')"

echo "📤 Отправка в GitHub..."
git push origin main

echo "✅ Готово! Railway автоматически обновит бота через ~1-2 минуты"

