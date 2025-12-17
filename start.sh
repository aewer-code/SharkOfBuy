#!/bin/bash

# Запуск бота в фоне
nohup python bot.py > bot.log 2>&1 &

# Запуск веб-сервера (основной процесс для Railway)
exec gunicorn webapp_server:app --bind 0.0.0.0:${PORT:-8080} --workers 2

