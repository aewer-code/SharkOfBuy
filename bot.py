"""
Xcrono игровой бот с честной игрой через эмодзи-рандом
Игры: кубики (чет/нечет), рулетка (777), угадай число, фриспины
"""
import asyncio
import os
import logging
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    Dice, BotCommand, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from database import Database

# Загружаем переменные окружения
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")

ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(",") if admin_id.strip()]

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

# Инициализация БД
db = Database()

# Состояния FSM
class GameStates(StatesGroup):
    waiting_bet_cubes = State()
    waiting_bet_roulette = State()
    waiting_bet_guess_number = State()
    waiting_guess_number = State()

# Роутер
router = Router()

# ============= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =============

def format_number(num: int) -> str:
    """Форматировать число с разделителями"""
    return f"{num:,}".replace(",", " ")

def get_main_menu() -> InlineKeyboardMarkup:
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎲 Кубики", callback_data="game_cubes"),
            InlineKeyboardButton(text="🎰 Рулетка", callback_data="game_roulette")
        ],
        [
            InlineKeyboardButton(text="🎯 Угадай число", callback_data="game_guess_number"),
            InlineKeyboardButton(text="🎁 Фриспины", callback_data="game_freespins")
        ],
        [
            InlineKeyboardButton(text="🛒 Магазин", callback_data="shop"),
            InlineKeyboardButton(text="💰 Заработать", callback_data="earn")
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
            InlineKeyboardButton(text="🏆 Лидерборд", callback_data="leaderboard")
        ],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])

def get_earn_menu() -> InlineKeyboardMarkup:
    """Меню заработка"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily_bonus")],
        [InlineKeyboardButton(text="📋 Задания", callback_data="tasks")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def get_shop_menu() -> InlineKeyboardMarkup:
    """Меню магазина"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Бусты", callback_data="shop_boosts")],
        [InlineKeyboardButton(text="🏆 Титулы", callback_data="shop_titles")],
        [InlineKeyboardButton(text="📦 Кейсы", callback_data="shop_cases")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура внизу экрана"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 ИГРАТЬ")],
            [
                KeyboardButton(text="⚡ Профиль"),
                KeyboardButton(text="🔗 Реферальная система")
            ]
        ],
        resize_keyboard=True,
        persistent=True
    )

