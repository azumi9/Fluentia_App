from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic import BaseModel
import uvicorn
import sqlite3
import os
import json
import urllib.request
import random
import re
import httpx


from common.db import init_db, save_user, get_user_vocabulary, delete_word_from_vocabulary
from services.gemini_service import translate_with_example_gemini, generate_distractors_gemini

init_db()

app = FastAPI(title="Fluentia Web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UserData(BaseModel):
    user_id: int
    name: str
    age: int
    level: str


class RoleplayRequest(BaseModel):
    user_id: int
    scenario: str
    text: str
    level: str


class FeedbackRequest(BaseModel):
    user_id: int
    scenario: str


class TranslateRequest(BaseModel):
    user_id: int
    text: str
    level: str = "B1"

class QuizRequest(BaseModel):
        user_id: int
        exclude_ids: list[int] = []


class SaveWordRequest(BaseModel):
    user_id: int
    original: str
    translation: str


@app.post("/api/onboarding")
async def onboarding(user: UserData):
    save_user(user.user_id, user.name, user.age, user.level)
    return {"status": "success"}


@app.post("/api/translate")
async def translate_text(request: TranslateRequest):
    try:
        result = await translate_with_example_gemini(
            text_to_translate=request.text,
            user_level=request.level
        )
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/save_word")
async def save_word(req: SaveWordRequest):
    try:
        db_path = os.path.join(os.getcwd(), "db.sqlite3")
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (req.user_id,))
            cursor.execute("SELECT id FROM vocabulary WHERE user_id = ? AND original_text = ?",
                           (req.user_id, req.original.strip()))
            if cursor.fetchone():
                return {"status": "error"}
            cursor.execute(
                "INSERT INTO vocabulary (user_id, original_text, translation) VALUES (?, ?, ?)",
                (req.user_id, req.original.strip(), req.translation.strip())
            )
            conn.commit()
            return {"status": "success"}
    except Exception as e:
        print(f"Помилка БД: {e}")
        return {"status": "error"}


@app.get("/api/dictionary/{user_id}")
async def get_dict(user_id: int):
    try:
        words = get_user_vocabulary(user_id, 100, 0)
        # Додаємо "id": w[0] у відповідь, щоб фронтенд міг його використовувати
        data = [{"id": w[0], "original": w[1], "translation": w[2]} for w in words]
        return {"status": "success", "words": data}
    except Exception as e:
        return {"status": "error"}

@app.delete("/api/dictionary/{user_id}/{word_id}")
async def delete_word(user_id: int, word_id: int):
    try:
        success = delete_word_from_vocabulary(user_id, word_id)
        if success:
            return {"status": "success"}
        else:
            return {"status": "error", "message": "Слово не знайдено"}
    except Exception as e:
        print(f"Помилка видалення слова: {e}")
        return {"status": "error"}

@app.post("/api/roleplay")
async def roleplay(req: RoleplayRequest):
    db_path = os.path.join(os.getcwd(), "db.sqlite3")

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO roleplay_history (user_id, scenario, role, content) VALUES (?, ?, ?, ?)",
                       (req.user_id, req.scenario, "user", req.text))
        cursor.execute("SELECT role, content FROM roleplay_history WHERE user_id = ? AND scenario = ? ORDER BY id ASC",
                       (req.user_id, req.scenario))
        history = cursor.fetchall()

    api_key = os.getenv("GEMINI_API_KEY")

    # Повертаємо актуальну модель, як ти і казав!
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={api_key}"

    prompts = {
        "cafe": f"Act as a waiter in a cafe. The user has {req.level} English.",
        "school": f"Act as a new classmate at school. The user is a student with {req.level} English.",
        "city": f"Act as a local on the street. The user is a tourist with {req.level} English."
    }

    system_instruction = f"""{prompts.get(req.scenario, "Answer naturally in English.")}
УВАГА: Ти — вчитель англійської для дітей. 
1. Твій пріоритет — навчання та підтримка.
2. Якщо учень помилився, дай пораду УКРАЇНСЬКОЮ МОВОЮ.
3. ЗАБОРОНЕНО використовувати зірочки (*), решітки (#) та Markdown.
4. Якщо все вірно, напиши "Perfect!".
5. Якщо учень пише коротко (наприклад "Ok"), ПРИЙМИ ЦЕ.
Дотримуйся формату:
FEEDBACK: [Твоя порада УКРАЇНСЬКОЮ]
REPLY: [Твоя відповідь у ролі АНГЛІЙСЬКОЮ]
"""

    contents = []
    for i, (role, content) in enumerate(history):
        text_content = content
        if i == 0 and role == "user":
            text_content = f"--- INSTRUCTIONS FOR AI ---\n{system_instruction}\n--- END INSTRUCTIONS ---\n\nUSER SAYS: {content}"

        contents.append({
            "role": "user" if role == "user" else "model",
            "parts": [{"text": text_content}]
        })

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.7}
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers={'Content-Type': 'application/json'}, json=payload)
            response.raise_for_status()
            data = response.json()
            reply_text = data['candidates'][0]['content']['parts'][0]['text']

            if "REPLY:" in reply_text:
                clean_reply = reply_text.split("REPLY:")[-1].strip()
            else:
                clean_reply = reply_text.strip()

            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO roleplay_history (user_id, scenario, role, content) VALUES (?, ?, ?, ?)",
                               (req.user_id, req.scenario, "model", clean_reply))
                conn.commit()

            return {"status": "success", "result": reply_text}

        except httpx.HTTPStatusError as e:
            error_msg = e.response.text
            print(f"❌ Помилка API (Roleplay): HTTP {e.response.status_code} - {error_msg}")
            return {"status": "error"}
        except Exception as e:
            print(f"❌ Критична помилка (Roleplay): {e}")
            return {"status": "error"}


