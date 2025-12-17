import os
import json
import logging
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='webapp')
CORS(app)

# Путь к базе данных бота
DATABASE_FILE = "database.json"

# Загрузка данных из базы
def load_database():
    try:
        if os.path.exists(DATABASE_FILE):
            with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке БД: {e}")
    return {
        "products": {},
        "categories": {},
        "orders": [],
        "stats": {"total_orders": 0, "total_revenue": 0}
    }

# Сохранение данных в базу
def save_database(data):
    try:
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении БД: {e}")
        return False

# Главная страница - веб-приложение
@app.route('/')
def index():
    return send_from_directory('webapp', 'index.html')

# Статические файлы
@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('webapp', path)

# API: Получить список товаров
@app.route('/api/products')
def get_products():
    try:
        user_id = request.args.get('user_id')
        db = load_database()
        
        # Преобразуем товары в список
        products_list = []
        for product_id, product in db.get('products', {}).items():
            # Проверяем, есть ли товар в наличии (для отображения)
            if product.get('stock', 0) != 0 or product.get('stock') is None:
                products_list.append({
                    'id': product_id,
                    'name': product.get('name', ''),
                    'description': product.get('description', ''),
                    'price': product.get('price', 0),
                    'category': product.get('category', 'Без категории'),
                    'stock': product.get('stock'),
                    'image': None  # TODO: добавить поддержку изображений
                })
        
        # Получаем уникальные категории
        categories = list(set([p['category'] for p in products_list]))
        
        return jsonify({
            'success': True,
            'products': products_list,
            'categories': categories
        })
    except Exception as e:
        logger.error(f"Ошибка при получении товаров: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# API: Получить заказы пользователя
@app.route('/api/orders')
def get_orders():
    try:
        user_id = request.args.get('user_id')
        db = load_database()
        
        # Фильтруем заказы пользователя
        user_orders = []
        for order in db.get('orders', []):
            if str(order.get('user_id')) == str(user_id):
                user_orders.append({
                    'id': order.get('order_id', ''),
                    'product_name': order.get('product_name', ''),
                    'price': order.get('price', 0),
                    'status': order.get('status', 'completed'),
                    'date': order.get('date', datetime.now().isoformat())
                })
        
        # Сортируем по дате (новые первыми)
        user_orders.sort(key=lambda x: x.get('date', ''), reverse=True)
        
        return jsonify({
            'success': True,
            'orders': user_orders
        })
    except Exception as e:
        logger.error(f"Ошибка при получении заказов: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# API: Получить профиль пользователя
@app.route('/api/profile')
def get_profile():
    try:
        user_id = request.args.get('user_id')
        db = load_database()
        
        # Подсчитываем статистику пользователя
        user_orders = [order for order in db.get('orders', []) if str(order.get('user_id')) == str(user_id)]
        total_orders = len(user_orders)
        total_spent = sum([order.get('price', 0) for order in user_orders])
        
        return jsonify({
            'success': True,
            'profile': {
                'total_orders': total_orders,
                'total_spent': total_spent
            }
        })
    except Exception as e:
        logger.error(f"Ошибка при получении профиля: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# API: Создать заказ
@app.route('/api/order', methods=['POST'])
def create_order():
    try:
        data = request.json
        user_id = data.get('user_id')
        product_id = data.get('product_id')
        init_data = data.get('init_data')
        
        if not user_id or not product_id:
            return jsonify({'success': False, 'error': 'Не указаны обязательные параметры'}), 400
        
        db = load_database()
        
        # Получаем товар
        product = db.get('products', {}).get(product_id)
        if not product:
            return jsonify({'success': False, 'error': 'Товар не найден'}), 404
        
        # Проверяем наличие
        stock = product.get('stock')
        if stock is not None and stock <= 0:
            return jsonify({'success': False, 'error': 'Товар закончился'}), 400
        
        # Создаем заказ
        order = {
            'order_id': f"WEB{len(db.get('orders', [])) + 1}",
            'user_id': user_id,
            'product_id': product_id,
            'product_name': product.get('name', ''),
            'price': product.get('price', 0),
            'status': 'pending',  # pending = ожидает обработки
            'date': datetime.now().isoformat(),
            'source': 'webapp'
        }
        
        # Сохраняем заказ
        if 'orders' not in db:
            db['orders'] = []
        db['orders'].append(order)
        
        # Уменьшаем количество товара
        if stock is not None:
            db['products'][product_id]['stock'] = stock - 1
        
        # Обновляем статистику
        if 'stats' not in db:
            db['stats'] = {'total_orders': 0, 'total_revenue': 0}
        db['stats']['total_orders'] += 1
        db['stats']['total_revenue'] += product.get('price', 0)
        
        # Добавляем в очередь ожидания для обработки администратором
        if 'pending_orders' not in db:
            db['pending_orders'] = []
        db['pending_orders'].append(order)
        
        # Сохраняем изменения
        if not save_database(db):
            return jsonify({'success': False, 'error': 'Ошибка при сохранении заказа'}), 500
        
        logger.info(f"Создан заказ {order['order_id']} от пользователя {user_id}")
        
        return jsonify({
            'success': True,
            'order': order
        })
    except Exception as e:
        logger.error(f"Ошибка при создании заказа: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Health check
@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

