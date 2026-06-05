import asyncio
from datetime import datetime, time
import math
import random

from aiogram import F, types, Router, Bot
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv, find_dotenv

# Імпорти функцій для роботи з базою даних
from common.db import (
    update_user_level, get_user_level,
    add_or_update_reminder, delete_reminders, get_active_reminders_for_time,
    deactivate_reminder,
    add_word_to_vocabulary, get_user_vocabulary, count_user_vocabulary,
    delete_user_vocabulary, delete_word_from_vocabulary, search_user_vocabulary,
    get_random_words
)
# Імпорти функцій для створення клавіатур
from kbds.reply import get_keyboard
from kbds.inline import (
    get_save_word_keyboard, CALLBACK_DATA_SEPARATOR,
    get_vocabulary_list_keyboard, WORDS_PER_PAGE
)
# Імпорт функцій для взаємодії з Google Gemini API
from services.gemini_service import translate_with_example_gemini, generate_distractors_gemini
# Завантажуємо змінні середовища
load_dotenv(find_dotenv())
# Створюємо роутер для обробки приватних повідомлень користувача
user_private_router = Router()

# СТАНИ FSM
# Група станів для процесів, пов'язаних з навчанням (рівень, нагадування)
class LearningState(StatesGroup):
    choosing_level = State() # Стан вибору рівня
    choosing_reminder_time = State() # Стан вибору часу нагадування
    choosing_reminder_frequency = State() # Стан вибору частоти нагадування
    choosing_reminder_weekday = State() # Стан вибору дня тижня для щотижневого нагадування
# Група станів для процесу перекладу
class TranslationState(StatesGroup):
    waiting_for_text = State() # Стан очікування тексту для перекладу
# Група станів для процесу пошуку у словнику
class SearchState(StatesGroup):
    waiting_for_search_query = State() # Стан очікування пошукового запиту
# Група станів для процесу тестування словника
class QuizState(StatesGroup):
    choosing_quiz_length = State() # Стан вибору кількості питань у тесті
    in_quiz = State() # Стан активного проходження тесту

# ФУНКЦІЯ НАГАДУВАНЬ
async def send_reminders(bot: Bot):
    print("Фонова задача нагадувань запущена.")
    while True:
        now = datetime.now()
        current_time_str = now.strftime('%H:%M')
        current_weekday = now.weekday()
        try:
            reminders_to_send = get_active_reminders_for_time(current_time_str)
            for reminder_id, user_id, frequency, weekday in reminders_to_send:
                send_now = False
                if frequency == 'daily':
                    send_now = True
                elif frequency == 'weekly' and isinstance(weekday, int) and current_weekday == weekday:
                    send_now = True
                elif frequency == 'once':
                    send_now = True

                if send_now:
                    try:
                        await bot.send_message(user_id, "⏰ Час навчатися! 🇬🇧")
                        print(f"Sent reminder {reminder_id} ({frequency}) to {user_id}")
                        if frequency == 'once':
                            deactivate_reminder(reminder_id)
                            print(f"Deactivated reminder {reminder_id}")
                    except Exception as e:
                        if isinstance(e, TelegramBadRequest) and ("bot was blocked" in str(e) or "chat not found" in str(e)):
                            print(f"Reminder {reminder_id} failed for {user_id}: Bot blocked or chat not found. Deleting reminder.")
                            delete_reminders(user_id)
                        else:
                            print(f"Failed sending reminder {reminder_id} to {user_id}: {e}")
        except Exception as e:
            print(f"Error in send_reminders loop: {e}")

        now_after_check = datetime.now()
        sleep_duration = 60 - now_after_check.second - now_after_check.microsecond / 1_000_000
        await asyncio.sleep(max(0.1, sleep_duration))

# ГОЛОВНЕ МЕНЮ
def main_menu():
    return get_keyboard(
        "✍ Перекладач", "📚 Вибрати рівень",
        "⏰ Нагадування", "📖 Мій словник",
        "🧠 Тест словника",
        placeholder="Що тебе цікавить?",
        sizes=(2, 2, 1)
    )

# ОБРОБНИКИ КОМАНД
@user_private_router.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    current_level = get_user_level(user_id)
    if current_level == "Не встановлено":
        update_user_level(user_id, None)
    await message.answer(
        f"Привіт, {message.from_user.first_name}! Я твій помічник у вивченні англійської 🇬🇧\n"
        f"Обери дію з клавіатури або використай меню команд (/)",
        reply_markup=main_menu(),
    )
