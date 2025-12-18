"""
Модуль для работы с Telegram сессиями через MTProto (Telethon)
Управление сессиями, сканирование чатов и рассылка сообщений
"""
import asyncio
import os
import json
import logging
from typing import Optional, List, Dict
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, PhoneCodeInvalidError
from telethon.tl.types import User, Chat, Channel
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import JoinChannelRequest

logger = logging.getLogger(__name__)


class SessionManager:
    """Менеджер для работы с Telegram сессиями"""
    
    def __init__(self, sessions_dir: str = "sessions"):
        self.sessions_dir = sessions_dir
        self.clients: Dict[str, TelegramClient] = {}
        self.sessions_data: Dict[str, dict] = {}
        self.load_sessions_data()
        
        # Создаем директорию для сессий если её нет
        os.makedirs(sessions_dir, exist_ok=True)
    
    def load_sessions_data(self):
        """Загружает данные о сессиях из файла"""
        data_file = os.path.join(self.sessions_dir, "sessions_data.json")
        if os.path.exists(data_file):
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    self.sessions_data = json.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки данных сессий: {e}")
                self.sessions_data = {}
        else:
            self.sessions_data = {}
    
    def save_sessions_data(self):
        """Сохраняет данные о сессиях в файл"""
        data_file = os.path.join(self.sessions_dir, "sessions_data.json")
        try:
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(self.sessions_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения данных сессий: {e}")
    
    async def start_phone_auth(
        self,
        user_id: int,
        api_id: int,
        api_hash: str,
        phone: str
    ) -> tuple[bool, str, Optional[TelegramClient]]:
        """
        Начинает авторизацию по номеру телефона
        
        Returns:
            (success, message, client)
        """
        try:
            user_id_str = str(user_id)
            session_path = os.path.join(self.sessions_dir, f"user_{user_id}.session")
            
            # Создаем директорию если её нет
            os.makedirs(self.sessions_dir, exist_ok=True)
            
            # Если сессия уже существует, отключаем старую
            if user_id_str in self.clients:
                try:
                    await self.clients[user_id_str].disconnect()
                except:
                    pass
                del self.clients[user_id_str]
            
            # Создаем клиент
            client = TelegramClient(session_path, api_id, api_hash)
            await client.connect()
            
            # Проверяем, авторизован ли уже
            if await client.is_user_authorized():
                me = await client.get_me()
                self.clients[user_id_str] = client
                self.sessions_data[user_id_str] = {
                    "api_id": api_id,
                    "api_hash": api_hash,
                    "session_path": session_path,
                    "phone": me.phone,
                    "username": me.username,
                    "first_name": me.first_name,
                    "last_name": me.last_name,
                    "telegram_user_id": me.id
                }
                self.save_sessions_data()
                return True, f"✅ Уже авторизован: @{me.username or me.phone}", client
            
            # Отправляем код
            await client.send_code_request(phone)
            
            # Сохраняем временные данные
            if not hasattr(self, "_auth_data"):
                self._auth_data = {}
            self._auth_data[user_id_str] = {
                "client": client,
                "api_id": api_id,
                "api_hash": api_hash,
                "phone": phone,
                "session_path": session_path
            }
            
            return True, "Код отправлен в Telegram", client
            
        except Exception as e:
            logger.error(f"Ошибка начала авторизации: {e}")
            return False, f"Ошибка: {str(e)}", None
    
    async def complete_phone_auth(
        self,
        user_id: int,
        code: str,
        password: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Завершает авторизацию по коду
        
        Returns:
            (success, message)
        """
        try:
            user_id_str = str(user_id)
            
            if not hasattr(self, "_auth_data") or user_id_str not in self._auth_data:
                return False, "Сессия авторизации не найдена. Начните заново."
            
            auth_data = self._auth_data[user_id_str]
            client = auth_data["client"]
            phone = auth_data["phone"]
            
            try:
                # Пытаемся войти с кодом
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                if not password:
                    return False, "NEED_PASSWORD"
                try:
                    await client.sign_in(password=password)
                except Exception as e:
                    return False, f"Ошибка входа с паролем: {str(e)}"
            except PhoneCodeInvalidError:
                return False, "Неверный код. Попробуйте снова."
            except Exception as e:
                return False, f"Ошибка входа: {str(e)}"
            
            # Получаем информацию о пользователе
            me = await client.get_me()
            
            # Сохраняем данные сессии
            self.sessions_data[user_id_str] = {
                "api_id": auth_data["api_id"],
                "api_hash": auth_data["api_hash"],
                "session_path": auth_data["session_path"],
                "phone": me.phone,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "telegram_user_id": me.id
            }
            self.save_sessions_data()
            
            # Сохраняем клиент
            self.clients[user_id_str] = client
            
            # Удаляем временные данные
            del self._auth_data[user_id_str]
            
            return True, f"✅ Сессия успешно добавлена!\n\n👤 Аккаунт: @{me.username or me.phone}\n🆔 ID: {me.id}"
            
        except Exception as e:
            logger.error(f"Ошибка завершения авторизации: {e}")
            return False, f"Ошибка: {str(e)}"
    
    async def add_session(
        self, 
        user_id: int,
        api_id: int, 
        api_hash: str,
        session_file_path: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Добавляет новую сессию для пользователя (из файла)
        
        Args:
            user_id: ID пользователя бота
            api_id: API ID
            api_hash: API Hash
            session_file_path: Путь к файлу сессии (если None, создается новый файл)
        
        Returns:
            (success, message)
        """
        try:
            user_id_str = str(user_id)
            
            # Если сессия уже существует, отключаем старую
            if user_id_str in self.clients:
                try:
                    await self.clients[user_id_str].disconnect()
                except:
                    pass
                del self.clients[user_id_str]
            
            # Определяем путь к файлу сессии
            if session_file_path:
                if not os.path.exists(session_file_path):
                    return False, f"Файл сессии не найден: {session_file_path}"
                session_path = session_file_path
            else:
                # Создаем новый файл сессии для пользователя
                session_path = os.path.join(self.sessions_dir, f"user_{user_id}.session")
            
            # Создаем клиент
            client = TelegramClient(session_path, api_id, api_hash)
            
            # Подключаемся
            await client.connect()
            
            if not await client.is_user_authorized():
                return False, "Сессия не авторизована. Нужно авторизоваться через код из Telegram"
            
            # Получаем информацию о пользователе
            me = await client.get_me()
            
            # Сохраняем данные сессии
            self.sessions_data[user_id_str] = {
                "api_id": api_id,
                "api_hash": api_hash,
                "session_path": session_path,
                "phone": me.phone,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "telegram_user_id": me.id
            }
            self.save_sessions_data()
            
            # Сохраняем клиент
            self.clients[user_id_str] = client
            
            return True, f"✅ Сессия успешно добавлена!\n\n👤 Аккаунт: @{me.username or me.phone}\n🆔 ID: {me.id}"
            
        except SessionPasswordNeededError:
            return False, "Требуется двухфакторная аутентификация. Пока не поддерживается"
        except Exception as e:
            logger.error(f"Ошибка добавления сессии: {e}")
            return False, f"Ошибка: {str(e)}"
    
    async def remove_session(self, user_id: int) -> tuple[bool, str]:
        """Удаляет сессию пользователя"""
        try:
            user_id_str = str(user_id)
            
            if user_id_str in self.clients:
                client = self.clients[user_id_str]
                await client.disconnect()
                del self.clients[user_id_str]
            
            if user_id_str in self.sessions_data:
                # Удаляем файл сессии
                session_path = self.sessions_data[user_id_str].get("session_path")
                if session_path and os.path.exists(session_path):
                    try:
                        os.remove(session_path)
                    except:
                        pass
                
                del self.sessions_data[user_id_str]
                self.save_sessions_data()
            
            return True, "✅ Сессия удалена"
        except Exception as e:
            logger.error(f"Ошибка удаления сессии: {e}")
            return False, f"Ошибка: {str(e)}"
    
    def get_user_session(self, user_id: int) -> Optional[Dict]:
        """Возвращает данные сессии пользователя"""
        user_id_str = str(user_id)
        if user_id_str in self.sessions_data:
            data = self.sessions_data[user_id_str].copy()
            data["is_active"] = user_id_str in self.clients
            return data
        return None
    
    def list_sessions(self) -> List[Dict]:
        """Возвращает список всех сессий (для админов)"""
        sessions = []
        for user_id_str, data in self.sessions_data.items():
            is_active = user_id_str in self.clients
            sessions.append({
                "user_id": int(user_id_str),
                "phone": data.get("phone", "N/A"),
                "username": data.get("username", "N/A"),
                "first_name": data.get("first_name", "N/A"),
                "is_active": is_active
            })
        return sessions
    
    async def get_chats(self, user_id: int, limit: int = 200) -> tuple[bool, str, List[Dict]]:
        """
        Получает список чатов для сессии пользователя
        
        Returns:
            (success, message, chats_list)
        """
        try:
            user_id_str = str(user_id)
            
            if user_id_str not in self.clients:
                # Пытаемся переподключить
                if user_id_str not in self.sessions_data:
                    return False, "Сессия не найдена. Сначала добавьте сессию через /sessions", []
                
                data = self.sessions_data[user_id_str]
                client = TelegramClient(
                    data["session_path"],
                    data["api_id"],
                    data["api_hash"]
                )
                await client.connect()
                if not await client.is_user_authorized():
                    return False, "Сессия не авторизована", []
                self.clients[user_id_str] = client
            
            client = self.clients[user_id_str]
            chats = []
            
            async for dialog in client.iter_dialogs(limit=limit):
                chat_info = {
                    "id": dialog.id,
                    "title": dialog.name,
                    "type": "channel" if dialog.is_channel else ("group" if dialog.is_group else "user"),
                    "username": getattr(dialog.entity, "username", None),
                    "unread_count": dialog.unread_count,
                    "is_muted": dialog.is_muted
                }
                chats.append(chat_info)
            
            return True, f"Найдено {len(chats)} чатов", chats
            
        except Exception as e:
            logger.error(f"Ошибка получения чатов: {e}")
            return False, f"Ошибка: {str(e)}", []
    
    async def send_message_to_chats(
        self,
        user_id: int,
        text: str,
        chat_ids: List[int],
        delay: float = 1.0
    ) -> tuple[int, int, List[str]]:
        """
        Отправляет сообщение в указанные чаты (как новое сообщение, не пересылка)
        
        Args:
            user_id: ID пользователя бота
            text: Текст сообщения
            chat_ids: Список ID чатов
            delay: Задержка между отправками (в секундах)
        
        Returns:
            (success_count, failed_count, errors)
        """
        user_id_str = str(user_id)
        
        if user_id_str not in self.clients:
            if user_id_str not in self.sessions_data:
                return 0, len(chat_ids), ["Сессия не найдена. Сначала добавьте сессию через /sessions"]
            
            # Переподключаем
            data = self.sessions_data[user_id_str]
            client = TelegramClient(
                data["session_path"],
                data["api_id"],
                data["api_hash"]
            )
            await client.connect()
            if not await client.is_user_authorized():
                return 0, len(chat_ids), ["Сессия не авторизована"]
            self.clients[user_id_str] = client
        
        client = self.clients[user_id_str]
        success_count = 0
        failed_count = 0
        errors = []
        
        for chat_id in chat_ids:
            try:
                await client.send_message(chat_id, text)
                success_count += 1
                await asyncio.sleep(delay)  # Задержка между отправками
            except FloodWaitError as e:
                wait_time = e.seconds
                errors.append(f"Chat {chat_id}: FloodWait {wait_time} секунд")
                await asyncio.sleep(wait_time)
                # Пытаемся еще раз
                try:
                    await client.send_message(chat_id, text)
                    success_count += 1
                except Exception as retry_e:
                    failed_count += 1
                    errors.append(f"Chat {chat_id}: {str(retry_e)}")
            except Exception as e:
                failed_count += 1
                errors.append(f"Chat {chat_id}: {str(e)}")
        
        return success_count, failed_count, errors
    
    async def archive_chats(self, user_id: int, chat_ids: List[int]) -> tuple[int, int, List[str]]:
        """
        Архивирует указанные чаты
        
        Returns:
            (success_count, failed_count, errors)
        """
        user_id_str = str(user_id)
        
        if user_id_str not in self.clients:
            if user_id_str not in self.sessions_data:
                return 0, len(chat_ids), ["Сессия не найдена"]
            
            # Переподключаем
            data = self.sessions_data[user_id_str]
            client = TelegramClient(
                data["session_path"],
                data["api_id"],
                data["api_hash"]
            )
            await client.connect()
            if not await client.is_user_authorized():
                return 0, len(chat_ids), ["Сессия не авторизована"]
            self.clients[user_id_str] = client
        
        client = self.clients[user_id_str]
        success_count = 0
        failed_count = 0
        errors = []
        
        for chat_id in chat_ids:
            try:
                # Архивируем чат через редактирование диалога
                entity = await client.get_entity(chat_id)
                await client.edit_folder(entity, folder=1)  # 1 = архив
                success_count += 1
                await asyncio.sleep(0.1)  # Небольшая задержка
            except Exception as e:
                # Если метод не работает, просто пропускаем
                failed_count += 1
                errors.append(f"Chat {chat_id}: {str(e)}")
        
        return success_count, failed_count, errors
    
    async def join_chats_from_file(self, user_id: int, file_path: str) -> tuple[int, int, List[str]]:
        """
        Присоединяется к чатам из файла и архивирует их
        
        Returns:
            (success_count, failed_count, errors)
        """
        user_id_str = str(user_id)
        
        if user_id_str not in self.clients:
            if user_id_str not in self.sessions_data:
                return 0, 0, ["Сессия не найдена"]
            
            data = self.sessions_data[user_id_str]
            client = TelegramClient(
                data["session_path"],
                data["api_id"],
                data["api_hash"]
            )
            await client.connect()
            if not await client.is_user_authorized():
                return 0, 0, ["Сессия не авторизована"]
            self.clients[user_id_str] = client
        
        client = self.clients[user_id_str]
        
        # Читаем файл
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            return 0, 0, [f"Ошибка чтения файла: {str(e)}"]
        
        # Парсим ссылки
        chat_usernames = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Извлекаем username из ссылки
            if 't.me/' in line:
                username = line.split('t.me/')[-1].split('/')[0].split('?')[0]
                if username:
                    chat_usernames.append(username)
        
        if not chat_usernames:
            return 0, 0, ["Не найдено валидных ссылок в файле"]
        
        success_count = 0
        failed_count = 0
        errors = []
        joined_chat_ids = []
        
        # Присоединяемся к чатам
        for username in chat_usernames:
            try:
                entity = await client.get_entity(username)
                if hasattr(entity, 'broadcast') or hasattr(entity, 'megagroup'):
                    # Канал или супергруппа
                    await client(JoinChannelRequest(entity))
                else:
                    # Обычная группа
                    await client(ImportChatInviteRequest(entity))
                joined_chat_ids.append(entity.id)
                success_count += 1
                await asyncio.sleep(0.5)  # Задержка между присоединениями
            except Exception as e:
                # Пробуем как invite ссылку
                try:
                    if username.startswith('+') or username.startswith('joinchat'):
                        hash_part = username.replace('+', '').replace('joinchat/', '')
                        await client(ImportChatInviteRequest(hash_part))
                        success_count += 1
                    else:
                        failed_count += 1
                        errors.append(f"@{username}: {str(e)}")
                except:
                    failed_count += 1
                    errors.append(f"@{username}: {str(e)}")
        
        # Архивируем все присоединенные чаты
        if joined_chat_ids:
            archived, failed_arch, arch_errors = await self.archive_chats(user_id, joined_chat_ids)
            errors.extend(arch_errors)
        
        return success_count, failed_count, errors
    
    async def get_chat_ids_from_usernames(self, user_id: int, usernames: List[str]) -> List[int]:
        """
        Получает ID чатов по их username
        
        Returns:
            List[int]: Список ID чатов
        """
        user_id_str = str(user_id)
        
        if user_id_str not in self.clients:
            if user_id_str not in self.sessions_data:
                return []
            
            data = self.sessions_data[user_id_str]
            client = TelegramClient(
                data["session_path"],
                data["api_id"],
                data["api_hash"]
            )
            await client.connect()
            if not await client.is_user_authorized():
                return []
            self.clients[user_id_str] = client
        
        client = self.clients[user_id_str]
        chat_ids = []
        
        for username in usernames:
            try:
                entity = await client.get_entity(username)
                chat_ids.append(entity.id)
            except:
                pass
        
        return chat_ids
    
    async def disconnect_all(self):
        """Отключает все активные сессии"""
        for name, client in list(self.clients.items()):
            try:
                await client.disconnect()
            except:
                pass
        self.clients.clear()


# Глобальный экземпляр менеджера
session_manager = SessionManager()