# ============= ОБРАБОТЧИКИ КОМАНД =============

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Стартовая команда"""
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Обработка реферальной ссылки
    referrer_id = None
    if message.text and len(message.text.split()) > 1:
        try:
            referrer_id = int(message.text.split()[1])
            # Проверяем, что пользователь не регистрирует сам себя
            if referrer_id == user_id:
                referrer_id = None
        except ValueError:
            pass
    
    # Создаем пользователя, если его нет
    if not db.get_user(user_id):
        db.create_user(user_id, username, referrer_id)
        balance = 1000
        text = (
            "👋 <b>Добро пожаловать, @{username}!</b>\n\n"
            "🎮 <b>XCRONO ИГРОВОЙ БОТ</b>\n\n"
            "🎲 <b>Честная игра через эмодзи Telegram</b>\n"
            "Все результаты определяются случайными эмодзи от Telegram!\n\n"
            f"💰 Ваш стартовый баланс: <b>{format_number(balance)} монет</b>\n\n"
            "<i>Выберите действие:</i>"
        ).format(username=username or "игрок")
    else:
        user = db.get_user(user_id)
        balance = user['balance']
        bonus_balance = db.get_bonus_balance(user_id)
        text = (
            "🎮 <b>XCRONO ИГРОВОЙ БОТ</b>\n\n"
            f"💰 Баланс: <b>{format_number(balance)} монет</b>\n"
            f"💎 Бонусный баланс: <b>{format_number(bonus_balance)} монет</b>\n"
            f"📊 Уровень: <b>{user['level']}</b>\n"
            f"⭐ Опыт: <b>{user['experience']}/100</b>\n\n"
            "<i>Выберите действие:</i>"
        )
    
    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.HTML)

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    """Проверить баланс"""
    user_id = message.from_user.id
    balance = db.get_balance(user_id)
    await message.answer(f"💰 Ваш баланс: <b>{format_number(balance)} монет</b>", parse_mode=ParseMode.HTML)

# ============= ОБРАБОТЧИКИ CALLBACK =============

@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    """Главное меню"""
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    if not user:
        db.create_user(user_id, callback.from_user.username)
        user = db.get_user(user_id)
    
    balance = user['balance']
    text = (
        "🎰 <b>КАЗИНО</b>\n\n"
        f"💰 Баланс: <b>{format_number(balance)} монет</b>\n"
        f"📊 Уровень: <b>{user['level']}</b>\n"
        f"⭐ Опыт: <b>{user['experience']}/100</b>\n\n"
        "<i>Выберите действие:</i>"
    )
    await callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "game_cubes")
async def callback_game_cubes(callback: CallbackQuery, state: FSMContext):
    """Игра в кубики"""
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    if balance < 10:
        await callback.answer("❌ Недостаточно монет! Минимум 10 монет для игры.", show_alert=True)
        return
    
    text = (
        "🎲 <b>Игра в кубики</b>\n\n"
        "Правила:\n"
        "• Ставка на четное или нечетное\n"
        "• Коэффициент выигрыша: <b>x1.8</b>\n"
        "• Минимальная ставка: <b>10 монет</b>\n\n"
        f"💰 Ваш баланс: <b>{format_number(balance)} монет</b>\n\n"
        "Введите сумму ставки (или выберите):"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="10", callback_data="bet_cubes_10"),
            InlineKeyboardButton(text="50", callback_data="bet_cubes_50"),
            InlineKeyboardButton(text="100", callback_data="bet_cubes_100")
        ],
        [
            InlineKeyboardButton(text="500", callback_data="bet_cubes_500"),
            InlineKeyboardButton(text="1000", callback_data="bet_cubes_1000")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await state.set_state(GameStates.waiting_bet_cubes)
    await callback.answer()

@router.callback_query(F.data.startswith("bet_cubes_"))
async def callback_bet_cubes_amount(callback: CallbackQuery, state: FSMContext):
    """Выбор суммы ставки для кубиков"""
    bet_amount = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    if balance < bet_amount:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)
        return
    
    await state.update_data(bet_amount=bet_amount)
    
    text = (
        f"🎲 <b>Ставка: {format_number(bet_amount)} монет</b>\n\n"
        "Выберите, на что ставите:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚪ Четное", callback_data="cubes_even"),
            InlineKeyboardButton(text="⚫ Нечетное", callback_data="cubes_odd")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="game_cubes")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data.startswith("cubes_"))
async def callback_cubes_play(callback: CallbackQuery, state: FSMContext):
    """Игра в кубики"""
    user_id = callback.from_user.id
    data = await state.get_data()
    bet_amount = data.get("bet_amount")
    
    if not bet_amount:
        await callback.answer("❌ Ошибка! Попробуйте снова.", show_alert=True)
        return
    
    choice = "even" if callback.data == "cubes_even" else "odd"
    balance = db.get_balance(user_id)
    
    if balance < bet_amount:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)
        return
    
    # Списываем ставку
    db.update_balance(user_id, -bet_amount)
    
    # Отправляем эмодзи кубика
    try:
        bot = callback.bot
        dice_message = await bot.send_dice(callback.message.chat.id, emoji="🎲")
        
        # Ждем результат
        await asyncio.sleep(4)
        
        # Получаем значение кубика (1-6)
        dice_value = dice_message.dice.value
    except Exception as e:
        logger.error(f"Ошибка при отправке кубика: {e}")
        await callback.answer("❌ Ошибка! Попробуйте снова.", show_alert=True)
        return
    
    # Определяем четное или нечетное
    is_even = dice_value % 2 == 0
    won = (choice == "even" and is_even) or (choice == "odd" and not is_even)
    
    if won:
        win_amount = int(bet_amount * 1.8)
        db.update_balance(user_id, win_amount)
        db.record_game(user_id, "cubes", bet_amount, "win", win_amount, f"🎲 {dice_value}")
        db.add_experience(user_id, 5)
        
        result_text = (
            f"🎉 <b>ВЫ ВЫИГРАЛИ!</b>\n\n"
            f"🎲 Выпало: <b>{dice_value}</b> <i>({'четное' if is_even else 'нечетное'})</i>\n"
            f"💰 Ставка: <b>{format_number(bet_amount)} монет</b>\n"
            f"💵 Выигрыш: <b>+{format_number(win_amount)} монет</b>\n"
            f"📈 Новый баланс: <b>{format_number(db.get_balance(user_id))} монет</b>"
        )
    else:
        db.record_game(user_id, "cubes", bet_amount, "loss", 0, f"🎲 {dice_value}")
        db.add_experience(user_id, 2)
        
        result_text = (
            f"❌ <b>ВЫ ПРОИГРАЛИ</b>\n\n"
            f"🎲 Выпало: <b>{dice_value}</b> <i>({'четное' if is_even else 'нечетное'})</i>\n"
            f"💰 Ставка: <b>{format_number(bet_amount)} монет</b>\n"
            f"📉 Новый баланс: <b>{format_number(db.get_balance(user_id))} монет</b>"
        )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Играть снова", callback_data="game_cubes")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    # Используем bot для отправки сообщения, чтобы callback работал
    bot = callback.bot
    await bot.send_message(
        callback.message.chat.id,
        result_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "game_roulette")
async def callback_game_roulette(callback: CallbackQuery, state: FSMContext):
    """Игра в рулетку"""
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    if balance < 50:
        await callback.answer("❌ Недостаточно монет! Минимум 50 монет для игры.", show_alert=True)
        return
    
    text = (
        "🎰 <b>Рулетка 777</b>\n\n"
        "Правила:\n"
        "• Выпадает 777 = выигрыш <b>x2.0</b>\n"
        "• Иначе = проигрыш\n"
        "• Минимальная ставка: <b>50 монет</b>\n\n"
        f"💰 Ваш баланс: <b>{format_number(balance)} монет</b>\n\n"
        "Введите сумму ставки:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="50", callback_data="bet_roulette_50"),
            InlineKeyboardButton(text="100", callback_data="bet_roulette_100"),
            InlineKeyboardButton(text="500", callback_data="bet_roulette_500")
        ],
        [
            InlineKeyboardButton(text="1000", callback_data="bet_roulette_1000"),
            InlineKeyboardButton(text="5000", callback_data="bet_roulette_5000")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await state.set_state(GameStates.waiting_bet_roulette)
    await callback.answer()

@router.callback_query(F.data.startswith("bet_roulette_"))
async def callback_roulette_play(callback: CallbackQuery, state: FSMContext):
    """Игра в рулетку"""
    bet_amount = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    if balance < bet_amount:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)
        return
    
    # Списываем ставку
    db.update_balance(user_id, -bet_amount)
    
    # Отправляем одно эмодзи рулетки (слот-машины)
    try:
        bot = callback.bot
        slot_message = await bot.send_dice(callback.message.chat.id, emoji="🎰")
        
        # Ждем результат
        await asyncio.sleep(4)
        
        # Получаем значение (1-64 для слот-машины, где 64 = 777)
        slot_value = slot_message.dice.value
        
        # Проверяем на 777: значение должно быть 64
        won = (slot_value == 64)
        
        emoji_result = f"🎰 {slot_value}"
        
        if won:
            win_amount = int(bet_amount * 2.0)
            db.update_balance(user_id, win_amount)
            db.record_game(user_id, "roulette", bet_amount, "win", win_amount, emoji_result)
            db.add_experience(user_id, 10)
            
            result_text = (
                f"🎉🎉🎉 <b>ДЖЕКПОТ! 777!</b> 🎉🎉🎉\n\n"
                f"🎰 Результат: <b>777</b>\n"
                f"💰 Ставка: <b>{format_number(bet_amount)} монет</b>\n"
                f"💵 Выигрыш: <b>+{format_number(win_amount)} монет</b>\n"
                f"📈 Новый баланс: <b>{format_number(db.get_balance(user_id))} монет</b>"
            )
        else:
            db.record_game(user_id, "roulette", bet_amount, "loss", 0, emoji_result)
            db.add_experience(user_id, 3)
            
            result_text = (
                f"❌ <b>НЕ ПОВЕЗЛО</b>\n\n"
                f"🎰 Результат: <b>{slot_value}</b>\n"
                f"💰 Ставка: <b>{format_number(bet_amount)} монет</b>\n"
                f"📉 Новый баланс: <b>{format_number(db.get_balance(user_id))} монет</b>\n\n"
                "💡 <i>Попробуйте еще раз!</i>"
            )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Играть снова", callback_data="game_roulette")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
        ])
        
        await bot.send_message(
            callback.message.chat.id,
            result_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        await state.clear()
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в рулетке: {e}")
        await callback.answer("❌ Ошибка! Попробуйте снова.", show_alert=True)
        # Возвращаем ставку при ошибке
        db.update_balance(user_id, bet_amount)

@router.callback_query(F.data == "game_guess_number")
async def callback_game_guess_number(callback: CallbackQuery, state: FSMContext):
    """Игра Угадай число"""
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    if balance < 50:
        await callback.answer("❌ Недостаточно монет! Минимум 50 монет для игры.", show_alert=True)
        return
    
    text = (
        "🎯 <b>Угадай число</b>\n\n"
        "Правила:\n"
        "• Бросаются 3 кубика (сумма от 3 до 18)\n"
        "• Угадай сумму всех кубиков\n"
        "• Коэффициент выигрыша: <b>x2.0</b>\n"
        "• Минимальная ставка: <b>50 монет</b>\n\n"
        f"💰 Ваш баланс: <b>{format_number(balance)} монет</b>\n\n"
        "Введите сумму ставки:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="50", callback_data="bet_guess_50"),
            InlineKeyboardButton(text="100", callback_data="bet_guess_100"),
            InlineKeyboardButton(text="500", callback_data="bet_guess_500")
        ],
        [
            InlineKeyboardButton(text="1000", callback_data="bet_guess_1000"),
            InlineKeyboardButton(text="5000", callback_data="bet_guess_5000")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await state.set_state(GameStates.waiting_bet_guess_number)
    await callback.answer()

@router.callback_query(F.data.startswith("bet_guess_"))
async def callback_guess_number_bet(callback: CallbackQuery, state: FSMContext):
    """Выбор суммы ставки для угадай число"""
    bet_amount = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    if balance < bet_amount:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)
        return
    
    await state.update_data(bet_amount=bet_amount)
    
    text = (
        f"🎯 <b>Ставка: {format_number(bet_amount)} монет</b>\n\n"
        "Угадай сумму трех кубиков (от 3 до 18):\n\n"
        "Выберите число:"
    )
    
    # Создаем кнопки с числами от 3 до 18
    buttons = []
    row = []
    for num in range(3, 19):
        row.append(InlineKeyboardButton(text=str(num), callback_data=f"guess_{num}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="game_guess_number")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await state.set_state(GameStates.waiting_guess_number)
    await callback.answer()

@router.callback_query(F.data.startswith("guess_"))
async def callback_guess_number_play(callback: CallbackQuery, state: FSMContext):
    """Игра угадай число"""
    guessed_number = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    data = await state.get_data()
    bet_amount = data.get("bet_amount")
    
    if not bet_amount:
        await callback.answer("❌ Ошибка! Попробуйте снова.", show_alert=True)
        return
    
    balance = db.get_balance(user_id)
    if balance < bet_amount:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)
        return
    
    # Списываем ставку
    db.update_balance(user_id, -bet_amount)
    
    # Отправляем 3 эмодзи кубика
    try:
        bot = callback.bot
        dice1 = await bot.send_dice(callback.message.chat.id, emoji="🎲")
        dice2 = await bot.send_dice(callback.message.chat.id, emoji="🎲")
        dice3 = await bot.send_dice(callback.message.chat.id, emoji="🎲")
        
        # Ждем результаты
        await asyncio.sleep(4)
        
        # Получаем значения
        val1 = dice1.dice.value
        val2 = dice2.dice.value
        val3 = dice3.dice.value
    except Exception as e:
        logger.error(f"Ошибка при отправке кубиков: {e}")
        await callback.answer("❌ Ошибка! Попробуйте снова.", show_alert=True)
        return
    
    # Сумма всех кубиков
    total_sum = val1 + val2 + val3
    won = (guessed_number == total_sum)
    
    emoji_result = f"🎲{val1}+🎲{val2}+🎲{val3}={total_sum}"
    
    if won:
        win_amount = int(bet_amount * 2.0)
        db.update_balance(user_id, win_amount)
        db.record_game(user_id, "guess_number", bet_amount, "win", win_amount, emoji_result)
        db.add_experience(user_id, 10)
        
        result_text = (
            f"🎉 <b>ВЫ УГАДАЛИ!</b>\n\n"
            f"🎲 Результат: <b>{val1} + {val2} + {val3} = {total_sum}</b>\n"
            f"🎯 Ваше число: <b>{guessed_number}</b>\n"
            f"💰 Ставка: <b>{format_number(bet_amount)} монет</b>\n"
            f"💵 Выигрыш: <b>+{format_number(win_amount)} монет</b>\n"
            f"📈 Новый баланс: <b>{format_number(db.get_balance(user_id))} монет</b>"
        )
    else:
        db.record_game(user_id, "guess_number", bet_amount, "loss", 0, emoji_result)
        db.add_experience(user_id, 3)
        
        result_text = (
            f"❌ <b>НЕ УГАДАЛИ</b>\n\n"
            f"🎲 Результат: <b>{val1} + {val2} + {val3} = {total_sum}</b>\n"
            f"🎯 Ваше число: <b>{guessed_number}</b>\n"
            f"💰 Ставка: <b>{format_number(bet_amount)} монет</b>\n"
            f"📉 Новый баланс: <b>{format_number(db.get_balance(user_id))} монет</b>\n\n"
            "💡 <i>Попробуйте еще раз!</i>"
        )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Играть снова", callback_data="game_guess_number")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    # Используем bot для отправки сообщения, чтобы callback работал
    bot = callback.bot
    await bot.send_message(
        callback.message.chat.id,
        result_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "game_freespins")
async def callback_freespins(callback: CallbackQuery):
    """Фриспины"""
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    can_freespin = db.can_claim_freespin(user_id)
    
    if can_freespin:
        status_text = "✅ <b>Доступен</b>"
    else:
        user = db.get_user(user_id)
        last_freespin = user.get('last_freespin')
        if last_freespin:
            try:
                last_date = datetime.strptime(last_freespin, "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                time_diff = now - last_date
                hours_left = 12 - (time_diff.total_seconds() / 3600)
                if hours_left > 0:
                    status_text = f"⏳ <b>Доступен через {int(hours_left)} ч. {int((hours_left % 1) * 60)} мин.</b>"
                else:
                    status_text = "✅ <b>Доступен</b>"
            except:
                status_text = "✅ <b>Доступен</b>"
        else:
            status_text = "✅ <b>Доступен</b>"
    
    text = (
        "🎁 <b>Фриспины</b>\n\n"
        "Бесплатные вращения с маленькими выигрышами!\n"
        "Используйте фриспины для получения монет.\n"
        "<i>Доступно 1 раз в 12 часов</i>\n\n"
        f"💰 Ваш баланс: <b>{format_number(balance)} монет</b>\n"
        f"📊 Статус: {status_text}\n\n"
        "Нажмите кнопку для бесплатного вращения:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Крутить бесплатно", callback_data="do_freespin")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "do_freespin")
async def callback_do_freespin(callback: CallbackQuery):
    """Выполнить фриспин"""
    user_id = callback.from_user.id
    import random
    
    # Отправляем эмодзи слот-машины
    try:
        bot = callback.bot
        slot_message = await bot.send_dice(callback.message.chat.id, emoji="🎰")
        
        await asyncio.sleep(4)
        
        # Получаем значение (1-64 для слот-машины)
        slot_value = slot_message.dice.value
    except Exception as e:
        logger.error(f"Ошибка при отправке фриспина: {e}")
        await callback.answer("❌ Ошибка! Попробуйте снова.", show_alert=True)
        return
    
    # Маленькие выигрыши: 10-50 монет в зависимости от значения
    # Чем выше значение, тем больше выигрыш
    if slot_value >= 60:
        win_amount = random.randint(40, 50)
    elif slot_value >= 40:
        win_amount = random.randint(25, 40)
    elif slot_value >= 20:
        win_amount = random.randint(15, 25)
    else:
        win_amount = random.randint(10, 15)
    
    db.update_balance(user_id, win_amount)
    db.record_game(user_id, "freespin", 0, "win", win_amount, f"🎰 {slot_value}")
    db.add_experience(user_id, 1)
    
    result_text = (
        f"🎁 <b>ФРИСПИН ЗАВЕРШЕН!</b>\n\n"
        f"🎰 Результат: <b>{slot_value}</b>\n"
        f"💵 Выигрыш: <b>+{format_number(win_amount)} монет</b>\n"
        f"📈 Новый баланс: <b>{format_number(db.get_balance(user_id))} монет</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Крутить еще", callback_data="do_freespin")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    bot = callback.bot
    await bot.send_message(
        callback.message.chat.id,
        result_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "earn")
async def callback_earn(callback: CallbackQuery):
    """Меню заработка"""
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    
    can_daily = db.can_claim_daily(user_id)
    daily_text = "✅ Доступен" if can_daily else "⏳ Уже получен сегодня"
    
    text = (
        "💰 <b>Заработать монеты</b>\n\n"
        f"🎁 Ежедневный бонус: {daily_text}\n"
        "📋 Задания: доступны\n\n"
        "Выберите способ заработка:"
    )
    
    await callback.message.edit_text(text, reply_markup=get_earn_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "daily_bonus")
async def callback_daily_bonus(callback: CallbackQuery):
    """Ежедневный бонус"""
    user_id = callback.from_user.id
    
    if not db.can_claim_daily(user_id):
        await callback.answer("❌ Вы уже получили бонус сегодня! Приходите завтра.", show_alert=True)
        return
    
    bonus = db.claim_daily_bonus(user_id)
    new_balance = db.get_balance(user_id)
    
    text = (
        f"🎁 <b>Ежедневный бонус получен!</b>\n\n"
        f"💰 Бонус: <b>{format_number(bonus)} монет</b>\n"
        f"📈 Новый баланс: <b>{format_number(new_balance)} монет</b>\n\n"
        "Приходите завтра за новым бонусом!"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="earn")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):
    """Статистика"""
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        db.create_user(user_id, callback.from_user.username)
        user = db.get_user(user_id)
    
    winrate = db.get_winrate(user_id)
    total_games = user['total_wins'] + user['total_losses']
    
    text = (
        "📊 <b>Ваша статистика</b>\n\n"
        f"💰 Баланс: <b>{format_number(user['balance'])} монет</b>\n"
        f"📈 Уровень: <b>{user['level']}</b>\n"
        f"⭐ Опыт: <b>{user['experience']}/100</b>\n\n"
        f"🎮 Всего игр: <b>{total_games}</b>\n"
        f"✅ Побед: <b>{user['total_wins']}</b>\n"
        f"❌ Поражений: <b>{user['total_losses']}</b>\n"
        f"📊 Винрейт: <b>{winrate:.2f}%</b>\n"
        f"💵 Всего поставлено: <b>{format_number(user['total_bet'])} монет</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "leaderboard")
async def callback_leaderboard(callback: CallbackQuery):
    """Лидерборд по винрейту"""
    leaderboard = db.get_leaderboard(10)
    
    if not leaderboard:
        text = "🏆 <b>Лидерборд</b>\n\nПока нет игроков в рейтинге."
    else:
        text = "🏆 <b>Лидерборд по винрейту</b>\n\n"
        for i, player in enumerate(leaderboard, 1):
            username = player['username'] or f"ID{player['user_id']}"
            winrate = player['winrate']
            wins = player['total_wins']
            games = player['total_wins'] + player['total_losses']
            
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            text += f"{medal} <b>{username}</b>\n"
            text += f"   📊 {winrate:.2f}% ({wins}/{games} игр)\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="leaderboard")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "shop")
async def callback_shop(callback: CallbackQuery):
    """Магазин"""
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    text = (
        "🛒 <b>Магазин</b>\n\n"
        f"💰 Ваш баланс: <b>{format_number(balance)} монет</b>\n\n"
        "Выберите категорию:"
    )
    
    await callback.message.edit_text(text, reply_markup=get_shop_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "shop_boosts")
async def callback_shop_boosts(callback: CallbackQuery):
    """Бусты в магазине"""
    text = (
        "⚡ <b>Бусты и улучшения</b>\n\n"
        "🔄 Увеличение ежедневного бонуса +10% - <b>500 монет</b>\n"
        "📈 Увеличение лимита ставок +100 - <b>300 монет</b>\n"
        "🎁 5 дополнительных фриспинов - <b>200 монет</b>\n"
        "🛡️ Защита от проигрыша (1 раз) - <b>150 монет</b>\n\n"
        "💡 Скоро в продаже!"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в магазин", callback_data="shop")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "shop_titles")
async def callback_shop_titles(callback: CallbackQuery):
    """Титулы в магазине"""
    text = (
        "🏆 <b>Титулы</b>\n\n"
        "Титулы отображаются в вашем профиле и статистике:\n\n"
        "🎯 Новичок - <b>Бесплатно</b> (при регистрации)\n"
        "⭐ Удачливый - <b>500 монет</b>\n"
        "💎 Богач - <b>1000 монет</b>\n"
        "👑 Легенда - <b>2000 монет</b>\n"
        "🔥 Мастер - <b>5000 монет</b>\n\n"
        "💡 Скоро в продаже!"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в магазин", callback_data="shop")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "shop_cases")
async def callback_shop_cases(callback: CallbackQuery):
    """Кейсы в магазине"""
    text = (
        "📦 <b>Кейсы</b>\n\n"
        "📦 Обычный кейс (10-100 монет) - <b>100 монет</b>\n"
        "📦 Редкий кейс (50-300 монет) - <b>300 монет</b>\n"
        "📦 Эпический кейс (200-1000 монет) - <b>500 монет</b>\n\n"
        "💡 Скоро в продаже!"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в магазин", callback_data="shop")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery):
    """Помощь"""
    text = (
        "ℹ️ <b>Помощь</b>\n\n"
        "🎲 <b>Кубики:</b>\n"
        "Ставка на четное/нечетное\n"
        "Коэффициент: x1.8\n"
        "Минимум: 10 монет\n\n"
        "🎰 <b>Рулетка 777:</b>\n"
        "Крутите рулетку (🎰)\n"
        "Выпадает 777 = выигрыш x2.0\n"
        "Минимум: 50 монет\n\n"
        "🎯 <b>Угадай число:</b>\n"
        "Угадай сумму трех кубиков (3-18)\n"
        "Коэффициент: x2.0\n"
        "Минимум: 50 монет\n\n"
        "🎁 <b>Фриспины:</b>\n"
        "Бесплатные вращения\n"
        "Выигрыши: 10-50 монет\n\n"
        "💰 <b>Заработок:</b>\n"
        "• Ежедневный бонус (100-300 монет)\n"
        "• Задания (скоро)\n\n"
        "🎯 <b>Особенность:</b>\n"
        "Все игры используют честный рандом от Telegram!\n"
        "Результаты определяются эмодзи-кубиками.\n"
        "Обмануть невозможно!"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

# Обработка текстовых ставок
@router.message(StateFilter(GameStates.waiting_bet_cubes))
async def handle_bet_cubes_text(message: Message, state: FSMContext):
    """Обработка текстовой ставки для кубиков"""
    if not message.text or not message.text.strip().isdigit():
        return  # Игнорируем нечисловые сообщения
    
    try:
        bet_amount = int(message.text.strip())
        if bet_amount < 10:
            await message.answer("❌ Минимальная ставка: 10 монет")
            return
        
        balance = db.get_balance(message.from_user.id)
        if balance < bet_amount:
            await message.answer("❌ Недостаточно монет!")
            return
        
        await state.update_data(bet_amount=bet_amount)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⚪ Четное", callback_data="cubes_even"),
                InlineKeyboardButton(text="⚫ Нечетное", callback_data="cubes_odd")
            ]
        ])
        
        await message.answer(
            f"🎲 Ставка: <b>{format_number(bet_amount)} монет</b>\n\nВыберите, на что ставите:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except (ValueError, AttributeError):
        pass  # Игнорируем ошибки

@router.message(StateFilter(GameStates.waiting_bet_roulette))
async def handle_bet_roulette_text(message: Message, state: FSMContext):
    """Обработка текстовой ставки для рулетки"""
    if not message.text or not message.text.strip().isdigit():
        return  # Игнорируем нечисловые сообщения
    
    try:
        bet_amount = int(message.text.strip())
        if bet_amount < 50:
            await message.answer("❌ Минимальная ставка: 50 монет")
            return
        
        balance = db.get_balance(message.from_user.id)
        if balance < bet_amount:
            await message.answer("❌ Недостаточно монет!")
            return
        
        # Автоматически запускаем игру
        user_id = message.from_user.id
        db.update_balance(user_id, -bet_amount)
        
        bot = message.bot
        try:
            slot_message = await bot.send_dice(message.chat.id, emoji="🎰")
            
            await asyncio.sleep(4)
            
            slot_value = slot_message.dice.value
            
            # Проверяем на 777: значение должно быть 64
            won = (slot_value == 64)
            emoji_result = f"🎰 {slot_value}"
            
            if won:
                win_amount = int(bet_amount * 2.0)
                db.update_balance(user_id, win_amount)
                db.record_game(user_id, "roulette", bet_amount, "win", win_amount, emoji_result)
                db.add_experience(user_id, 10)
                
                result_text = (
                    f"🎉🎉🎉 <b>ДЖЕКПОТ! 777!</b> 🎉🎉🎉\n\n"
                    f"🎰 Результат: <b>777</b>\n"
                    f"💰 Ставка: <b>{format_number(bet_amount)} монет</b>\n"
                    f"💵 Выигрыш: <b>+{format_number(win_amount)} монет</b>\n"
                    f"📈 Новый баланс: <b>{format_number(db.get_balance(user_id))} монет</b>"
                )
            else:
                db.record_game(user_id, "roulette", bet_amount, "loss", 0, emoji_result)
                db.add_experience(user_id, 3)
                
                result_text = (
                    f"❌ <b>НЕ ПОВЕЗЛО</b>\n\n"
                    f"🎰 Результат: <b>{slot_value}</b>\n"
                    f"💰 Ставка: <b>{format_number(bet_amount)} монет</b>\n"
                    f"📉 Новый баланс: <b>{format_number(db.get_balance(user_id))} монет</b>\n\n"
                    "💡 <i>Попробуйте еще раз!</i>"
                )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Играть снова", callback_data="game_roulette")],
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
            
            await bot.send_message(
                message.chat.id,
                result_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            await state.clear()
        except Exception as e:
            logger.error(f"Ошибка в рулетке: {e}")
            await message.answer("❌ Ошибка! Попробуйте снова.")
            await state.clear()
    except ValueError:
        pass  # Игнорируем ошибки

# ============= ОБРАБОТЧИКИ КНОПОК ПОСТОЯННОЙ КЛАВИАТУРЫ =============

@router.message(F.text == "🚀 ИГРАТЬ")
async def handle_play_button(message: Message):
    """Обработка кнопки ИГРАТЬ"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        db.create_user(user_id, message.from_user.username)
        user = db.get_user(user_id)
    
    balance = user['balance']
    bonus_balance = db.get_bonus_balance(user_id)
    
    text = (
        "🎮 <b>ВЫБЕРИТЕ ИГРУ</b>\n\n"
        f"💰 Баланс: <b>{format_number(balance)} монет</b>\n"
        f"💎 Бонусный баланс: <b>{format_number(bonus_balance)} монет</b>\n\n"
        "<i>Выберите игру:</i>"
    )
    
    keyboard = get_main_menu()
    
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

