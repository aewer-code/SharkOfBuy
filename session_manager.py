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
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import User, Chat, Channel

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
    
    async def add_session(
        self, 
        user_id: int,
        api_id: int, 
        api_hash: str,
        session_file_path: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Добавляет новую сессию для пользователя
        
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

