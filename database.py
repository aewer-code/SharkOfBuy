"""
База данных для бота казино
Использует SQLite для хранения данных пользователей
"""
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "casino.db"):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """Получить соединение с БД"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Инициализация базы данных"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 1000,
                total_wins INTEGER DEFAULT 0,
                total_losses INTEGER DEFAULT 0,
                total_bet INTEGER DEFAULT 0,
                last_daily_bonus TEXT,
                level INTEGER DEFAULT 1,
                experience INTEGER DEFAULT 0,
                inventory TEXT DEFAULT '[]',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Миграция: добавляем колонку total_bet, если её нет
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN total_bet INTEGER DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Колонка уже существует
        
        # Таблица игр (история)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_type TEXT,
                bet INTEGER,
                result TEXT,
                win_amount INTEGER DEFAULT 0,
                emoji_result TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Таблица заданий
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_type TEXT,
                progress INTEGER DEFAULT 0,
                target INTEGER,
                completed INTEGER DEFAULT 0,
                reward INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Получить данные пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def create_user(self, user_id: int, username: str = None):
        """Создать нового пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, username, balance, last_daily_bonus)
            VALUES (?, ?, 1000, ?)
        """, (user_id, username, "2000-01-01 00:00:00"))
        
        conn.commit()
        conn.close()
        logger.info(f"Создан пользователь {user_id}")
    
    def update_balance(self, user_id: int, amount: int):
        """Обновить баланс пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
    
    def get_balance(self, user_id: int) -> int:
        """Получить баланс пользователя"""
        user = self.get_user(user_id)
        return user['balance'] if user else 1000
    
    def can_claim_daily(self, user_id: int) -> bool:
        """Проверить, может ли пользователь получить ежедневный бонус"""
        user = self.get_user(user_id)
        if not user:
            return True
        
        last_bonus = user.get('last_daily_bonus')
        if not last_bonus:
            return True
        
        try:
            last_date = datetime.strptime(last_bonus, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            return (now - last_date).days >= 1
        except:
            return True
    
    def claim_daily_bonus(self, user_id: int) -> int:
        """Выдать ежедневный бонус"""
        import random
        bonus = random.randint(100, 300)
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users 
            SET balance = balance + ?, 
                last_daily_bonus = ?
            WHERE user_id = ?
        """, (bonus, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
        
        conn.commit()
        conn.close()
        
        return bonus
    
    def record_game(self, user_id: int, game_type: str, bet: int, result: str, 
                   win_amount: int, emoji_result: str):
        """Записать результат игры"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Обновляем статистику пользователя
        if win_amount > 0:
            cursor.execute("""
                UPDATE users 
                SET total_wins = total_wins + 1,
                    total_bet = total_bet + ?
                WHERE user_id = ?
            """, (bet, user_id))
        else:
            cursor.execute("""
                UPDATE users 
                SET total_losses = total_losses + 1,
                    total_bet = total_bet + ?
                WHERE user_id = ?
            """, (bet, user_id))
        
        # Записываем игру
        cursor.execute("""
            INSERT INTO games (user_id, game_type, bet, result, win_amount, emoji_result)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, game_type, bet, result, win_amount, emoji_result))
        
        conn.commit()
        conn.close()
    
    def get_winrate(self, user_id: int) -> float:
        """Получить винрейт пользователя"""
        user = self.get_user(user_id)
        if not user:
            return 0.0
        
        total_games = user['total_wins'] + user['total_losses']
        if total_games == 0:
            return 0.0
        
        return (user['total_wins'] / total_games) * 100
    
    def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        """Получить лидерборд по винрейту"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Получаем всех пользователей с играми
        cursor.execute("""
            SELECT user_id, username, 
                   total_wins, total_losses,
                   CASE 
                       WHEN (total_wins + total_losses) > 0 
                       THEN (total_wins * 100.0 / (total_wins + total_losses))
                       ELSE 0
                   END as winrate
            FROM users
            WHERE (total_wins + total_losses) > 0
            ORDER BY winrate DESC, total_wins DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def add_experience(self, user_id: int, exp: int):
        """Добавить опыт пользователю"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users 
            SET experience = experience + ?
            WHERE user_id = ?
        """, (exp, user_id))
        
        # Проверяем повышение уровня (100 опыта = 1 уровень)
        cursor.execute("SELECT experience, level FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            new_level = (row['experience'] // 100) + 1
            if new_level > row['level']:
                cursor.execute("UPDATE users SET level = ? WHERE user_id = ?", (new_level, user_id))
                conn.commit()
                conn.close()
                return new_level
        
        conn.commit()
        conn.close()
        return None
    
    def get_inventory(self, user_id: int) -> List[Dict]:
        """Получить инвентарь пользователя"""
        user = self.get_user(user_id)
        if not user:
            return []
        
        try:
            return json.loads(user.get('inventory', '[]'))
        except:
            return []
    
    def add_to_inventory(self, user_id: int, item: Dict):
        """Добавить предмет в инвентарь"""
        inventory = self.get_inventory(user_id)
        inventory.append(item)
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users 
            SET inventory = ?
            WHERE user_id = ?
        """, (json.dumps(inventory), user_id))
        
        conn.commit()
        conn.close()
    
    def get_recent_games(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Получить последние игры пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM games 
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]