@router.message(F.text == "⚡ Профиль")
async def handle_profile_button(message: Message):
    """Обработка кнопки Профиль"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        db.create_user(user_id, message.from_user.username)
        user = db.get_user(user_id)
    
    balance = user['balance']
    bonus_balance = db.get_bonus_balance(user_id)
    winrate = db.get_winrate(user_id)
    total_games = user['total_wins'] + user['total_losses']
    max_win = user.get('max_win', 0)
    referral_earnings = user.get('referral_earnings', 0)
    
    # Вычисляем дни с нами
    try:
        created_at = datetime.strptime(user.get('created_at', ''), "%Y-%m-%d %H:%M:%S")
        days_with_us = (datetime.now() - created_at).days
    except:
        days_with_us = 0
    
    text = (
        "⚡ <b>ПРОФИЛЬ</b>\n\n"
        f"💰 Баланс: {format_number(balance)} монет\n"
        f"💎 Бонусный баланс: {format_number(bonus_balance)} монет\n\n"
        "<b>🎮 Игровая статистика:</b>\n"
        f"🎲 Кол-во игр: {total_games}\n"
        f"💸 Сумма ставок: {format_number(user['total_bet'])} монет\n"
        f"🏆 Макс. выигрыш: {format_number(max_win)} монет\n"
        f"📈 Винрейт: {winrate:.2f}%\n\n"
        "<b>📊 Общая статистика:</b>\n"
        f"🥉 Лига: Bronze 🥉\n"
        f"🤝 Реферальный заработок: {format_number(referral_earnings)} монет\n"
        f"🗓️ Вы с нами {days_with_us} дней\n\n"
        f"⚙️ ID: <code>{user_id}</code>"
    )
    
    # Проверяем, является ли пользователь админом
    is_admin = user_id in ADMIN_IDS
    
    keyboard_buttons = [
        [
            InlineKeyboardButton(text="🏆 Топ", callback_data="top_players"),
            InlineKeyboardButton(text="🎁 Бонусы", callback_data="bonuses")
        ],
        [InlineKeyboardButton(text="🏷️ Промокод", callback_data="promo_code")]
    ]
    
    if is_admin:
        keyboard_buttons.append([InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin_panel")])
    
    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

@router.message(F.text == "🔗 Реферальная система")
async def handle_referral_button(message: Message):
    """Обработка кнопки Реферальная система"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        db.create_user(user_id, message.from_user.username)
        user = db.get_user(user_id)
    
    referral_earnings = user.get('referral_earnings', 0)
    referrals_count = user.get('referrals_count', 0)
    balance = user['balance']
    
    # Получаем статистику игр рефералов
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) as games FROM games g
        JOIN users u ON g.user_id = u.user_id
        WHERE u.referrer_id = ?
    """, (user_id,))
    row = cursor.fetchone()
    referral_games = row['games'] if row else 0
    conn.close()
    
    # Получаем username бота из токена (первые цифры до двоеточия)
    bot_username = "XcronoBot"  # Замените на реальный username вашего бота
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    
    text = (
        "🔗 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
        "Твоя комиссия — <b>10%</b> с выигрышных ставок рефералов.\n"
        "(80% нашей прибыли)\n\n"
        "<b>📊 Общая информация:</b>\n"
        f"💰 Баланс: <b>{format_number(balance)} монет</b>\n"
        f"🥉 Лига: <b>Bronze</b>\n\n"
        "<b>📈 За всё время:</b>\n"
        f"💵 Заработано: <b>{format_number(referral_earnings)} монет</b>\n"
        f"👥 Рефералы: <b>{referrals_count}</b>\n"
        f"🎮 Игр пройдено: <b>{referral_games}</b>\n\n"
        f"🔗 <b>Реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="referral_stats"),
            InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "deposit")
async def callback_deposit(callback: CallbackQuery):
    """Пополнение баланса"""
    user_id = callback.from_user.id
    balance = db.get_balance(user_id)
    
    text = (
        "💸 <b>Пришлите сумму монет для игры</b> 👇\n\n"
        "Минимум: <b>50 монет</b>\n"
        f"💰 Баланс: <b>{format_number(balance)} монет</b>\n\n"
        "<i>Введите сумму для пополнения (минимум 50 монет):</i>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="50", callback_data="deposit_50"),
            InlineKeyboardButton(text="100", callback_data="deposit_100"),
            InlineKeyboardButton(text="500", callback_data="deposit_500")
        ],
        [
            InlineKeyboardButton(text="1000", callback_data="deposit_1000"),
            InlineKeyboardButton(text="5000", callback_data="deposit_5000")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data.startswith("deposit_"))
async def callback_deposit_amount(callback: CallbackQuery):
    """Пополнение баланса на указанную сумму"""
    amount = int(callback.data.split("_")[1])
    
    if amount < 50:
        await callback.answer("❌ Минимум 50 монет!", show_alert=True)
        return
    
    user_id = callback.from_user.id
    db.update_balance(user_id, amount)
    new_balance = db.get_balance(user_id)
    
    text = (
        f"✅ <b>Баланс пополнен!</b>\n\n"
        f"💰 Пополнено: <b>+{format_number(amount)} монет</b>\n"
        f"📈 Новый баланс: <b>{format_number(new_balance)} монет</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer("✅ Баланс пополнен!")

@router.callback_query(F.data == "play_balance")
async def callback_play_balance(callback: CallbackQuery):
    """Игра с обычным балансом"""
    await callback.answer("Выберите игру из меню")
    await callback_main_menu(callback)


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
        logger.info("✅ Webhook удален")
        
        await asyncio.sleep(1)
        
        commands = [
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="balance", description="Проверить баланс"),
        ]
        await bot.set_my_commands(commands)
        
        logger.info("🎮 Xcrono игровой бот запущен!")
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())

