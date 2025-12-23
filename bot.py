import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, \
    CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiohttp
import json
import os
from datetime import datetime
import subprocess
import signal

# Настройки
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable is not set!")

API_URL = "http://api.onlysq.ru/ai/v2"
MODEL = "gemini-3-pro"
DB_FILE = "chat_history.json"
BOTS_DB_FILE = "bots_data.json"
BOTS_DIR = "user_bots"
MAX_MESSAGE_LENGTH = 4000

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Создаем папку для ботов
os.makedirs(BOTS_DIR, exist_ok=True)

# Храним процессы запущенных ботов
running_bots = {}


# === FSM STATES ===
class BotCreation(StatesGroup):
    waiting_for_token = State()
    waiting_for_prompt = State()


class BotEdit(StatesGroup):
    waiting_for_changes = State()


# === КЛАВИАТУРЫ ===
def get_main_keyboard():
    """Главная клавиатура"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤖 Создать бота")],
            [KeyboardButton(text="📋 Мои боты")],
            [KeyboardButton(text="💬 Чат с AI")]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_bot_management_keyboard(bot_id: str, is_running: bool):
    """Клавиатура управления ботом"""
    buttons = []

    if is_running:
        buttons.append([InlineKeyboardButton(text="⏹️ Остановить бота", callback_data=f"stop_{bot_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="▶️ Запустить бота", callback_data=f"start_{bot_id}")])

    buttons.append([
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{bot_id}"),
        InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_{bot_id}")
    ])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_bots")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === РАБОТА С JSON БАЗОЙ ЧАТОВ ===
def load_db():
    """Загрузить JSON базу"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_db(data):
    """Сохранить в JSON"""
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_message(user_id: int, role: str, content: str):
    """Сохранить сообщение"""
    db = load_db()
    user_id_str = str(user_id)

    if user_id_str not in db:
        db[user_id_str] = []

    db[user_id_str].append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat()
    })

    save_db(db)


def get_history(user_id: int, limit: int = 20) -> list:
    """Получить историю"""
    db = load_db()
    user_id_str = str(user_id)

    if user_id_str not in db:
        return []

    messages = db[user_id_str][-limit:]
    return [{"role": msg["role"], "content": msg["content"]} for msg in messages]


def clear_history(user_id: int):
    """Очистить историю"""
    db = load_db()
    user_id_str = str(user_id)

    if user_id_str in db:
        db[user_id_str] = []
        save_db(db)


