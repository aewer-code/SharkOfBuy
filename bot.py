"""
Бот для рассылки сообщений в Telegram чаты
Функционал рассылки с поддержкой сессий
"""
import asyncio
import os
import logging
import re
import shutil
from typing import Optional
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from session_manager import session_manager


def parse_time_interval(time_str: str) -> float:
    """
    Парсит строку времени в секунды
    Поддерживает форматы: 1ч, 30м, 1ч30м, 1ч30м30с, 2д1ч3м30с
    """
    time_str = time_str.lower().strip()
    total_seconds = 0
    
    # Дни
    days_match = re.search(r'(\d+)д', time_str)
    if days_match:
        total_seconds += int(days_match.group(1)) * 86400
    
    # Часы
    hours_match = re.search(r'(\d+)ч', time_str)
    if hours_match:
        total_seconds += int(hours_match.group(1)) * 3600
    
    # Минуты
    minutes_match = re.search(r'(\d+)м', time_str)
    if minutes_match:
        total_seconds += int(minutes_match.group(1)) * 60
    
    # Секунды
    seconds_match = re.search(r'(\d+)с', time_str)
    if seconds_match:
        total_seconds += int(seconds_match.group(1))
    
    # Если ничего не найдено, пробуем как число (секунды)
    if total_seconds == 0:
        try:
            total_seconds = float(time_str)
        except ValueError:
            total_seconds = 60  # По умолчанию
    
    return total_seconds


def format_time_interval(seconds: float) -> str:
    """Форматирует секунды в читаемый формат"""
    seconds = int(seconds)
    
    if seconds < 60:
        return f"{seconds} сек"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        if secs > 0:
            return f"{minutes}м {secs}с"
        return f"{minutes}м"
    elif seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        parts = []
        if hours > 0:
            parts.append(f"{hours}ч")
        if minutes > 0:
            parts.append(f"{minutes}м")
        if secs > 0 and len(parts) < 2:
            parts.append(f"{secs}с")
        return " ".join(parts) if parts else "0"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 86400 % 3600) // 60
        parts = []
        if days > 0:
            parts.append(f"{days}д")
        if hours > 0:
            parts.append(f"{hours}ч")
        if minutes > 0:
            parts.append(f"{minutes}м")
        return " ".join(parts) if parts else "0"


# Загружаем переменные окружения
load_dotenv()

# ============= КОНФИГУРАЦИЯ =============
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

# ============= СОСТОЯНИЯ =============
class SessionStates(StatesGroup):
    waiting_api_id = State()
    waiting_api_hash = State()
    waiting_session_file = State()
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()
    waiting_chats_file = State()

# ============= РОУТЕР =============
router = Router()

