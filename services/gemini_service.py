import os
import httpx
import json
from dotenv import load_dotenv, find_dotenv
import traceback # Для відстеження помилок
import re # Для регулярних виразів (використовується у перевірці мови)

# Завантажуємо змінні середовища, щоб отримати ключ API
load_dotenv(find_dotenv())

# ФУНКЦІЯ ПЕРЕКЛАДУ
async def translate_with_example_gemini(text_to_translate: str, user_level: str | None = None) -> str:
    """
    Асинхронно перекладає текст (UA<>EN).
    - Для РЕЧЕНЬ/ФРАЗ надає ТІЛЬКИ переклад.
    - Для СЛІВ/ІДІОМ надає переклад + приклад оригіналу + ПОВНИЙ переклад прикладу,
      адаптований під рівень користувача (якщо вказано).
    Намагається максимально точно дотримуватись інструкцій щодо мови та формату.
    """
    # Отримання ключа API зі змінних середовища
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY не знайдено.")
        return "Помилка конфігурації: API ключ для Google Gemini не знайдено."
    # Визначення моделі та URL API Gemini
    model = "gemini-3.1-flash-lite-preview"
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    prompt = (
        f"Проаналізуй текст: '{text_to_translate}'.\n"
        f"Завдання: Надай переклад та, якщо ТИП ТЕКСТУ = ОДИНИЧНЕ_СЛОВО або ІДІОМА, то також приклад використання.\n"
        f"1. Визнач Мову Оригіналу (МОВ_ОРГ: українська або англійська).\n"
        f"2. Визнач Мову Перекладу (МОВ_ПЕР), протилежну МОВ_ОРГ.\n"
        f"3. Визнач Тип Тексту: ОДИНИЧНЕ_СЛОВО, ІДІОМА чи РЕЧЕННЯ/ФРАЗА. **Це КРИТИЧНО ВАЖЛИВО для формату виводу!** Якщо текст містить більше 4 слів АБО розділові знаки кінця речення (.?!), вважати його РЕЧЕННЯ/ФРАЗА.\n"
        f"4. Перевір, чи текст є ідіомою у МОВ_ОРГ (для Кроку 3 та 5).\n\n"
        f"5. Згенеруй ПЕРЕКЛАД на МОВ_ПЕР:\n"
        f"   - Якщо ІДІОМА (з кроку 4): ОДИН переклад ЗНАЧЕННЯ + '(ідіома)'.\n"
        f"   - Якщо РЕЧЕННЯ/ФРАЗА (з Кроку 3): ОДИН точний переклад.\n"
        f"   - Якщо ОДИНИЧНЕ_СЛОВО (з Кроку 3): 1-3 варіанти перекладу через кому.\n\n"
        f"6. (ТІЛЬКИ ЯКЩО Тип Тексту з Кроку 3 = ОДИНИЧНЕ_СЛОВО або ІДІОМА) Згенеруй ПРИКЛАД ОРИГІНАЛУ:\n"
        f"   - **УВАГА! МОВА ПРИКЛАДУ == МОВА ОРИГІНАЛУ!:** Це речення МАЄ БУТИ НАПИСАНО ВИКЛЮЧНО мовою МОВ_ОРГ (мова тексту '{text_to_translate}'). АБСОЛЮТНО ЗАБОРОНЕНО використовувати слова з МОВ_ПЕР. Перевір мову прикладу перед виводом! Якщо '{text_to_translate}' англійською - приклад має бути ТІЛЬКИ англійською. Якщо '{text_to_translate}' українською - приклад має бути ТІЛЬКИ українською. ЖОДНИХ ЗМІШУВАНЬ!\n"
        f"   - ОДНЕ речення, що використовує ОРИГІНАЛЬНИЙ текст ('{text_to_translate}').\n"
        f"   - **КРИТИЧНА ВИМОГА (РЕГІСТР):** У прикладі використовуй оригінальне слово/фразу ('{text_to_translate}') ТОЧНО в тому ж регістрі, ЯК ВОНО БУЛО НАДАНО КОРИСТУВАЧЕМ. Це стосується КОЖНОГО входження цього слова/фрази в прикладі, НЕЗАЛЕЖНО від його позиції в реченні (крім випадків, коли правила граматики МОВИ ОРИГІНАЛУ вимагають зміни регістру на початку речення). ЗАБОРОНЕНО змінювати регістр слова/фрази без граматичної необхідності мови прикладу.\n"
        f"   - Пріоритет НЕЙТРАЛЬНИМ/БУКВАЛЬНИМ значенням.\n"
        f"   - **АДАПТАЦІЯ РІВНЯ:** Складність речення та лексика прикладу мають ВІДЧУТНО відповідати рівню користувача ({user_level if user_level else 'Не встановлено'}). Наприклад: A1/A2 - прості речення (Present Simple, Past Simple), базова лексика (дім, їжа, кольори); B1/B2 - складніші речення (conditionals, passive voice), ширша лексика (подорожі, робота, емоції); C1/C2 - складні граматичні конструкції, ідіоми, вузькоспеціалізована або абстрактна лексика. Якщо рівень 'Не встановлено', генеруй приклад середньої складності (B1).\n\n"
        f"7. (ТІЛЬКИ ЯКЩО виконано Крок 6 і він був 100% мовою МОВ_ОРГ) Згенеруй ПОВНИЙ ПЕРЕКЛАД ПРИКЛАДУ:\n"
        f"   - Мова: СУВОРО МОВ_ПЕР.\n"
        f"   - Точний і ПОВНИЙ переклад речення з Кроку 6.\n"
        f"   - **КРИТИЧНА ВИМОГА (МОВА):** У цьому перекладі прикладу НЕ ПОВИННО бути ЖОДНОГО слова з мови оригіналу (МОВ_ОРГ). ВСІ слова мають бути перекладені на МОВ_ПЕР. **Змішування мов ЗАБОРОНЕНО!**\n\n"
        f"8. **СТРОГО ВИВЕДИ РЕЗУЛЬТАТ В ОДНОМУ З ДВОХ ФОРМАТІВ НИЖЧЕ, ЗАЛЕЖНО ВІД ТИПУ ТЕКСТУ (Крок 3):**\n"
        f"   **ЗАБОРОНЕНО:** Будь-які інші рядки, пояснення, номери кроків, примітки, порожні рядки між обов'язковими.\n\n"
        f"   **ФОРМАТ 1 (Якщо Тип Тексту = РЕЧЕННЯ/ФРАЗА):**\n"
        f"     📖 Переклад: [Результат Кроку 5]\n"
        f"     **(ТІЛЬКИ ЦЕЙ РЯДОК. ПРИКЛАД НЕ ПОТРІБЕН І НЕ ГЕНЕРУЄТЬСЯ ДЛЯ ЦЬОГО ТИПУ!)**\n\n"
        f"   **ФОРМАТ 2 (Якщо Тип Тексту = ОДИНИЧНЕ_СЛОВО або ІДІОМА):**\n"
        f"     📖 Переклад: [Результат Кроку 5]\n"
        f"     📌 Приклад: [Результат Кроку 6, згенерований СУВОРО мовою МОВ_ОРГ]\n"
        f"     ➡️ [Результат Кроку 7, згенерований СУВОРО мовою МОВ_ПЕР]\n"
        f"     **(ТІЛЬКИ ЦІ ТРИ РЯДКИ. ПЕРЕВІР ЩЕ РАЗ МОВУ КОЖНОГО РЯДКА!)**"
    )
    # Формування тіла запиту до API
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.25, "maxOutputTokens": 450},
        "safetySettings": [
             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
    }
    # Виконання асинхронного запиту до API за допомогою httpx
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            if not data.get("candidates"):
                feedback = data.get("promptFeedback"); block_reason = feedback.get("blockReason") if feedback else None
                print(f"No candidates/Blocked in Gemini translate for input: '{text_to_translate}'. Reason: {block_reason}")
                return f"❌ Запит заблоковано ({block_reason})." if block_reason else "Помилка: Немає кандидатів у відповіді API."
            # Отримання результату та перевірка причини завершення генерації
            candidate = data["candidates"][0]
            finish_reason = candidate.get("finishReason")
            if finish_reason not in ["STOP", None]:
                 print(f"Gemini response finished with unexpected reason '{finish_reason}' for input: '{text_to_translate}'")
            # Перевірка наявності текстового контенту у відповіді
            if not candidate.get("content") or not candidate["content"].get("parts"):
                 print(f"No content/parts in Gemini response for input: '{text_to_translate}'. Data: {data}")
                 return "Помилка: Немає тексту у відповіді API."
            # Об'єднання текстових частин відповіді
            text_result = "".join(part.get("text", "") for part in candidate["content"]["parts"]).strip()
            if not text_result:
                 print(f"Empty text result from Gemini for input: '{text_to_translate}'")
                 return "Помилка: Отримано порожню відповідь від сервісу."
            # Розбір отриманого тексту на рядки для вилучення перекладу та прикладів
            lines = [line.strip() for line in text_result.split('\n') if line.strip()]
            translation_line = next((line for line in lines if line.startswith("📖 Переклад:")), None)
            example_line = next((line for line in lines if line.startswith("📌 Приклад:")), None)
            example_translation_line = next((line for line in lines if line.startswith("➡️ ")), None)
            # Визначення типу вхідного тексту (орієнтовно) для вибору формату відповіді
            is_likely_sentence = len(text_to_translate.split()) > 4 or any(p in text_to_translate for p in '.?!')
            # Повернення результату у відповідному форматі
            if is_likely_sentence: # Якщо це речення/фраза
                if translation_line: return translation_line
                else: print(f"Error: No translation found for likely sentence: '{text_to_translate}'"); return text_result
            else: # Якщо це слово/ідіома
                if translation_line and example_line and example_translation_line: return f"{translation_line}\n{example_line}\n{example_translation_line}"  # Якщо є всі три частини
                elif translation_line: print(f"Warning: Example missing for word/idiom: '{text_to_translate}'. Returning translation only."); return translation_line
                else: print(f"Error: No translation found in the result for word/idiom: '{text_to_translate}'"); return text_result
        # Обробка різних типів помилок при взаємодії з API
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code; error_msg = f"HTTP Status {status_code}"
            try: error_details = e.response.json(); error_msg = error_details.get("error", {}).get("message", error_msg)
            except: pass
            print(f"Gemini API HTTP Error ({status_code}) for '{text_to_translate}': {error_msg}")
            if "API key not valid" in error_msg: return "Помилка API: Неправильний ключ Google Gemini."
            elif "quota" in str(e.response.content).lower() or status_code == 429: return "Помилка API: Перевищено ліміт запитів."
            elif status_code >= 500: return f"Помилка сервера Google Gemini ({status_code})."
            else: return f"Помилка Google Gemini API ({status_code})."
        except httpx.TimeoutException: print(f"Gemini API Timeout for '{text_to_translate}'"); return "Помилка: Час очікування відповіді від Gemini вичерпано."
        except httpx.NetworkError as e: print(f"Gemini API Network Error for '{text_to_translate}': {e}"); return "Помилка мережі. Перевірте з'єднання."
        except httpx.RequestError as e: print(f"Gemini API Request Error for '{text_to_translate}': {e}"); return "Помилка запиту до сервісу перекладу."
        except json.JSONDecodeError as e: print(f"Gemini API JSON Decode Error for '{text_to_translate}': {e}"); return "Помилка: Неправильна відповідь від сервісу перекладу."
        except Exception as e: print(f"Unexpected error in Gemini translation for '{text_to_translate}': {e}\n{traceback.format_exc()}"); return "Сталася неочікувана системна помилка під час перекладу."

