import asyncio
import json
import os
import logging
import time
from datetime import datetime
from typing import Optional, List
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, ContentType, ReplyKeyboardMarkup, KeyboardButton
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
            "all_users": []  # Список всех user_id для рассылки
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
                    delivery_type="auto", stock=None):
        self.data["products"][product_id] = {
            "name": name,
            "description": description,
            "price": price,
            "material": material,
            "category": category,
            "delivery_type": delivery_type,  # "auto" или "manual"
            "stock": stock,  # None = безлимит, число = остаток
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

    def add_order(self, user_id, username, product_id, product_name, price, status="completed"):
        order = {
            "user_id": user_id,
            "username": username,
            "product_id": product_id,
            "product_name": product_name,
            "price": price,
            "status": status,  # "completed" или "pending"
            "date": datetime.now().isoformat()
        }
        self.data["orders"].append(order)
        self.data["stats"]["total_orders"] += 1
        self.data["stats"]["total_revenue"] += price
        self.save()
        return order

    def add_pending_order(self, user_id, username, product_id, product_name, price):
        """Добавить заказ в очередь ожидания ручной выдачи"""
        pending = {
            "order_id": f"ord_{int(time.time())}_{user_id}",
            "user_id": user_id,
            "username": username,
            "product_id": product_id,
            "product_name": product_name,
            "price": price,
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


# ============= КЛАВИАТУРЫ =============
PRODUCTS_PER_PAGE = 5

def get_main_reply_keyboard():
    """Главная Reply клавиатура после подписки"""
    keyboard = [
        [KeyboardButton(text="🛍️ Каталог товаров"), KeyboardButton(text="👤 Личный кабинет")],
        [KeyboardButton(text="🎁 Получить подарок"), KeyboardButton(text="📜 Мои заказы")],
        [KeyboardButton(text="🎯 Реферальная программа"), KeyboardButton(text="❓ FAQ")],
        [KeyboardButton(text="💬 Поддержка"), KeyboardButton(text="ℹ️ О боте")]
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
        
        keyboard.append([InlineKeyboardButton(
            text=f"🛍 {product['name']} - {product['price']} ⭐{stock_text}",
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
    
    keyboard = [
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add_product")],
        [InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_list_products")],
        [InlineKeyboardButton(text="🎫 Промокоды", callback_data="admin_promo_codes")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📦 Заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(text=pending_text, callback_data="admin_pending_orders")]
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
        db.register_user(user_id, message.from_user.username)
        
        # Пользователь подписан - показываем приветствие
        balance = db.get_balance(user_id)
        welcome_text = (
            "🎉 <b>Добро пожаловать в Shark Of Buy!</b>\n\n"
            "<i>Быстро • Надежно • Безопасно</i>\n\n"
            f"💰 <b>Баланс:</b> {balance} ⭐\n\n"
            "<b>Доступные команды:</b>\n"
            "/buy - Каталог товаров\n"
            "/profile - Личный кабинет\n"
            "/myorders - Мои заказы\n"
            "/referral - Реферальная программа\n"
            "/faq - Частые вопросы\n"
            "/support - Поддержка\n"
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
            db.register_user(user_id, callback.from_user.username)
            
            # Проверяем реферальную ссылку
            if callback.message.text and "start=ref_" in callback.message.text:
                try:
                    ref_id = int(callback.message.text.split("start=ref_")[1].split()[0])
                    if ref_id != user_id:  # Нельзя быть рефералом самому себе
                        db.add_referral(ref_id, user_id)
                        # Уведомляем реферера
                        try:
                            await callback.bot.send_message(
                                ref_id,
                                f"🎉 <b>У вас новый реферал!</b>\n\n"
                                f"👤 @{callback.from_user.username or 'Пользователь'}\n\n"
                                f"💡 Когда он пополнит баланс, вы получите 10% бонус!",
                                parse_mode=ParseMode.HTML
                            )
                        except:
                            pass
                except:
                    pass
            
            balance = db.get_balance(user_id)
            welcome_text = (
                "🎉 <b>Добро пожаловать в Shark Of Buy!</b>\n\n"
                "<i>Быстро • Надежно • Безопасно</i>\n\n"
                f"💰 <b>Баланс:</b> {balance} ⭐\n\n"
                "<b>Доступные команды:</b>\n"
                "/buy - Каталог товаров\n"
                "/profile - Личный кабинет\n"
                "/myorders - Мои заказы\n"
                "/referral - Реферальная программа\n"
                "/faq - Частые вопросы\n"
                "/support - Поддержка\n"
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
        "<i>Пополните баланс и покупайте товары за звезды внутри бота</i>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="topup_balance")],
        [InlineKeyboardButton(text="🎫 Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton(text="📜 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="🎯 Реферальная программа", callback_data="referral_program")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "topup_balance")
async def process_topup_balance(callback: CallbackQuery):
    """Выбор суммы пополнения"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 10 звезд", callback_data="topup_10")],
        [InlineKeyboardButton(text="⭐ 50 звезд", callback_data="topup_50")],
        [InlineKeyboardButton(text="⭐ 100 звезд", callback_data="topup_100")],
        [InlineKeyboardButton(text="⭐ 250 звезд", callback_data="topup_250")],
        [InlineKeyboardButton(text="⭐ 500 звезд", callback_data="topup_500")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_profile")]
    ])
    
    await callback.message.edit_text(
        "💰 <b>Пополнение баланса</b>\n\n"
        "Выберите сумму пополнения:\n\n"
        "💡 <i>Звезды будут конвертированы в баланс 1:1</i>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("topup_"))
async def process_topup_amount(callback: CallbackQuery):
    """Обработка пополнения баланса"""
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
        "<i>Пополните баланс и покупайте товары за звезды внутри бота</i>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="topup_balance")],
        [InlineKeyboardButton(text="🎫 Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton(text="📜 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="🎯 Реферальная программа", callback_data="referral_program")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


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


@router.message(Command("faq"))
@router.message(F.text == "❓ FAQ")
async def cmd_faq(message: Message):
    """Частые вопросы"""
    text = (
        "❓ <b>Частые вопросы</b>\n\n"
        "<b>Q: Как купить товар?</b>\n"
        "A: Выберите товар из каталога и оплатите звездами Telegram.\n\n"
        "<b>Q: Что такое звезды Telegram?</b>\n"
        "A: Это внутренняя валюта Telegram для оплаты.\n\n"
        "<b>Q: Как получить товар?</b>\n"
        "A: После оплаты товар придет автоматически или вручную от админа.\n\n"
        "<b>Q: Можно ли вернуть деньги?</b>\n"
        "A: Обратитесь в поддержку для решения вопроса.\n\n"
        f"<b>Остались вопросы?</b> Напишите: {BOT_CREATOR}"
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("support"))
@router.message(F.text == "💬 Поддержка")
async def cmd_support(message: Message):
    """Поддержка"""
    text = (
        "💬 <b>Поддержка</b>\n\n"
        f"По всем вопросам обращайтесь к создателю:\n"
        f"{BOT_CREATOR}\n\n"
        "Время ответа: обычно в течение 24 часов"
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(F.text == "ℹ️ О боте")
async def cmd_about(message: Message):
    """О боте"""
    text = (
        "ℹ️ <b>О боте Shark Of Buy</b>\n\n"
        "Автоматизированный магазин для покупки товаров и услуг\n\n"
        "<b>Особенности:</b>\n"
        "• Мгновенная доставка\n"
        "• Безопасные платежи\n"
        "• Качественные товары\n"
        "• Бонусы и подарки\n"
        "• Реферальная программа\n\n"
        f"<b>Создатель:</b> {BOT_CREATOR}\n"
        f"<b>Канал:</b> {REQUIRED_CHANNEL}"
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(F.text == "🎁 Получить подарок")
async def cmd_get_gift(message: Message):
    """Получить платный подарок (мишка)"""
    text = (
        "🎁 <b>Получите подарок-мишку от бота!</b>\n\n"
        "🧸 Заплатите <b>20 звезд</b>, чтобы получить подарок мишку от бота!\n\n"
        "💝 Это отличный способ порадовать себя или друга!"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Купить подарок за 20 ⭐", callback_data="buy_gift_bear")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "buy_gift_bear")
async def process_buy_gift(callback: CallbackQuery):
    """Обработка покупки подарка"""
    try:
        prices = [LabeledPrice(label="Подарок мишка 🧸", amount=20)]
        
        await callback.message.answer_invoice(
            title="🎁 Подарок мишка",
            description="Получите подарок-мишку от бота Shark Of Buy!",
            payload="gift_bear",
            provider_token="",
            currency="XTR",
            prices=prices
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при покупке подарка: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к админ-панели!")
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
    
    # Подтверждение рассылки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить", callback_data=f"broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    # Сохраняем текст рассылки временно
    if not hasattr(message.bot, "_broadcast_text"):
        message.bot._broadcast_text = {}
    message.bot._broadcast_text[message.from_user.id] = text
    
    await message.answer(
        f"📢 <b>Подтверждение рассылки</b>\n\n"
        f"Сообщение будет отправлено <b>{len(all_users)}</b> пользователям:\n\n"
        f"<i>{text[:200]}{'...' if len(text) > 200 else ''}</i>\n\n"
        f"Вы уверены?",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


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
    
    await callback.message.edit_text("📤 <b>Рассылка началась...</b>", parse_mode=ParseMode.HTML)
    
    all_users = db.get_all_users()
    success = 0
    failed = 0
    
    for user_id in all_users:
        try:
            await callback.bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            success += 1
            await asyncio.sleep(0.05)  # Задержка для избежания flood control
        except Exception as e:
            failed += 1
            logger.error(f"Ошибка рассылки пользователю {user_id}: {e}")
    
    # Удаляем сохраненный текст
    del callback.bot._broadcast_text[callback.from_user.id]
    
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
    if callback.bot._broadcast_text and callback.from_user.id in callback.bot._broadcast_text:
        del callback.bot._broadcast_text[callback.from_user.id]
    
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

        # Проверяем баланс пользователя
        user_balance = db.get_balance(callback.from_user.id)
        
        # Выбор способа оплаты
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💰 Баланс ({user_balance} ⭐)", callback_data=f"pay_balance_{product_id}")],
            [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay_stars_{product_id}")]
        ])
        
        await callback.message.answer(
            f"🛍 <b>{product['name']}</b>\n\n"
            f"💰 Цена: {product['price']} ⭐\n\n"
            "Выберите способ оплаты:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка при покупке: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)}")


@router.callback_query(F.data.startswith("pay_balance_"))
async def process_pay_with_balance(callback: CallbackQuery):
    """Оплата товара балансом"""
    try:
        product_id = callback.data.replace("pay_balance_", "")
        product = db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден!", show_alert=True)
            return
        
        user_id = callback.from_user.id
        balance = db.get_balance(user_id)
        price = product["price"]
        
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
            f"Цена: {price} ⭐\n"
            f"Списано с баланса: {price} ⭐\n"
            f"Остаток: {db.get_balance(user_id)} ⭐",
            parse_mode=ParseMode.HTML
        )
        
        if delivery_type == "manual":
            # Ручная выдача
            pending = db.add_pending_order(
                user_id,
                callback.from_user.username or "Без username",
                product_id,
                product["name"],
                price
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
                        f"Цена: {price} ⭐\n"
                        f"Покупатель: @{callback.from_user.username or callback.from_user.id}",
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )
                except:
                    pass
            
            db.add_order(user_id, callback.from_user.username or "Без username",
                        product_id, product["name"], price, status="pending")
        else:
            # Автоматическая выдача
            material = product["material"]
            if material["type"] == "text":
                await callback.message.answer(f"📄 <b>Ваш материал:</b>\n\n{material['content']}", parse_mode=ParseMode.HTML)
            elif material["type"] == "file":
                await callback.message.answer_document(document=material["file_id"], caption="📄 Ваш материал")
            elif material["type"] == "photo":
                await callback.message.answer_photo(photo=material["file_id"], caption="📄 Ваш материал")
            elif material["type"] == "video":
                await callback.message.answer_video(video=material["file_id"], caption="📄 Ваш материал")
            
            for admin_id in ADMIN_IDS:
                try:
                    await callback.bot.send_message(
                        admin_id,
                        f"💰 <b>Продажа (баланс)!</b>\n\n"
                        f"Товар: {product['name']}\n"
                        f"Цена: {price} ⭐\n"
                        f"Покупатель: @{callback.from_user.username or callback.from_user.id}",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
            
            db.add_order(user_id, callback.from_user.username or "Без username",
                        product_id, product["name"], price, status="completed")
        
        # Уменьшаем остаток
        db.decrease_stock(product_id)
        logger.info(f"Товар {product_id} куплен за баланс пользователем {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка оплаты балансом: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("pay_stars_"))
async def process_pay_with_stars(callback: CallbackQuery):
    """Оплата товара Telegram Stars"""
    try:
        product_id = callback.data.replace("pay_stars_", "")
        product = db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден!", show_alert=True)
            return
        
        price = max(1, product["price"])
        prices = [LabeledPrice(label=product["name"], amount=price)]

        await callback.message.answer_invoice(
            title=product["name"],
            description=product["description"],
            payload=f"product_{product_id}",
            provider_token="",
            currency="XTR",
            prices=prices
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка оплаты звездами: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


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
                0
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
                        product_id, product["name"], 0, status="pending")
        else:
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
                        product_id, product["name"], 0, status="completed")

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
        product_id = pre_checkout_query.invoice_payload.replace("product_", "")
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
        if stock is not None and stock <= 0:
            await pre_checkout_query.answer(
                ok=False,
                error_message="❌ Товар закончился"
            )
            logger.warning(f"Pre-checkout отклонён: товар {product_id} закончился")
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
            # Пополнение баланса
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
        
        # Проверяем, это подарок или товар
        if payload == "gift_bear":
            # Отправляем подарок мишку
            await message.answer(
                "🎉 <b>Спасибо за покупку подарка!</b>\n\n"
                "Вот ваш подарок:",
                parse_mode=ParseMode.HTML
            )
            
            # Отправляем gift с подписью
            await message.answer_gift(
                gift_id="7876657539541926320",  # ID подарка мишка
                text="@SharkBuy_rebot - лучший бот для покупки различных товаров!",
                text_parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Подарок мишка выдан пользователю {message.from_user.id}")
            
            # Уведомляем админов
            for admin_id in ADMIN_IDS:
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"🎁 <b>Продан подарок мишка!</b>\n\n"
                        f"Покупатель: @{message.from_user.username or message.from_user.id}\n"
                        f"Цена: 20 ⭐",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
            return
        
        # Обычный товар
        product_id = payload.replace("product_", "")
        logger.info(f"Успешная оплата: product_id={product_id}, user_id={message.from_user.id}")

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

        # Отправляем подтверждение
        await message.answer(
            f"✅ <b>Спасибо за покупку!</b>\n\n"
            f"Товар: {product['name']}\n"
            f"Цена: {product['price']} ⭐",
            parse_mode=ParseMode.HTML
        )

        if delivery_type == "manual":
            # Ручная выдача - добавляем в очередь
            pending = db.add_pending_order(
                message.from_user.id,
                message.from_user.username or "Без username",
                product_id,
                product["name"],
                product["price"]
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
                        f"Цена: {product['price']} ⭐\n"
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
                product["price"],
                status="pending"
            )
        else:
            # Автоматическая выдача
            material = product["material"]

            if material["type"] == "text":
                await message.answer(
                    f"📄 <b>Ваш материал:</b>\n\n{material['content']}",
                    parse_mode=ParseMode.HTML
                )
            elif material["type"] == "file":
                await message.answer_document(
                    document=material["file_id"],
                    caption="📄 Ваш материал"
                )
            elif material["type"] == "photo":
                await message.answer_photo(
                    photo=material["file_id"],
                    caption="📄 Ваш материал"
                )
            elif material["type"] == "video":
                await message.answer_video(
                    video=material["file_id"],
                    caption="📄 Ваш материал"
                )

            # Уведомляем админов о продаже
            for admin_id in ADMIN_IDS:
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"💰 <b>Новая продажа (авто)!</b>\n\n"
                        f"Товар: {product['name']}\n"
                        f"Цена: {product['price']} ⭐\n"
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
                product["price"],
                status="completed"
            )

        # Уменьшаем остаток товара
        db.decrease_stock(product_id)

    except Exception as e:
        logger.error(f"Критическая ошибка в successful_payment: {e}", exc_info=True)
        await message.answer(f"❌ Критическая ошибка: {str(e)}")


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
    
    # Статистика по категориям
    category_stats = {}
    for product in products.values():
        cat = product.get("category", "Без категории")
        category_stats[cat] = category_stats.get(cat, 0) + 1

    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"🛍 Товаров: {products_count}\n"
        f"📁 Категорий: {categories_count}\n"
        f"📦 Заказов: {stats['total_orders']}\n"
        f"💰 Доход: {stats['total_revenue']} ⭐\n\n"
    )
    
    if category_stats:
        text += "<b>По категориям:</b>\n"
        for cat, count in sorted(category_stats.items(), key=lambda x: x[1], reverse=True):
            text += f"  {cat}: {count}\n"

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
async def main():
    try:
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(router)

        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🤖 Бот запущен!")
        logger.info(f"Админы: {ADMIN_IDS}")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())