# ============= ОБРАБОТЧИКИ =============
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Стартовое сообщение"""
    user_id = message.from_user.id
    session_data = session_manager.get_user_session(user_id)
    
    text = (
        "🤖 <b>Что может делать этот бот?</b>\n\n"
        "С помощью этого бота можно подключить расширение на аккаунт. "
        "Нажимай кнопку, чтобы продолжить 👇"
    )
    
    if not session_data:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Подключить аккаунт", callback_data="session_add")],
        ])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Мои чаты", callback_data="session_chats")],
            [InlineKeyboardButton(text="📤 Рассылка", callback_data="session_broadcast")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="session_settings")],
        ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# Обработчик прямого ввода API ID (должен быть ПЕРЕД обработчиком команд)
@router.message(
    F.text.regexp(r'^\d{6,}$') & 
    ~StateFilter(SessionStates.waiting_code) &
    ~StateFilter(SessionStates.waiting_password) &
    ~StateFilter(SessionStates.waiting_phone) &
    ~StateFilter(SessionStates.waiting_session_file) &
    ~StateFilter(SessionStates.waiting_api_hash) &
    ~StateFilter(SessionStates.waiting_api_id) &
    ~F.text.startswith(".")
)
async def session_api_id_direct(message: Message, state: FSMContext):
    """Обработка прямого ввода API ID"""
    # Всегда отвечаем на число, если не в процессе другой операции
    logger.info(f"Обработчик прямого ввода API ID вызван для пользователя {message.from_user.id}, текст: {message.text}")
    try:
        api_id = int(message.text.strip())
        await state.update_data(api_id=api_id)
        await state.set_state(SessionStates.waiting_api_hash)
        logger.info(f"API ID {api_id} принят, переходим к API Hash")
        await message.answer(
            f"✅ API ID: <b>{api_id}</b>\n\n"
            "Теперь введите ваш <b>API Hash</b> (строка):",
            parse_mode=ParseMode.HTML
        )
    except ValueError as e:
        logger.error(f"Ошибка парсинга API ID: {e}")
        pass


# Обработчик команд с префиксом точки
@router.message(F.text.startswith("."))
async def handle_dot_command(message: Message, state: FSMContext):
    """Обработка команд с префиксом точки"""
    text = message.text.strip()
    command = text.split()[0].lower() if text.split() else ""
    args = text.split()[1:] if len(text.split()) > 1 else []
    
    user_id = message.from_user.id
    
    # Проверяем наличие сессии
    session_data = session_manager.get_user_session(user_id)
    if not session_data and command not in [".команды", ".помощь", ".help"]:
        await message.answer(
            "❌ Сначала подключите аккаунт через /start",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Команда .спам
    if command in [".спам", ".spam", ".флуд", ".flood"]:
        if len(args) < 3:
            await message.answer(
                "❌ <b>Использование:</b>\n"
                "<code>.спам 'сообщение' 'количество' 'интервал'</code>\n\n"
                "Пример: <code>.спам 'Привет' 10 5</code>\n"
                "Отправит 'Привет' 10 раз с интервалом 5 секунд",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Парсим аргументы
        try:
            msg_text = args[0].strip("'\"")
            count = int(args[1])
            # Парсим интервал (поддержка форматов: секунды, 1ч, 30м, 1ч30м)
            try:
                delay = float(args[2])
            except ValueError:
                delay = parse_time_interval(args[2])
        except:
            await message.answer("❌ Неверный формат аргументов")
            return

        # Получаем ID текущего чата (если это не личка)
        if message.chat.type == "private":
            await message.answer("❌ Эта команда работает только в чатах")
            return
        
        chat_id = message.chat.id
        
        delay_display = format_time_interval(delay)
        await message.answer(f"⏳ Начинаю рассылку: {count} сообщений с интервалом {delay_display}...")
        
        success = 0
        failed = 0
        
        for i in range(count):
            try:
                await message.bot.send_message(chat_id, msg_text)
                success += 1
                await asyncio.sleep(delay)
            except Exception as e:
                failed += 1
                logger.error(f"Ошибка отправки: {e}")
        
        await message.answer(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"✅ Успешно: {success}\n"
            f"❌ Ошибок: {failed}",
            parse_mode=ParseMode.HTML
        )
    
    # Команда .команды
    elif command in [".команды", ".commands", ".помощь", ".help", ".кмд"]:
        await message.answer(
            "📋 <b>Доступные команды:</b>\n\n"
            "<code>.спам 'текст' количество интервал</code> - Рассылка в текущий чат\n"
            "<code>.чаты</code> - Загрузить список чатов из .txt файла\n"
            "<code>.рассылка 'текст' интервал</code> - Рассылка по всем чатам из списка\n\n"
            "<b>Форматы интервала:</b>\n"
            "• Секунды: <code>60</code>, <code>3600</code>\n"
            "• Время: <code>1ч</code>, <code>30м</code>, <code>1ч30м</code>, <code>2д1ч</code>\n\n"
            "💡 <b>Важно:</b> Интервал обязателен для рассылки!\n"
            "💡 Все команды работают с префиксом точки",
                parse_mode=ParseMode.HTML
            )
    
    # Команда .чаты
    elif command in [".чаты", ".chats"]:
        await message.answer(
            "📋 <b>Загрузка списка чатов</b>\n\n"
            "Отправьте .txt файл со списком ссылок на чаты.\n"
            "Формат:\n"
            "<code>https://t.me/reklamnyy_chat\n"
            "https://t.me/piarchattttt</code>",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(SessionStates.waiting_chats_file)
    
    # Команда .рассылка
    elif command in [".рассылка", ".broadcast", ".рассыл"]:
        if not args or len(args) < 2:
            await message.answer(
                "❌ <b>Использование:</b>\n"
                "<code>.рассылка 'текст сообщения' интервал</code>\n\n"
                "Примеры:\n"
                "<code>.рассылка 'Привет' 60</code> - интервал 60 секунд\n"
                "<code>.рассылка 'Привет' 1ч</code> - интервал 1 час\n"
                "<code>.рассылка 'Привет' 30м</code> - интервал 30 минут\n"
                "<code>.рассылка 'Привет' 1ч30м</code> - интервал 1 час 30 минут",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Парсим аргументы: текст и интервал
        # Последний аргумент - интервал, остальное - текст
        # Последний аргумент - интервал
        delay_str = args[-1]
        # Все остальное - текст сообщения
        msg_text = " ".join(args[:-1]).strip("'\"")
        
        # Если текст пустой, берем весь текст без последнего аргумента
        if not msg_text:
            msg_text = " ".join(args[:-1])
        
        # Парсим интервал (поддержка форматов: секунды, 1ч, 30м, 1ч30м)
        try:
            # Пробуем как число (секунды)
            delay_seconds = float(delay_str)
        except ValueError:
            # Парсим формат времени (1ч, 30м, 1ч30м)
            delay_seconds = parse_time_interval(delay_str)
        
        if delay_seconds < 1:
            delay_seconds = 60  # Минимум 1 секунда
        
        # Получаем список чатов из сохраненного файла
        if not hasattr(message.bot, "_user_chats"):
            message.bot._user_chats = {}
        
        if user_id not in message.bot._user_chats:
            await message.answer("❌ Сначала загрузите список чатов через .чаты")
            return
    
        chat_usernames = message.bot._user_chats[user_id]
        chat_ids = await session_manager.get_chat_ids_from_usernames(user_id, chat_usernames)
        
        if not chat_ids:
            await message.answer("❌ Не удалось получить ID чатов")
            return
        
        # Форматируем интервал для отображения
        delay_display = format_time_interval(delay_seconds)
        
        await message.answer(
            f"⏳ Отправляю сообщение в {len(chat_ids)} чатов...\n"
            f"⏱ Интервал между сообщениями: {delay_display}"
        )
        
        success, failed, errors = await session_manager.send_message_to_chats(
            user_id, msg_text, chat_ids, delay=delay_seconds
        )
        
        result = (
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"✅ Успешно: {success}\n"
            f"❌ Ошибок: {failed}\n"
            f"⏱ Интервал: {delay_display}"
        )
        
        if errors and len(errors) <= 5:
            result += "\n\n<b>Ошибки:</b>\n" + "\n".join(errors[:5])
        
        await message.answer(result, parse_mode=ParseMode.HTML)


# Обработка загрузки файла со списком чатов
@router.message(F.document & F.document.file_name.endswith('.txt'))
async def handle_chats_file(message: Message, state: FSMContext):
    """Обработка загрузки .txt файла со списком чатов"""
    user_id = message.from_user.id
    
    try:
        # Скачиваем файл
        file = await message.bot.get_file(message.document.file_id)
        file_path = f"temp_chats_{user_id}.txt"
        
        await message.bot.download_file(file.file_path, file_path)
        
        await message.answer("⏳ Обрабатываю файл...")
        
        # Присоединяемся к чатам и архивируем их
        success, failed, errors = await session_manager.join_chats_from_file(user_id, file_path)
        
        # Сохраняем список username для рассылки
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        chat_usernames = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if 't.me/' in line:
                username = line.split('t.me/')[-1].split('/')[0].split('?')[0]
                if username:
                    chat_usernames.append(username)
        
        if not hasattr(message.bot, "_user_chats"):
            message.bot._user_chats = {}
        message.bot._user_chats[user_id] = chat_usernames
        
        # Удаляем временный файл
        os.remove(file_path)
        
        result = (
            f"✅ <b>Обработка завершена!</b>\n\n"
            f"✅ Присоединено: {success}\n"
            f"❌ Ошибок: {failed}\n"
            f"📋 Всего чатов в списке: {len(chat_usernames)}\n\n"
            f"Все чаты заархивированы."
        )
        
        if errors and len(errors) <= 5:
            result += "\n\n<b>Ошибки:</b>\n" + "\n".join(errors[:5])
        
        await message.answer(result, parse_mode=ParseMode.HTML)
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка обработки файла: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()


# Остальные обработчики сессий
@router.callback_query(F.data == "session_add")
async def session_add_start(callback: CallbackQuery, state: FSMContext):
    """Начало добавления сессии"""
    await callback.message.edit_text(
        "🤖 <b>Подключение аккаунта</b>\n\n"
        "Для работы бота необходимо авторизоваться в ваш аккаунт Telegram.\n\n"
        "📋 <b>Настройки авторизации:</b>\n"
        "Для начала введите ваш <b>API ID</b> (число):\n\n"
        "💡 Получить можно на https://my.telegram.org/apps",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(SessionStates.waiting_api_id)
    await callback.answer()


@router.message(SessionStates.waiting_api_id)
async def session_add_api_id(message: Message, state: FSMContext):
    """Обработка API ID"""
    try:
        api_id = int(message.text.strip())
        await state.update_data(api_id=api_id)
        await state.set_state(SessionStates.waiting_api_hash)
        await message.answer(
            f"✅ API ID: <b>{api_id}</b>\n\n"
            "Теперь введите ваш <b>API Hash</b> (строка):",
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await message.answer("❌ API ID должен быть числом. Введите снова:")


@router.message(SessionStates.waiting_api_hash)
async def session_add_api_hash(message: Message, state: FSMContext):
    """Обработка API Hash"""
    api_hash = message.text.strip()
    await state.update_data(api_hash=api_hash)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Загрузить файл сессии", callback_data="session_method_file")],
        [InlineKeyboardButton(text="📱 Войти по номеру телефона", callback_data="session_method_phone")]
    ])
    
    await message.answer(
        f"✅ API Hash: <b>{api_hash}</b>\n\n"
        "Выберите способ авторизации:",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "session_method_file")
async def session_method_file(callback: CallbackQuery, state: FSMContext):
    """Выбор метода - файл сессии"""
    await callback.message.edit_text(
        "📁 <b>Загрузка файла сессии</b>\n\n"
        "Отправьте файл сессии (<code>.session</code>):",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(SessionStates.waiting_session_file)
    await callback.answer()


@router.callback_query(F.data == "session_method_phone")
async def session_method_phone(callback: CallbackQuery, state: FSMContext):
    """Выбор метода - номер телефона"""
    await callback.message.edit_text(
        "📱 <b>Авторизация по номеру телефона</b>\n\n"
        "Введите номер телефона в международном формате:\n"
        "Например: +79001234567",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(SessionStates.waiting_phone)
    await callback.answer()


@router.message(StateFilter(SessionStates.waiting_phone))
async def session_add_phone(message: Message, state: FSMContext):
    """Обработка номера телефона"""
    phone = message.text.strip()
    
    if not phone.startswith('+'):
        phone = '+' + phone
    
    await state.update_data(phone=phone)
    
    data = await state.get_data()
    api_id = data["api_id"]
    api_hash = data["api_hash"]
    
    await message.answer("⏳ Отправляю код в Telegram...")
    
    success, msg, client = await session_manager.start_phone_auth(
        message.from_user.id, api_id, api_hash, phone
    )
    
    if not success:
        await message.answer(f"❌ <b>Ошибка:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
        await state.clear()
        return

    if "Уже авторизован" in msg:
        await message.answer(msg, parse_mode=ParseMode.HTML)
        await state.clear()
        return

    code_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1"), KeyboardButton(text="2"), KeyboardButton(text="3")],
            [KeyboardButton(text="4"), KeyboardButton(text="5"), KeyboardButton(text="6")],
            [KeyboardButton(text="7"), KeyboardButton(text="8"), KeyboardButton(text="9")],
            [KeyboardButton(text="< Стереть"), KeyboardButton(text="0")],
            [KeyboardButton(text="✅ Отправить")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
    await message.answer(
        f"✅ {msg}\n\n"
        "🔑 <b>Введите код:</b>\n\n"
        "Код пришел в приложении Telegram.\n"
        "Используйте клавиатуру ниже для ввода:",
        reply_markup=code_keyboard,
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(SessionStates.waiting_code)
    await state.update_data(code_input="")


@router.message(StateFilter(SessionStates.waiting_code))
async def session_add_code(message: Message, state: FSMContext):
    """Обработка кода авторизации"""
    data = await state.get_data()
    code_input = data.get("code_input", "")
    
    text = message.text.strip()
    
    if text == "< Стереть":
        if code_input:
            code_input = code_input[:-1]
            await state.update_data(code_input=code_input)
            await message.answer(f"🔑 Введите код: {code_input or '_'}")
        return
    
    if text == "✅ Отправить":
        if not code_input or len(code_input) < 5:
            await message.answer("❌ Код должен содержать минимум 5 цифр")
        return
    
        await message.answer("⏳ Проверяю код...", reply_markup=None)
        
        success, msg = await session_manager.complete_phone_auth(
            message.from_user.id, code_input
        )
        
        if success:
            await message.answer(
                f"{msg}\n\n"
                "Теперь вы можете использовать команды для рассылки.",
                parse_mode=ParseMode.HTML
            )
            await state.clear()
        elif msg == "NEED_PASSWORD":
            await message.answer(
                "🔐 <b>Требуется пароль двухфакторной аутентификации</b>\n\n"
                "Введите пароль:",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(SessionStates.waiting_password)
            await state.update_data(code=code_input)
        else:
            await message.answer(f"❌ <b>Ошибка:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
            code_keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="1"), KeyboardButton(text="2"), KeyboardButton(text="3")],
                    [KeyboardButton(text="4"), KeyboardButton(text="5"), KeyboardButton(text="6")],
                    [KeyboardButton(text="7"), KeyboardButton(text="8"), KeyboardButton(text="9")],
                    [KeyboardButton(text="< Стереть"), KeyboardButton(text="0")],
                    [KeyboardButton(text="✅ Отправить")]
                ],
                resize_keyboard=True,
                one_time_keyboard=False
            )
            await message.answer(
                "🔑 <b>Введите код снова:</b>",
                reply_markup=code_keyboard,
                parse_mode=ParseMode.HTML
            )
            await state.update_data(code_input="")
        return
    
    # Добавляем цифру
    if text.isdigit() and len(text) == 1:
        code_input += text
        await state.update_data(code_input=code_input)
        await message.answer(f"🔑 Введите код: {code_input}{'_' * (5 - len(code_input)) if len(code_input) < 5 else ''}")
    elif text.isdigit() and len(text) >= 5:
        # Пользователь ввел код целиком
        await message.answer("⏳ Проверяю код...", reply_markup=None)
        
        success, msg = await session_manager.complete_phone_auth(
            message.from_user.id, text
        )
        
        if success:
            await message.answer(
                f"{msg}\n\n"
                "Теперь вы можете использовать команды для рассылки.",
                parse_mode=ParseMode.HTML
            )
            await state.clear()
        elif msg == "NEED_PASSWORD":
            await message.answer(
                "🔐 <b>Требуется пароль двухфакторной аутентификации</b>\n\n"
                "Введите пароль:",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(SessionStates.waiting_password)
            await state.update_data(code=text)
        else:
            await message.answer(f"❌ <b>Ошибка:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
            code_keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="1"), KeyboardButton(text="2"), KeyboardButton(text="3")],
                    [KeyboardButton(text="4"), KeyboardButton(text="5"), KeyboardButton(text="6")],
                    [KeyboardButton(text="7"), KeyboardButton(text="8"), KeyboardButton(text="9")],
                    [KeyboardButton(text="< Стереть"), KeyboardButton(text="0")],
                    [KeyboardButton(text="✅ Отправить")]
                ],
                resize_keyboard=True,
                one_time_keyboard=False
            )
            await message.answer(
                "🔑 <b>Введите код снова:</b>",
                reply_markup=code_keyboard,
                parse_mode=ParseMode.HTML
            )
            await state.update_data(code_input="")


@router.message(StateFilter(SessionStates.waiting_password))
async def session_add_password(message: Message, state: FSMContext):
    """Обработка пароля двухфакторной аутентификации"""
    password = message.text.strip()
    data = await state.get_data()
    code = data.get("code", "")
    
    await message.answer("⏳ Проверяю пароль...")
    
    success, msg = await session_manager.complete_phone_auth(
        message.from_user.id, code, password
    )
    
    if success:
        await message.answer(
            f"{msg}\n\n"
            "Теперь вы можете использовать команды для рассылки.",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(f"❌ <b>Ошибка:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
    
    await state.clear()


@router.message(StateFilter(SessionStates.waiting_session_file), F.document)
async def session_add_file(message: Message, state: FSMContext):
    """Обработка файла сессии"""
    try:
        user_id = message.from_user.id
        data = await state.get_data()
        api_id = data["api_id"]
        api_hash = data["api_hash"]
        
        file = await message.bot.get_file(message.document.file_id)
        file_path = os.path.join("sessions", f"user_{user_id}.session")
        
        os.makedirs("sessions", exist_ok=True)
        await message.bot.download_file(file.file_path, file_path)
        
        await message.answer("⏳ Подключаюсь к сессии...")
        
        success, msg = await session_manager.add_session(
            user_id, api_id, api_hash, file_path
        )
        
        if success:
            await message.answer(
                f"{msg}\n\n"
                "Теперь вы можете использовать команды для рассылки.",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer(f"❌ <b>Ошибка:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка добавления сессии: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()

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
        ]
        await bot.set_my_commands(commands)
        
        logger.info("🤖 Бот запущен!")
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        raise
    finally:
        await session_manager.disconnect_all()


if __name__ == "__main__":
    asyncio.run(main())