# Обробник команди /translator або тексту "Перекладач"
@user_private_router.message(Command("translator"))
@user_private_router.message(F.text == "✍ Перекладач")
async def translator_command(message: types.Message, state: FSMContext):
    current_state_str = await state.get_state()
    if current_state_str == TranslationState.waiting_for_text.state:
        await message.answer("✍️ Я вже чекаю на текст для перекладу. Просто надішли його.", reply_markup=types.ReplyKeyboardRemove())
        return
    await state.clear()
    await message.answer("✍️ Надішли мені слово або фразу українською чи англійською мовою для перекладу та прикладу:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(TranslationState.waiting_for_text)
# Обробник команди /profile
@user_private_router.message(Command("profile"))
async def profile_command(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    level = get_user_level(user_id)
    await message.answer(f"👤 Твій профіль:\n\n🎓 Рівень: {level}", reply_markup=main_menu())
# Обробник команди /about
@user_private_router.message(Command("about"))
async def about_command(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("ℹ️ Я – бот Fluentia, створений для допомоги у вивченні англійської мови! 🇬🇧\n\n"
                         "Можливості:\n"
                         "✍️ Переклад слів та фраз з прикладами (адаптованими під ваш рівень).\n"
                         "📖 Збереження слів у персональний словник (з можливістю пошуку).\n"
                         "📚 Встановлення вашого рівня мови.\n"
                         "⏰ Налаштування нагадувань про навчання.\n"
                         "🧠 Тестування слів з вашого словника.\n\n"
                         "Використовуй кнопки меню або команди /.",
                         reply_markup=main_menu())
# ОБРОБНИК КНОПОК ГОЛОВНОГО МЕНЮ
MIN_WORDS_FOR_QUIZ = 5 # Мінімальна кількість слів у словнику для запуску тест
@user_private_router.message(F.text.in_([
    "📚 Вибрати рівень", "⏰ Нагадування", "📖 Мій словник",
    "🧠 Тест словника"
]))
async def process_main_menu_buttons(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    # Обробка натискання "Вибрати рівень"
    if message.text == "📚 Вибрати рівень":
        level = get_user_level(user_id)
        await message.answer(f"Ваш поточний рівень: {level}\nВибери новий рівень або скинь його:",
            reply_markup=get_keyboard("A1", "A2", "B1", "B2", "C1", "C2", "❌ Скинути рівень", "◀️ Назад", placeholder="Виберіть бажаний рівень", sizes=(2, 2, 2, 1)))
        await state.set_state(LearningState.choosing_level)
    # Обробка натискання "Нагадування"
    elif message.text == "⏰ Нагадування":
        await reminder_menu(message, state)
    # Обробка натискання "Мій словник"
    elif message.text == "📖 Мій словник":
        await show_vocabulary_handler(message, state, page=0)
    # Обробка натискання "Тест словника"
    elif message.text == "🧠 Тест словника":
        word_count = count_user_vocabulary(user_id)
        if word_count < MIN_WORDS_FOR_QUIZ:
            await message.answer(f"❌ Для тесту потрібно мати у словнику хоча б {MIN_WORDS_FOR_QUIZ} слова.\nЗараз у вас: {word_count}. Додайте ще слів через перекладач!", reply_markup=main_menu())
            return
        await message.answer("Скільки питань у тесті?", reply_markup=get_keyboard("5 питань", "10 питань", "15 питань", "◀️ Назад", placeholder="Виберіть кількість", sizes=(3, 1)))
        await state.set_state(QuizState.choosing_quiz_length)

# ОБРОБКА ПЕРЕКЛАДУ
@user_private_router.message(TranslationState.waiting_for_text, F.text)
async def handle_text_for_translation(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    original_text = message.text.strip()
    if not original_text:
        await message.answer("Будь ласка, введіть якийсь текст для перекладу.")
        return

    level = get_user_level(user_id)
    user_level_for_prompt = level if level != "Не встановлено" else None

    thinking_message = await message.answer("⏳ Обробляю ваш запит...")
    result_text = await translate_with_example_gemini(original_text, user_level=user_level_for_prompt)

    reply_markup_inline = None
    primary_translation = ""

    if result_text and not result_text.startswith("Помилка") and not result_text.startswith("❌"):
        try:
            lines = result_text.split('\n')
            translation_line = next((l for l in lines if l.startswith("📖 Переклад:")), None)

            if translation_line:
                translation_part = translation_line.split(":", 1)[1].strip().replace("(ідіома)", "").strip()
                if translation_part:
                    primary_translation = translation_part.split(',')[0].strip()

            is_likely_sentence = len(original_text.split()) > 5 or any(p in original_text for p in '.?!')

            if primary_translation and not is_likely_sentence:
                 reply_markup_inline = get_save_word_keyboard(original_text, primary_translation)

        except Exception as e:
            print(f"Err parsing translation line or generating save button for '{original_text}': {e}")
            reply_markup_inline = None

    try:
        await thinking_message.edit_text(
            result_text,
            reply_markup=reply_markup_inline,
            parse_mode=None
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
             print(f"Err editing translation message: {e}")
             await message.answer(result_text, reply_markup=reply_markup_inline, parse_mode=None)
    except Exception as e:
        print(f"Err editing translation message: {e}")
        await message.answer(result_text, reply_markup=reply_markup_inline, parse_mode=None)

    await message.answer(
        "Надішліть наступне слово/фразу або команду /start для виходу.",
        reply_markup=types.ReplyKeyboardRemove()
    )

@user_private_router.message(TranslationState.waiting_for_text)
async def handle_non_text_for_translation(message: types.Message):
    await message.answer("Будь ласка, надішліть саме текст (слово або фразу) для перекладу.")

# --- ОБРОБНИКИ РОБОТИ ЗІ СЛОВНИКОМ ---
@user_private_router.callback_query(F.data.startswith(f"save_word{CALLBACK_DATA_SEPARATOR}"))
async def save_word_callback_handler(query: types.CallbackQuery):
    user_id = query.from_user.id
    callback_data = query.data
    try:
        parts = callback_data.split(CALLBACK_DATA_SEPARATOR)
        if len(parts) < 3: raise ValueError("Недостатньо частин у callback_data")
        original = parts[1].strip()
        translation = parts[2].strip()
    except Exception as e:
        print(f"Error parsing save_word callback: {e}, data: {callback_data}")
        await query.answer("❌ Помилка даних для збереження.", show_alert=True)
        return

    if not original or not translation:
        await query.answer("❌ Неможливо зберегти порожні дані.", show_alert=True)
        return

    added = add_word_to_vocabulary(user_id, original, translation)

    await query.answer("✅ Слово збережено!" if added else "⚠️ Це слово вже є у словнику.", show_alert=False)
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest as e:
         if "message is not modified" not in str(e): print(f"Error editing reply markup after save: {e}")
    except Exception as e: print(f"Error editing reply markup after save: {e}")


async def show_vocabulary_handler(message_or_query: types.Message | types.CallbackQuery, state: FSMContext, page: int = 0):
    user_id = message_or_query.from_user.id
    is_callback = isinstance(message_or_query, types.CallbackQuery)
    message_to_edit = message_or_query.message if is_callback else None

    offset = page * WORDS_PER_PAGE
    total_words = count_user_vocabulary(user_id)
    vocabulary_page_data = get_user_vocabulary(user_id, limit=WORDS_PER_PAGE, offset=offset)

    reply_markup = get_vocabulary_list_keyboard(vocabulary_page_data, page, total_words)

    text = ""
    total_pages = math.ceil(total_words / WORDS_PER_PAGE) if total_words > 0 else 1
    current_display_page = page + 1

    if not vocabulary_page_data and page > 0:
        print(f"Vocabulary page {current_display_page} is empty, showing last available page.")
        new_page = max(0, total_pages - 1)
        if is_callback: return await show_vocabulary_handler(message_or_query, state, page=new_page)
        else:
             text = "Ваш словничок поки що порожній..."
             reply_markup = get_vocabulary_list_keyboard([], 0, 0)

    elif not vocabulary_page_data and page == 0:
        text = "Ваш словничок поки що порожній..."
    else:
        text = f"📖 **Ваш словничок** (Сторінка {current_display_page}/{total_pages}, Всього: {total_words})\n\n"
        text += "\n".join(f"{i+offset+1}. **{orig}** - {trans}" for i, (wid, orig, trans) in enumerate(vocabulary_page_data))
        text += "\n\n_Натисніть ❌ біля слова, щоб видалити його._"

    if is_callback:
        if message_to_edit and (message_to_edit.text != text or message_to_edit.reply_markup != reply_markup):
            try:
                await message_to_edit.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
            except TelegramBadRequest as e:
                 if "message is not modified" not in str(e): print(f"Vocabulary edit error: {e}")
            except Exception as e: print(f"Vocabulary edit error: {e}")
        await message_or_query.answer()
    else:
        await message_or_query.answer(text, reply_markup=reply_markup, parse_mode="Markdown")

@user_private_router.callback_query(F.data.startswith(f"vocab_page{CALLBACK_DATA_SEPARATOR}"))
async def vocabulary_page_callback_handler(query: types.CallbackQuery, state: FSMContext):
    try:
        page = int(query.data.split(CALLBACK_DATA_SEPARATOR)[1])
        await show_vocabulary_handler(query, state, page=max(0, page))
    except Exception as e:
        print(f"Vocabulary page callback error: {e}")
        await query.answer("Помилка переходу на сторінку.", show_alert=True)

@user_private_router.callback_query(F.data.startswith(f"vocab_delete{CALLBACK_DATA_SEPARATOR}"))
async def vocabulary_delete_callback_handler(query: types.CallbackQuery, state: FSMContext):
    user_id = query.from_user.id
    try:
        word_id = int(query.data.split(CALLBACK_DATA_SEPARATOR)[1])
    except Exception as e:
        print(f"Error parsing word_id for delete: {e}")
        await query.answer("Помилка ідентифікатора слова.", show_alert=True)
        return

    if delete_word_from_vocabulary(user_id, word_id):
        await query.answer("✅ Слово видалено!", show_alert=False)
        current_page = 0
        try:
             if query.message.reply_markup:
                 page_button = next((btn for row in query.message.reply_markup.inline_keyboard for btn in row if btn.callback_data=="noop"), None)
                 if page_button and "/" in page_button.text:
                     current_page = int(page_button.text.split('/')[0]) - 1
                     current_page = max(0, current_page)
        except Exception as e:
            print(f"Could not determine current page after delete: {e}")

        total_words = count_user_vocabulary(user_id)
        total_pages = math.ceil(total_words / WORDS_PER_PAGE) if total_words > 0 else 1
        current_page = max(0, min(current_page, total_pages - 1))

        await show_vocabulary_handler(query, state, page=current_page)
    else:
        await query.answer("❌ Не вдалося видалити слово (можливо, вже видалено).", show_alert=False)

@user_private_router.callback_query(F.data == "noop")
async def noop_callback_handler(query: types.CallbackQuery):
    await query.answer()

# --- ПОШУК У СЛОВНИКУ ---
@user_private_router.callback_query(F.data == "vocab_search_start")
async def vocabulary_search_start_handler(query: types.CallbackQuery, state: FSMContext):
    try:
        await query.message.edit_text("🔍 Введіть слово або частину слова для пошуку:", reply_markup=None)
        await state.set_state(SearchState.waiting_for_search_query)
        await query.answer()
    except TelegramBadRequest as e:
         if "message to edit not found" in str(e):
              await query.message.answer("🔍 Введіть слово або частину слова для пошуку:")
              await state.set_state(SearchState.waiting_for_search_query)
              await query.answer()
         else: print(f"Vocabulary search start error: {e}"); await query.answer("Сталася помилка.", show_alert=True)
    except Exception as e:
        print(f"Vocabulary search start error: {e}")
        await query.answer("Сталася помилка при запуску пошуку.", show_alert=True)

@user_private_router.message(SearchState.waiting_for_search_query, F.text)
async def process_search_query(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    query_text = message.text.strip()
    if not query_text:
        await message.answer("Введіть текст для пошуку.")
        return

    thinking_msg = await message.answer(f"🔍 Шукаю '{query_text}'...")
    results = search_user_vocabulary(user_id, query_text)
    await state.clear()

    response_text = ""
    if not results:
        response_text = f"На жаль, нічого не знайдено за запитом '{query_text}'."
    else:
        response_text = f"🔎 **Результати пошуку для '{query_text}':**\n\n"
        limit = 50
        response_text += "\n".join(f"{i}. **{orig}** - {trans}" for i, (orig, trans) in enumerate(results[:limit], 1))
        if len(results) > limit:
            response_text += f"\n\n_(Показано перші {limit} з {len(results)} знайдених)_"

    try:
        await thinking_msg.edit_text(response_text, parse_mode="Markdown", reply_markup=None)
    except Exception as e:
        print(f"Err editing search results message: {e}")
        await message.answer(response_text, parse_mode="Markdown")

    await message.answer("Головне меню:", reply_markup=main_menu())

@user_private_router.message(SearchState.waiting_for_search_query)
async def handle_non_text_for_search(message: types.Message):
    await message.answer("Введіть саме текст для пошуку.")

# ВИБІР РІВНЯ АНГЛІЙСЬКОЇ
@user_private_router.message(LearningState.choosing_level, F.text.in_(["A1", "A2", "B1", "B2", "C1", "C2", "❌ Скинути рівень"]))
async def save_level(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()
    if message.text == "❌ Скинути рівень":
        if get_user_level(user_id) != "Не встановлено":
            update_user_level(user_id, None)
            await message.answer("✅ Рівень скинуто!", reply_markup=main_menu())
        else:
            await message.answer("🤔 Рівень вже не встановлено.", reply_markup=main_menu())
    else:
        level = message.text
        update_user_level(user_id, level)
        await message.answer( f"✅ Рівень встановлено: {level}!", reply_markup=main_menu())

@user_private_router.message(LearningState.choosing_level, F.text != "◀️ Назад")
async def incorrect_level_choice(message: types.Message, state: FSMContext):
     level = get_user_level(message.from_user.id)
     await message.answer(f"❌ Неправильний вибір.\nВаш поточний рівень: {level}\nБудь ласка, виберіть одну з кнопок нижче або натисніть 'Назад'.",
         reply_markup=get_keyboard( "A1", "A2", "B1", "B2", "C1", "C2", "❌ Скинути рівень", "◀️ Назад", placeholder="Виберіть рівень", sizes=(2, 2, 2, 1)))

# НАЛАШТУВАННЯ НАГАДУВАНЬ
async def reminder_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("⚙️ Налаштування нагадувань:",
        reply_markup=get_keyboard("➕ Додати/Змінити", "❌ Видалити нагадування", "◀️ Назад", placeholder="Виберіть дію", sizes=(2, 1)))

@user_private_router.message(F.text == "➕ Додати/Змінити")
async def set_reminder(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("⏰ Введіть бажаний час для нагадування у форматі **ГГ:ХХ** (наприклад, 09:30 або 18:05):",
                         parse_mode="Markdown",
                         reply_markup=get_keyboard("◀️ Назад", placeholder="Введіть час ГГ:ХХ", sizes=(1,)))
    await state.set_state(LearningState.choosing_reminder_time)

@user_private_router.message(LearningState.choosing_reminder_time, F.text)
async def save_reminder_time(message: types.Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await reminder_menu(message, state)
        return
    try:
        time_str = message.text.strip()
        reminder_time_obj = datetime.strptime(time_str, "%H:%M").time()
        await state.update_data(reminder_time=reminder_time_obj)
        await message.answer("🗓️ Як часто ви хочете отримувати нагадування?",
                             reply_markup=get_keyboard("Один раз", "Щодня", "Щотижня", "◀️ Назад", placeholder="Виберіть частоту", sizes=(1, 2, 1)))
        await state.set_state(LearningState.choosing_reminder_frequency)
    except ValueError:
        await message.answer("❌ Неправильний формат часу. Будь ласка, введіть час у форматі **ГГ:ХХ** (наприклад, 10:00) або натисніть 'Назад'.", parse_mode="Markdown")

@user_private_router.message(LearningState.choosing_reminder_time)
async def incorrect_time_format(message: types.Message):
    await message.answer("Будь ласка, введіть час у форматі **ГГ:ХХ** або натисніть кнопку 'Назад'.", parse_mode="Markdown")

@user_private_router.message(LearningState.choosing_reminder_frequency, F.text)
async def save_reminder_frequency(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    frequency_text = message.text

    if frequency_text == "◀️ Назад":
        await message.answer("⏰ Введіть час **ГГ:ХХ**:", parse_mode="Markdown", reply_markup=get_keyboard("◀️ Назад", placeholder="Введіть час ГГ:ХХ", sizes=(1,)))
        await state.set_state(LearningState.choosing_reminder_time)
        return

    if frequency_text == "Щотижня":
        await message.answer("📅 Обери день тижня для щотижневого нагадування:",
                             reply_markup=get_keyboard("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд", "◀️ Назад", placeholder="Виберіть день тижня", sizes=(3, 4, 1)))
        await state.set_state(LearningState.choosing_reminder_weekday)
    elif frequency_text in ["Один раз", "Щодня"]:
        frequency_code = {"Один раз": "once", "Щодня": "daily"}.get(frequency_text)
        try:
            data = await state.get_data()
            reminder_time = data["reminder_time"]
            add_or_update_reminder(user_id, reminder_time, frequency_code, None)
            await message.answer(f"✅ Нагадування встановлено!\nЧас: {reminder_time.strftime('%H:%M')}\nЧастота: {frequency_text.lower()}", reply_markup=main_menu())
            await state.clear()
        except KeyError:
            print(f"Error saving {frequency_code} reminder: reminder_time not found in state for user {user_id}")
            await message.answer("❌ Сталася помилка (час не знайдено). Спробуйте налаштувати знову.", reply_markup=main_menu())
            await state.clear()
        except Exception as e:
            print(f"Err save {frequency_code} reminder: {e}")
            await message.answer("❌ Сталася помилка під час збереження нагадування.", reply_markup=main_menu())
            await state.clear()
    else:
        await message.answer("❌ Будь ласка, виберіть частоту за допомогою кнопок або натисніть 'Назад'.",
                             reply_markup=get_keyboard("Один раз", "Щодня", "Щотижня", "◀️ Назад", placeholder="Виберіть частоту", sizes=(1, 2, 1)))

@user_private_router.message(LearningState.choosing_reminder_frequency)
async def incorrect_frequency_choice(message: types.Message):
     await message.answer("Будь ласка, оберіть частоту за допомогою кнопок або натисніть 'Назад'.")

@user_private_router.message(LearningState.choosing_reminder_weekday, F.text)
async def save_reminder_weekday(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    weekday_text = message.text

    if weekday_text == "◀️ Назад":
        await message.answer("🗓️ Як часто ви хочете отримувати нагадування?",
                             reply_markup=get_keyboard("Один раз", "Щодня", "Щотижня", "◀️ Назад", placeholder="Виберіть частоту", sizes=(1, 2, 1)))
        await state.set_state(LearningState.choosing_reminder_frequency)
        return

    weekday_map = {"Пн": 0, "Вт": 1, "Ср": 2, "Чт": 3, "Пт": 4, "Сб": 5, "Нд": 6}
    if weekday_text in weekday_map:
        weekday_code = weekday_map[weekday_text]
        try:
            data = await state.get_data()
            reminder_time = data["reminder_time"]
            add_or_update_reminder(user_id, reminder_time, "weekly", weekday_code)
            await message.answer( f"✅ Нагадування встановлено!\nЧас: {reminder_time.strftime('%H:%M')}\nЧастота: щотижня ({weekday_text})", reply_markup=main_menu())
            await state.clear()
        except KeyError:
             print(f"Error saving weekly reminder: reminder_time not found in state for user {user_id}")
             await message.answer("❌ Сталася помилка (час не знайдено). Спробуйте налаштувати знову.", reply_markup=main_menu())
             await state.clear()
        except Exception as e:
            print(f"Err save weekly reminder: {e}")
            await message.answer("❌ Сталася помилка під час збереження нагадування.", reply_markup=main_menu())
            await state.clear()
    else:
        await message.answer("❌ Будь ласка, виберіть день тижня за допомогою кнопок або натисніть 'Назад'.",
                             reply_markup=get_keyboard("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд", "◀️ Назад", placeholder="Виберіть день тижня", sizes=(3, 4, 1)))

@user_private_router.message(LearningState.choosing_reminder_weekday)
async def incorrect_weekday_choice(message: types.Message):
    await message.answer("Будь ласка, оберіть день тижня за допомогою кнопок або натисніть 'Назад'.")

@user_private_router.message(F.text == "❌ Видалити нагадування")
async def reset_reminders(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if delete_reminders(user_id):
        await message.answer("✅ Всі ваші нагадування видалено!", reply_markup=main_menu())
    else:
        await message.answer("🤔 У вас немає активних нагадувань для видалення.", reply_markup=main_menu())

# ЛОГІКА ТЕСТУВАННЯ СЛОВНИКА
@user_private_router.message(QuizState.choosing_quiz_length, F.text.in_(['5 питань', '10 питань', '15 питань']))
async def handle_quiz_length_choice(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        chosen_len = int(message.text.split()[0])
    except Exception as e:
        print(f"Error parsing quiz length: {e}")
        await message.answer("Помилка вибору кількості питань.", reply_markup=main_menu())
        await state.clear()
        return

    word_count = count_user_vocabulary(user_id)
    if word_count < MIN_WORDS_FOR_QUIZ:
        await message.answer(f"❌ Мало слів у словнику (<{MIN_WORDS_FOR_QUIZ}). Додайте ще.", reply_markup=main_menu())
        await state.clear()
        return

    actual_quiz_len = min(chosen_len, word_count)

    await message.answer(f"🚀 Починаємо тест з {actual_quiz_len} питань!", reply_markup=types.ReplyKeyboardRemove())

    quiz_words = get_random_words(user_id, actual_quiz_len)
    if len(quiz_words) < actual_quiz_len:
        print(f"Warning: Requested {actual_quiz_len} words for quiz, but got {len(quiz_words)} for user {user_id}")
        actual_quiz_len = len(quiz_words)
        if actual_quiz_len < MIN_WORDS_FOR_QUIZ:
            await message.answer("❌ Сталася помилка при вибірці слів для тесту.", reply_markup=main_menu())
            await state.clear()
            return

    await state.set_state(QuizState.in_quiz)
    await state.update_data(quiz_words=quiz_words, current_question_index=0, score=0, actual_len=actual_quiz_len)
    await ask_next_question(message, state)

@user_private_router.message(QuizState.choosing_quiz_length, F.text != "◀️ Назад")
async def incorrect_quiz_length_choice(message: types.Message):
    await message.answer("Будь ласка, виберіть кількість питань кнопками або натисніть 'Назад'.",
        reply_markup=get_keyboard("5 питань", "10 питань", "15 питань", "◀️ Назад", placeholder="Виберіть кількість", sizes=(3, 1)))

# Функція для постановки наступного питання
async def ask_next_question(message_or_query: types.Message | types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_index = data.get("current_question_index", 0)
    quiz_words = data.get("quiz_words", [])
    actual_len = data.get("actual_len", 0)
    user_id = message_or_query.from_user.id

    user_level = get_user_level(user_id)
    user_level_for_prompt = user_level if user_level != "Не встановлено" else None

    if current_index >= actual_len:
        await show_quiz_results(message_or_query, state)
        return

    if not quiz_words or current_index >= len(quiz_words):
         print(f"ERROR: Quiz index {current_index} out of bounds for quiz_words list (len: {len(quiz_words)}) for user {user_id}.")
         await show_quiz_results(message_or_query, state)
         return

    current_word_id, original, translation = quiz_words[current_index]

    if not original or not translation:
        print(f"ERROR: Missing original ('{original}') or translation ('{translation}') for word_id {current_word_id}. Skipping question.")
        await state.update_data(current_question_index=current_index + 1)
        if isinstance(message_or_query, types.CallbackQuery):
            try: await message_or_query.answer("Помилка даних слова, пропускаємо питання.", show_alert=True)
            except Exception as e_ans: print(f"Error answering callback query: {e_ans}")
        asyncio.create_task(ask_next_question(message_or_query, state))
        return

    direction = random.choice(['orig_to_trans', 'trans_to_orig'])
    question_word, correct_answer_option, distractor_language, question_prompt = "", "", "", ""

    # Змінено формулювання питання на нейтральне
    if direction == 'orig_to_trans':
        question_word, correct_answer_option, distractor_language = original, translation, "українська"
        question_prompt = f"Як перекладається слово/фраза: `{question_word}`?"
    else:
        question_word, correct_answer_option, distractor_language = translation, original, "англійська"
        question_prompt = f"Який відповідник до слова/фрази: *{question_word}*?"

    print(f"Q{current_index+1} for user {user_id}: Question word='{question_word}', Correct option='{correct_answer_option}', Distractor lang='{distractor_language}'")

    # Отримання дистракторів від Gemini
    distractors = await generate_distractors_gemini(
        question_word,
        correct_answer_option,
        distractor_language,
        user_level=user_level_for_prompt,
        count=3
    )

    # НАДІЙНА РЕЗЕРВНА ЛОГІКА
    if distractors is None: # Якщо Gemini не впорався АБО повернув невалідний результат
        print(f"Warning: Using RELIABLE fallback distractors (v6) for user {user_id}, word: '{question_word}', target_lang: {distractor_language}")
        distractors = []
        all_user_words = get_user_vocabulary(user_id, limit=500, offset=0)

        possible_options = []
        correct_lower = correct_answer_option.lower()

        # Вибираємо слова потрібної мови
        if distractor_language == "українська":
            possible_options = [
                word[2] for word in all_user_words
                if word[0] != current_word_id and word[2] and word[2].lower() != correct_lower
            ]
            print(f"Fallback (v6): Looking for UKRAINIAN options. Found {len(possible_options)} candidates initially.")
        elif distractor_language == "англійська":
            possible_options = [
                word[1] for word in all_user_words
                if word[0] != current_word_id and word[1] and word[1].lower() != correct_lower
            ]
            print(f"Fallback (v6): Looking for ENGLISH options. Found {len(possible_options)} candidates initially.")
        else:
             print(f"CRITICAL ERROR: Unknown distractor language '{distractor_language}' in fallback logic.")
             possible_options = []

        seen = set()
        unique_possible_options = []
        for item in possible_options:
            item_lower = item.lower()
            if item_lower not in seen:
                seen.add(item_lower)
                unique_possible_options.append(item)

        random.shuffle(unique_possible_options)
        print(f"Fallback (v6): Unique possible options ({distractor_language}): {unique_possible_options[:10]}")

        distractors = unique_possible_options[:3]

        if len(distractors) < 3:
            print(f"Fallback (v6): Not enough options from vocabulary ({len(distractors)} found). Adding GUARANTEED placeholders.")
            generic_options_ua = ["Неправильний варіант", "Інша відповідь", "Щось інше", "Не той переклад", "Помилка"]
            generic_options_en = ["Incorrect option", "Another answer", "Something else", "Wrong translation", "Mistake"]
            generic_options = generic_options_ua if distractor_language == "українська" else generic_options_en
            random.shuffle(generic_options)

            existing_lower = {d.lower() for d in distractors}
            for opt in generic_options:
                 if len(distractors) < 3:
                     opt_lower = opt.lower()
                     if opt_lower != correct_lower and opt_lower not in existing_lower:
                         distractors.append(opt)
                         existing_lower.add(opt_lower)

            while len(distractors) < 3:
                 simple_placeholder = f"Option {random.randint(1000, 9999)}"
                 if simple_placeholder.lower() not in existing_lower and simple_placeholder.lower() != correct_lower :
                     distractors.append(simple_placeholder)
                     existing_lower.add(simple_placeholder.lower())

        print(f"Fallback distractors generated (v6) - GUARANTEED 3 options: {distractors}")

    if len(distractors) != 3:
         print(f"CRITICAL ERROR: Could not ensure 3 distractors for '{correct_answer_option}'. Generated: {distractors}")
         await message_or_query.message.answer("Виникла критична помилка при генерації варіантів тесту. Тест перервано.", reply_markup=main_menu())
         await state.clear()
         return

    options = distractors + [correct_answer_option]
    random.shuffle(options)
    print(f"Final options for question '{question_word}' -> '{correct_answer_option}': {options}")

    await state.update_data(correct_answer=correct_answer_option, current_question_word=question_word)

    builder = InlineKeyboardBuilder()
    for option in options:
        max_callback_text_len = 58
        callback_text = option[:max_callback_text_len] if len(option) > max_callback_text_len else option
        callback_data_full = f"quiz_ans::{callback_text}"
        if len(callback_data_full.encode('utf-8')) <= 64:
            builder.button(text=option, callback_data=callback_data_full)
        else:
             trim_bytes = len(callback_data_full.encode('utf-8')) - 64
             chars_to_remove = math.ceil(trim_bytes / 1.5) + 3
             trim_len = max(0, max_callback_text_len - chars_to_remove)
             if trim_len > 0 :
                 callback_text_short = option[:trim_len] + "..."
                 callback_data_short = f"quiz_ans::{callback_text_short}"
                 if len(callback_data_short.encode('utf-8')) <= 64:
                      builder.button(text=option, callback_data=callback_data_short)
                      print(f"Warning: Callback data for option '{option}' was shortened to fit limit: '{callback_text_short}'")
                 else:
                      print(f"ERROR: Callback data for option '{option}' could not be shortened enough even after severe trimming. Skipping button.")
             else:
                 print(f"ERROR: Callback data for option '{option}' is fundamentally too long to create callback data. Skipping button.")
    builder.adjust(1)

    question_number = current_index + 1
    text = f"Питання {question_number}/{actual_len}:\n\n{question_prompt}" # Нейтральне питання

    message_to_handle = message_or_query.message if isinstance(message_or_query, types.CallbackQuery) else message_or_query
    try:
        if isinstance(message_or_query, types.CallbackQuery):
             if message_to_handle.text != text or message_to_handle.reply_markup != builder.as_markup():
                 await message_to_handle.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
             await message_or_query.answer()
        else:
             await message_to_handle.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except TelegramBadRequest as e:
         if "message is not modified" in str(e):
             print("Message not modified, skipping edit.")
             if isinstance(message_or_query, types.CallbackQuery): await message_or_query.answer()
         elif "message to edit not found" in str(e):
             print("Message to edit not found, sending new.")
             await message_to_handle.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
         else:
             print(f"Error sending/editing question: {e}")
             await message_to_handle.answer("❌ Сталася помилка під час показу питання.", reply_markup=main_menu())
             await state.clear()
    except Exception as e:
        print(f"Unexpected error sending/editing question: {e}")
        await message_to_handle.answer("❌ Сталася неочікувана помилка під час показу питання.", reply_markup=main_menu())
        await state.clear()

# Обробник відповіді на питання тесту
@user_private_router.callback_query(QuizState.in_quiz, F.data.startswith("quiz_ans::"))
async def handle_quiz_answer(query: types.CallbackQuery, state: FSMContext):
    user_answer_potentially_trimmed = query.data.split("::", 1)[1]

    data = await state.get_data()
    correct_answer = data.get("correct_answer")
    current_question_word = data.get("current_question_word")
    current_index = data.get("current_question_index", 0)
    score = data.get("score", 0)

    feedback_text = ""
    is_correct = False

    len_user_ans = len(user_answer_potentially_trimmed)
    correct_answer_trimmed_for_check = correct_answer[:len_user_ans] if correct_answer else ""

    if correct_answer and user_answer_potentially_trimmed == correct_answer_trimmed_for_check:
        if user_answer_potentially_trimmed == correct_answer or len(user_answer_potentially_trimmed) > 3:
            feedback_text = "✅ Правильно!"
            score += 1
            is_correct = True
            await query.answer("✅", show_alert=False)
        else:
            feedback_text = f"❌ Неправильно.\nПравильна відповідь: **{correct_answer}**"
            await query.answer("❌", show_alert=False)
    else:
        feedback_text = f"❌ Неправильно.\nПравильна відповідь: **{correct_answer}**"
        await query.answer("❌", show_alert=False)

    try:
        current_text = query.message.text or ""
        text_to_edit = current_text.split('\n\n')[0]
        await query.message.edit_text(
            f"{text_to_edit}\n\n{feedback_text}",
            reply_markup=None,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Err editing feedback message: {e}")
        await query.message.answer(feedback_text, parse_mode="Markdown")

    current_index += 1
    await state.update_data(current_question_index=current_index, score=score)

    await asyncio.sleep(1.5 if is_correct else 3.0)
    asyncio.create_task(ask_next_question(query, state))

# Функція для показу результатів тесту
async def show_quiz_results(message_or_query: types.Message | types.CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        print(f"State was already cleared when trying to show results for user {message_or_query.from_user.id}.")
        return

    data = await state.get_data()
    score = data.get("score", 0)
    actual_len = data.get("actual_len", 0)
    user_id = message_or_query.from_user.id

    percent = 0
    if actual_len > 0:
        percent = round((score / actual_len) * 100)

    result_text = f"🏁 Тест завершено!\n\nВаш результат: **{score}** з **{actual_len}**"
    emoji = "🤔"
    if actual_len > 0:
        if percent >= 90: emoji = "🎉 Чудово!"
        elif percent >= 70: emoji = "👍 Добре!"
        elif percent >= 50: emoji = "🙂 Непогано!"
        else: emoji = "🤔 Варто ще потренуватись."
        result_text += f" ({percent}%)\n\n{emoji}"

    msg_origin = message_or_query.message if isinstance(message_or_query, types.CallbackQuery) else message_or_query

    await state.clear()
    await msg_origin.answer(result_text, reply_markup=main_menu(), parse_mode="Markdown")
    print(f"Quiz finished for user {user_id}. Score: {score}/{actual_len}. State cleared.")


# ЗАГАЛЬНИЙ ОБРОБНИК КНОПКИ "Назад"
@user_private_router.message(StateFilter(LearningState, SearchState, TranslationState, QuizState), F.text == "◀️ Назад")
@user_private_router.message(StateFilter(None), F.text == "◀️ Назад")
async def go_back_handler(message: types.Message, state: FSMContext):
    current_state_str = await state.get_state()
    print(f"Back button pressed from state: {current_state_str}")

    if current_state_str == LearningState.choosing_level.state:
        await state.clear()
        await message.answer("Головне меню:", reply_markup=main_menu())
    elif current_state_str == LearningState.choosing_reminder_time.state:
        await reminder_menu(message, state)
    elif current_state_str == LearningState.choosing_reminder_frequency.state:
        await message.answer("⏰ Введіть час **ГГ:ХХ**:", parse_mode="Markdown", reply_markup=get_keyboard("◀️ Назад", placeholder="Введіть час ГГ:ХХ", sizes=(1,)))
        await state.set_state(LearningState.choosing_reminder_time)
    elif current_state_str == LearningState.choosing_reminder_weekday.state:
        await message.answer("🗓️ Як часто ви хочете отримувати нагадування?", reply_markup=get_keyboard("Один раз", "Щодня", "Щотижня", "◀️ Назад", placeholder="Виберіть частоту", sizes=(1, 2, 1)))
        await state.set_state(LearningState.choosing_reminder_frequency)
    elif current_state_str == SearchState.waiting_for_search_query.state:
        await state.clear()
        await message.answer("Пошук скасовано.")
        await show_vocabulary_handler(message, state, page=0)
    elif current_state_str == QuizState.choosing_quiz_length.state:
        await state.clear()
        await message.answer("Вибір скасовано. Головне меню:", reply_markup=main_menu())
    elif current_state_str == QuizState.in_quiz.state:
         await state.clear()
         await message.answer("Тест перервано. Головне меню:", reply_markup=main_menu())
    else:
        await state.clear()
        await message.answer("Головне меню:", reply_markup=main_menu())

@user_private_router.message(StateFilter(None))
async def handle_unknown_text(message: types.Message):
    await message.reply("Не розумію вас. Скористайтеся кнопками меню або командами /")