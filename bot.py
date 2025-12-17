import asyncio
import json
import os
import logging
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List
from dotenv import load_dotenv
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, ContentType, ReplyKeyboardMarkup, KeyboardButton,
    BotCommand, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
)
from aiogram.enums import ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Загружаем переменные окружения
load_dotenv()

# ============= КОНФИГУРАЦИЯ =============
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения! Создайте файл .env")

ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(",") if admin_id.strip()]

# CryptoBot API
CRYPTOBOT_API_TOKEN = os.getenv("CRYPTOBOT_API_TOKEN", "502801:AA8q8d59ImInEBXTwj65KXNfdiOUPMhZTqp")
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api/"

# Обязательная подписка
REQUIRED_CHANNEL = "@SharkOfDark"
REQUIRED_CHANNEL_ID = "@SharkOfDark"  # Или ID канала -100...

# Создатель бота
BOT_CREATOR = "@ecronx"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============= БАЗА ДАННЫХ =============
class Database:
    def __init__(self, filename="database.json"):
        self.filename = filename
        self.data = self.load()

    def load(self):
        try:
            if os.path.exists(self.filename):
                with open(self.filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Миграция: добавляем категории если их нет
                    if "categories" not in data:
                        data["categories"] = {}
                    # Миграция: добавляем очередь ожидания
                    if "pending_orders" not in data:
                        data["pending_orders"] = []
                    # Миграция: добавляем товары на модерации
                    if "pending_products" not in data:
                        data["pending_products"] = []
                    # Миграция: добавляем категорию к товарам если её нет
                    for product_id, product in data.get("products", {}).items():
                        if "category" not in product:
                            product["category"] = "Без категории"
                        # Миграция: добавляем тип выдачи
                        if "delivery_type" not in product:
                            product["delivery_type"] = "auto"
                        # Миграция: добавляем количество товара
                        if "stock" not in product:
                            product["stock"] = None  # None = безлимитный
                    return data
        except Exception as e:
            logger.error(f"Ошибка при загрузке БД: {e}")
            # Создаём резервную копию
            if os.path.exists(self.filename):
                backup_name = f"{self.filename}.backup_{int(time.time())}"
                os.rename(self.filename, backup_name)
                logger.warning(f"Создана резервная копия: {backup_name}")
        
        return {
            "start_message": {
                "text": "👋 <b>Добро пожаловать!</b>\n\nВыберите товар для покупки:",
                "media_type": None,
                "media_id": None
            },
            "products": {},
            "categories": {"Без категории": "Без категории"},
            "orders": [],
            "pending_orders": [],
            "stats": {"total_orders": 0, "total_revenue": 0},
            "subscribed_users": [],  # Список пользователей, прошедших проверку подписки
            "referrals": {},  # Реферальная система: {user_id: [список рефералов]}
            "promo_codes": {},  # Промокоды: {code: {"discount": 10, "uses": 0, "max_uses": 100}}
            "users": {},  # Пользователи: {user_id: {"balance": 0, "username": "..."}}
            "all_users": [],  # Список всех user_id для рассылки
            "pending_products": []  # Товары на модерации: [{"product_id": "...", "user_id": ..., ...}]
        }

    def save(self):
        try:
            # Создаём резервную копию перед сохранением
            if os.path.exists(self.filename):
                backup_name = f"{self.filename}.backup"
                with open(self.filename, "r", encoding="utf-8") as src:
                    with open(backup_name, "w", encoding="utf-8") as dst:
                        dst.write(src.read())
            
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка при сохранении БД: {e}")
            raise

    def add_product(self, product_id, name, description, price, material, category="Без категории", 
                    delivery_type="auto", stock=None, owner_id=None):
        self.data["products"][product_id] = {
            "name": name,
            "description": description,
            "price": price,
            "material": material,
            "category": category,
            "delivery_type": delivery_type,  # "auto" или "manual"
            "stock": stock,  # None = безлимит, число = остаток
            "owner_id": owner_id,  # ID владельца товара (None = админ)
            "created_at": datetime.now().isoformat()
        }
        self.save()

    def update_product(self, product_id, name=None, description=None, price=None, material=None, 
                      category=None, delivery_type=None, stock=None):
        if product_id not in self.data["products"]:
            return False
        product = self.data["products"][product_id]
        if name is not None:
            product["name"] = name
        if description is not None:
            product["description"] = description
        if price is not None:
            product["price"] = price
        if material is not None:
            product["material"] = material
        if category is not None:
            product["category"] = category
        if delivery_type is not None:
            product["delivery_type"] = delivery_type
        if stock is not None:
            product["stock"] = stock
        product["updated_at"] = datetime.now().isoformat()
        self.save()
        return True

    def get_products(self, category=None):
        products = self.data["products"]
        if category and category != "Все":
            return {pid: p for pid, p in products.items() if p.get("category") == category}
        return products

    def get_product(self, product_id):
        return self.data["products"].get(product_id)

    def delete_product(self, product_id):
        if product_id in self.data["products"]:
            del self.data["products"][product_id]
            self.save()
            return True
        return False

    def get_categories(self):
        categories = set()
        for product in self.data["products"].values():
            categories.add(product.get("category", "Без категории"))
        return sorted(list(categories))

    def add_category(self, category_name):
        if category_name not in self.data.get("categories", {}):
            self.data.setdefault("categories", {})[category_name] = category_name
            self.save()

    def get_user_orders(self, user_id):
        return [order for order in self.data["orders"] if order["user_id"] == user_id]

    def add_order(self, user_id, username, product_id, product_name, price, status="completed", quantity=1):
        order = {
            "user_id": user_id,
            "username": username,
            "product_id": product_id,
            "product_name": product_name,
            "price": price,
            "quantity": quantity,
            "status": status,  # "completed" или "pending"
            "date": datetime.now().isoformat()
        }
        self.data["orders"].append(order)
        self.data["stats"]["total_orders"] += 1
        self.data["stats"]["total_revenue"] += price
        self.save()
        return order

    def add_pending_order(self, user_id, username, product_id, product_name, price, quantity=1):
        """Добавить заказ в очередь ожидания ручной выдачи"""
        pending = {
            "order_id": f"ord_{int(time.time())}_{user_id}",
            "user_id": user_id,
            "username": username,
            "product_id": product_id,
            "product_name": product_name,
            "price": price,
            "quantity": quantity,
            "date": datetime.now().isoformat()
        }
        self.data.setdefault("pending_orders", []).append(pending)
        self.save()
        return pending

    def get_pending_orders(self):
        """Получить все ожидающие заказы"""
        return self.data.get("pending_orders", [])

    def remove_pending_order(self, order_id):
        """Удалить заказ из очереди"""
        self.data["pending_orders"] = [o for o in self.data.get("pending_orders", []) 
                                       if o.get("order_id") != order_id]
        self.save()

    def decrease_stock(self, product_id):
        """Уменьшить остаток товара"""
        product = self.data["products"].get(product_id)
        if product and product.get("stock") is not None:
            if product["stock"] > 0:
                product["stock"] -= 1
                self.save()
                return True
            return False  # Товар закончился
        return True  # Безлимитный товар

    def get_stats(self):
        return self.data["stats"]
    
    def add_pending_product(self, product_data):
        """Добавить товар на модерацию"""
        if "pending_products" not in self.data:
            self.data["pending_products"] = []
        self.data["pending_products"].append(product_data)
        self.save()
        return product_data
    
    def get_pending_products(self):
        """Получить все товары на модерации"""
        return self.data.get("pending_products", [])
    
    def remove_pending_product(self, product_id):
        """Удалить товар из очереди модерации"""
        self.data["pending_products"] = [p for p in self.data.get("pending_products", []) 
                                         if p.get("product_id") != product_id]
        self.save()
    
    def approve_pending_product(self, product_id):
        """Одобрить товар и добавить в каталог"""
        pending = next((p for p in self.data.get("pending_products", []) 
                       if p.get("product_id") == product_id), None)
        if pending:
            # Добавляем в каталог с указанием владельца
            self.add_product(
                pending["product_id"],
                pending["name"],
                pending["description"],
                pending["price"],
                pending["material"],
                pending.get("category", "Без категории"),
                pending.get("delivery_type", "auto"),
                pending.get("stock", None),
                owner_id=pending.get("user_id")  # Сохраняем владельца товара
            )
            # Удаляем из очереди модерации
            self.remove_pending_product(product_id)
            return True
        return False

    def set_start_message(self, text, media_type=None, media_id=None):
        self.data["start_message"] = {
            "text": text,
            "media_type": media_type,
            "media_id": media_id
        }
        self.save()

    def get_start_message(self):
        return self.data["start_message"]
    
    def is_user_subscribed(self, user_id):
        """Проверка, прошел ли пользователь проверку подписки"""
        return user_id in self.data.get("subscribed_users", [])
    
    def add_subscribed_user(self, user_id):
        """Добавить пользователя в список подписавшихся"""
        if "subscribed_users" not in self.data:
            self.data["subscribed_users"] = []
        if user_id not in self.data["subscribed_users"]:
            self.data["subscribed_users"].append(user_id)
            self.save()
    
    def add_referral(self, referrer_id, referred_id):
        """Добавить реферала"""
        if "referrals" not in self.data:
            self.data["referrals"] = {}
        if referrer_id not in self.data["referrals"]:
            self.data["referrals"][referrer_id] = []
        if referred_id not in self.data["referrals"][referrer_id]:
            self.data["referrals"][referrer_id].append(referred_id)
            self.save()
    
    def get_referrals(self, user_id):
        """Получить список рефералов"""
        return self.data.get("referrals", {}).get(user_id, [])
    
    def register_user(self, user_id, username=None):
        """Регистрация пользователя в системе"""
        if "users" not in self.data:
            self.data["users"] = {}
        if "all_users" not in self.data:
            self.data["all_users"] = []
        
        user_id_str = str(user_id)
        if user_id_str not in self.data["users"]:
            self.data["users"][user_id_str] = {
                "balance": 0,
                "username": username,
                "registered_at": datetime.now().isoformat()
            }
        
        if user_id not in self.data["all_users"]:
            self.data["all_users"].append(user_id)
        
        self.save()
    
    def get_balance(self, user_id):
        """Получить баланс пользователя"""
        user_id_str = str(user_id)
        return self.data.get("users", {}).get(user_id_str, {}).get("balance", 0)
    
    def add_balance(self, user_id, amount):
        """Добавить средства на баланс"""
        user_id_str = str(user_id)
        if "users" not in self.data:
            self.data["users"] = {}
        if user_id_str not in self.data["users"]:
            self.register_user(user_id)
        
        self.data["users"][user_id_str]["balance"] = self.data["users"][user_id_str].get("balance", 0) + amount
        self.save()
        return self.data["users"][user_id_str]["balance"]
    
    def subtract_balance(self, user_id, amount):
        """Снять средства с баланса"""
        user_id_str = str(user_id)
        current_balance = self.get_balance(user_id)
        
        if current_balance < amount:
            return False
        
        self.data["users"][user_id_str]["balance"] = current_balance - amount
        self.save()
        return True
    
    def get_all_users(self):
        """Получить список всех пользователей для рассылки"""
        return self.data.get("all_users", [])
    
    def create_promo_code(self, code, amount, max_uses=None):
        """Создать промокод"""
        if "promo_codes" not in self.data:
            self.data["promo_codes"] = {}
        
        self.data["promo_codes"][code.upper()] = {
            "amount": amount,
            "uses": 0,
            "max_uses": max_uses,
            "created_at": datetime.now().isoformat()
        }
        self.save()
    
    def use_promo_code(self, code, user_id):
        """Использовать промокод"""
        code = code.upper()
        promo = self.data.get("promo_codes", {}).get(code)
        
        if not promo:
            return None, "Промокод не найден"
        
        # Проверяем лимит использований
        if promo.get("max_uses") and promo["uses"] >= promo["max_uses"]:
            return None, "Промокод исчерпан"
        
        # Начисляем бонус
        amount = promo["amount"]
        self.add_balance(user_id, amount)
        
        # Увеличиваем счетчик использований
        self.data["promo_codes"][code]["uses"] += 1
        self.save()
        
        return amount, None
    
    def get_promo_codes(self):
        """Получить все промокоды"""
        return self.data.get("promo_codes", {})


db = Database()


# ============= FSM СОСТОЯНИЯ =============
class BuyStates(StatesGroup):
    waiting_quantity = State()
    waiting_message = State()

class UserProductStates(StatesGroup):
    waiting_product_name = State()
    waiting_product_description = State()
    waiting_product_price = State()
    waiting_product_category = State()
    waiting_product_material = State()

class AdminStates(StatesGroup):
    waiting_product_name = State()
    waiting_product_description = State()
    waiting_product_price = State()
    waiting_product_category = State()
    waiting_product_delivery_type = State()
    waiting_product_stock = State()
    waiting_product_material = State()
    waiting_start_text = State()
    waiting_start_media = State()
    waiting_edit_product = State()
    waiting_edit_field = State()
    waiting_manual_delivery = State()
    waiting_promo_code = State()
    waiting_create_promo_code = State()
    waiting_create_promo_amount = State()
    waiting_create_promo_uses = State()
    waiting_broadcast_button = State()


# ============= КЛАВИАТУРЫ =============
PRODUCTS_PER_PAGE = 5

def get_main_reply_keyboard():
    """Главная Reply клавиатура после подписки"""
    keyboard = [
        [KeyboardButton(text="🛍️ Каталог товаров"), KeyboardButton(text="👤 Личный кабинет")],
        [KeyboardButton(text="📜 Мои заказы"), KeyboardButton(text="🎯 Реферальная программа")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_main_keyboard(page=0, category="Все"):
    products = db.get_products(category if category != "Все" else None)
    products_list = list(products.items())
    
    # Пагинация
    total_pages = (len(products_list) + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE if products_list else 1
    start_idx = page * PRODUCTS_PER_PAGE
    end_idx = start_idx + PRODUCTS_PER_PAGE
    page_products = products_list[start_idx:end_idx]
    
    keyboard = []
    
    # Кнопки категорий
    categories = ["Все"] + db.get_categories()
    if len(categories) > 1:
        category_row = []
        for cat in categories[:3]:  # Максимум 3 категории в ряд
            emoji = "✅" if cat == category else "📁"
            category_row.append(InlineKeyboardButton(
                text=f"{emoji} {cat}",
                callback_data=f"cat_{cat}"
            ))
        if category_row:
            keyboard.append(category_row)
    
    # Товары на текущей странице
    for pid, product in page_products:
        stock_text = ""
        stock = product.get("stock")
        if stock is not None:
            if stock == 0:
                stock_text = " [НЕТ В НАЛИЧИИ]"
            else:
                stock_text = f" (осталось: {stock})"
        
        # Показываем продавца товара
        owner_id = product.get("owner_id")
        seller_text = ""
        if owner_id:
            # Получаем username владельца
            owner_data = db.data.get("users", {}).get(str(owner_id), {})
            owner_username = owner_data.get("username", f"ID{owner_id}")
            seller_text = f" 👤 @{owner_username}"
        
        keyboard.append([InlineKeyboardButton(
            text=f"🛍 {product['name']} - {product['price']} ⭐{stock_text}{seller_text}",
            callback_data=f"buy_{pid}"
        )])
    
    # Навигация по страницам
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"page_{page-1}_{category}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"page_{page+1}_{category}"))
    if nav_row:
        keyboard.append(nav_row)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_keyboard():
    pending_count = len(db.get_pending_orders())
    pending_text = f"⏳ Ожидают выдачи ({pending_count})" if pending_count > 0 else "⏳ Ожидают выдачи"
    
    pending_products_count = len(db.get_pending_products())
    pending_products_text = f"🔍 Товары на модерации ({pending_products_count})" if pending_products_count > 0 else "🔍 Товары на модерации"
    
    keyboard = [
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add_product")],
        [InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_list_products")],
        [InlineKeyboardButton(text="🎫 Промокоды", callback_data="admin_promo_codes")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📦 Заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(text=pending_text, callback_data="admin_pending_orders")],
        [InlineKeyboardButton(text=pending_products_text, callback_data="admin_pending_products")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_product_manage_keyboard(product_id):
    keyboard = [
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"admin_edit_{product_id}")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data=f"admin_delete_confirm_{product_id}")],
        [InlineKeyboardButton(text="◀️ К списку товаров", callback_data="admin_list_products")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])


# ============= РОУТЕР =============
router = Router()


# ============= ПРОВЕРКА АДМИНА =============
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ============= ОБРАБОТЧИКИ =============
async def check_subscription(bot: Bot, user_id: int) -> bool:
    """Проверка подписки на канал"""
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL_ID, user_id=user_id)
        return member.status in [ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER]
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False


@router.message(Command("start"))
async def cmd_start(message: Message):
    try:
        user_id = message.from_user.id
        
        # Проверяем, прошел ли пользователь проверку подписки ранее
        if not db.is_user_subscribed(user_id):
            # Проверяем подписку на канал
            is_subscribed = await check_subscription(message.bot, user_id)
            
            if not is_subscribed:
                # Показываем сообщение с требованием подписки
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}")],
                    [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
                ])
                
                await message.answer(
                    "📢 <b>Чтобы получить доступ к боту, подпишитесь на наш канал!</b>\n\n"
                    f"👉 {REQUIRED_CHANNEL}\n\n"
                    "После подписки нажмите кнопку <b>\"Проверить\"</b>",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Пользователь {user_id} не подписан на канал")
                return
            else:
                # Пользователь подписан, добавляем в БД
                db.add_subscribed_user(user_id)
        
        # Регистрируем пользователя в системе
        was_new_user = user_id not in db.data.get("all_users", [])
        db.register_user(user_id, message.from_user.username)
        
        # Проверяем реферальную ссылку
        bonus_given = False
        if message.text and "start=ref_" in message.text:
            try:
                # Парсим реферальную ссылку более надежно
                parts = message.text.split("start=ref_")
                if len(parts) > 1:
                    ref_id_str = parts[1].split()[0] if parts[1].split() else parts[1].strip()
                    ref_id = int(ref_id_str)
                    
                    if ref_id != user_id:  # Нельзя быть рефералом самому себе
                        # Проверяем, не является ли пользователь уже рефералом этого реферера
                        existing_referrals = db.get_referrals(ref_id)
                        if user_id not in existing_referrals:
                            # Добавляем реферала
                            db.add_referral(ref_id, user_id)
                            logger.info(f"Реферал добавлен: {ref_id} -> {user_id}")
                            
                            # Если это новый пользователь, даем ему бонус 10 звезд
                            if was_new_user:
                                db.add_balance(user_id, 10)
                                bonus_given = True
                                logger.info(f"Новому рефералу {user_id} начислен бонус 10 ⭐")
                            
                            # Уведомляем реферера
                            try:
                                await message.bot.send_message(
                                    ref_id,
                                    f"🎉 <b>У вас новый реферал!</b>\n\n"
                                    f"👤 @{message.from_user.username or 'Пользователь'}\n\n"
                                    f"💡 Когда он пополнит баланс, вы получите 10% бонус!",
                                    parse_mode=ParseMode.HTML
                                )
                            except Exception as e:
                                logger.warning(f"Не удалось уведомить реферера {ref_id}: {e}")
                        else:
                            logger.info(f"Пользователь {user_id} уже является рефералом {ref_id}")
            except Exception as e:
                logger.error(f"Ошибка обработки реферальной ссылки: {e}, text: {message.text}")
        
        # Пользователь подписан - показываем приветствие
        balance = db.get_balance(user_id)
        bonus_text = "\n\n🎁 <b>Вам начислен приветственный бонус: 10 ⭐!</b>" if bonus_given else ""
        welcome_text = (
            "🎉 <b>Добро пожаловать в Shark Of Buy!</b>\n\n"
            "<i>Быстро • Надежно • Безопасно</i>\n\n"
            f"💰 <b>Баланс:</b> {balance} ⭐{bonus_text}\n\n"
            "<b>Доступные команды:</b>\n"
            "/buy - Каталог товаров\n"
            "/profile - Личный кабинет\n"
            "/myorders - Мои заказы\n"
            "/referral - Реферальная программа\n"
            "/help - Справка\n\n"
            f"<b>Создатель:</b> {BOT_CREATOR}"
        )
        
        await message.answer(
            welcome_text,
            reply_markup=get_main_reply_keyboard(),
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Пользователь {user_id} использовал /start")
        
    except Exception as e:
        logger.error(f"Ошибка в /start: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")


@router.callback_query(F.data == "check_subscription")
async def process_check_subscription(callback: CallbackQuery):
    """Обработка проверки подписки"""
    try:
        user_id = callback.from_user.id
        is_subscribed = await check_subscription(callback.bot, user_id)
        
        if is_subscribed:
            # Пользователь подписан!
            db.add_subscribed_user(user_id)
            
            # Регистрируем пользователя
            was_new_user = user_id not in db.data.get("all_users", [])
            db.register_user(user_id, callback.from_user.username)
            
            # Проверяем реферальную ссылку
            bonus_given = False
            if callback.message.text and "start=ref_" in callback.message.text:
                try:
                    # Парсим реферальную ссылку более надежно
                    parts = callback.message.text.split("start=ref_")
                    if len(parts) > 1:
                        ref_id_str = parts[1].split()[0] if parts[1].split() else parts[1].strip()
                        ref_id = int(ref_id_str)
                        
                        if ref_id != user_id:  # Нельзя быть рефералом самому себе
                            # Проверяем, не является ли пользователь уже рефералом этого реферера
                            existing_referrals = db.get_referrals(ref_id)
                            if user_id not in existing_referrals:
                                # Добавляем реферала
                                db.add_referral(ref_id, user_id)
                                logger.info(f"Реферал добавлен: {ref_id} -> {user_id}")
                                
                                # Если это новый пользователь, даем ему бонус 10 звезд
                                if was_new_user:
                                    db.add_balance(user_id, 10)
                                    bonus_given = True
                                    logger.info(f"Новому рефералу {user_id} начислен бонус 10 ⭐")
                                
                                # Уведомляем реферера
                                try:
                                    await callback.bot.send_message(
                                        ref_id,
                                        f"🎉 <b>У вас новый реферал!</b>\n\n"
                                        f"👤 @{callback.from_user.username or 'Пользователь'}\n\n"
                                        f"💡 Когда он пополнит баланс, вы получите 10% бонус!",
                                        parse_mode=ParseMode.HTML
                                    )
                                except Exception as e:
                                    logger.warning(f"Не удалось уведомить реферера {ref_id}: {e}")
                            else:
                                logger.info(f"Пользователь {user_id} уже является рефералом {ref_id}")
                except Exception as e:
                    logger.error(f"Ошибка обработки реферальной ссылки: {e}, text: {callback.message.text}")
            
            balance = db.get_balance(user_id)
            bonus_text = "\n\n🎁 <b>Вам начислен приветственный бонус: 10 ⭐!</b>" if bonus_given else ""
            welcome_text = (
                "🎉 <b>Добро пожаловать в Shark Of Buy!</b>\n\n"
                "<i>Быстро • Надежно • Безопасно</i>\n\n"
                f"💰 <b>Баланс:</b> {balance} ⭐{bonus_text}\n\n"
                "<b>Доступные команды:</b>\n"
                "/buy - Каталог товаров\n"
                "/profile - Личный кабинет\n"
                "/myorders - Мои заказы\n"
                "/referral - Реферальная программа\n"
                "/help - Справка\n\n"
                f"<b>Создатель:</b> {BOT_CREATOR}"
            )
            
            await callback.message.delete()
            await callback.message.answer(
                welcome_text,
                reply_markup=get_main_reply_keyboard(),
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Пользователь {user_id} успешно подписался")
        else:
            await callback.answer(
                "❌ Вы еще не подписались на канал!\n\n"
                f"Подпишитесь на {REQUIRED_CHANNEL} и попробуйте снова.",
                show_alert=True
            )
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}", exc_info=True)
        await callback.answer("❌ Ошибка проверки. Попробуйте позже.", show_alert=True)


@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📖 <b>Помощь</b>\n\n"
        "<b>Команды:</b>\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/myorders - Мои заказы\n\n"
        "<b>Как купить товар:</b>\n"
        "1. Выберите товар из списка\n"
        "2. Нажмите кнопку оплаты\n"
        "3. Оплатите звездами Telegram\n"
        "4. Получите материал автоматически\n\n"
        "<b>Вопросы?</b> Обратитесь к администратору."
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)


@router.message(Command("profile"))
@router.message(F.text == "👤 Личный кабинет")
async def cmd_profile(message: Message):
    """Личный кабинет пользователя"""
    user_id = message.from_user.id
    balance = db.get_balance(user_id)
    orders_count = len(db.get_user_orders(user_id))
    referrals_count = len(db.get_referrals(user_id))
    
    text = (
        "👤 <b>Личный кабинет</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Имя: @{message.from_user.username or 'Без username'}\n\n"
        f"💰 <b>Баланс:</b> {balance} ⭐\n"
        f"<b>Заказов:</b> {orders_count}\n"
        f"<b>Рефералов:</b> {referrals_count}\n\n"
        "<i>Зарабатывайте на продаже товаров! При продаже вы получаете 98% от цены.</i>"
    )
    
    # Обычные пользователи не могут пополнять баланс - только зарабатывать на продаже товаров
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести средства", callback_data="withdraw_balance")],
        [InlineKeyboardButton(text="🎫 Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton(text="📜 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="🎯 Реферальная программа", callback_data="referral_program")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="user_add_product")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "topup_balance")
async def process_topup_balance(callback: CallbackQuery):
    """Выбор суммы пополнения (только для админов)"""
    # Обычные пользователи не могут пополнять баланс
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Пополнение баланса недоступно! Зарабатывайте на продаже товаров.", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 10 звезд", callback_data="topup_10")],
        [InlineKeyboardButton(text="⭐ 50 звезд", callback_data="topup_50")],
        [InlineKeyboardButton(text="⭐ 100 звезд", callback_data="topup_100")],
        [InlineKeyboardButton(text="⭐ 250 звезд", callback_data="topup_250")],
        [InlineKeyboardButton(text="⭐ 500 звезд", callback_data="topup_500")],
        [InlineKeyboardButton(text="💳 CryptoBot (USDT)", callback_data="topup_crypto")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_profile")]
    ])
    
    await callback.message.edit_text(
        "💰 <b>Пополнение баланса</b>\n\n"
        "Выберите способ пополнения:\n\n"
        "💡 <i>Звезды будут конвертированы в баланс 1:1</i>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("topup_") & ~F.data.startswith("topup_crypto"))
async def process_topup_amount(callback: CallbackQuery):
    """Обработка пополнения баланса через Telegram Stars"""
    try:
        if callback.data == "topup_balance":
            return
        
        amount = int(callback.data.replace("topup_", ""))
        
        prices = [LabeledPrice(label=f"Пополнение баланса на {amount} ⭐", amount=amount)]
        
        await callback.message.answer_invoice(
            title=f"💰 Пополнение баланса",
            description=f"Пополнение баланса на {amount} звезд",
            payload=f"topup_{amount}",
            provider_token="",
            currency="XTR",
            prices=prices
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка пополнения: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "topup_crypto")
async def process_topup_crypto(callback: CallbackQuery):
    """Пополнение баланса через CryptoBot"""
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 10 звезд", callback_data="topup_crypto_10")],
            [InlineKeyboardButton(text="⭐ 50 звезд", callback_data="topup_crypto_50")],
            [InlineKeyboardButton(text="⭐ 100 звезд", callback_data="topup_crypto_100")],
            [InlineKeyboardButton(text="⭐ 250 звезд", callback_data="topup_crypto_250")],
            [InlineKeyboardButton(text="⭐ 500 звезд", callback_data="topup_crypto_500")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="topup_balance")]
        ])
        
        await callback.message.edit_text(
            "💳 <b>Пополнение баланса через CryptoBot</b>\n\n"
            "Выберите сумму пополнения:\n\n"
            "💡 <i>1 звезда ≈ 0.015 USDT</i>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка пополнения через CryptoBot: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("topup_crypto_"))
async def process_topup_crypto_amount(callback: CallbackQuery):
    """Создание инвойса CryptoBot для пополнения баланса"""
    try:
        amount = int(callback.data.replace("topup_crypto_", ""))
        # Конвертация: 50 звезд = $0.75, значит 1 звезда = $0.015
        usdt_amount = amount * 0.015
        
        payload = f"topup_{amount}"
        invoice = await create_cryptobot_invoice(
            callback.from_user.id,
            f"Пополнение баланса на {amount} ⭐",
            usdt_amount,
            payload
        )
        
        if not invoice:
            await callback.message.answer(
                "❌ <b>Ошибка создания платежа</b>\n\n"
                "Не удалось создать инвойс через CryptoBot.",
                parse_mode=ParseMode.HTML
            )
            await callback.answer()
            return
        
        invoice_url = invoice.get("pay_url")
        invoice_id = invoice.get("invoice_id")
        
        if not invoice_id:
            await callback.message.answer(
                "❌ <b>Ошибка создания платежа</b>\n\n"
                "Не удалось получить ID инвойса от CryptoBot.",
                parse_mode=ParseMode.HTML
            )
            await callback.answer()
            return
        
        # Сохраняем invoice_id для проверки
        if "crypto_invoices" not in db.data:
            db.data["crypto_invoices"] = {}
        db.data["crypto_invoices"][str(invoice_id)] = {
            "user_id": callback.from_user.id,
            "type": "topup",
            "amount": amount,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        db.save()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить через CryptoBot", url=invoice_url)]
        ])
        
        await callback.message.answer(
            f"💳 <b>Пополнение баланса через CryptoBot</b>\n\n"
            f"Сумма: {amount} ⭐\n"
            f"К оплате: {usdt_amount:.2f} USDT\n\n"
            f"Нажмите кнопку ниже для оплаты:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
    except ValueError as e:
        logger.error(f"Ошибка парсинга суммы: {e}")
        await callback.answer("❌ Неверная сумма", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка создания инвойса для пополнения: {e}", exc_info=True)
        await callback.message.answer(
            f"❌ <b>Ошибка</b>\n\n"
            f"Детали: {str(e)}\n\n"
            f"Проверьте логи бота для подробностей.",
            parse_mode=ParseMode.HTML
        )
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    """Вернуться в личный кабинет"""
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    orders_count = len(db.get_user_orders(user_id))
    referrals_count = len(db.get_referrals(user_id))
    
    text = (
        "👤 <b>Личный кабинет</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Имя: @{callback.from_user.username or 'Без username'}\n\n"
        f"💰 <b>Баланс:</b> {balance} ⭐\n"
        f"<b>Заказов:</b> {orders_count}\n"
        f"<b>Рефералов:</b> {referrals_count}\n\n"
        "<i>Зарабатывайте на продаже товаров! При продаже вы получаете 98% от цены.</i>"
    )
    
    # Обычные пользователи не могут пополнять баланс - только зарабатывать на продаже товаров
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести средства", callback_data="withdraw_balance")],
        [InlineKeyboardButton(text="🎫 Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton(text="📜 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="🎯 Реферальная программа", callback_data="referral_program")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="user_add_product")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "withdraw_balance")
async def process_withdraw_balance(callback: CallbackQuery):
    """Запрос на вывод средств"""
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    if balance <= 0:
        await callback.answer("❌ У вас нет средств для вывода!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"💸 <b>Вывод средств</b>\n\n"
        f"💰 Ваш баланс: {balance} ⭐\n\n"
        f"Для вывода средств напишите администратору:\n"
        f"• Ваш ID: <code>{user_id}</code>\n"
        f"• Сумма вывода: {balance} ⭐\n"
        f"• Способ получения (Telegram Stars, CryptoBot и т.д.)\n\n"
        f"Администратор обработает ваш запрос в ближайшее время.\n\n"
        f"💡 <i>Минимальная сумма вывода: 10 ⭐</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Написать админу", url=f"https://t.me/{BOT_CREATOR.replace('@', '')}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_profile")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()
    
    # Уведомляем админов о запросе на вывод
    for admin_id in ADMIN_IDS:
        try:
            await callback.bot.send_message(
                admin_id,
                f"💸 <b>Запрос на вывод средств</b>\n\n"
                f"👤 Пользователь: @{callback.from_user.username or 'Без username'}\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"💰 Сумма: {balance} ⭐\n\n"
                f"Обработайте запрос через команду /pay {user_id} <сумма>",
                parse_mode=ParseMode.HTML
            )
        except:
            pass


@router.callback_query(F.data == "referral_program")
async def process_referral_program(callback: CallbackQuery):
    """Реферальная программа из callback"""
    user_id = callback.from_user.id
    referrals = db.get_referrals(user_id)
    referral_link = f"https://t.me/{(await callback.bot.get_me()).username}?start=ref_{user_id}"
    
    text = (
        "🎯 <b>Реферальная программа</b>\n\n"
        "Приглашайте друзей и получайте бонусы!\n\n"
        f"<b>Ваших рефералов:</b> {len(referrals)}\n\n"
        f"<b>Ваша реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        "<b>Бонусы:</b>\n"
        "• Друг пополняет баланс → вы получаете 10%\n\n"
        "<i>Чем больше рефералов, тем больше заработок</i>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_profile")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


# ============= ПОЛЬЗОВАТЕЛИ: ДОБАВЛЕНИЕ ТОВАРА =============
@router.callback_query(F.data == "user_add_product")
async def user_add_product_start(callback: CallbackQuery, state: FSMContext):
    """Начало добавления товара пользователем"""
    # Показываем предупреждение о запрещенных товарах
    warning_text = (
        "⚠️ <b>Внимание!</b>\n\n"
        "<b>Запрещено выставлять:</b>\n"
        "❌ 18+ материалы\n"
        "❌ Базы данных\n"
        "❌ Краденые аккаунты\n\n"
        "Товар будет проверен администратором перед публикацией.\n\n"
        "Продолжить?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Продолжить", callback_data="user_add_product_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_profile")]
    ])
    
    await callback.message.edit_text(warning_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "user_add_product_confirm")
