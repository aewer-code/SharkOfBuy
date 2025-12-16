#!/bin/bash

echo "🌐 Frontend запущен на http://localhost:8000"
echo "⚠️  ВАЖНО: Используйте http://localhost:8000 (не https://)"
echo ""
python3 -m http.server 8000