# ФУНКЦІЯ ПЕРЕВІРКИ МОВИ
def is_correct_language(text: str, expected_lang: str) -> bool:
    """Базова перевірка, чи текст ймовірно написаний очікуваною мовою."""
    if not text: return False
    cleaned_text = re.sub(r'[\d\s,.!?-]', '', text)
    if not cleaned_text: return True # Якщо тільки символи/цифри, вважаємо, що мова невизначена
    if expected_lang == "українська":
        # Перевіряємо наявність кирилиці та відсутність "заборонених" латинських
        has_cyrillic = bool(re.search(r'[а-яіїєґ]', cleaned_text, re.IGNORECASE))
        has_forbidden_latin = bool(re.search(r'[wqx]', cleaned_text, re.IGNORECASE))
        # Додатково перевіримо кількість інших латинських літер
        other_latin_count = len(re.findall(r'[a-pr-vyz]', cleaned_text, re.IGNORECASE)) # Латиниця крім w, q, x
        # Вважаємо українською, якщо є кирилиця І (немає заборонених латинських АБО інших латинських не більше 2)
        return has_cyrillic and (not has_forbidden_latin or other_latin_count <= 2)

    elif expected_lang == "англійська":
        # Перевіряємо наявність латиниці та відсутність "заборонених" кириличних
        has_latin = bool(re.search(r'[a-z]', cleaned_text, re.IGNORECASE))
        has_forbidden_cyrillic = bool(re.search(r'[іїєґщьюяч]', cleaned_text, re.IGNORECASE)) # Додано більше специфічних
        # Додатково перевіримо кількість інших кириличних літер
        other_cyrillic_count = len(re.findall(r'[абвгджзклмнопрстуфхцш]', cleaned_text, re.IGNORECASE))
        # Вважаємо англійською, якщо є латиниця І (немає заборонених кириличних АБО інших кириличних не більше 2)
        return has_latin and (not has_forbidden_cyrillic or other_cyrillic_count <= 2)

    return True # Якщо інша мова, пропускаємо перевірку

