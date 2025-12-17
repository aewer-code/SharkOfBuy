#!/bin/bash

# Запуск бота и веб-сервера одновременно
python bot.py &
gunicorn webapp_server:app --bind 0.0.0.0:${PORT:-5000} --workers 2

