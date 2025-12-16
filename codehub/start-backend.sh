#!/bin/bash

cd backend

if [ ! -d "venv" ]; then
    echo "📦 Создание виртуального окружения..."
    python3 -m venv venv
fi

source venv/bin/activate

if [ ! -f "venv/.installed" ]; then
    echo "📥 Установка зависимостей..."
    pip install -r requirements.txt
    touch venv/.installed
fi

echo "🔧 Backend запущен на http://localhost:5000"
python app.py