# ФУНКЦІЯ ГЕНЕРАЦІЇ ДИСТРАКТОРІВ
async def generate_distractors_gemini(
    question_word: str,
    correct_option: str,
    distractor_language: str,
    user_level: str | None = None,
    count: int = 3
) -> list[str] | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found for distractor generation.")
        return None

    model = "gemini-1.5-flash-latest"
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    source_language = "англійська" if distractor_language == "українська" else "українська"

    level_prompt_part = ""
    if user_level and user_level != "Не встановлено":
        level_prompt_part = f"- Складність дистракторів має приблизно відповідати рівню {user_level}.\n"
    else:
        level_prompt_part = f"- Дистрактори мають бути середньої складності (рівень B1).\n"

    prompt = (
         f"УВАГА! ЦЕ ЗАВДАННЯ НА ГЕНЕРАЦІЮ ДИСТРАКТОРІВ ДЛЯ МОВНОГО ТЕСТУ. НАЙГОЛОВНІША ВИМОГА - Дотримання мови!\n\n"
         f"ЗАВДАННЯ: Згенеруй РІВНО {count} УНІКАЛЬНИХ, але НЕПРАВИЛЬНИХ варіанти відповіді (дистрактори).\n"
         f"СЛОВО У ПИТАННІ: '{question_word}' (мова: {source_language})\n"
         f"ПРАВИЛЬНА ВІДПОВІДЬ (НЕ ГЕНЕРУВАТИ): '{correct_option}' (мова: {distractor_language})\n\n"
         f"**МЕГА-КРИТИЧНА ВИМОГА (МОВА):** ВСІ ЗГЕНЕРОВАНІ ТОБОЮ ДИСТРАКТОРИ МАЮТЬ БУТИ НАПИСАНІ ВИКЛЮЧНО ОДНІЄЮ МОВОЮ: **{distractor_language.upper()}**. ПОВТОРЮЮ: ТІЛЬКИ **{distractor_language.upper()}** МОВОЮ! ЖОДНИХ СЛІВ, ФРАЗ, ЛІТЕР З МОВИ '{source_language.upper()}' У ВІДПОВІДІ БУТИ НЕ ПОВИННО! ПЕРЕВІР СЕБЕ ПЕРЕД ТИМ, ЯК НАДАТИ ВІДПОВІДЬ!\n\n"
         f"ІНШІ ВИМОГИ:\n"
         f"{level_prompt_part}"
         f"- По можливості, генеруй ОДНОСЛІВНІ дистрактори, якщо правильна відповідь - одне слово.\n"
         f"- Дистрактори мають бути схожими або пов'язаними з правильною відповіддю, але гарантовано неправильними.\n"
         f"- НЕ ПОВИННІ бути однаковими між собою (ігноруй регістр при перевірці унікальності).\n"
         f"- НЕ ПОВИННІ бути '{correct_option}' (ігноруй регістр).\n\n"
         f"**ФОРМАТ ВИВОДУ:** ТІЛЬКИ список дистракторів (РІВНО {count} штук!), мовою **{distractor_language.upper()}**, розділених ';;;'. Без нумерації, пояснень, приміток чи зайвих символів.\n"
         f"ПРИКЛАД ВИВОДУ (якщо мова дистракторів - українська): Перший_укр_дистрактор;;;Другий_укр_дистрактор;;;Третій_укр_дистрактор\n"
         f"ПРИКЛАД ВИВОДУ (якщо мова дистракторів - англійська): First_eng_distractor;;;Second_eng_distractor;;;Third_eng_distractor"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.55, "maxOutputTokens": 150},
        "safetySettings": [
             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
        ]
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(api_url, headers=headers, json=payload)
            if response.status_code != 200:
                try: error_details = response.json(); error_msg = error_details.get("error", {}).get("message", f"HTTP Status {response.status_code}")
                except: error_msg = f"HTTP Status {response.status_code}"
                print(f"Gemini API HTTP Error ({response.status_code}) for distractors (v7): {error_msg}")
                return None

            data = response.json()

            if not data.get("candidates"):
                feedback = data.get("promptFeedback"); block_reason = feedback.get("blockReason") if feedback else None
                print(f"No candidates/Blocked in Gemini distractors (v7). Reason: {block_reason}")
                return None
            candidate = data["candidates"][0]
            finish_reason = candidate.get("finishReason")
            if finish_reason not in ["STOP", None]:
                print(f"Gemini response finished with reason '{finish_reason}' for distractors (v7). Content: {candidate.get('content')}")
                return None
            if not candidate.get("content") or not candidate["content"].get("parts"):
                print(f"No content/parts in Gemini distractor response (v7). Data: {data}")
                return None

            text_result = "".join(part.get("text", "") for part in candidate["content"]["parts"]).strip()
            raw_distractors = [d.strip() for d in text_result.split(';;;') if d.strip()]
            print(f"RAW Distractors from Gemini (v7) for '{correct_option}' ({distractor_language}): {raw_distractors}")

            # ПОСТ-ОБРОБКА ТА СУВОРА ПЕРЕВІРКА МОВИ
            valid_distractors = []
            unique_distractors_lower = set()
            correct_lower = correct_option.lower()
            all_correct_language = True

            for d in raw_distractors:
                if len(valid_distractors) >= count:
                    break

                # Сувора перевірка мови
                if not is_correct_language(d, distractor_language):
                    print(f"LANG CHECK FAILED for distractor: '{d}'. Expected: {distractor_language}")
                    all_correct_language = False
                    break # Якщо хоч один дистрактор неправильною мовою, відкидаємо всю відповідь Gemini

                d_lower = d.lower()
                if d_lower != correct_lower and d_lower not in unique_distractors_lower:
                    valid_distractors.append(d)
                    unique_distractors_lower.add(d_lower)

            # Повертаємо результат ТІЛЬКИ якщо ВСІ дистрактори були правильної мови
            # І якщо їх кількість рівно `count`
            if all_correct_language and len(valid_distractors) == count:
                print(f"Returning {count} LANGUAGE-VALIDATED distractors from Gemini (v7): {valid_distractors}")
                return valid_distractors
            else:
                 if not all_correct_language:
                     print(f"Warning: Gemini response contained distractors in the wrong language for '{correct_option}'. Using fallback.")
                 else: # Кількість неправильна
                     print(f"Warning: Gemini returned {len(valid_distractors)} unique/valid distractors (v7), needed {count}. Using fallback.")
                 return None

        except httpx.TimeoutException:
             print(f"Gemini API Timeout for distractors (v7)")
             return None
        except httpx.RequestError as e:
            print(f"Gemini API Request Error for distractors (v7): {e}")
            return None
        except Exception as e:
            print(f"Error in Gemini distractor generation (v7) for: '{question_word}' -> '{correct_option}': {e}\n{traceback.format_exc()}")
            return None