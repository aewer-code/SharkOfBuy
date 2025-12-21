#!/bin/bash
# Скрипт для быстрого деплоя бота

cd /home/ecronx/Загрузки/Xcrono

echo "🔄 Добавляем изменения..."
git add bot.py requirements.txt .gitignore Procfile start.sh database.py deploy.sh

echo "💾 Коммит..."
git commit -m "🚀 Обновление бота $(date '+%Y-%m-%d %H:%M')" || echo "⚠️ Нет изменений для коммита"

echo "📤 Отправка в GitHub..."
git push origin main

echo "✅ Готово! Railway автоматически обновит бота через ~1-2 минуты"

