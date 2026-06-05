import sqlite3
from datetime import datetime, time
import random

# Визначаємо шлях до файлу бази даних. Використовуємо змінну середовища або поточну папку.
DB_NAME = "db.sqlite3"
WORDS_PER_PAGE_DB = 10  # Константа: кількість слів на сторінці словника


def init_db():
    """Ініціалізує базу даних, створюючи таблиці, якщо вони не існують."""
    conn = sqlite3.connect(DB_NAME)  # Встановлення з'єднання з БД
    cursor = conn.cursor()  # Створення об'єкту курсора для виконання SQL запитів

    # Створення таблиці користувачів (оновлена версія)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            level TEXT DEFAULT 'B1'
        )
    ''')

    # Створення таблиці нагадувань
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reminder_time TEXT NOT NULL,
            frequency TEXT NOT NULL CHECK(frequency IN ('once', 'daily', 'weekly')),
            weekday INTEGER,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')

    # Створення таблиці словника
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vocabulary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            original_text TEXT NOT NULL COLLATE NOCASE,
            translation TEXT NOT NULL,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            UNIQUE(user_id, original_text)
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vocabulary_user_id ON vocabulary (user_id)")

    # Створення таблиці історії рольових ігор
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS roleplay_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            scenario TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')

    conn.commit()  # Збереження змін у базі даних
    conn.close()  # Закриття з'єднання з БД
    print("Базу даних ініціалізовано/перевірено.")


# Функції для роботи з таблицею Users
def save_user(user_id: int, name: str, age: int, level: str):
    """Зберігає або повністю оновлює дані користувача."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, name, age, level) VALUES (?, ?, ?, ?)",
            (user_id, name, age, level)
        )
        conn.commit()
    except sqlite3.Error as e:
        print(f"Помилка збереження користувача {user_id}: {e}")
        conn.rollback()
    finally:
        conn.close()


def update_user_level(user_id: int, level: str | None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Додаємо користувача, якщо його ще немає (ігноруємо помилку, якщо вже є)
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        cursor.execute("UPDATE users SET level = ? WHERE user_id = ?",
                       (level if level is not None else 'B1', user_id))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Помилка оновлення рівня для {user_id}: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_user_level(user_id: int) -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    level = "B1"
    try:
        # Вибираємо рівень з таблиці users за user_id
        cursor.execute("SELECT level FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()  # Отримуємо один рядок результату
        if result and result[0]:
            level = result[0]
    except sqlite3.Error as e:
        print(f"Помилка отримання рівня для {user_id}: {e}")
    finally:
        conn.close()
    return level  # Повертаємо отриманий рівень або значення за замовчуванням


# Функції для роботи з таблицею Reminders
def add_or_update_reminder(user_id: int, reminder_time: time, frequency: str, weekday: int | None):
    time_str = reminder_time.strftime('%H:%M')  # Форматуємо час у рядок 'ГГ:ХХ'
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        cursor.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
        cursor.execute("""
            INSERT INTO reminders (user_id, reminder_time, frequency, weekday, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (user_id, time_str, frequency, weekday))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Помилка збереження/оновлення нагадування для {user_id}: {e}")
        conn.rollback()
    finally:
        conn.close()


def delete_reminders(user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    deleted_rows = 0  # Лічильник видалених рядків
    try:
        cursor.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
        deleted_rows = cursor.rowcount
        conn.commit()
    except sqlite3.Error as e:
        print(f"Помилка видалення нагадувань для {user_id}: {e}")
        conn.rollback()
    finally:
        conn.close()
    return deleted_rows > 0  # Повертає True, якщо хоча б одне нагадування було видалено


def get_active_reminders_for_time(current_time_str: str) -> list[tuple[int, int, str, int | None]]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    reminders_list = []
    try:
        # Вибираємо активні нагадування за поточним часом
        cursor.execute("""
            SELECT id, user_id, frequency, weekday
            FROM reminders
            WHERE reminder_time = ? AND is_active = 1
        """, (current_time_str,))
        reminders_list = cursor.fetchall()  # Отримуємо всі відповідні рядки
    except sqlite3.Error as e:
        print(f"Помилка отримання активних нагадувань: {e}")
    finally:
        conn.close()
    return reminders_list  # Повертаємо список кортежів


def deactivate_reminder(reminder_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE reminders SET is_active = 0 WHERE id = ?", (reminder_id,))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Помилка деактивації нагадування ID {reminder_id}: {e}")
        conn.rollback()
    finally:
        conn.close()


# Функції для роботи з таблицею Vocabulary
def add_word_to_vocabulary(user_id: int, original: str, translation: str) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    added = False  # Прапорець успішного додавання
    try:
        # Додаємо користувача, якщо його немає
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        cursor.execute("""
            INSERT OR IGNORE INTO vocabulary (user_id, original_text, translation)
            VALUES (?, ?, ?)
        """, (user_id, original.strip(), translation.strip()))
        added = cursor.rowcount > 0  # Якщо було додано хоча б 1 рядок, встановлюємо прапорець
        conn.commit()
    except sqlite3.Error as e:
        print(f"Помилка додавання слова до словника для {user_id}: {e}")
        conn.rollback()
    finally:
        conn.close()
    return added


def get_user_vocabulary(user_id: int, limit: int = WORDS_PER_PAGE_DB, offset: int = 0) -> list[tuple[int, str, str]]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    vocabulary_list = []
    try:
        # Додаємо COLLATE NOCASE до ORDER BY для стабільного сортування
        cursor.execute("""
            SELECT id, original_text, translation
            FROM vocabulary
            WHERE user_id = ?
            ORDER BY added_at DESC, LOWER(original_text) COLLATE NOCASE
            LIMIT ? OFFSET ?
        """, (user_id, limit, offset))
        vocabulary_list = cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Помилка отримання словника для {user_id}: {e}")
    finally:
        conn.close()
    return vocabulary_list  # Повертаємо список кортежів (id, original, translation)


def count_user_vocabulary(user_id: int) -> int:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    count = 0  # Лічильник слів
    try:
        cursor.execute("SELECT COUNT(*) FROM vocabulary WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            count = result[0]  # Отримуємо значення лічильника
    except sqlite3.Error as e:
        print(f"Помилка підрахунку слів у словнику для {user_id}: {e}")
    finally:
        conn.close()
    return count


def delete_word_from_vocabulary(user_id: int, word_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    deleted = False
    try:
        # Виконуємо запит DELETE за ID слова та ID користувача
        cursor.execute("DELETE FROM vocabulary WHERE id = ? AND user_id = ?", (word_id, user_id))
        deleted = cursor.rowcount > 0  # Перевіряємо, чи був видалений хоча б один рядок
        conn.commit()
    except sqlite3.Error as e:
        print(f"Помилка видалення слова ID {word_id} для користувача {user_id}: {e}")
        conn.rollback()
    finally:
        conn.close()
    return deleted


def search_user_vocabulary(user_id: int, query: str) -> list[tuple[str, str]]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    results = []
    search_pattern = f"%{query.lower()}%"
    try:
        cursor.execute("""
            SELECT original_text, translation
            FROM vocabulary
            WHERE user_id = ? AND (LOWER(original_text) LIKE ? OR LOWER(translation) LIKE ?)
            ORDER BY added_at DESC
            LIMIT 50
        """, (user_id, search_pattern, search_pattern))
        results = cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Помилка пошуку у словнику для {user_id} з запитом '{query}': {e}")
    finally:
        conn.close()
    return results  # Повертаємо список знайдених пар (original, translation)


def delete_user_vocabulary(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM vocabulary WHERE user_id = ?", (user_id,))
        conn.commit()
        print(f"Словник для користувача {user_id} очищено.")
    except sqlite3.Error as e:
        print(f"Помилка очищення словника для {user_id}: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_random_words(user_id: int, count: int) -> list[tuple[int, str, str]]:
    """Повертає список випадкових слів (id, original, translation) зі словника користувача."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    words = []
    try:
        # Вибираємо слова, сортуємо випадковим чином (ORDER BY RANDOM()) та обмежуємо кількість (LIMIT)
        cursor.execute("""
            SELECT id, original_text, translation
            FROM vocabulary
            WHERE user_id = ?
            ORDER BY RANDOM()
            LIMIT ?
        """, (user_id, count))
        words = cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Помилка отримання випадкових слів для {user_id}: {e}")
    finally:
        conn.close()
    return words  # Повертаємо список випадкових слів