# === РАБОТА С БАЗОЙ БОТОВ ===
def load_bots_db():
    """Загрузить базу ботов"""
    if os.path.exists(BOTS_DB_FILE):
        with open(BOTS_DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_bots_db(data):
    """Сохранить базу ботов"""
    with open(BOTS_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_bot(user_id: int, bot_token: str, prompt: str, bot_id: str):
    """Добавить бота в базу"""
    db = load_bots_db()
    user_id_str = str(user_id)

    if user_id_str not in db:
        db[user_id_str] = []

    db[user_id_str].append({
        "bot_id": bot_id,
        "token": bot_token,
        "prompt": prompt,
        "created_at": datetime.now().isoformat(),
        "is_running": False
    })

    save_bots_db(db)


def get_user_bots(user_id: int) -> list:
    """Получить ботов пользователя"""
    db = load_bots_db()
    user_id_str = str(user_id)
    return db.get(user_id_str, [])


def update_bot_status(user_id: int, bot_id: str, is_running: bool):
    """Обновить статус бота"""
    db = load_bots_db()
    user_id_str = str(user_id)

    if user_id_str in db:
        for bot_data in db[user_id_str]:
            if bot_data["bot_id"] == bot_id:
                bot_data["is_running"] = is_running
                save_bots_db(db)
                break


def delete_bot_from_db(user_id: int, bot_id: str):
    """Удалить бота из базы"""
    db = load_bots_db()
    user_id_str = str(user_id)

    if user_id_str in db:
        db[user_id_str] = [b for b in db[user_id_str] if b["bot_id"] != bot_id]
        save_bots_db(db)


def get_bot_data(user_id: int, bot_id: str):
    """Получить данные бота"""
    bots = get_user_bots(user_id)
    for bot_data in bots:
        if bot_data["bot_id"] == bot_id:
            return bot_data
    return None


def update_bot_prompt(user_id: int, bot_id: str, new_prompt: str):
    """Обновить промпт бота"""
    db = load_bots_db()
    user_id_str = str(user_id)

    if user_id_str in db:
        for bot_data in db[user_id_str]:
            if bot_data["bot_id"] == bot_id:
                bot_data["prompt"] = new_prompt
                save_bots_db(db)
                break


# === РАЗБИВКА ДЛИННЫХ СООБЩЕНИЙ ===
def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list:
    """Разбить длинное сообщение на части"""
    if len(text) <= max_length:
        return [text]

    parts = []
    while text:
        if len(text) <= max_length:
            parts.append(text)
            break

        split_pos = text.rfind('\n', 0, max_length)
        if split_pos == -1:
            split_pos = text.rfind(' ', 0, max_length)
        if split_pos == -1:
            split_pos = max_length

        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip()

    return parts


async def send_long_message(message: Message, text: str):
    """Отправить длинное сообщение"""
    parts = split_message(text)

    for i, part in enumerate(parts):
        if i > 0:
            await asyncio.sleep(0.5)
        await message.answer(part)


# === РАБОТА С AI ===
async def get_ai_response(user_id: int, user_message: str) -> str:
    """Получить ответ от AI с историей"""
    headers = {
        "Authorization": "Bearer openai"
    }

    history = get_history(user_id, limit=20)
    history.append({
        "role": "user",
        "content": user_message
    })

    send = {
        "model": MODEL,
        "request": {
            "messages": history
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=send, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    ai_reply = data['choices'][0]['message']['content']

                    save_message(user_id, "user", user_message)
                    save_message(user_id, "assistant", ai_reply)

                    return ai_reply
                else:
                    return "❌ Ошибка API"
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return "❌ Ошибка соединения"


async def generate_bot_code(prompt: str, bot_token: str) -> str:
    """Сгенерировать код бота через AI"""
    headers = {
        "Authorization": "Bearer openai"
    }

    system_prompt = f"""Создай код Telegram бота на Python с использованием aiogram 3.x.
Требования:
1. Бот должен соответствовать следующему описанию: {prompt}
2. Используй aiogram 3.x
3. Токен бота: {bot_token}
4. Код должен быть полным и готовым к запуску
5. Добавь базовый функционал и команду /start
6. Используй async/await
7. Верни ТОЛЬКО код Python без объяснений, без markdown разметки
8. Код должен начинаться с import и заканчиваться asyncio.run(main())"""

    send = {
        "model": MODEL,
        "request": {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Создай бота: {prompt}"}
            ]
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=send, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    code = data['choices'][0]['message']['content']

                    # Очистка кода от markdown
                    code = code.replace('```python', '').replace('```', '').strip()

                    return code
                else:
                    return None
    except Exception as e:
        logging.error(f"Ошибка генерации кода: {e}")
        return None


# === УПРАВЛЕНИЕ БОТАМИ ===
def start_bot_process(bot_id: str, user_id: int):
    """Запустить процесс бота"""
    bot_file = os.path.join(BOTS_DIR, f"bot_{user_id}_{bot_id}.py")

    if not os.path.exists(bot_file):
        return False

    try:
        process = subprocess.Popen(
            ["python3", bot_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )
        running_bots[bot_id] = process
        update_bot_status(user_id, bot_id, True)
        return True
    except Exception as e:
        logging.error(f"Ошибка запуска бота: {e}")
        return False


def stop_bot_process(bot_id: str, user_id: int):
    """Остановить процесс бота"""
    if bot_id in running_bots:
        try:
            os.killpg(os.getpgid(running_bots[bot_id].pid), signal.SIGTERM)
            del running_bots[bot_id]
            update_bot_status(user_id, bot_id, False)
            return True
        except Exception as e:
            logging.error(f"Ошибка остановки бота: {e}")
            return False
    return False


# === КОМАНДЫ БОТА ===
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🤖 Привет! Я мультифункциональный бот.\n\n"
        "Я могу:\n"
        "• Создавать Telegram ботов для вас\n"
        "• Управлять вашими ботами\n"
        "• Общаться с AI\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )


@dp.message(F.text == "🤖 Создать бота")
async def create_bot_start(message: Message, state: FSMContext):
    await state.set_state(BotCreation.waiting_for_token)
    await message.answer(
        "🔑 Отправьте API токен вашего бота\n\n"
        "Получить токен можно у @BotFather"
    )


@dp.message(BotCreation.waiting_for_token)
async def process_token(message: Message, state: FSMContext):
    token = message.text.strip()

    # Простая валидация токена
    if ':' not in token or len(token) < 30:
        await message.answer("❌ Неверный формат токена. Попробуйте снова:")
        return

    await state.update_data(token=token)
    await state.set_state(BotCreation.waiting_for_prompt)
    await message.answer(
        "📝 Отлично! Теперь опишите, что должен делать ваш бот.\n\n"
        "Например:\n"
        "- Простой эхо-бот\n"
        "- Бот для заметок\n"
        "- Бот-калькулятор\n"
        "- Бот с кнопками для голосования"
    )


@dp.message(BotCreation.waiting_for_prompt)
async def process_prompt(message: Message, state: FSMContext):
    prompt = message.text
    data = await state.get_data()
    token = data['token']

    status_msg = await message.answer("⏳ Создаю бота... Это может занять минуту.")

    # Генерируем код бота
    bot_code = await generate_bot_code(prompt, token)

    if not bot_code:
        await status_msg.edit_text("❌ Ошибка при генерации кода бота")
        await state.clear()
        return

    # Создаем уникальный ID бота
    bot_id = f"{message.from_user.id}_{datetime.now().timestamp()}"
    bot_file = os.path.join(BOTS_DIR, f"bot_{message.from_user.id}_{bot_id}.py")

    # Сохраняем код бота
    with open(bot_file, 'w', encoding='utf-8') as f:
        f.write(bot_code)

    # Устанавливаем зависимости
    await status_msg.edit_text("📦 Устанавливаю зависимости...")

    try:
        subprocess.run(
            ["pip", "install", "-q", "aiogram", "aiohttp"],
            check=True,
            capture_output=True
        )
    except:
        pass  # Зависимости уже установлены

    # Сохраняем в базу
    add_bot(message.from_user.id, token, prompt, bot_id)

    await status_msg.edit_text(
        "✅ Бот успешно создан!\n\n"
        "Ваш бот готов к запуску.\n"
        "Используйте кнопку 'Мои боты' для управления."
    )

    # Отправляем клавиатуру отдельным сообщением
    await message.answer("Выберите действие:", reply_markup=get_main_keyboard())

    await state.clear()


@dp.message(F.text == "📋 Мои боты")
async def show_my_bots(message: Message):
    bots = get_user_bots(message.from_user.id)

    if not bots:
        await message.answer(
            "У вас пока нет ботов.\n"
            "Создайте первого бота!",
            reply_markup=get_main_keyboard()
        )
        return

    text = "🤖 Ваши боты:\n\n"
    buttons = []

    for i, bot_data in enumerate(bots, 1):
        status = "🟢 Работает" if bot_data.get("is_running", False) else "🔴 Остановлен"
        prompt_short = bot_data['prompt'][:50] + "..." if len(bot_data['prompt']) > 50 else bot_data['prompt']
        text += f"{i}. {status}\n📝 {prompt_short}\n\n"

        buttons.append([InlineKeyboardButton(
            text=f"Бот #{i}",
            callback_data=f"manage_{bot_data['bot_id']}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("manage_"))
async def manage_bot(callback: CallbackQuery):
    bot_id = callback.data.split("_", 1)[1]
    bot_data = get_bot_data(callback.from_user.id, bot_id)

    if not bot_data:
        await callback.answer("Бот не найден")
        return

    is_running = bot_data.get("is_running", False)
    status = "🟢 Работает" if is_running else "🔴 Остановлен"

    text = f"🤖 Управление ботом\n\n"
    text += f"Статус: {status}\n"
    text += f"📝 Описание: {bot_data['prompt']}\n"
    text += f"📅 Создан: {bot_data['created_at'][:10]}"

    await callback.message.edit_text(
        text,
        reply_markup=get_bot_management_keyboard(bot_id, is_running)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("start_"))
async def start_bot(callback: CallbackQuery):
    bot_id = callback.data.split("_", 1)[1]

    if start_bot_process(bot_id, callback.from_user.id):
        await callback.answer("✅ Бот запущен!")

        # Обновляем сообщение
        bot_data = get_bot_data(callback.from_user.id, bot_id)
        text = f"🤖 Управление ботом\n\n"
        text += f"Статус: 🟢 Работает\n"
        text += f"📝 Описание: {bot_data['prompt']}\n"
        text += f"📅 Создан: {bot_data['created_at'][:10]}"

        await callback.message.edit_text(
            text,
            reply_markup=get_bot_management_keyboard(bot_id, True)
        )
    else:
        await callback.answer("❌ Ошибка запуска бота")


@dp.callback_query(F.data.startswith("stop_"))
async def stop_bot(callback: CallbackQuery):
    bot_id = callback.data.split("_", 1)[1]

    if stop_bot_process(bot_id, callback.from_user.id):
        await callback.answer("⏹️ Бот остановлен!")

        # Обновляем сообщение
        bot_data = get_bot_data(callback.from_user.id, bot_id)
        text = f"🤖 Управление ботом\n\n"
        text += f"Статус: 🔴 Остановлен\n"
        text += f"📝 Описание: {bot_data['prompt']}\n"
        text += f"📅 Создан: {bot_data['created_at'][:10]}"

        await callback.message.edit_text(
            text,
            reply_markup=get_bot_management_keyboard(bot_id, False)
        )
    else:
        await callback.answer("❌ Ошибка остановки бота")


@dp.callback_query(F.data.startswith("edit_"))
async def edit_bot_start(callback: CallbackQuery, state: FSMContext):
    bot_id = callback.data.split("_", 1)[1]

    await state.update_data(bot_id=bot_id)
    await state.set_state(BotEdit.waiting_for_changes)

    await callback.message.answer(
        "✏️ Опишите, какие изменения нужно внести в бота:"
    )
    await callback.answer()


@dp.message(BotEdit.waiting_for_changes)
async def process_bot_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data['bot_id']
    changes = message.text

    bot_data = get_bot_data(message.from_user.id, bot_id)

    if not bot_data:
        await message.answer("❌ Бот не найден")
        await state.clear()
        return

    # Останавливаем бота если он запущен
    if bot_data.get("is_running", False):
        stop_bot_process(bot_id, message.from_user.id)

    status_msg = await message.answer("⏳ Пересоздаю бота с новыми правками...")

    # Новый промпт с изменениями
    new_prompt = f"{bot_data['prompt']}\n\nДополнительные изменения: {changes}"

    # Генерируем новый код
    bot_code = await generate_bot_code(new_prompt, bot_data['token'])

    if not bot_code:
        await status_msg.edit_text("❌ Ошибка при генерации кода")
        await state.clear()
        return

    # Перезаписываем файл бота
    bot_file = os.path.join(BOTS_DIR, f"bot_{message.from_user.id}_{bot_id}.py")
    with open(bot_file, 'w', encoding='utf-8') as f:
        f.write(bot_code)

    # Обновляем промпт в базе
    update_bot_prompt(message.from_user.id, bot_id, new_prompt)

    await status_msg.edit_text(
        "✅ Бот успешно обновлен!\n\n"
        "Изменения применены. Запустите бота заново."
    )

    # Отправляем клавиатуру отдельным сообщением
    await message.answer("Выберите действие:", reply_markup=get_main_keyboard())

    await state.clear()


@dp.callback_query(F.data.startswith("delete_"))
async def delete_bot(callback: CallbackQuery):
    bot_id = callback.data.split("_", 1)[1]

    # Останавливаем бота если запущен
    bot_data = get_bot_data(callback.from_user.id, bot_id)
    if bot_data and bot_data.get("is_running", False):
        stop_bot_process(bot_id, callback.from_user.id)

    # Удаляем файл
    bot_file = os.path.join(BOTS_DIR, f"bot_{callback.from_user.id}_{bot_id}.py")
    if os.path.exists(bot_file):
        os.remove(bot_file)

    # Удаляем из базы
    delete_bot_from_db(callback.from_user.id, bot_id)

    await callback.message.edit_text(
        "🗑️ Бот успешно удален!",
        reply_markup=None
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_bots")
async def back_to_bots(callback: CallbackQuery):
    bots = get_user_bots(callback.from_user.id)

    text = "🤖 Ваши боты:\n\n"
    buttons = []

    for i, bot_data in enumerate(bots, 1):
        status = "🟢 Работает" if bot_data.get("is_running", False) else "🔴 Остановлен"
        prompt_short = bot_data['prompt'][:50] + "..." if len(bot_data['prompt']) > 50 else bot_data['prompt']
        text += f"{i}. {status}\n📝 {prompt_short}\n\n"

        buttons.append([InlineKeyboardButton(
            text=f"Бот #{i}",
            callback_data=f"manage_{bot_data['bot_id']}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.message(F.text == "💬 Чат с AI")
async def ai_chat_mode(message: Message):
    await message.answer(
        "💬 Режим чата с AI активирован!\n\n"
        "Просто отправьте мне сообщение.\n\n"
        "Команды:\n"
        "/clear - очистить историю\n"
        "/history - показать историю"
    )


@dp.message(F.text == "/clear")
async def cmd_clear(message: Message):
    clear_history(message.from_user.id)
    await message.answer("🗑️ История очищена!")


@dp.message(F.text == "/history")
async def cmd_history(message: Message):
    history = get_history(message.from_user.id, limit=10)

    if not history:
        await message.answer("📭 История пуста")
        return

    text = "📚 Последние 10 сообщений:\n\n"
    for msg in history:
        role = "👤" if msg["role"] == "user" else "🤖"
        content = msg["content"][:50] + "..." if len(msg["content"]) > 50 else msg["content"]
        text += f"{role} {content}\n\n"

    await message.answer(text)


@dp.message(F.text)
async def handle_message(message: Message, state: FSMContext):
    # Проверяем, не находимся ли мы в состоянии FSM
    current_state = await state.get_state()
    if current_state:
        return

    if message.text.startswith('/'):
        return

    thinking_msg = await message.answer("💭 Думаю...")
    await bot.send_chat_action(message.chat.id, "typing")

    ai_response = await get_ai_response(message.from_user.id, message.text)

    await thinking_msg.delete()
    await send_long_message(message, ai_response)


async def main():
    logging.info("🚀 Мультифункциональный бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())