#!/bin/bash

echo "🚀 Запуск CodeHub..."

# Start backend
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

echo "🔧 Запуск backend на http://localhost:5000"
python app.py &
BACKEND_PID=$!

# Wait a bit for backend to start
sleep 2

# Start frontend server
cd ..
echo "🌐 Запуск frontend на http://localhost:8000"
echo ""
echo "✅ Серверы запущены!"
echo "📝 Откройте в браузере: http://localhost:8000"
echo "⚠️  ВАЖНО: Используйте http:// (не https://)"
echo ""
echo "Для остановки нажмите Ctrl+C"

python3 -m http.server 8000

# Cleanup on exit
kill $BACKEND_PID 2>/dev/null