async def user_add_product_confirm(callback: CallbackQuery, state: FSMContext):
    """Подтверждение добавления товара"""
    await callback.message.edit_text(
        "📝 <b>Добавление товара</b>\n\n"
        "Введите название товара:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_profile")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(UserProductStates.waiting_product_name)
    await callback.answer()


@router.message(UserProductStates.waiting_product_name)
async def user_product_name(message: Message, state: FSMContext):
    """Обработка названия товара от пользователя"""
    await state.update_data(name=message.text)
    await message.answer(
        "📝 Введите описание товара:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="user_cancel_product")]
        ])
    )
    await state.set_state(UserProductStates.waiting_product_description)


@router.message(UserProductStates.waiting_product_description)
async def user_product_description(message: Message, state: FSMContext):
    """Обработка описания товара от пользователя"""
    await state.update_data(description=message.text)
    await message.answer(
        "💰 Введите цену в звездах (целое число, минимум 1):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="user_cancel_product")]
        ])
    )
    await state.set_state(UserProductStates.waiting_product_price)


@router.message(UserProductStates.waiting_product_price)
async def user_product_price(message: Message, state: FSMContext):
    """Обработка цены товара от пользователя"""
    try:
        price = int(message.text)
        if price < 1:
            await message.answer("❌ Цена должна быть минимум 1 ⭐! Введите корректную цену:")
            return
    except ValueError:
        await message.answer("❌ Введите корректную цену (целое число, минимум 1)!")
        return
    
    await state.update_data(price=price)
    
    # Получаем категории
    categories = db.get_categories()
    keyboard = []
    for cat in categories[:3]:  # Максимум 3 в ряд
        keyboard.append([InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"user_select_cat_{cat}")])
    keyboard.append([InlineKeyboardButton(text="⏭ Пропустить", callback_data="user_skip_category")])
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="user_cancel_product")])
    
    await message.answer(
        "📁 <b>Выберите категорию товара:</b>\n\n"
        "Или пропустите этот шаг",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(UserProductStates.waiting_product_category)


@router.callback_query(F.data.startswith("user_select_cat_"))
async def user_select_category(callback: CallbackQuery, state: FSMContext):
    """Выбор категории пользователем"""
    category = callback.data.replace("user_select_cat_", "")
    await state.update_data(category=category)
    
    await callback.message.edit_text(
        "📦 <b>Тип выдачи товара:</b>\n\n"
        "• <b>Автоматическая</b> - товар выдается сразу после оплаты\n"
        "• <b>Ручная</b> - товар выдается администратором вручную",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Автоматическая", callback_data="user_delivery_auto")],
            [InlineKeyboardButton(text="👤 Ручная", callback_data="user_delivery_manual")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="user_cancel_product")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(UserProductStates.waiting_product_delivery_type)
    await callback.answer()


@router.callback_query(F.data == "user_skip_category")
async def user_skip_category(callback: CallbackQuery, state: FSMContext):
    """Пропуск категории"""
    await state.update_data(category="Без категории")
    
    await callback.message.edit_text(
        "📦 <b>Тип выдачи товара:</b>\n\n"
        "• <b>Автоматическая</b> - товар выдается сразу после оплаты\n"
        "• <b>Ручная</b> - товар выдается администратором вручную",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Автоматическая", callback_data="user_delivery_auto")],
            [InlineKeyboardButton(text="👤 Ручная", callback_data="user_delivery_manual")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="user_cancel_product")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(UserProductStates.waiting_product_delivery_type)
    await callback.answer()


@router.callback_query(F.data.startswith("user_delivery_"))
async def user_select_delivery_type(callback: CallbackQuery, state: FSMContext):
    """Выбор типа выдачи пользователем"""
    delivery_type = callback.data.replace("user_delivery_", "")
    await state.update_data(delivery_type=delivery_type)
    
    await callback.message.edit_text(
        "📊 <b>Количество товара:</b>\n\n"
        "Выберите количество товара на складе:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="∞ Безлимит", callback_data="user_stock_unlimited")],
            [InlineKeyboardButton(text="🔢 Указать количество", callback_data="user_stock_custom")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="user_cancel_product")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(UserProductStates.waiting_product_stock)
    await callback.answer()


@router.callback_query(F.data == "user_stock_unlimited")
async def user_stock_unlimited(callback: CallbackQuery, state: FSMContext):
    """Безлимитный товар"""
    await state.update_data(stock=None)
    
    await callback.message.edit_text(
        "📦 <b>Отправьте материал товара:</b>\n\n"
        "Вы можете отправить:\n"
        "• Текст\n"
        "• Фото\n"
        "• Видео\n\n"
        "Этот материал будет выдан покупателю после оплаты.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="user_cancel_product")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(UserProductStates.waiting_product_material)
    await callback.answer()


@router.callback_query(F.data == "user_stock_custom")
async def user_stock_custom(callback: CallbackQuery, state: FSMContext):
    """Ввод количества товара"""
    await callback.message.edit_text(
        "🔢 <b>Введите количество товара:</b>\n\n"
        "Укажите, сколько единиц товара будет доступно для продажи.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="user_cancel_product")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(UserProductStates.waiting_product_stock)
    await callback.answer()


@router.message(UserProductStates.waiting_product_stock)
async def user_product_stock_input(message: Message, state: FSMContext):
    """Обработка количества товара от пользователя"""
    try:
        stock = int(message.text)
        if stock < 1:
            await message.answer("❌ Количество должно быть минимум 1! Введите корректное количество:")
            return
    except ValueError:
        await message.answer("❌ Введите корректное количество (целое число, минимум 1)!")
        return
    
    await state.update_data(stock=stock)
    
    await message.answer(
        "📦 <b>Отправьте материал товара:</b>\n\n"
        "Вы можете отправить:\n"
        "• Текст\n"
        "• Фото\n"
        "• Видео\n\n"
        "Этот материал будет выдан покупателю после оплаты.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="user_cancel_product")]
        ])
    )
    await state.set_state(UserProductStates.waiting_product_material)


@router.message(UserProductStates.waiting_product_material)
async def user_product_material(message: Message, state: FSMContext):
    """Обработка материала товара от пользователя"""
    material = {}
    
    if message.text:
        material = {"type": "text", "content": message.text}
    elif message.photo:
        material = {"type": "photo", "file_id": message.photo[-1].file_id}
    elif message.video:
        material = {"type": "video", "file_id": message.video.file_id}
    else:
        await message.answer("❌ Отправьте текст, фото или видео!")
        return
    
    data = await state.get_data()
    product_id = f"user_prod_{int(time.time())}_{message.from_user.id}"
    
    # Сохраняем товар на модерацию
    pending_product = {
        "product_id": product_id,
        "user_id": message.from_user.id,
        "username": message.from_user.username or "Без username",
        "name": data["name"],
        "description": data["description"],
        "price": data["price"],
        "category": data.get("category", "Без категории"),
        "material": material,
        "delivery_type": data.get("delivery_type", "auto"),
        "stock": data.get("stock", None),
        "created_at": datetime.now().isoformat(),
        "status": "pending"
    }
    
    db.add_pending_product(pending_product)
    
    # Уведомляем пользователя
    await message.answer(
        f"✅ <b>Товар отправлен на модерацию!</b>\n\n"
        f"Название: {data['name']}\n"
        f"Описание: {data['description']}\n"
        f"Цена: {data['price']} ⭐\n"
        f"Категория: {data.get('category', 'Без категории')}\n\n"
        f"⏳ Товар будет проверен администратором и добавлен в каталог после одобрения.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В профиль", callback_data="back_to_profile")]
        ]),
        parse_mode=ParseMode.HTML
    )
    
    # Уведомляем админов
    for admin_id in ADMIN_IDS:
        try:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_product_{product_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_product_{product_id}")]
            ])
            
            await message.bot.send_message(
                admin_id,
                f"🔔 <b>Новый товар на модерации</b>\n\n"
                f"👤 От: @{message.from_user.username or message.from_user.id} (ID: {message.from_user.id})\n\n"
                f"📝 Название: {data['name']}\n"
                f"📄 Описание: {data['description']}\n"
                f"💰 Цена: {data['price']} ⭐\n"
                f"📁 Категория: {data.get('category', 'Без категории')}\n"
                f"📦 Материал: {'Текст' if material['type'] == 'text' else material['type'].capitalize()}\n\n"
                f"ID товара: <code>{product_id}</code>",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
    
    logger.info(f"Пользователь {message.from_user.id} добавил товар на модерацию: {product_id}")
    await state.clear()


@router.callback_query(F.data == "user_cancel_product")
async def user_cancel_product(callback: CallbackQuery, state: FSMContext):
    """Отмена добавления товара"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Добавление товара отменено",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В профиль", callback_data="back_to_profile")]
        ])
    )
    await callback.answer()


# ============= АДМИН: МОДЕРАЦИЯ ТОВАРОВ =============
@router.callback_query(F.data.startswith("approve_product_"))
async def admin_approve_product(callback: CallbackQuery):
    """Одобрение товара администратором"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    product_id = callback.data.replace("approve_product_", "")
    
    if db.approve_pending_product(product_id):
        await callback.message.edit_text(
            f"✅ <b>Товар одобрен и добавлен в каталог!</b>\n\n"
            f"ID: <code>{product_id}</code>",
            parse_mode=ParseMode.HTML
        )
        
        # Уведомляем пользователя
        pending = next((p for p in db.data.get("pending_products", []) 
                       if p.get("product_id") == product_id), None)
        if pending:
            try:
                await callback.bot.send_message(
                    pending["user_id"],
                    f"✅ <b>Ваш товар одобрен и выставлен на продажу!</b>\n\n"
                    f"📝 Товар: <b>\"{pending['name']}\"</b>\n"
                    f"💰 Цена: {pending['price']} ⭐\n"
                    f"📁 Категория: {pending.get('category', 'Без категории')}\n\n"
                    f"🎉 Товар добавлен в каталог и теперь его могут покупать другие пользователи!\n\n"
                    f"💡 При каждой продаже вы получите 98% от цены на баланс.",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        
        logger.info(f"Админ {callback.from_user.id} одобрил товар {product_id}")
    else:
        await callback.answer("❌ Товар не найден!", show_alert=True)
    
    await callback.answer()


@router.callback_query(F.data.startswith("reject_product_"))
async def admin_reject_product(callback: CallbackQuery):
    """Отклонение товара администратором"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    product_id = callback.data.replace("reject_product_", "")
    pending = next((p for p in db.data.get("pending_products", []) 
                   if p.get("product_id") == product_id), None)
    
    if pending:
        db.remove_pending_product(product_id)
        await callback.message.edit_text(
            f"❌ <b>Товар отклонен</b>\n\n"
            f"ID: <code>{product_id}</code>",
            parse_mode=ParseMode.HTML
        )
        
        # Уведомляем пользователя
        try:
            await callback.bot.send_message(
                pending["user_id"],
                f"❌ <b>Ваш товар отклонен</b>\n\n"
                f"Товар <b>\"{pending['name']}\"</b> был отклонен администратором.\n\n"
                f"Возможные причины:\n"
                f"• Нарушение правил (18+, базы данных, краденые аккаунты)\n"
                f"• Некорректное описание\n"
                f"• Другая причина",
                parse_mode=ParseMode.HTML
            )
        except:
            pass
        
        logger.info(f"Админ {callback.from_user.id} отклонил товар {product_id}")
    else:
        await callback.answer("❌ Товар не найден!", show_alert=True)
    
    await callback.answer()


# ============= АДМИН: ТОВАРЫ НА МОДЕРАЦИИ =============
@router.callback_query(F.data == "admin_pending_products")
async def admin_pending_products(callback: CallbackQuery):
    """Просмотр товаров на модерации"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    pending = db.get_pending_products()
    if not pending:
        await callback.message.edit_text(
            "🔍 <b>Нет товаров на модерации</b>\n\n"
            "Все товары обработаны!",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return
    
    text = f"🔍 <b>Товары на модерации:</b> {len(pending)}\n\n"
    keyboard = []
    
    for product in pending:
        date = datetime.fromisoformat(product.get("created_at", datetime.now().isoformat())).strftime("%d.%m.%Y %H:%M")
        text += (
            f"📝 <b>{product['name']}</b>\n"
            f"💰 {product['price']} ⭐\n"
            f"👤 @{product['username']} (ID: {product['user_id']})\n"
            f"📅 {date}\n\n"
        )
        keyboard.append([
            InlineKeyboardButton(text=f"✅ Одобрить", callback_data=f"approve_product_{product['product_id']}"),
            InlineKeyboardButton(text=f"❌ Отклонить", callback_data=f"reject_product_{product['product_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ============= INLINE РЕЖИМ - ОТПРАВКА РЕКЛАМЫ =============
@router.inline_query()
async def process_inline_query(inline_query: InlineQuery):
    """Обработка inline запросов для отправки рекламы"""
    try:
        user_id = inline_query.from_user.id
        query = inline_query.query.strip()
        
        logger.info(f"Inline query от пользователя {user_id}, query: '{query}'")
        
        # Получаем username бота
        bot_me = await inline_query.bot.get_me()
        bot_username = bot_me.username
        
        # Создаем реферальную ссылку для пользователя
        referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        
        # Текст рекламного сообщения
        ad_text = (
            "Привет! 👋\n\n"
            "Смотри какой бот для покупки цифровых товаров: @SharkBuy_rebot"
        )
        
        # Создаем кнопку с реферальной ссылкой
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Перейти в бот", url=referral_link)]
        ])
        
        # Создаем результат inline запроса
        # Используем уникальный ID на основе user_id для кэширования
        result = InlineQueryResultArticle(
            id=f"ad_{user_id}_{int(time.time())}",  # Уникальный ID
            title="📢 Отправить рекламу",
            description="Отправить рекламное сообщение",
            input_message_content=InputTextMessageContent(
                message_text=ad_text,
                parse_mode=ParseMode.HTML
            ),
            reply_markup=keyboard
        )
        
        # Отвечаем на запрос, показывая результат даже при пустом query
        await inline_query.answer([result], cache_time=0, is_personal=False)
        logger.info(f"Inline query обработан для пользователя {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки inline запроса: {e}", exc_info=True)
        try:
            await inline_query.answer([], cache_time=1)
        except:
            pass


@router.callback_query(F.data == "activate_promo")
async def process_activate_promo(callback: CallbackQuery, state: FSMContext):
    """Активация промокода"""
    await callback.message.edit_text(
        "🎫 <b>Активация промокода</b>\n\n"
        "Введите промокод для получения бонуса:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_profile")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_promo_code)
    await callback.answer()


@router.message(AdminStates.waiting_promo_code)
async def process_promo_code_input(message: Message, state: FSMContext):
    """Обработка введенного промокода"""
    code = message.text.strip()
    user_id = message.from_user.id
    
    amount, error = db.use_promo_code(code, user_id)
    
    if error:
        await message.answer(
            f"❌ <b>Ошибка!</b>\n\n{error}",
            parse_mode=ParseMode.HTML
        )
    else:
        new_balance = db.get_balance(user_id)
        await message.answer(
            f"✅ <b>Промокод активирован!</b>\n\n"
            f"🎁 Бонус: <b>{amount} ⭐</b>\n"
            f"💳 Ваш баланс: <b>{new_balance} ⭐</b>",
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Пользователь {user_id} активировал промокод {code}")
    
    await state.clear()


@router.message(Command("buy"))
@router.message(F.text == "🛍️ Каталог товаров")
async def cmd_buy(message: Message):
    """Показать каталог товаров"""
    keyboard = get_main_keyboard()
    await message.answer(
        "🛍️ <b>Каталог товаров</b>\n\nВыберите товар:",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


@router.message(Command("myorders"))
@router.message(F.text == "📜 Мои заказы")
async def cmd_my_orders(message: Message):
    orders = db.get_user_orders(message.from_user.id)
    if not orders:
        await message.answer("📜 У вас пока нет заказов.")
        return
    
    text = "📜 <b>Ваши заказы:</b>\n\n"
    for i, order in enumerate(reversed(orders[-10:]), 1):  # Последние 10 заказов
        date = datetime.fromisoformat(order["date"]).strftime("%d.%m.%Y %H:%M")
        status_emoji = "✅" if order.get("status") == "completed" else "⏳"
        text += f"{i}. {status_emoji} {order['product_name']} - {order['price']} ⭐\n   📅 {date}\n\n"
    
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("referral"))
@router.message(F.text == "🎯 Реферальная программа")
async def cmd_referral(message: Message):
    """Реферальная программа"""
    user_id = message.from_user.id
    referrals = db.get_referrals(user_id)
    referral_link = f"https://t.me/{(await message.bot.get_me()).username}?start=ref_{user_id}"
    
    text = (
        "🎯 <b>Реферальная программа</b>\n\n"
        "🎁 Приглашайте друзей и получайте бонусы!\n\n"
        f"👥 Ваших рефералов: <b>{len(referrals)}</b>\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        "💡 <i>За каждого друга вы получите бонус!</i>"
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("pay"))
async def cmd_pay(message: Message):
    """Выдача баланса пользователю (только для админов)"""
    if not is_admin(message.from_user.id):
        return  # Не отвечаем не-админам
    
    try:
        parts = message.text.split()
        if len(parts) < 3:
            await message.answer(
                "❌ <b>Неверный формат команды</b>\n\n"
                "Использование: <code>/pay &lt;user_id&gt; &lt;сумма&gt;</code>\n\n"
                "Пример: <code>/pay 123456789 100</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        user_id = int(parts[1])
        amount = int(parts[2])
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0!")
            return
        
        new_balance = db.add_balance(user_id, amount)
        
        await message.answer(
            f"✅ <b>Баланс выдан!</b>\n\n"
            f"👤 Пользователь: <code>{user_id}</code>\n"
            f"💰 Выдано: {amount} ⭐\n"
            f"💳 Новый баланс: {new_balance} ⭐",
            parse_mode=ParseMode.HTML
        )
        
        # Уведомляем пользователя
        try:
            await message.bot.send_message(
                user_id,
                f"💰 <b>Вам начислен баланс!</b>\n\n"
                f"💰 Зачислено: {amount} ⭐\n"
                f"💳 Ваш баланс: {new_balance} ⭐",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            await message.answer(f"⚠️ Баланс выдан, но не удалось уведомить пользователя (возможно, он не начинал диалог с ботом)")
        
        logger.info(f"Админ {message.from_user.id} выдал {amount} ⭐ пользователю {user_id}")
        
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка!</b>\n\n"
            "ID пользователя и сумма должны быть числами.\n\n"
            "Использование: <code>/pay &lt;user_id&gt; &lt;сумма&gt;</code>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /pay: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        # Не отвечаем не-админам
        logger.warning(f"Попытка доступа к админ-панели от {message.from_user.id}")
        return

    total_users = len(db.get_all_users())
    await message.answer(
        f"<b>🔧 Админ-панель</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n\n"
        f"Выберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    logger.info(f"Админ {message.from_user.id} открыл админ-панель")


@router.message(Command("send"))
async def cmd_send(message: Message):
    """Рассылка сообщений всем пользователям"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа!")
        return
    
    # Получаем текст после команды
    text = message.text.replace("/send", "").strip()
    
    if not text:
        await message.answer(
            "📢 <b>Рассылка сообщений</b>\n\n"
            "Использование:\n"
            "<code>/send Ваше сообщение</code>\n\n"
            "Сообщение будет отправлено всем пользователям бота.",
            parse_mode=ParseMode.HTML
        )
        return
    
    all_users = db.get_all_users()
    
    if not all_users:
        await message.answer("❌ Нет пользователей для рассылки!")
        return
    
    # Сохраняем текст рассылки временно
    if not hasattr(message.bot, "_broadcast_text"):
        message.bot._broadcast_text = {}
    if not hasattr(message.bot, "_broadcast_button"):
        message.bot._broadcast_button = {}
    
    message.bot._broadcast_text[message.from_user.id] = text
    message.bot._broadcast_button[message.from_user.id] = None  # Пока кнопки нет
    
    # Спрашиваем, нужно ли добавить кнопку
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="broadcast_add_button")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="broadcast_no_button")]
    ])
    
    await message.answer(
        f"📢 <b>Рассылка сообщения</b>\n\n"
        f"Сообщение будет отправлено <b>{len(all_users)}</b> пользователям:\n\n"
        f"<i>{text[:200]}{'...' if len(text) > 200 else ''}</i>\n\n"
        f"Добавить к сообщению кнопку?",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "broadcast_no_button")
async def process_broadcast_no_button(callback: CallbackQuery):
    """Рассылка без кнопки - сразу подтверждение"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    # Показываем подтверждение
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    text = callback.bot._broadcast_text.get(callback.from_user.id, "")
    all_users = db.get_all_users()
    
    await callback.message.edit_text(
        f"📢 <b>Подтверждение рассылки</b>\n\n"
        f"Сообщение будет отправлено <b>{len(all_users)}</b> пользователям:\n\n"
        f"<i>{text[:200]}{'...' if len(text) > 200 else ''}</i>\n\n"
        f"Вы уверены?",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data == "broadcast_add_button")
async def process_broadcast_add_button(callback: CallbackQuery, state: FSMContext):
    """Запрос данных кнопки для рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🔘 <b>Добавление кнопки</b>\n\n"
        "Напишите текст кнопки и ссылку в формате:\n"
        "<code>текст - ссылка</code>\n\n"
        "Пример:\n"
        "<code>канал - sharkbuys.t.me</code>\n\n"
        "Или:\n"
        "<code>Перейти - https://t.me/sharkbuys</code>",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_broadcast_button)
    await callback.answer()


@router.message(AdminStates.waiting_broadcast_button)
async def process_broadcast_button_input(message: Message, state: FSMContext):
    """Обработка ввода текста кнопки и ссылки"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    try:
        # Парсим формат "текст - ссылка"
        input_text = message.text.strip()
        if " - " not in input_text:
            await message.answer(
                "❌ <b>Неверный формат!</b>\n\n"
                "Используйте формат: <code>текст - ссылка</code>\n\n"
                "Пример: <code>канал - sharkbuys.t.me</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        parts = input_text.split(" - ", 1)
        button_text = parts[0].strip()
        button_url = parts[1].strip()
        
        if not button_text or not button_url:
            await message.answer("❌ Текст кнопки и ссылка не могут быть пустыми!")
            return
        
        # Нормализуем ссылку (добавляем https:// если нужно)
        if not button_url.startswith(("http://", "https://", "t.me/", "@")):
            if button_url.startswith("sharkbuys.t.me") or "." in button_url:
                button_url = f"https://{button_url}"
            else:
                # Если это просто username без @, добавляем t.me/
                button_url = f"https://t.me/{button_url.replace('@', '')}"
        
        # Сохраняем данные кнопки
        if not hasattr(message.bot, "_broadcast_button"):
            message.bot._broadcast_button = {}
        message.bot._broadcast_button[message.from_user.id] = {
            "text": button_text,
            "url": button_url
        }
        
        await state.clear()
        
        # Показываем подтверждение
        text = message.bot._broadcast_text.get(message.from_user.id, "")
        all_users = db.get_all_users()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, отправить", callback_data="broadcast_confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
        ])
        
        await message.answer(
            f"📢 <b>Подтверждение рассылки</b>\n\n"
            f"Сообщение будет отправлено <b>{len(all_users)}</b> пользователям:\n\n"
            f"<i>{text[:200]}{'...' if len(text) > 200 else ''}</i>\n\n"
            f"🔘 Кнопка: <b>{button_text}</b> → {button_url}\n\n"
            f"Вы уверены?",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки кнопки рассылки: {e}")
        await message.answer("❌ Ошибка! Попробуйте еще раз.")
        await state.clear()


@router.callback_query(F.data == "broadcast_confirm")
async def process_broadcast_confirm(callback: CallbackQuery):
    """Подтверждение и выполнение рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    # Получаем текст рассылки
    text = callback.bot._broadcast_text.get(callback.from_user.id)
    if not text:
        await callback.answer("❌ Текст рассылки не найден!", show_alert=True)
        return
    
    # Получаем данные кнопки (если есть)
    button_data = callback.bot._broadcast_button.get(callback.from_user.id)
    
    await callback.message.edit_text("📤 <b>Рассылка началась...</b>", parse_mode=ParseMode.HTML)
    
    all_users = db.get_all_users()
    success = 0
    failed = 0
    
    # Создаем клавиатуру с кнопкой (если есть)
    reply_markup = None
    if button_data:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button_data["text"], url=button_data["url"])]
        ])
        reply_markup = keyboard
    
    for user_id in all_users:
        try:
            await callback.bot.send_message(
                user_id, 
                text, 
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            success += 1
            await asyncio.sleep(0.05)  # Задержка для избежания flood control
        except Exception as e:
            failed += 1
            logger.error(f"Ошибка рассылки пользователю {user_id}: {e}")
    
    # Удаляем сохраненные данные
    if callback.from_user.id in callback.bot._broadcast_text:
        del callback.bot._broadcast_text[callback.from_user.id]
    if callback.from_user.id in callback.bot._broadcast_button:
        del callback.bot._broadcast_button[callback.from_user.id]
    
    await callback.message.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}\n"
        f"📊 Всего: {len(all_users)}",
        parse_mode=ParseMode.HTML
    )
    
    logger.info(f"Админ {callback.from_user.id} выполнил рассылку: {success} успешно, {failed} ошибок")


@router.callback_query(F.data == "broadcast_cancel")
async def process_broadcast_cancel(callback: CallbackQuery):
    """Отмена рассылки"""
    if hasattr(callback.bot, "_broadcast_text") and callback.from_user.id in callback.bot._broadcast_text:
        del callback.bot._broadcast_text[callback.from_user.id]
    if hasattr(callback.bot, "_broadcast_button") and callback.from_user.id in callback.bot._broadcast_button:
        del callback.bot._broadcast_button[callback.from_user.id]
    
    await callback.message.edit_text("❌ Рассылка отменена", parse_mode=ParseMode.HTML)
    await callback.answer()


# ============= ПОКУПКА ТОВАРА =============
@router.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    try:
        product_id = callback.data.replace("buy_", "")
        logger.info(f"Попытка покупки товара {product_id} пользователем {callback.from_user.id}")

        product = db.get_product(product_id)

        if not product:
            await callback.answer("❌ Товар не найден!", show_alert=True)
            logger.warning(f"Товар {product_id} не найден")
            return

        # Проверка остатка товара
        stock = product.get("stock")
        if stock is not None and stock <= 0:
            await callback.answer("❌ Товар закончился!", show_alert=True)
            return

        await callback.answer()

        # БЕСПЛАТНАЯ ВЫДАЧА для товаров за 0 звезд
        if product["price"] == 0:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎁 Получить бесплатно", callback_data=f"get_free_{product_id}")]
            ])
            await callback.message.answer(
                f"🎁 <b>Бесплатный товар!</b>\n\n"
                f"🛍 Товар: {product['name']}\n"
                f"💰 Цена: БЕСПЛАТНО\n\n"
                f"Нажмите кнопку ниже, чтобы получить товар:",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            return

        # Сначала спрашиваем количество
        max_quantity = stock if stock is not None else 10  # Максимум 10 или остаток
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 шт.", callback_data=f"qty_{product_id}_1"),
             InlineKeyboardButton(text="2 шт.", callback_data=f"qty_{product_id}_2"),
             InlineKeyboardButton(text="3 шт.", callback_data=f"qty_{product_id}_3")],
            [InlineKeyboardButton(text="5 шт.", callback_data=f"qty_{product_id}_5"),
             InlineKeyboardButton(text="10 шт.", callback_data=f"qty_{product_id}_10")],
        ])
        
        await callback.message.answer(
            f"🛍 <b>{product['name']}</b>\n\n"
            f"💰 Цена за 1 шт.: {product['price']} ⭐\n\n"
            "Выберите количество:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка при покупке: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)}")


@router.callback_query(F.data.startswith("qty_"))
async def process_quantity(callback: CallbackQuery):
    """Обработка выбора количества"""
    try:
        # Используем rsplit чтобы разделить только по последнему подчеркиванию
        # Формат: qty_product_id_quantity
        data = callback.data.replace("qty_", "")
        parts = data.rsplit("_", 1)  # Разделяем только по последнему "_"
        if len(parts) != 2:
            await callback.answer("❌ Ошибка формата!", show_alert=True)
            return
        
        product_id = parts[0]
        quantity = int(parts[1])
        
        product = db.get_product(product_id)
        if not product:
            await callback.answer("❌ Товар не найден!", show_alert=True)
            return
        
        # Проверка остатка
        stock = product.get("stock")
        if stock is not None and stock < quantity:
            await callback.answer(f"❌ Недостаточно товара! В наличии: {stock} шт.", show_alert=True)
            return
        
        await callback.answer()
        
        user_balance = db.get_balance(callback.from_user.id)
        total_price = product["price"] * quantity
        
        # Создаем клавиатуру с вариантами оплаты
        # Обычные пользователи могут оплачивать балансом только если у них есть заработанные средства
        keyboard_buttons = []
        
        # Показываем кнопку баланса только если у пользователя есть баланс (заработанные средства)
        if user_balance > 0:
            keyboard_buttons.append([InlineKeyboardButton(text=f"💰 Баланс ({user_balance} ⭐)", callback_data=f"pay_balance_{product_id}_{quantity}")])
        
        keyboard_buttons.extend([
            [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay_stars_{product_id}_{quantity}")],
            [InlineKeyboardButton(text="💳 CryptoBot (USDT)", callback_data=f"pay_crypto_{product_id}_{quantity}")]
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.answer(
            f"🛍 <b>{product['name']}</b>\n\n"
            f"📦 Количество: {quantity} шт.\n"
            f"💰 Цена за 1 шт.: {product['price']} ⭐\n"
            f"💵 <b>Итого: {total_price} ⭐</b>\n\n"
            "Выберите способ оплаты:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка при выборе количества: {e}")
        await callback.answer("❌ Ошибка!", show_alert=True)


@router.callback_query(F.data.startswith("pay_balance_"))
async def process_pay_with_balance(callback: CallbackQuery):
    """Оплата товара балансом"""
    try:
        # Используем rsplit чтобы разделить только по последнему подчеркиванию
        data = callback.data.replace("pay_balance_", "")
        parts = data.rsplit("_", 1)
        if len(parts) != 2:
            await callback.answer("❌ Ошибка формата!", show_alert=True)
            return
        
        product_id = parts[0]
        quantity = int(parts[1])
        
        product = db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден!", show_alert=True)
            return
        
        user_id = callback.from_user.id
        balance = db.get_balance(user_id)
        price = product["price"] * quantity
        
        if balance < price:
            await callback.answer(
                f"❌ Недостаточно средств!\n\n"
                f"Ваш баланс: {balance} ⭐\n"
                f"Нужно: {price} ⭐\n\n"
                "Пополните баланс в личном кабинете!",
                show_alert=True
            )
            return
        
        # Списываем средства
        if not db.subtract_balance(user_id, price):
            await callback.answer("❌ Ошибка списания средств!", show_alert=True)
            return
        
        await callback.answer("✅ Оплачено!", show_alert=True)
        
        # Выдаем товар
        delivery_type = product.get("delivery_type", "auto")
        
        await callback.message.answer(
            f"✅ <b>Спасибо за покупку!</b>\n\n"
            f"Товар: {product['name']}\n"
            f"Количество: {quantity} шт.\n"
            f"Цена: {price} ⭐\n"
            f"Списано с баланса: {price} ⭐\n"
            f"Остаток: {db.get_balance(user_id)} ⭐\n\n"
            "💬 Хотите оставить сообщение к заказу? (Напишите сообщение или отправьте /skip)",
            parse_mode=ParseMode.HTML
        )
        
        # Сохраняем данные для запроса сообщения в БД (временное решение)
        if "buy_messages" not in db.data:
            db.data["buy_messages"] = {}
        db.data["buy_messages"][str(user_id)] = {
            "product_id": product_id,
            "quantity": quantity,
            "price": price,
            "payment_type": "balance"
        }
        db.save()
        
        if delivery_type == "manual":
            # Ручная выдача
            pending = db.add_pending_order(
                user_id,
                callback.from_user.username or "Без username",
                product_id,
                product["name"],
                price,
                quantity
            )
            
            await callback.message.answer(
                "⏳ <b>Ваш заказ принят!</b>\n\n"
                "Товар будет выдан вручную администратором.",
                parse_mode=ParseMode.HTML
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Выдать товар", callback_data=f"deliver_{pending['order_id']}")]
                    ])
                    await callback.bot.send_message(
                        admin_id,
                        f"🔔 <b>Новый заказ (оплата балансом)!</b>\n\n"
                        f"Товар: {product['name']}\n"
                        f"Количество: {quantity} шт.\n"
                        f"Цена: {price} ⭐\n"
                        f"Покупатель: @{callback.from_user.username or callback.from_user.id}",
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )
                except:
                    pass
            
            db.add_order(user_id, callback.from_user.username or "Без username",
                        product_id, product["name"], price, status="pending", quantity=quantity)
        else:
            # Автоматическая выдача - выдаем quantity раз
            material = product["material"]
            for i in range(quantity):
                if material["type"] == "text":
                    await callback.message.answer(f"📄 <b>Ваш материал ({i+1}/{quantity}):</b>\n\n{material['content']}", parse_mode=ParseMode.HTML)
                elif material["type"] == "file":
                    await callback.message.answer_document(document=material["file_id"], caption=f"📄 Ваш материал ({i+1}/{quantity})")
                elif material["type"] == "photo":
                    await callback.message.answer_photo(photo=material["file_id"], caption=f"📄 Ваш материал ({i+1}/{quantity})")
                elif material["type"] == "video":
                    await callback.message.answer_video(video=material["file_id"], caption=f"📄 Ваш материал ({i+1}/{quantity})")
                await asyncio.sleep(0.5)  # Небольшая задержка между выдачами
            
            # Начисляем деньги владельцу товара (98% от цены, 2% комиссия)
            owner_id = product.get("owner_id")
            if owner_id and owner_id != user_id:  # Если товар принадлежит пользователю
                owner_earnings = int(price * 0.98)  # 98% владельцу
                db.add_balance(owner_id, owner_earnings)
                
                # Уведомляем владельца
                try:
                    await callback.bot.send_message(
                        owner_id,
                        f"💰 <b>Ваш товар куплен!</b>\n\n"
                        f"Товар: {product['name']}\n"
                        f"Количество: {quantity} шт.\n"
                        f"Цена: {price} ⭐\n"
                        f"💰 Вам начислено: <b>{owner_earnings} ⭐</b> (98%)\n"
                        f"💳 Ваш баланс: {db.get_balance(owner_id)} ⭐\n\n"
                        f"Покупатель: @{callback.from_user.username or callback.from_user.id}",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
                logger.info(f"Владельцу товара {owner_id} начислено {owner_earnings} ⭐ за покупку товара {product_id}")
            
            for admin_id in ADMIN_IDS:
                try:
                    await callback.bot.send_message(
                        admin_id,
                        f"💰 <b>Продажа (баланс)!</b>\n\n"
                        f"Товар: {product['name']}\n"
                        f"Количество: {quantity} шт.\n"
                        f"Цена: {price} ⭐\n"
                        f"Покупатель: @{callback.from_user.username or callback.from_user.id}",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
            
            db.add_order(user_id, callback.from_user.username or "Без username",
                        product_id, product["name"], price, status="completed", quantity=quantity)
        
        # Уменьшаем остаток на quantity
        for _ in range(quantity):
            db.decrease_stock(product_id)
        logger.info(f"Товар {product_id} куплен за баланс пользователем {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка оплаты балансом: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("pay_stars_"))
async def process_pay_with_stars(callback: CallbackQuery):
    """Оплата товара Telegram Stars"""
    try:
        # Используем rsplit чтобы разделить только по последнему подчеркиванию
        data = callback.data.replace("pay_stars_", "")
        parts = data.rsplit("_", 1)
        if len(parts) != 2:
            await callback.answer("❌ Ошибка формата!", show_alert=True)
            return
        
        product_id = parts[0]
        quantity = int(parts[1])
        
        product = db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден!", show_alert=True)
            return
        
        # Проверка остатка
        stock = product.get("stock")
        if stock is not None and stock < quantity:
            await callback.answer(f"❌ Недостаточно товара! В наличии: {stock} шт.", show_alert=True)
            return
        
        total_price = max(1, product["price"] * quantity)
        prices = [LabeledPrice(label=f"{product['name']} x{quantity}", amount=total_price)]

        await callback.message.answer_invoice(
            title=f"{product['name']} x{quantity}",
            description=product["description"],
            payload=f"product_{product_id}_{quantity}",
            provider_token="",
            currency="XTR",
            prices=prices
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка оплаты звездами: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ============= CRYPTOBOT ОПЛАТА =============
async def create_cryptobot_invoice(user_id: int, product_name: str, amount: float, payload: str) -> Optional[dict]:
    """Создать инвойс через CryptoBot API"""
    try:
        url = f"{CRYPTOBOT_API_URL}createInvoice"
        headers = {
            "Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN,
            "Content-Type": "application/json"
        }
        data = {
            "asset": "USDT",
            "amount": str(amount),
            "description": product_name,
            "hidden_message": payload,
            "paid_btn_name": "viewItem",
            "paid_btn_url": f"https://t.me/{BOT_CREATOR.replace('@', '')}",
            "payload": payload
        }
        
        logger.info(f"Создание CryptoBot инвойса: {data}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as response:
                response_text = await response.text()
                logger.info(f"CryptoBot API response status: {response.status}, body: {response_text}")
                
                if response.status == 200:
                    try:
                        result = await response.json()
                        logger.info(f"CryptoBot API JSON response: {result}")
                        if result.get("ok"):
                            return result.get("result")
                        else:
                            error_msg = result.get("error", {}).get("name", "Unknown error")
                            logger.error(f"CryptoBot API error: {result}")
                            return None
                    except Exception as json_error:
                        logger.error(f"Ошибка парсинга JSON ответа CryptoBot: {json_error}, response: {response_text}")
                        return None
                else:
                    logger.error(f"CryptoBot API HTTP error: {response.status}, response: {response_text}")
                    return None
    except Exception as e:
        logger.error(f"Ошибка создания CryptoBot инвойса: {e}", exc_info=True)
        return None


def verify_cryptobot_signature(data: dict, signature: str) -> bool:
    """Проверка подписи запроса от CryptoBot"""
    try:
        # Создаем строку для проверки подписи
        data_str = json.dumps(data, separators=(',', ':'), sort_keys=True)
        secret_key = CRYPTOBOT_API_TOKEN.split(':')[1] if ':' in CRYPTOBOT_API_TOKEN else CRYPTOBOT_API_TOKEN
        
        # Вычисляем HMAC SHA256
        expected_signature = hmac.new(
            secret_key.encode(),
            data_str.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
    except Exception as e:
        logger.error(f"Ошибка проверки подписи CryptoBot: {e}")
        return False


@router.callback_query(F.data.startswith("pay_crypto_"))
async def process_pay_with_crypto(callback: CallbackQuery):
    """Оплата товара через CryptoBot"""
    try:
        # Используем rsplit чтобы разделить только по последнему подчеркиванию
        data = callback.data.replace("pay_crypto_", "")
        parts = data.rsplit("_", 1)
        if len(parts) != 2:
            await callback.answer("❌ Ошибка формата!", show_alert=True)
            return
        
        product_id = parts[0]
        quantity = int(parts[1])
        
        product = db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден!", show_alert=True)
            return
        
        # Проверка остатка
        stock = product.get("stock")
        if stock is not None and stock < quantity:
            await callback.answer(f"❌ Недостаточно товара! В наличии: {stock} шт.", show_alert=True)
            return
        
        total_price = product["price"] * quantity
        
        # Конвертация: 50 звезд = $0.75, значит 1 звезда = $0.015
        usdt_amount = total_price * 0.015
        
        await callback.answer()
        
        # Создаем инвойс через CryptoBot
        payload = f"product_{product_id}_{quantity}"
        invoice = await create_cryptobot_invoice(
            callback.from_user.id,
            f"{product['name']} x{quantity}",
            usdt_amount,
            payload
        )
        
        if not invoice:
            await callback.message.answer(
                "❌ <b>Ошибка создания платежа</b>\n\n"
                "Не удалось создать инвойс через CryptoBot. Попробуйте другой способ оплаты.",
                parse_mode=ParseMode.HTML
            )
            return
        
        invoice_url = invoice.get("pay_url")
        invoice_id = invoice.get("invoice_id")
        
        if not invoice_id:
            await callback.message.answer(
                "❌ <b>Ошибка создания платежа</b>\n\n"
                "Не удалось получить ID инвойса от CryptoBot.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Сохраняем invoice_id для проверки
        if "crypto_invoices" not in db.data:
            db.data["crypto_invoices"] = {}
        db.data["crypto_invoices"][str(invoice_id)] = {
            "user_id": callback.from_user.id,
            "product_id": product_id,
            "quantity": quantity,
            "price": total_price,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        db.save()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить через CryptoBot", url=invoice_url)]
        ])
        
        await callback.message.answer(
            f"💳 <b>Оплата через CryptoBot</b>\n\n"
            f"Товар: {product['name']}\n"
            f"Количество: {quantity} шт.\n"
            f"Сумма: {usdt_amount:.2f} USDT\n\n"
            f"Нажмите кнопку ниже для оплаты:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка оплаты через CryptoBot: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(Command("cryptobot_webhook"))
async def cryptobot_webhook_handler(message: Message):
    """Обработчик webhook от CryptoBot (для ручной проверки)"""
    if not is_admin(message.from_user.id):
        return
    
    # Это команда для тестирования, реальный webhook будет через HTTP
    await message.answer("Webhook обрабатывается автоматически при оплате через CryptoBot")


@router.message(Command("check_crypto_payment"))
async def check_crypto_payment(message: Message, state: FSMContext):
    """Проверка статуса платежа CryptoBot (для админов)"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        # Получаем список ожидающих платежей
        if "crypto_invoices" not in db.data:
            await message.answer("Нет ожидающих платежей через CryptoBot.")
            return
        
        pending = [inv for inv in db.data["crypto_invoices"].values() if inv["status"] == "pending"]
        
        if not pending:
            await message.answer("Нет ожидающих платежей через CryptoBot.")
            return
        
        text = f"⏳ <b>Ожидающие платежи CryptoBot:</b> {len(pending)}\n\n"
        for inv in pending[:10]:  # Показываем первые 10
            text += f"ID: {inv.get('invoice_id', 'N/A')}\n"
            text += f"Пользователь: {inv['user_id']}\n"
            text += f"Товар: {inv['product_id']}\n"
            text += f"Сумма: {inv['price']} ⭐\n\n"
        
        await message.answer(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка проверки платежей: {e}")


# Функция для проверки статуса инвойса через CryptoBot API
async def check_cryptobot_invoice_status(invoice_id: int) -> Optional[dict]:
    """Проверить статус инвойса через CryptoBot API"""
    try:
        url = f"{CRYPTOBOT_API_URL}getInvoices"
        headers = {
            "Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN
        }
        params = {
            "invoice_ids": str(invoice_id)
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok") and result.get("result", {}).get("items"):
                        return result["result"]["items"][0]
                    return None
                return None
    except Exception as e:
        logger.error(f"Ошибка проверки статуса инвойса: {e}")
        return None


@router.callback_query(F.data.startswith("get_free_"))
async def process_get_free(callback: CallbackQuery):
    """Бесплатная выдача товара за 0 звезд"""
    try:
        product_id = callback.data.replace("get_free_", "")
        product = db.get_product(product_id)

        if not product:
            await callback.answer("❌ Товар не найден!", show_alert=True)
            return

        if product["price"] != 0:
            await callback.answer("❌ Этот товар не бесплатный!", show_alert=True)
            return

        await callback.answer()
        delivery_type = product.get("delivery_type", "auto")

        await callback.message.answer(
            f"✅ <b>Вы получили бесплатный товар!</b>\n\n"
            f"Товар: {product['name']}\n"
            f"Цена: БЕСПЛАТНО 🎁",
            parse_mode=ParseMode.HTML
        )

        if delivery_type == "manual":
            pending = db.add_pending_order(
                callback.from_user.id,
                callback.from_user.username or "Без username",
                product_id,
                product["name"],
                0,
                quantity=1
            )
            
            await callback.message.answer(
                "⏳ <b>Ваш заказ принят!</b>\n\n"
                "Товар будет выдан вручную администратором.",
                parse_mode=ParseMode.HTML
            )

            for admin_id in ADMIN_IDS:
                try:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Выдать товар", callback_data=f"deliver_{pending['order_id']}")]
                    ])
                    await callback.bot.send_message(
                        admin_id,
                        f"🔔 <b>Бесплатный заказ!</b>\n\n"
                        f"Товар: {product['name']}\n"
                        f"Покупатель: @{callback.from_user.username or callback.from_user.id}",
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )
                except:
                    pass

            db.add_order(callback.from_user.id, callback.from_user.username or "Без username",
                        product_id, product["name"], 0, status="pending", quantity=1)
        else:
            # Автоматическая выдача бесплатного товара
            material = product["material"]
            if material["type"] == "text":
                await callback.message.answer(f"📄 <b>Ваш материал:</b>\n\n{material['content']}", parse_mode=ParseMode.HTML)
            elif material["type"] == "file":
                await callback.message.answer_document(document=material["file_id"], caption="📄 Ваш материал")
            elif material["type"] == "photo":
                await callback.message.answer_photo(photo=material["file_id"], caption="📄 Ваш материал")
            elif material["type"] == "video":
                await callback.message.answer_video(video=material["file_id"], caption="📄 Ваш материал")

            db.add_order(callback.from_user.id, callback.from_user.username or "Без username",
                        product_id, product["name"], 0, status="completed", quantity=1)

        db.decrease_stock(product_id)
        logger.info(f"Бесплатный товар {product_id} выдан {callback.from_user.id}")
    except Exception as e:
        logger.error(f"Ошибка бесплатной выдачи: {e}", exc_info=True)
        await callback.message.answer(f"❌ Ошибка: {str(e)}")


@router.callback_query(F.data.startswith("page_"))
async def process_page(callback: CallbackQuery):
    try:
        parts = callback.data.replace("page_", "").split("_")
        page = int(parts[0])
        category = "_".join(parts[1:]) if len(parts) > 1 else "Все"
        keyboard = get_main_keyboard(page, category)
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при смене страницы: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("cat_"))
async def process_category(callback: CallbackQuery):
    try:
        category = callback.data.replace("cat_", "")
        keyboard = get_main_keyboard(0, category)
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer(f"Категория: {category}")
    except Exception as e:
        logger.error(f"Ошибка при смене категории: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "my_orders")
async def process_my_orders(callback: CallbackQuery):
    orders = db.get_user_orders(callback.from_user.id)
    if not orders:
        await callback.answer("📜 У вас пока нет заказов.", show_alert=True)
        return
    
    text = "📜 <b>Ваши заказы:</b>\n\n"
    for i, order in enumerate(reversed(orders[-10:]), 1):
        date = datetime.fromisoformat(order["date"]).strftime("%d.%m.%Y %H:%M")
        text += f"{i}. {order['product_name']} - {order['price']} ⭐\n   📅 {date}\n\n"
    
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    """
    ВАЖНО: Это НЕ оплата! Это только ПРОВЕРКА перед оплатой.
    Telegram спрашивает "можно ли принять платёж?".
    НИКОГДА не выдавайте товар здесь!
    """
    try:
        # Проверяем наличие товара
        parts = pre_checkout_query.invoice_payload.replace("product_", "").split("_")
        product_id = parts[0]
        quantity = int(parts[1]) if len(parts) > 1 else 1
        
        product = db.get_product(product_id)
        
        if not product:
            await pre_checkout_query.answer(
                ok=False, 
                error_message="❌ Товар не найден"
            )
            logger.warning(f"Pre-checkout отклонён: товар {product_id} не найден")
            return
        
        # Проверяем остаток
        stock = product.get("stock")
        if stock is not None and stock < quantity:
            await pre_checkout_query.answer(
                ok=False,
                error_message=f"❌ Недостаточно товара! В наличии: {stock} шт."
            )
            logger.warning(f"Pre-checkout отклонён: товар {product_id} закончился (нужно {quantity}, есть {stock})")
            return
        
        # Всё ОК, можно принимать платёж
        await pre_checkout_query.answer(ok=True)
        logger.info(f"Pre-checkout одобрен для {pre_checkout_query.from_user.id}, товар {product_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в pre-checkout: {e}")
        await pre_checkout_query.answer(ok=False, error_message="Ошибка обработки платежа")


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    try:
        payment = message.successful_payment
        payload = payment.invoice_payload
        
        # Проверяем тип платежа
        if payload.startswith("topup_"):
            # Пополнение баланса (только для админов)
            if not is_admin(message.from_user.id):
                await message.answer("❌ Пополнение баланса недоступно! Зарабатывайте на продаже товаров.")
                return
            
            amount = int(payload.replace("topup_", ""))
            user_id = message.from_user.id
            
            new_balance = db.add_balance(user_id, amount)
            
            # Начисляем бонус рефереру (10% от пополнения)
            referrer_bonus = 0
            referrer_id = None
            for ref_id, referrals in db.data.get("referrals", {}).items():
                if user_id in referrals:
                    referrer_id = int(ref_id)
                    referrer_bonus = int(amount * 0.1)  # 10% бонус
                    db.add_balance(referrer_id, referrer_bonus)
                    
                    # Уведомляем реферера о бонусе
                    try:
                        await message.bot.send_message(
                            referrer_id,
                            f"🎉 <b>Реферальный бонус!</b>\n\n"
                            f"Ваш реферал @{message.from_user.username or 'пользователь'} "
                            f"пополнил баланс на {amount} ⭐\n\n"
                            f"💰 Вам начислено: <b>{referrer_bonus} ⭐</b>\n"
                            f"💳 Ваш баланс: {db.get_balance(referrer_id)} ⭐",
                            parse_mode=ParseMode.HTML
                        )
                    except:
                        pass
                    break
            
            bonus_text = f"\n\n🎁 <b>Реферальный бонус вашему другу: {referrer_bonus} ⭐</b>" if referrer_bonus > 0 else ""
            
            await message.answer(
                f"✅ <b>Баланс пополнен!</b>\n\n"
                f"💰 Зачислено: {amount} ⭐\n"
                f"💳 Новый баланс: {new_balance} ⭐{bonus_text}\n\n"
                f"Теперь вы можете покупать товары за баланс!",
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Пользователь {user_id} пополнил баланс на {amount} звезд. Бонус реферу: {referrer_bonus}")
            
            # Уведомляем админов
            for admin_id in ADMIN_IDS:
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"💰 <b>Пополнение баланса!</b>\n\n"
                        f"Пользователь: @{message.from_user.username or message.from_user.id}\n"
                        f"Сумма: {amount} ⭐\n"
                        f"Бонус реферу: {referrer_bonus} ⭐",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
            return
        
        
        # Обычный товар
        parts = payload.replace("product_", "").split("_")
        product_id = parts[0]
        quantity = int(parts[1]) if len(parts) > 1 else 1
        logger.info(f"Успешная оплата: product_id={product_id}, quantity={quantity}, user_id={message.from_user.id}")

        product = db.get_product(product_id)

        if not product:
            await message.answer(
                f"❌ Ошибка при получении товара!\n\n"
                f"ID товара: {product_id}\n"
                f"Доступные товары: {', '.join(db.get_products().keys())}\n\n"
                f"Обратитесь к администратору!"
            )
            # Уведомляем админов
            for admin_id in ADMIN_IDS:
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"⚠️ ОШИБКА! Пользователь @{message.from_user.username or message.from_user.id} "
                        f"оплатил товар {product_id}, но товар не найден в БД!"
                    )
                except:
                    pass
            return

        # Проверяем тип выдачи
        delivery_type = product.get("delivery_type", "auto")

        total_price = product['price'] * quantity
        
        # Отправляем подтверждение и запрашиваем сообщение
        await message.answer(
            f"✅ <b>Спасибо за покупку!</b>\n\n"
            f"Товар: {product['name']}\n"
            f"Количество: {quantity} шт.\n"
            f"Цена: {total_price} ⭐\n\n"
            "💬 Хотите оставить сообщение к заказу? (Напишите сообщение или отправьте /skip)",
            parse_mode=ParseMode.HTML
        )
        
        # Сохраняем данные для запроса сообщения в БД
        if "buy_messages" not in db.data:
            db.data["buy_messages"] = {}
        db.data["buy_messages"][str(message.from_user.id)] = {
            "product_id": product_id,
            "quantity": quantity,
            "price": total_price,
            "payment_type": "stars"
        }
        db.save()

        if delivery_type == "manual":
            # Ручная выдача - добавляем в очередь
            pending = db.add_pending_order(
                message.from_user.id,
                message.from_user.username or "Без username",
                product_id,
                product["name"],
                total_price,
                quantity
            )
            
            await message.answer(
                "⏳ <b>Ваш заказ принят!</b>\n\n"
                "Товар будет выдан вручную администратором.\n"
                "Вы получите уведомление после обработки.",
                parse_mode=ParseMode.HTML
            )

            # Уведомляем админов о новом заказе на ручную выдачу
            for admin_id in ADMIN_IDS:
                try:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Выдать товар", callback_data=f"deliver_{pending['order_id']}")]
                    ])
                    await message.bot.send_message(
                        admin_id,
                        f"🔔 <b>Новый заказ на ручную выдачу!</b>\n\n"
                        f"Товар: {product['name']}\n"
                        f"Количество: {quantity} шт.\n"
                        f"Цена: {total_price} ⭐\n"
                        f"Покупатель: @{message.from_user.username or message.from_user.id}\n"
                        f"ID: {message.from_user.id}",
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logger.error(f"Ошибка уведомления админа: {e}")

            # Сохраняем заказ как ожидающий
            db.add_order(
                message.from_user.id,
                message.from_user.username or "Без username",
                product_id,
                product["name"],
                total_price,
                status="pending",
                quantity=quantity
            )
        else:
            # Автоматическая выдача - выдаем quantity раз
            material = product["material"]
            for i in range(quantity):
                if material["type"] == "text":
                    await message.answer(
                        f"📄 <b>Ваш материал ({i+1}/{quantity}):</b>\n\n{material['content']}",
                        parse_mode=ParseMode.HTML
                    )
                elif material["type"] == "file":
                    await message.answer_document(
                        document=material["file_id"],
                        caption=f"📄 Ваш материал ({i+1}/{quantity})"
                    )
                elif material["type"] == "photo":
                    await message.answer_photo(
                        photo=material["file_id"],
                        caption=f"📄 Ваш материал ({i+1}/{quantity})"
                    )
                elif material["type"] == "video":
                    await message.answer_video(
                        video=material["file_id"],
                        caption=f"📄 Ваш материал ({i+1}/{quantity})"
                    )
                await asyncio.sleep(0.5)  # Небольшая задержка между выдачами

            # Начисляем деньги владельцу товара (98% от цены, 2% комиссия)
            owner_id = product.get("owner_id")
            if owner_id and owner_id != message.from_user.id:  # Если товар принадлежит пользователю
                owner_earnings = int(total_price * 0.98)  # 98% владельцу
                db.add_balance(owner_id, owner_earnings)
                
                # Уведомляем владельца
                try:
                    await message.bot.send_message(
                        owner_id,
                        f"💰 <b>Ваш товар куплен!</b>\n\n"
                        f"Товар: {product['name']}\n"
                        f"Количество: {quantity} шт.\n"
                        f"Цена: {total_price} ⭐\n"
                        f"💰 Вам начислено: <b>{owner_earnings} ⭐</b> (98%)\n"
                        f"💳 Ваш баланс: {db.get_balance(owner_id)} ⭐\n\n"
                        f"Покупатель: @{message.from_user.username or message.from_user.id}",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
                logger.info(f"Владельцу товара {owner_id} начислено {owner_earnings} ⭐ за покупку товара {product_id}")

            # Уведомляем админов о продаже
            for admin_id in ADMIN_IDS:
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"💰 <b>Новая продажа (авто)!</b>\n\n"
                        f"Товар: {product['name']}\n"
                        f"Количество: {quantity} шт.\n"
                        f"Цена: {total_price} ⭐\n"
                        f"Покупатель: @{message.from_user.username or message.from_user.id}",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass

            # Сохраняем заказ как выполненный
            db.add_order(
                message.from_user.id,
                message.from_user.username or "Без username",
                product_id,
                product["name"],
                total_price,
                status="completed",
                quantity=quantity
            )

        # Уменьшаем остаток товара на quantity
        for _ in range(quantity):
            db.decrease_stock(product_id)

    except Exception as e:
        logger.error(f"Критическая ошибка в successful_payment: {e}", exc_info=True)
        await message.answer(f"❌ Критическая ошибка: {str(e)}")


# ============= ОБРАБОТКА СООБЩЕНИЯ ПОСЛЕ ОПЛАТЫ =============
@router.message(Command("skip"))
async def skip_message(message: Message):
    """Пропустить сообщение после оплаты"""
    user_id = str(message.from_user.id)
    if "buy_messages" in db.data and user_id in db.data["buy_messages"]:
        del db.data["buy_messages"][user_id]
        db.save()
        await message.answer("✅ Сообщение пропущено.", parse_mode=ParseMode.HTML)


    
    buy_data = db.data["buy_messages"][user_id]
    product_id = buy_data["product_id"]
    quantity = buy_data["quantity"]
    price = buy_data["price"]
    payment_type = buy_data["payment_type"]
    
    # Удаляем из ожидающих
    del db.data["buy_messages"][user_id]
    db.save()
    
    # Сохраняем сообщение в заказе
    user_message = message.text
    
    # Уведомляем админов о сообщении
    for admin_id in ADMIN_IDS:
        try:
            product = db.get_product(product_id)
            await message.bot.send_message(
                admin_id,
                f"💬 <b>Сообщение от покупателя</b>\n\n"
                f"Товар: {product['name']}\n"
                f"Количество: {quantity} шт.\n"
                f"Цена: {price} ⭐\n"
                f"Покупатель: @{message.from_user.username or message.from_user.id}\n"
                f"ID: {message.from_user.id}\n\n"
                f"<b>Сообщение:</b>\n{user_message}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения админу: {e}")
    
    await message.answer("✅ Ваше сообщение отправлено администратору!", parse_mode=ParseMode.HTML)


# ============= АДМИН: ДОБАВИТЬ ТОВАР =============
@router.callback_query(F.data == "admin_add_product")
async def admin_add_product(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return

    await callback.message.edit_text(
        "📝 <b>Добавление товара</b>\n\nВведите название товара:",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_product_name)
    await callback.answer()


@router.message(AdminStates.waiting_product_name)
async def admin_product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer(
        "📝 Введите описание товара:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_product_description)


@router.message(AdminStates.waiting_product_description)
async def admin_product_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer(
        "💰 Введите цену в звездах (целое число):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_product_price)


@router.message(AdminStates.waiting_product_price)
async def admin_product_price(message: Message, state: FSMContext):
    try:
        price = int(message.text)
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректную цену (целое число, минимум 0)!")
        return

    await state.update_data(price=price)
    
    # Получаем категории
    categories = db.get_categories()
    keyboard = []
    for cat in categories[:3]:  # Максимум 3 в ряд
        keyboard.append([InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"select_cat_{cat}")])
    keyboard.append([InlineKeyboardButton(text="➕ Новая категория", callback_data="new_category")])
    keyboard.append([InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_category")])
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")])
    
    await message.answer(
        "📁 <b>Выберите категорию товара:</b>\n\n"
        "Или создайте новую категорию",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await state.set_state(AdminStates.waiting_product_category)


@router.callback_query(F.data.startswith("select_cat_"))
async def admin_select_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.replace("select_cat_", "")
    await state.update_data(category=category)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Автоматическая", callback_data="delivery_auto")],
        [InlineKeyboardButton(text="👨‍💼 Ручная (услуга)", callback_data="delivery_manual")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])
    
    await callback.message.edit_text(
        "🚚 <b>Выберите тип выдачи:</b>\n\n"
        "🤖 <b>Автоматическая</b> - товар выдаётся сразу после оплаты\n"
        "👨‍💼 <b>Ручная</b> - вы сами выдаёте товар (для услуг)",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_product_delivery_type)
    await callback.answer()


@router.callback_query(F.data == "new_category")
async def admin_new_category(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📁 <b>Введите название новой категории:</b>",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_product_category)
    await callback.answer()


@router.callback_query(F.data == "skip_category")
async def admin_skip_category(callback: CallbackQuery, state: FSMContext):
    await state.update_data(category="Без категории")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Автоматическая", callback_data="delivery_auto")],
        [InlineKeyboardButton(text="👨‍💼 Ручная (услуга)", callback_data="delivery_manual")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])
    
    await callback.message.edit_text(
        "🚚 <b>Выберите тип выдачи:</b>\n\n"
        "🤖 <b>Автоматическая</b> - товар выдаётся сразу после оплаты\n"
        "👨‍💼 <b>Ручная</b> - вы сами выдаёте товар (для услуг)",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_product_delivery_type)
    await callback.answer()


@router.message(AdminStates.waiting_product_category)
async def admin_product_category_input(message: Message, state: FSMContext):
    category = message.text.strip()
    db.add_category(category)
    await state.update_data(category=category)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Автоматическая", callback_data="delivery_auto")],
        [InlineKeyboardButton(text="👨‍💼 Ручная (услуга)", callback_data="delivery_manual")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])
    
    await message.answer(
        "🚚 <b>Выберите тип выдачи:</b>\n\n"
        "🤖 <b>Автоматическая</b> - товар выдаётся сразу после оплаты\n"
        "👨‍💼 <b>Ручная</b> - вы сами выдаёте товар (для услуг)",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_product_delivery_type)


@router.callback_query(F.data.startswith("delivery_"))
async def admin_select_delivery_type(callback: CallbackQuery, state: FSMContext):
    delivery_type = callback.data.replace("delivery_", "")
    await state.update_data(delivery_type=delivery_type)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Безлимитный", callback_data="stock_unlimited")],
        [InlineKeyboardButton(text="📝 Указать количество", callback_data="stock_custom")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])
    
    await callback.message.edit_text(
        "📦 <b>Укажите количество товара:</b>\n\n"
        "♾ <b>Безлимитный</b> - товар всегда доступен\n"
        "📝 <b>Указать количество</b> - ограниченный остаток",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_product_stock)
    await callback.answer()


@router.callback_query(F.data == "stock_unlimited")
async def admin_stock_unlimited(callback: CallbackQuery, state: FSMContext):
    await state.update_data(stock=None)
    
    data = await state.get_data()
    delivery_type = data.get("delivery_type", "auto")
    
    if delivery_type == "manual":
        # Для ручной выдачи не нужен материал
        await _finish_product_creation(callback.message, state, {"type": "text", "content": "Выдача вручную"})
    else:
        await callback.message.edit_text(
            "📦 <b>Отправьте материал товара:</b>\n\n"
            "Вы можете отправить:\n"
            "• Текст\n"
            "• Фото\n"
            "• Видео\n"
            "• Файл",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await state.set_state(AdminStates.waiting_product_material)
    await callback.answer()


@router.callback_query(F.data == "stock_custom")
async def admin_stock_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔢 <b>Введите количество товара:</b>\n\n"
        "Укажите целое положительное число",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_product_stock)
    await callback.answer()


@router.message(AdminStates.waiting_product_stock)
async def admin_product_stock_input(message: Message, state: FSMContext):
    try:
        stock = int(message.text)
        if stock < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное количество (целое число >= 0)!")
        return
    
    await state.update_data(stock=stock)
    
    data = await state.get_data()
    delivery_type = data.get("delivery_type", "auto")
    
    if delivery_type == "manual":
        # Для ручной выдачи не нужен материал
        await _finish_product_creation(message, state, {"type": "text", "content": "Выдача вручную"})
    else:
        await message.answer(
            "📦 <b>Отправьте материал товара:</b>\n\n"
            "Вы можете отправить:\n"
            "• Текст\n"
            "• Фото\n"
            "• Видео\n"
            "• Файл",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AdminStates.waiting_product_material)


async def _finish_product_creation(message: Message, state: FSMContext, material: dict):
    """Вспомогательная функция для завершения создания товара"""
    data = await state.get_data()
    product_id = f"prod_{int(time.time())}"
    
    category = data.get("category", "Без категории")
    delivery_type = data.get("delivery_type", "auto")
    stock = data.get("stock")

    db.add_product(
        product_id,
        data["name"],
        data["description"],
        data["price"],
        material,
        category,
        delivery_type,
        stock
    )

    stock_text = f"♾ Безлимитный" if stock is None else f"{stock} шт."
    delivery_text = "🤖 Автоматическая" if delivery_type == "auto" else "👨‍💼 Ручная"

    await message.answer(
        f"✅ <b>Товар успешно добавлен!</b>\n\n"
        f"Название: {data['name']}\n"
        f"Описание: {data['description']}\n"
        f"Цена: {data['price']} ⭐\n"
        f"Категория: {category}\n"
        f"Тип выдачи: {delivery_text}\n"
        f"Количество: {stock_text}",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    logger.info(f"Добавлен товар {product_id} админом")
    await state.clear()


@router.message(AdminStates.waiting_product_material)
async def admin_product_material(message: Message, state: FSMContext):
    material = {}

    if message.text:
        material = {"type": "text", "content": message.text}
    elif message.photo:
        material = {"type": "photo", "file_id": message.photo[-1].file_id}
    elif message.video:
        material = {"type": "video", "file_id": message.video.file_id}
    elif message.document:
        material = {"type": "file", "file_id": message.document.file_id}
    else:
        await message.answer("❌ Неподдерживаемый тип материала!")
        return

    await _finish_product_creation(message, state, material)


# ============= АДМИН: СПИСОК ТОВАРОВ =============
@router.callback_query(F.data == "admin_list_products")
async def admin_list_products(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return

    products = db.get_products()

    if not products:
        await callback.message.edit_text(
            "📋 <b>Список товаров пуст</b>",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    keyboard = []
    for pid, product in products.items():
        keyboard.append([InlineKeyboardButton(
            text=f"{product['name']} - {product['price']} ⭐",
            callback_data=f"admin_view_{pid}"
        )])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])

    await callback.message.edit_text(
        "📋 <b>Список товаров:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_view_"))
async def admin_view_product(callback: CallbackQuery):
    product_id = callback.data.replace("admin_view_", "")
    product = db.get_product(product_id)

    if not product:
        await callback.answer("❌ Товар не найден!", show_alert=True)
        return

    stock = product.get("stock")
    stock_text = "♾ Безлимитный" if stock is None else f"{stock} шт."
    
    delivery_type = product.get("delivery_type", "auto")
    delivery_text = "🤖 Автоматическая" if delivery_type == "auto" else "👨‍💼 Ручная"

    text = (
        f"🛍 <b>{product['name']}</b>\n\n"
        f"📝 Описание: {product['description']}\n"
        f"💰 Цена: {product['price']} ⭐\n"
        f"📁 Категория: {product.get('category', 'Без категории')}\n"
        f"🚚 Тип выдачи: {delivery_text}\n"
        f"📦 Количество: {stock_text}\n"
        f"📄 Материал: {product['material']['type']}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_product_manage_keyboard(product_id),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_delete_confirm_"))
async def admin_delete_product_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    product_id = callback.data.replace("admin_delete_confirm_", "")
    product = db.get_product(product_id)
    
    if not product:
        await callback.answer("❌ Товар не найден!", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_delete_yes_{product_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_view_{product_id}")]
    ])
    
    await callback.message.edit_text(
        f"⚠️ <b>Подтверждение удаления</b>\n\n"
        f"Вы уверены, что хотите удалить товар:\n"
        f"<b>{product['name']}</b>?\n\n"
        f"Это действие нельзя отменить!",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_delete_yes_"))
async def admin_delete_product_yes(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    product_id = callback.data.replace("admin_delete_yes_", "")
    if db.delete_product(product_id):
        logger.info(f"Товар {product_id} удален админом {callback.from_user.id}")
        await callback.answer("✅ Товар удален!", show_alert=True)
        await callback.message.edit_text(
            "🗑 <b>Товар успешно удален</b>",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.answer("❌ Товар не найден!", show_alert=True)


@router.callback_query(F.data.startswith("admin_edit_"))
async def admin_edit_product(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    product_id = callback.data.replace("admin_edit_", "")
    product = db.get_product(product_id)
    
    if not product:
        await callback.answer("❌ Товар не найден!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"edit_field_name_{product_id}")],
        [InlineKeyboardButton(text="✏️ Описание", callback_data=f"edit_field_desc_{product_id}")],
        [InlineKeyboardButton(text="✏️ Цена", callback_data=f"edit_field_price_{product_id}")],
        [InlineKeyboardButton(text="✏️ Категория", callback_data=f"edit_field_cat_{product_id}")],
        [InlineKeyboardButton(text="✏️ Тип выдачи", callback_data=f"edit_field_delivery_{product_id}")],
        [InlineKeyboardButton(text="✏️ Количество", callback_data=f"edit_field_stock_{product_id}")],
        [InlineKeyboardButton(text="✏️ Материал", callback_data=f"edit_field_mat_{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_view_{product_id}")]
    ]
    
    await callback.message.edit_text(
        f"✏️ <b>Редактирование товара:</b> {product['name']}\n\n"
        "Выберите что изменить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field_"))
async def admin_edit_field_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.replace("edit_field_", "").split("_", 1)
    field = parts[0]
    product_id = parts[1]
    
    field_names = {
        "name": "название",
        "desc": "описание",
        "price": "цену (0 или больше)",
        "cat": "категорию",
        "delivery": "тип выдачи (auto/manual)",
        "stock": "количество (число или 'unlimited')",
        "mat": "материал"
    }
    
    await state.update_data(edit_product_id=product_id, edit_field=field)
    await callback.message.edit_text(
        f"✏️ Введите новое {field_names.get(field, 'значение')}:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_edit_field)
    await callback.answer()


@router.message(AdminStates.waiting_edit_field)
async def admin_edit_field_process(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data["edit_product_id"]
    field = data["edit_field"]
    product = db.get_product(product_id)
    
    if not product:
        await message.answer("❌ Товар не найден!")
        await state.clear()
        return
    
    update_data = {}
    
    if field == "name":
        update_data["name"] = message.text
    elif field == "desc":
        update_data["description"] = message.text
    elif field == "price":
        try:
            price = int(message.text)
            if price < 0:
                raise ValueError
            update_data["price"] = price
        except ValueError:
            await message.answer("❌ Введите корректную цену (целое число >= 0)!")
            return
    elif field == "cat":
        update_data["category"] = message.text
        db.add_category(message.text)
    elif field == "delivery":
        delivery = message.text.lower().strip()
        if delivery not in ["auto", "manual"]:
            await message.answer("❌ Введите 'auto' (автоматическая) или 'manual' (ручная)!")
            return
        update_data["delivery_type"] = delivery
    elif field == "stock":
        if message.text.lower().strip() == "unlimited":
            update_data["stock"] = None
        else:
            try:
                stock = int(message.text)
                if stock < 0:
                    raise ValueError
                update_data["stock"] = stock
            except ValueError:
                await message.answer("❌ Введите число >= 0 или 'unlimited'!")
                return
    elif field == "mat":
        material = {}
        if message.text:
            material = {"type": "text", "content": message.text}
        elif message.photo:
            material = {"type": "photo", "file_id": message.photo[-1].file_id}
        elif message.video:
            material = {"type": "video", "file_id": message.video.file_id}
        elif message.document:
            material = {"type": "file", "file_id": message.document.file_id}
        else:
            await message.answer("❌ Неподдерживаемый тип материала!")
            return
        update_data["material"] = material
    
    if db.update_product(product_id, **update_data):
        await message.answer(
            "✅ Товар успешно обновлен!",
            reply_markup=get_admin_keyboard()
        )
        logger.info(f"Товар {product_id} обновлен админом {message.from_user.id}")
    else:
        await message.answer("❌ Ошибка при обновлении товара!")
    
    await state.clear()


# ============= АДМИН: ИЗМЕНИТЬ /START =============
@router.callback_query(F.data == "admin_edit_start")
async def admin_edit_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return

    await callback.message.edit_text(
        "✏️ <b>Изменение приветственного сообщения</b>\n\n"
        "Отправьте новый текст для /start:",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_start_text)
    await callback.answer()


@router.message(AdminStates.waiting_start_text)
async def admin_start_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer(
        "📸 <b>Отправьте медиа (фото/видео/гиф)</b>\n\n"
        "Или отправьте /skip чтобы пропустить",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_start_media)


@router.message(AdminStates.waiting_start_media, Command("skip"))
async def admin_start_media_skip(message: Message, state: FSMContext):
    data = await state.get_data()
    db.set_start_message(data["text"])

    await message.answer(
        "✅ Приветственное сообщение обновлено!",
        reply_markup=get_admin_keyboard()
    )
    await state.clear()


@router.message(AdminStates.waiting_start_media)
async def admin_start_media(message: Message, state: FSMContext):
    media_type = None
    media_id = None

    if message.photo:
        media_type = "photo"
        media_id = message.photo[-1].file_id
    elif message.video:
        media_type = "video"
        media_id = message.video.file_id
    elif message.animation:
        media_type = "animation"
        media_id = message.animation.file_id
    else:
        await message.answer("❌ Отправьте фото, видео или гиф!")
        return

    data = await state.get_data()
    db.set_start_message(data["text"], media_type, media_id)

    await message.answer(
        "✅ Приветственное сообщение обновлено с медиа!",
        reply_markup=get_admin_keyboard()
    )
    await state.clear()


# ============= АДМИН: СТАТИСТИКА =============
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return

    stats = db.get_stats()
    products = db.get_products()
    products_count = len(products)
    categories_count = len(db.get_categories())
    all_users = db.get_all_users()
    total_users = len(all_users)
    
    # Статистика по пользователям
    users_with_balance = 0
    users_with_orders = set()
    total_balance = 0
    new_today = 0
    new_week = 0
    active_week = set()
    total_referrals = 0
    
    current_time = datetime.now()
    today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = current_time - timedelta(days=7)
    
    # Собираем статистику по пользователям
    for user_id in all_users:
        user_id_str = str(user_id)
        user_data = db.data.get("users", {}).get(user_id_str, {})
        balance = user_data.get("balance", 0)
        total_balance += balance
        
        if balance > 0:
            users_with_balance += 1
        
        # Новые пользователи
        registered_at = user_data.get("registered_at")
        if registered_at:
            try:
                reg_date = datetime.fromisoformat(registered_at)
                if reg_date >= today_start:
                    new_today += 1
                if reg_date >= week_ago:
                    new_week += 1
            except:
                pass
        
        # Активные пользователи (с заказами за неделю)
        orders = db.data.get("orders", [])
        for order in orders:
            if order.get("user_id") == user_id:
                users_with_orders.add(user_id)
                try:
                    order_date = datetime.fromisoformat(order.get("date", ""))
                    if order_date >= week_ago:
                        active_week.add(user_id)
                except:
                    pass
    
    # Статистика по рефералам
    referrals_data = db.data.get("referrals", {})
    for ref_list in referrals_data.values():
        total_referrals += len(ref_list)
    
    # Статистика по категориям
    category_stats = {}
    for product in products.values():
        cat = product.get("category", "Без категории")
        category_stats[cat] = category_stats.get(cat, 0) + 1

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"<b>👥 Пользователи:</b>\n"
        f"  • Всего: {total_users}\n"
        f"  • Новых сегодня: {new_today}\n"
        f"  • Новых за неделю: {new_week}\n"
        f"  • С балансом: {users_with_balance}\n"
        f"  • С покупками: {len(users_with_orders)}\n"
        f"  • Активных (неделя): {len(active_week)}\n"
        f"  • Всего рефералов: {total_referrals}\n\n"
        f"<b>💰 Финансы:</b>\n"
        f"  • Общий баланс: {total_balance} ⭐\n"
        f"  • Доход: {stats['total_revenue']} ⭐\n\n"
        f"<b>🛍 Товары:</b>\n"
        f"  • Товаров: {products_count}\n"
        f"  • Категорий: {categories_count}\n"
        f"  • Заказов: {stats['total_orders']}\n"
    )
    
    if category_stats:
        text += "\n<b>📁 По категориям:</b>\n"
        for cat, count in sorted(category_stats.items(), key=lambda x: x[1], reverse=True):
            text += f"  • {cat}: {count}\n"

    await callback.message.edit_text(
        text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data == "admin_orders")
async def admin_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    orders = db.data.get("orders", [])
    if not orders:
        await callback.message.edit_text(
            "📦 <b>Заказов пока нет</b>",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return
    
    text = "📦 <b>Последние заказы:</b>\n\n"
    for order in reversed(orders[-10:]):  # Последние 10 заказов
        date = datetime.fromisoformat(order["date"]).strftime("%d.%m.%Y %H:%M")
        text += (
            f"🛍 {order['product_name']}\n"
            f"💰 {order['price']} ⭐\n"
            f"👤 @{order['username']}\n"
            f"📅 {date}\n\n"
        )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ============= АДМИН: ОЖИДАЮЩИЕ ЗАКАЗЫ =============
@router.callback_query(F.data == "admin_pending_orders")
async def admin_pending_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    pending = db.get_pending_orders()
    if not pending:
        try:
            await callback.message.edit_text(
                "⏳ <b>Нет ожидающих заказов</b>\n\n"
                "Все заказы обработаны!",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            # Если сообщение не изменилось, просто отвечаем
            await callback.answer("⏳ Нет ожидающих заказов", show_alert=True)
            return
        await callback.answer()
        return
    
    text = "⏳ <b>Ожидают выдачи:</b>\n\n"
    keyboard = []
    
    for order in pending:
        date = datetime.fromisoformat(order["date"]).strftime("%d.%m.%Y %H:%M")
        text += (
            f"🛍 {order['product_name']}\n"
            f"💰 {order['price']} ⭐\n"
            f"👤 @{order['username']} (ID: {order['user_id']})\n"
            f"📅 {date}\n\n"
        )
        keyboard.append([InlineKeyboardButton(
            text=f"✅ Выдать: {order['product_name']}",
            callback_data=f"deliver_{order['order_id']}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("deliver_"))
async def admin_deliver_product(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    order_id = callback.data.replace("deliver_", "")
    pending = db.get_pending_orders()
    order = next((o for o in pending if o.get("order_id") == order_id), None)
    
    if not order:
        await callback.answer("❌ Заказ не найден!", show_alert=True)
        return
    
    # Запрашиваем материал для выдачи
    await state.update_data(deliver_order_id=order_id, deliver_user_id=order["user_id"])
    await callback.message.edit_text(
        f"📦 <b>Выдача товара:</b> {order['product_name']}\n"
        f"👤 Покупатель: @{order['username']}\n\n"
        "Отправьте материал, который нужно выдать покупателю:\n"
        "• Текст\n"
        "• Фото\n"
        "• Видео\n"
        "• Файл",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_manual_delivery)
    await callback.answer()


@router.message(AdminStates.waiting_manual_delivery)
async def admin_manual_delivery_process(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data["deliver_order_id"]
    user_id = data["deliver_user_id"]
    
    pending = db.get_pending_orders()
    order = next((o for o in pending if o.get("order_id") == order_id), None)
    
    if not order:
        await message.answer("❌ Заказ не найден!")
        await state.clear()
        return
    
    try:
        # Отправляем материал покупателю
        if message.text:
            await message.bot.send_message(
                user_id,
                f"✅ <b>Ваш заказ выдан!</b>\n\n"
                f"Товар: {order['product_name']}\n\n"
                f"📄 {message.text}",
                parse_mode=ParseMode.HTML
            )
        elif message.photo:
            await message.bot.send_photo(
                user_id,
                photo=message.photo[-1].file_id,
                caption=f"✅ <b>Ваш заказ выдан!</b>\n\nТовар: {order['product_name']}",
                parse_mode=ParseMode.HTML
            )
        elif message.video:
            await message.bot.send_video(
                user_id,
                video=message.video.file_id,
                caption=f"✅ <b>Ваш заказ выдан!</b>\n\nТовар: {order['product_name']}",
                parse_mode=ParseMode.HTML
            )
        elif message.document:
            await message.bot.send_document(
                user_id,
                document=message.document.file_id,
                caption=f"✅ <b>Ваш заказ выдан!</b>\n\nТовар: {order['product_name']}",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer("❌ Неподдерживаемый тип материала!")
            return
        
        # Удаляем из очереди
        db.remove_pending_order(order_id)
        
        # Обновляем статус заказа
        for db_order in db.data.get("orders", []):
            if (db_order.get("user_id") == user_id and 
                db_order.get("product_name") == order["product_name"] and
                db_order.get("status") == "pending"):
                db_order["status"] = "completed"
                break
        db.save()
        
        await message.answer(
            f"✅ <b>Товар успешно выдан!</b>\n\n"
            f"Покупатель: @{order['username']}\n"
            f"Товар: {order['product_name']}",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.HTML
        )
        
        logger.info(f"Товар {order['product_name']} выдан вручную пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при выдаче товара: {e}")
        await message.answer(f"❌ Ошибка при отправке: {str(e)}")
    
    await state.clear()


# ============= АДМИН: ОТМЕНА/НАЗАД =============
@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "<b>🔧 Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer("❌ Действие отменено")


@router.callback_query(F.data == "admin_promo_codes")
async def admin_promo_codes(callback: CallbackQuery):
    """Управление промокодами"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    promo_codes = db.get_promo_codes()
    
    text = "🎫 <b>Промокоды</b>\n\n"
    
    if promo_codes:
        for code, info in promo_codes.items():
            max_uses_text = f"/{info.get('max_uses')}" if info.get('max_uses') else "/∞"
            text += (
                f"<b>{code}</b>\n"
                f"  💰 Бонус: {info['amount']} ⭐\n"
                f"  📊 Использований: {info.get('uses', 0)}{max_uses_text}\n\n"
            )
    else:
        text += "<i>Промокодов пока нет</i>\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_create_promo")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "admin_create_promo")
async def admin_create_promo(callback: CallbackQuery, state: FSMContext):
    """Создание промокода"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🎫 <b>Создание промокода</b>\n\n"
        "Введите код промокода (например: WELCOME2025):",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_create_promo_code)
    await callback.answer()


@router.message(AdminStates.waiting_create_promo_code)
async def admin_create_promo_code(message: Message, state: FSMContext):
    """Ввод кода промокода"""
    code = message.text.strip().upper()
    
    if len(code) < 3:
        await message.answer("❌ Код должен быть минимум 3 символа!")
        return
    
    if code in db.get_promo_codes():
        await message.answer("❌ Такой промокод уже существует!")
        return
    
    await state.update_data(promo_code=code)
    await message.answer(
        "💰 Введите бонус в звездах (например: 50):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_create_promo_amount)


@router.message(AdminStates.waiting_create_promo_amount)
async def admin_create_promo_amount(message: Message, state: FSMContext):
    """Ввод суммы бонуса"""
    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число!")
        return
    
    await state.update_data(promo_amount=amount)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Безлимитный", callback_data="promo_uses_unlimited")],
        [InlineKeyboardButton(text="📝 Указать лимит", callback_data="promo_uses_limit")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])
    
    await message.answer(
        "📊 Укажите максимальное количество использований:",
        reply_markup=keyboard
    )
    await state.set_state(AdminStates.waiting_create_promo_uses)


@router.callback_query(F.data == "promo_uses_unlimited")
async def admin_promo_uses_unlimited(callback: CallbackQuery, state: FSMContext):
    """Безлимитный промокод"""
    data = await state.get_data()
    code = data["promo_code"]
    amount = data["promo_amount"]
    
    db.create_promo_code(code, amount, max_uses=None)
    
    await callback.message.edit_text(
        f"✅ <b>Промокод создан!</b>\n\n"
        f"🎫 Код: <code>{code}</code>\n"
        f"💰 Бонус: {amount} ⭐\n"
        f"📊 Использований: ∞",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    
    logger.info(f"Админ создал промокод {code} на {amount} звезд (безлимит)")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "promo_uses_limit")
async def admin_promo_uses_limit(callback: CallbackQuery, state: FSMContext):
    """Ввод лимита использований"""
    await callback.message.edit_text(
        "🔢 Введите максимальное количество использований:",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.waiting_create_promo_uses)
    await callback.answer()


@router.message(AdminStates.waiting_create_promo_uses)
async def admin_promo_uses_input(message: Message, state: FSMContext):
    """Обработка лимита использований"""
    try:
        max_uses = int(message.text)
        if max_uses <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число!")
        return
    
    data = await state.get_data()
    code = data["promo_code"]
    amount = data["promo_amount"]
    
    db.create_promo_code(code, amount, max_uses=max_uses)
    
    await message.answer(
        f"✅ <b>Промокод создан!</b>\n\n"
        f"🎫 Код: <code>{code}</code>\n"
        f"💰 Бонус: {amount} ⭐\n"
        f"📊 Использований: 0/{max_uses}",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    
    logger.info(f"Админ создал промокод {code} на {amount} звезд (лимит: {max_uses})")
    await state.clear()


@router.message(
    F.text & 
    ~F.text.startswith("/") & 
    ~F.text.in_(["🛍️ Каталог товаров", "👤 Личный кабинет", "📜 Мои заказы", "🎯 Реферальная программа"])
)
async def process_buy_message(message: Message, state: FSMContext):
    """Обработка сообщения после оплаты"""
    # Проверяем, не находится ли пользователь в состоянии админ-панели или добавления товара
    # Админские и пользовательские обработчики имеют приоритет
    current_state = await state.get_state()
    if current_state and (current_state.startswith("AdminStates") or current_state.startswith("UserProductStates")):
        return  # Не обрабатываем, если пользователь в админ-панели или добавляет товар
    
    user_id = str(message.from_user.id)
    
    # Проверяем, есть ли ожидающее сообщение
    if "buy_messages" not in db.data or user_id not in db.data["buy_messages"]:
        return  # Не обрабатываем, если это не сообщение после оплаты
    
    buy_data = db.data["buy_messages"][user_id]
    product_id = buy_data["product_id"]
    quantity = buy_data["quantity"]
    price = buy_data["price"]
    payment_type = buy_data["payment_type"]
    
    # Удаляем из ожидающих
    del db.data["buy_messages"][user_id]
    db.save()
    
    # Сохраняем сообщение в заказе
    user_message = message.text
    
    # Уведомляем админов о сообщении
    for admin_id in ADMIN_IDS:
        try:
            product = db.get_product(product_id)
            await message.bot.send_message(
                admin_id,
                f"💬 <b>Сообщение от покупателя</b>\n\n"
                f"Товар: {product['name']}\n"
                f"Количество: {quantity} шт.\n"
                f"Цена: {price} ⭐\n"
                f"Покупатель: @{message.from_user.username or message.from_user.id}\n"
                f"ID: {message.from_user.id}\n\n"
                f"<b>Сообщение:</b>\n{user_message}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения админу: {e}")
    
    await message.answer("✅ Ваше сообщение отправлено администратору!", parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    total_users = len(db.get_all_users())
    await callback.message.edit_text(
        f"<b>🔧 Админ-панель</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n\n"
        f"Выберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ============= ЗАПУСК БОТА =============
async def check_crypto_payments_periodically(bot: Bot):
    """Периодическая проверка статуса платежей CryptoBot"""
    while True:
        try:
            await asyncio.sleep(30)  # Проверяем каждые 30 секунд
            
            if "crypto_invoices" not in db.data:
                continue
            
            # Удаляем инвойсы старше 15 минут
            current_time = datetime.now()
            expired_invoices = []
            
            for invoice_id_str, invoice_data in db.data["crypto_invoices"].items():
                if invoice_data.get("status") == "pending":
                    created_at_str = invoice_data.get("created_at")
                    if created_at_str:
                        try:
                            created_at = datetime.fromisoformat(created_at_str)
                            time_diff = current_time - created_at
                            if time_diff > timedelta(minutes=15):
                                expired_invoices.append(invoice_id_str)
                        except Exception as e:
                            logger.error(f"Ошибка парсинга времени создания инвойса {invoice_id_str}: {e}")
            
            # Удаляем просроченные инвойсы
            for invoice_id_str in expired_invoices:
                invoice_data = db.data["crypto_invoices"].pop(invoice_id_str, None)
                if invoice_data:
                    logger.info(f"Удален просроченный инвойс {invoice_id_str} (старше 15 минут)")
            
            if expired_invoices:
                db.save()
            
            pending_invoices = {
                inv_id: inv_data 
                for inv_id, inv_data in db.data["crypto_invoices"].items() 
                if inv_data.get("status") == "pending"
            }
            
            for invoice_id_str, invoice_data in pending_invoices.items():
                try:
                    invoice_id = int(invoice_id_str)
                    invoice_status = await check_cryptobot_invoice_status(invoice_id)
                    
                    if invoice_status and invoice_status.get("status") == "paid":
                        # Платеж успешен - обрабатываем
                        await process_crypto_payment_success(bot, invoice_id, invoice_data)
                except Exception as e:
                    logger.error(f"Ошибка проверки инвойса {invoice_id_str}: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка в периодической проверке платежей: {e}")
            await asyncio.sleep(60)


async def process_crypto_payment_success(bot: Bot, invoice_id: int, invoice_data: dict):
    """Обработка успешного платежа через CryptoBot"""
    try:
        user_id = invoice_data["user_id"]
        payment_type = invoice_data.get("type", "product")
        
        # Обновляем статус инвойса
        db.data["crypto_invoices"][str(invoice_id)]["status"] = "paid"
        db.save()
        
        # Обработка пополнения баланса
        if payment_type == "topup":
            amount = invoice_data["amount"]
            new_balance = db.add_balance(user_id, amount)
            
            try:
                await bot.send_message(
                    user_id,
                    f"✅ <b>Баланс пополнен через CryptoBot!</b>\n\n"
                    f"💰 Зачислено: {amount} ⭐\n"
                    f"💳 Новый баланс: {new_balance} ⭐",
                    parse_mode=ParseMode.HTML
                )
                
                # Начисляем бонус рефереру (10% от пополнения)
                referrer_bonus = 0
                referrer_id = None
                for ref_id, referrals in db.data.get("referrals", {}).items():
                    if user_id in referrals:
                        referrer_id = int(ref_id)
                        referrer_bonus = int(amount * 0.1)
                        db.add_balance(referrer_id, referrer_bonus)
                        
                        try:
                            await bot.send_message(
                                referrer_id,
                                f"🎉 <b>Реферальный бонус!</b>\n\n"
                                f"Ваш реферал пополнил баланс на {amount} ⭐ через CryptoBot\n\n"
                                f"💰 Вам начислено: <b>{referrer_bonus} ⭐</b>\n"
                                f"💳 Ваш баланс: {db.get_balance(referrer_id)} ⭐",
                                parse_mode=ParseMode.HTML
                            )
                        except:
                            pass
                        break
                
                # Уведомляем админов
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"💰 <b>Пополнение баланса через CryptoBot!</b>\n\n"
                            f"Пользователь: ID {user_id}\n"
                            f"Сумма: {amount} ⭐\n"
                            f"Бонус реферу: {referrer_bonus} ⭐",
                            parse_mode=ParseMode.HTML
                        )
                    except:
                        pass
                
                logger.info(f"Пользователь {user_id} пополнил баланс на {amount} звезд через CryptoBot")
                return
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
                return
        
        # Обработка покупки товара
        product_id = invoice_data["product_id"]
        quantity = invoice_data["quantity"]
        price = invoice_data["price"]
        
        product = db.get_product(product_id)
        if not product:
            logger.error(f"Товар {product_id} не найден при обработке CryptoBot платежа")
            return
        
        # Выдаем товар
        delivery_type = product.get("delivery_type", "auto")
        
        try:
            await bot.send_message(
                user_id,
                f"✅ <b>Оплата через CryptoBot успешна!</b>\n\n"
                f"Товар: {product['name']}\n"
                f"Количество: {quantity} шт.\n"
                f"Цена: {price} ⭐\n\n"
                "💬 Хотите оставить сообщение к заказу? (Напишите сообщение или отправьте /skip)",
                parse_mode=ParseMode.HTML
            )
            
            # Сохраняем данные для запроса сообщения
            if "buy_messages" not in db.data:
                db.data["buy_messages"] = {}
            db.data["buy_messages"][str(user_id)] = {
                "product_id": product_id,
                "quantity": quantity,
                "price": price,
                "payment_type": "crypto"
            }
            db.save()
            
            if delivery_type == "manual":
                # Ручная выдача
                pending = db.add_pending_order(
                    user_id,
                    "CryptoBot пользователь",
                    product_id,
                    product["name"],
                    price,
                    quantity
                )
                
                await bot.send_message(
                    user_id,
                    "⏳ <b>Ваш заказ принят!</b>\n\n"
                    "Товар будет выдан вручную администратором.",
                    parse_mode=ParseMode.HTML
                )
                
                # Уведомляем админов
                for admin_id in ADMIN_IDS:
                    try:
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="✅ Выдать товар", callback_data=f"deliver_{pending['order_id']}")]
                        ])
                        await bot.send_message(
                            admin_id,
                            f"🔔 <b>Новый заказ (CryptoBot)!</b>\n\n"
                            f"Товар: {product['name']}\n"
                            f"Количество: {quantity} шт.\n"
                            f"Цена: {price} ⭐\n"
                            f"Покупатель: ID {user_id}",
                            parse_mode=ParseMode.HTML,
                            reply_markup=keyboard
                        )
                    except:
                        pass
                
                db.add_order(user_id, "CryptoBot пользователь", product_id, product["name"], price, status="pending", quantity=quantity)
            else:
                # Автоматическая выдача - выдаем quantity раз
                material = product["material"]
                for i in range(quantity):
                    if material["type"] == "text":
                        await bot.send_message(user_id, f"📄 <b>Ваш материал ({i+1}/{quantity}):</b>\n\n{material['content']}", parse_mode=ParseMode.HTML)
                    elif material["type"] == "file":
                        await bot.send_document(user_id, document=material["file_id"], caption=f"📄 Ваш материал ({i+1}/{quantity})")
                    elif material["type"] == "photo":
                        await bot.send_photo(user_id, photo=material["file_id"], caption=f"📄 Ваш материал ({i+1}/{quantity})")
                    elif material["type"] == "video":
                        await bot.send_video(user_id, video=material["file_id"], caption=f"📄 Ваш материал ({i+1}/{quantity})")
                    await asyncio.sleep(0.5)
                
                # Начисляем деньги владельцу товара (98% от цены, 2% комиссия)
                owner_id = product.get("owner_id")
                if owner_id and owner_id != user_id:  # Если товар принадлежит пользователю
                    owner_earnings = int(price * 0.98)  # 98% владельцу
                    db.add_balance(owner_id, owner_earnings)
                    
                    # Уведомляем владельца
                    try:
                        await bot.send_message(
                            owner_id,
                            f"💰 <b>Ваш товар куплен!</b>\n\n"
                            f"Товар: {product['name']}\n"
                            f"Количество: {quantity} шт.\n"
                            f"Цена: {price} ⭐\n"
                            f"💰 Вам начислено: <b>{owner_earnings} ⭐</b> (98%)\n"
                            f"💳 Ваш баланс: {db.get_balance(owner_id)} ⭐\n\n"
                            f"Покупатель: ID {user_id}",
                            parse_mode=ParseMode.HTML
                        )
                    except:
                        pass
                    logger.info(f"Владельцу товара {owner_id} начислено {owner_earnings} ⭐ за покупку товара {product_id} через CryptoBot")
                
                # Уведомляем админов
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"💰 <b>Новая продажа (CryptoBot)!</b>\n\n"
                            f"Товар: {product['name']}\n"
                            f"Количество: {quantity} шт.\n"
                            f"Цена: {price} ⭐\n"
                            f"Покупатель: ID {user_id}",
                            parse_mode=ParseMode.HTML
                        )
                    except:
                        pass
                
                db.add_order(user_id, "CryptoBot пользователь", product_id, product["name"], price, status="completed", quantity=quantity)
            
            # Уменьшаем остаток
            for _ in range(quantity):
                db.decrease_stock(product_id)
            
            logger.info(f"CryptoBot платеж обработан: invoice_id={invoice_id}, user_id={user_id}, product_id={product_id}")
            
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка обработки CryptoBot платежа: {e}")


async def main():
    try:
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(router)

        # Удаляем webhook с несколькими попытками
        max_retries = 5
        for attempt in range(max_retries):
            try:
                await bot.delete_webhook(drop_pending_updates=True)
                logger.info("✅ Webhook успешно удален")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Попытка {attempt + 1}/{max_retries} удаления webhook не удалась: {e}. Повтор через 2 секунды...")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"Не удалось удалить webhook после {max_retries} попыток: {e}")
                    raise
        
        # Небольшая задержка перед запуском polling
        await asyncio.sleep(1)
        
        # Устанавливаем команды для автодополнения
        commands = [
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="buy", description="Каталог товаров"),
            BotCommand(command="profile", description="Личный кабинет"),
            BotCommand(command="myorders", description="Мои заказы"),
            BotCommand(command="referral", description="Реферальная программа"),
            BotCommand(command="help", description="Справка по командам"),
        ]
        await bot.set_my_commands(commands)
        
        # Запускаем периодическую проверку CryptoBot платежей
        asyncio.create_task(check_crypto_payments_periodically(bot))
        
        logger.info("🤖 Бот запущен!")
        logger.info(f"Админы: {ADMIN_IDS}")
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "pre_checkout_query", "successful_payment", "inline_query"])
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())