@app.post("/api/roleplay_feedback")
async def roleplay_feedback(req: FeedbackRequest):
    db_path = os.path.join(os.getcwd(), "db.sqlite3")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role, content FROM roleplay_history WHERE user_id = ? AND scenario = ? ORDER BY id ASC",
                       (req.user_id, req.scenario))
        history = cursor.fetchall()

    if not history:
        return {"status": "error", "message": "Немає історії."}

    dialog_text = ""
    for role, content in history:
        dialog_text += f"{'User' if role == 'user' else 'AI'}: {content}\n"

    api_key = os.getenv("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={api_key}"

    prompt = f"""Аналізуй цей діалог:
{dialog_text}

Твоє завдання: Надай коротке, підтримуюче резюме успіхів учня УКРАЇНСЬКОЮ МОВОЮ.
ВАЖЛИВІ ПРАВИЛА:
1. ЖОДНИХ ЗІРОЧОК (*), РЕШІТОК (#) ЧИ ІНШИХ СИМВОЛІВ РОЗМІТКИ.
2. Розбий текст на прості абзаци.
3. Розкажи, що було добре, вкажи на помилки та дай поради.
"""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers={'Content-Type': 'application/json'}, json=payload)
            response.raise_for_status()
            data = response.json()
            feedback_text = data['candidates'][0]['content']['parts'][0]['text']
            return {"status": "success", "result": feedback_text}

        except httpx.HTTPStatusError as e:
            error_msg = e.response.text
            print(f"❌ Помилка API (Feedback): HTTP {e.response.status_code} - {error_msg}")
            return {"status": "error"}
        except Exception as e:
            print(f"❌ Критична помилка (Feedback): {e}")
            return {"status": "error"}

@app.post("/api/quiz")
async def get_quiz(req: QuizRequest):
    words = get_user_vocabulary(req.user_id, 500, 0)
    if len(words) < 4:
        return {"status": "error", "message": "Додайте мінімум 4 слова до словника."}

    # Фільтруємо слова, щоб не було повторів
    available_words = [w for w in words if w[0] not in req.exclude_ids]
    if not available_words:
        return {"status": "error", "message": "Слова у словнику закінчилися! Тест завершено."}

    target_word = random.choice(available_words)
    word_id = target_word[0]
    original = target_word[1]
    correct_translation = target_word[2]

    # Визначаємо мову ПРАВИЛЬНОЇ відповіді
    is_ukrainian = bool(re.search(r'[а-яіїєґ]', correct_translation, re.IGNORECASE))
    distractor_lang = "українська" if is_ukrainian else "англійська"

    # Просимо Gemini згенерувати варіанти ТІЄЮ Ж мовою
    distractors = await generate_distractors_gemini(original, correct_translation, distractor_lang, "B1", 3)

    if not distractors:
        # Надійний Fallback, якщо API підведе
        other_words = [w[2] for w in words if w[0] != word_id]

        # Намагаємося підібрати запасні варіанти правильної мови
        valid_fallback = []
        for w in other_words:
            w_is_ukr = bool(re.search(r'[а-яіїєґ]', w, re.IGNORECASE))
            if (is_ukrainian and w_is_ukr) or (not is_ukrainian and not w_is_ukr):
                valid_fallback.append(w)

        if len(valid_fallback) >= 3:
            distractors = random.sample(valid_fallback, 3)
        else:
            distractors = random.sample(other_words, min(3, len(other_words)))

    options = distractors + [correct_translation]
    random.shuffle(options)

    return {
        "status": "success",
        "word_id": word_id,  # Віддаємо ID слова, щоб фронтенд його запам'ятав
        "question": original,
        "options": options,
        "correct": correct_translation
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
