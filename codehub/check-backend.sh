#!/bin/bash

echo "🔍 Проверка backend..."

# Check if backend is running
if curl -s http://localhost:5000/api/health > /dev/null 2>&1; then
    echo "✅ Backend работает на http://localhost:5000"
    curl -s http://localhost:5000/api/health | python3 -m json.tool
else
    echo "❌ Backend не отвечает на http://localhost:5000"
    echo "💡 Запустите backend: ./start-backend.sh"
fi

