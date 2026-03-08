import asyncio
import json
import os
import html
import base64
import aiohttp
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8458263203:AAFbvad4bGbz5F7cTMfrMwBj-qqlIOLdg84"
GIGACHAT_CREDENTIALS = "MDE5Y2NkNDAtMDhmYS03OWUyLThkZDctYjRjZjNmN2Y4ZjMzOjRlMTM4YTQyLTIwN2EtNDQ1MS04MjkzLWNhOWI1Y2UwZmQ3OA=="

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ================== FSM СОСТОЯНИЯ ==================
class Profile(StatesGroup):
    waiting_for_class = State()
    waiting_for_subject = State()
    waiting_for_mode = State()

class Solving(StatesGroup):
    waiting_for_task = State()          # Ожидаем задачу
    step_by_step = State()               # Пошаговый режим (храним задачу и текущий шаг)
    waiting_for_choice = State()         # После подсказки ждём выбора (след шаг / ответ)

# ================== РАБОТА С JSON ==================
DATA_FILE = "users_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ================== GIGACHAT ==================
_giga_token = None
_token_expires_at = None

async def get_gigachat_token() -> str:
    global _giga_token, _token_expires_at
    if _giga_token and _token_expires_at and datetime.now(timezone.utc) < _token_expires_at:
        print("✅ Токен GigaChat взят из кэша")
        return _giga_token

    print("🔄 Запрашиваю новый токен GigaChat...")
    try:
        decoded = base64.b64decode(GIGACHAT_CREDENTIALS).decode("utf-8")
        client_id, client_secret = decoded.split(":", 1)
    except Exception as e:
        print(f"❌ Не удалось декодировать credentials: {e}")
        raise Exception(f"Не удалось декодировать credentials: {e}")

    auth_str = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Authorization": f"Basic {auth_str}",
        "RqUID": client_id,
    }
    data = {"scope": "GIGACHAT_API_PERS"}

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(url, headers=headers, data=data) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"❌ Ошибка получения токена: {resp.status} - {text}")
                raise Exception(f"Ошибка получения токена: {resp.status} - {text}")
            json_resp = await resp.json()
            print(f"📦 Ответ от OAuth: {json_resp}")  # отладка

    _giga_token = json_resp["access_token"]

    # Определяем expires_at
    if "expires_at" in json_resp:
        expires_at_val = json_resp["expires_at"]
        try:
            if isinstance(expires_at_val, (int, float)):
                # Если число, это может быть timestamp в секундах или миллисекундах
                # Проверим порядок: если число > 1e10, вероятно миллисекунды
                if expires_at_val > 1e10:
                    # миллисекунды -> секунды
                    expires_at_val = expires_at_val / 1000.0
                _token_expires_at = datetime.fromtimestamp(expires_at_val, tz=timezone.utc)
                print(f"✅ Токен истекает (timestamp): {_token_expires_at}")
            else:
                # Строка ISO
                expires_at_str = expires_at_val.replace('Z', '+00:00')
                _token_expires_at = datetime.fromisoformat(expires_at_str)
                print(f"✅ Токен истекает (ISO): {_token_expires_at}")
        except Exception as e:
            print(f"⚠️ Не удалось распарсить expires_at ({expires_at_val}), ошибка: {e}, установлен запас 30 мин")
            _token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=1800)
    elif "expires_in" in json_resp:
        expires_in = int(json_resp["expires_in"])
        _token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        print(f"✅ Токен истекает через {expires_in} сек")
    else:
        _token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=1800)
        print("✅ Токен истекает через 1800 сек (по умолчанию)")

    return _giga_token

async def query_gigachat(prompt: str, system_prompt: str = None) -> str:
    """Отправляет запрос в GigaChat. Можно передать system_prompt для настройки режима."""
    try:
        token = await get_gigachat_token()
        print(f"✅ Токен GigaChat получен, отправляю запрос...")
    except Exception as e:
        print(f"❌ Ошибка авторизации GigaChat: {e}")
        return f"❌ Ошибка авторизации GigaChat: {str(e)}"

    if system_prompt is None:
        system_prompt = "Ты полезный помощник-учитель. Отвечай кратко и по делу."

    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "model": "GigaChat:latest",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 500,
    }

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            print(f"📤 Отправка запроса к GigaChat: {prompt[:50]}...")
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"❌ Ошибка GigaChat: {resp.status} - {text}")
                    return f"❌ Ошибка GigaChat: {resp.status} - {text}"
                data = await resp.json()
                try:
                    answer = data["choices"][0]["message"]["content"].strip()
                    print(f"✅ Получен ответ от GigaChat: {answer[:50]}...")
                    return answer
                except (KeyError, IndexError) as e:
                    print(f"❌ Неожиданный формат ответа: {e}, полный ответ: {data}")
                    return f"❌ Неожиданный формат ответа: {e}"
        except Exception as e:
            print(f"❌ Исключение при запросе к GigaChat: {e}")
            return f"❌ Ошибка соединения: {str(e)}"

# ================== РЕЖИМЫ ОБЪЯСНЕНИЯ ==================
def get_system_prompt(mode: str) -> str:
    prompts = {
        "simple": "Ты учитель, объясняющий очень простым языком, как другу. Избегай сложных терминов, используй примеры из жизни. Отвечай кратко.",
        "standard": "Ты учитель, объясняющий понятно, но достаточно подробно. Используй примеры.",
        "detailed": "Ты учитель, объясняющий очень подробно, как опытный педагог. Разжёвывай каждый шаг, приводи аналогии.",
        "hints": "Ты наставник, который не даёт готовых ответов, а только подсказывает. Если просят решение — дай только намёк, направляй. Не пиши полный ответ, пока явно не попросят."
    }
    return prompts.get(mode, prompts["standard"])

# ================== КЛАВИАТУРЫ ==================
def main_menu_keyboard():
    kb = [
        [KeyboardButton(text="📚 Задать вопрос / задачу")],
        [KeyboardButton(text="📊 Мои слабые темы")],
        [KeyboardButton(text="⚙️ Выбрать режим объяснения")],
        [KeyboardButton(text="❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def mode_selection_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 Очень просто", callback_data="mode_simple")
    builder.button(text="🟡 Стандарт", callback_data="mode_standard")
    builder.button(text="🔵 Подробно как учитель", callback_data="mode_detailed")
    builder.button(text="🔴 Только подсказки", callback_data="mode_hints")
    builder.adjust(1)
    return builder.as_markup()

def step_choice_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Следующий шаг", callback_data="step_next")
    builder.button(text="🔓 Показать полный ответ", callback_data="step_full")
    builder.button(text="🔄 Другая задача", callback_data="step_new")
    builder.adjust(1)
    return builder.as_markup()

# ================== ПОЛУЧЕНИЕ/ОБНОВЛЕНИЕ ДАННЫХ ПОЛЬЗОВАТЕЛЯ ==================
def get_user_data(user_id: int):
    data = load_data()
    return data.get(str(user_id), {})

def update_user_data(user_id: int, **kwargs):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    data[uid].update(kwargs)
    save_data(data)
    print(f"💾 Данные пользователя {user_id} обновлены: {kwargs}")

def update_topic_stats(user_id: int, topic: str, errors: int = 0, time_spent: int = 0):
    """Обновляет статистику по теме."""
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    if "topics" not in data[uid]:
        data[uid]["topics"] = {}
    if topic not in data[uid]["topics"]:
        data[uid]["topics"][topic] = {"errors": 0, "time": 0, "difficult": 0}
    data[uid]["topics"][topic]["errors"] += errors
    data[uid]["topics"][topic]["time"] += time_spent
    if data[uid]["topics"][topic]["errors"] >= 2:
        data[uid]["topics"][topic]["difficult"] = 1
    save_data(data)
    print(f"📊 Статистика по теме '{topic}' обновлена для {user_id}")

# ================== ОБРАБОТЧИКИ КОМАНД ==================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    print(f"📩 /start от {message.from_user.id}")
    await message.answer(
        "👋 Привет! Я твой персональный бот-учитель.\n"
        "Давай настроим профиль, чтобы я мог помогать эффективнее.\n\n"
        "📌 Введи свой класс (например: 7, 8, 9):"
    )
    await state.set_state(Profile.waiting_for_class)

@dp.message(Profile.waiting_for_class)
async def process_class(message: types.Message, state: FSMContext):
    class_num = message.text.strip()
    await state.update_data(class_num=class_num)
    print(f"📚 Класс: {class_num}")
    await message.answer("📚 Теперь напиши предмет (например: математика, физика, русский):")
    await state.set_state(Profile.waiting_for_subject)

@dp.message(Profile.waiting_for_subject)
async def process_subject(message: types.Message, state: FSMContext):
    subject = message.text.strip()
    await state.update_data(subject=subject)
    print(f"📚 Предмет: {subject}")
    await message.answer(
        "⚙️ Выбери режим объяснения (по умолчанию Стандарт):",
        reply_markup=mode_selection_keyboard()
    )
    await state.set_state(Profile.waiting_for_mode)

@dp.callback_query(StateFilter(Profile.waiting_for_mode))
async def process_mode(callback: types.CallbackQuery, state: FSMContext):
    mode_map = {
        "mode_simple": "simple",
        "mode_standard": "standard",
        "mode_detailed": "detailed",
        "mode_hints": "hints"
    }
    mode = mode_map.get(callback.data, "standard")
    data = await state.get_data()
    user_id = callback.from_user.id

    update_user_data(
        user_id,
        class_num=data.get("class_num"),
        subject=data.get("subject"),
        explain_mode=mode
    )

    await callback.answer()
    await callback.message.delete()

    await callback.message.answer(
        f"✅ Профиль настроен!\n"
        f"Класс: {data.get('class_num')}\n"
        f"Предмет: {data.get('subject')}\n"
        f"Режим: {mode}\n\n"
        f"Теперь ты можешь задавать вопросы или задачи.",
        reply_markup=main_menu_keyboard()
    )
    print(f"✅ Профиль {user_id} завершён")
    await state.clear()

# ================== ГЛАВНОЕ МЕНЮ ==================
@dp.message(lambda msg: msg.text == "📚 Задать вопрос / задачу")
async def ask_task(message: types.Message, state: FSMContext):
    print(f"📚 Кнопка 'Задать вопрос' от {message.from_user.id}")
    await message.answer("✍️ Напиши свой вопрос или задачу, и я помогу.")
    await state.set_state(Solving.waiting_for_task)

@dp.message(lambda msg: msg.text == "📊 Мои слабые темы")
async def show_weak_topics(message: types.Message):
    print(f"📊 Запрос слабых тем от {message.from_user.id}")
    user_id = message.from_user.id
    data = get_user_data(user_id)
    topics = data.get("topics", {})
    if not topics:
        await message.answer("Пока нет статистики. Решай задачи, и я начну отслеживать сложные темы.")
        return
    text = "📉 *Твои слабые темы:*\n"
    for topic, stats in topics.items():
        if stats.get("difficult") or stats.get("errors", 0) > 0:
            text += f"\n🔸 *{topic}* — ошибок: {stats['errors']}, время: {stats['time']} мин"
    text += "\n\nРекомендую повторить эти темы."
    await message.answer(text, parse_mode="Markdown")

@dp.message(lambda msg: msg.text == "⚙️ Выбрать режим объяснения")
async def change_mode(message: types.Message):
    print(f"⚙️ Запрос смены режима от {message.from_user.id}")
    await message.answer("Выбери новый режим объяснения:", reply_markup=mode_selection_keyboard())

@dp.callback_query(lambda c: c.data.startswith("mode_"))
async def set_mode_callback(callback: types.CallbackQuery):
    mode_map = {
        "mode_simple": "simple",
        "mode_standard": "standard",
        "mode_detailed": "detailed",
        "mode_hints": "hints"
    }
    mode = mode_map.get(callback.data, "standard")
    user_id = callback.from_user.id
    update_user_data(user_id, explain_mode=mode)
    await callback.answer()
    await callback.message.edit_text(f"✅ Режим объяснения изменён на *{mode}*", parse_mode="Markdown")
    print(f"⚙️ Режим для {user_id} изменён на {mode}")

@dp.message(lambda msg: msg.text == "❓ Помощь")
async def help_command(message: types.Message):
    print(f"❓ Помощь для {message.from_user.id}")
    await message.answer(
        "Я бот-учитель. Что я умею:\n"
        "• Отвечать на вопросы / решать задачи с учётом твоего уровня.\n"
        "• Работать в разных режимах объяснения (просто, подробно, подсказки).\n"
        "• Помогать по шагам, чтобы ты сам пришёл к решению.\n"
        "• Отслеживать твои слабые темы и предлагать повторение.\n\n"
        "Используй кнопки меню для навигации."
    )

# ================== УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ==================
@dp.message()
async def handle_all_text(message: types.Message, state: FSMContext):
    print(f"📩 Универсальный обработчик: {message.text[:50]} от {message.from_user.id}")
    # Проверяем, не находится ли пользователь в каком-либо состоянии
    current_state = await state.get_state()
    if current_state is not None:
        print(f"⚠️ Состояние активно: {current_state}, игнорируем (должен быть другой обработчик)")
        return

    user_id = message.from_user.id
    user_data = get_user_data(user_id)

    # Если профиль не настроен (нет класса или предмета), просим выполнить /start
    if not user_data.get("class_num") or not user_data.get("subject"):
        print(f"👤 Пользователь {user_id} без профиля")
        await message.answer(
            "👋 Привет! Похоже, ты ещё не настроил профиль.\n"
            "Введи /start, чтобы начать."
        )
        return

    # Если профиль есть, считаем, что пользователь хочет задать вопрос
    print(f"👤 Пользователь {user_id} с профилем, переводим в режим задачи")
    await state.set_state(Solving.waiting_for_task)
    # И сразу обрабатываем это сообщение как задачу
    await process_task(message, state)

# ================== ОБРАБОТКА ЗАДАЧ (ОСНОВНАЯ) ==================
@dp.message(Solving.waiting_for_task)
async def process_task(message: types.Message, state: FSMContext):
    task_text = message.text
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    mode = user_data.get("explain_mode", "standard")
    system_prompt = get_system_prompt(mode)

    print(f"📥 Задача от {user_id}: {task_text[:50]}... (режим: {mode})")

    # Сразу отвечаем, что думаем
    await message.answer("⏳ Думаю над ответом...")

    # Сохраняем задачу в историю
    if "history" not in user_data:
        user_data["history"] = []
    user_data["history"].append(task_text)
    update_user_data(user_id, history=user_data["history"][-5:])  # храним последние 5

    # Если режим "подсказки" - сразу переходим в пошаговый режим
    if mode == "hints":
        await state.update_data(task=task_text, step=1, full_answer=None)
        # Запрашиваем у GigaChat подсказку (первый шаг)
        prompt = f"Задача: {task_text}\nДай только одну небольшую подсказку, не раскрывая полное решение. Начни с 'Подсказка:'."
        hint = await query_gigachat(prompt, system_prompt)
        escaped = html.escape(hint)
        await message.answer(
            f"🧩 *Подсказка:*\n{escaped}\n\nВыбери действие:",
            reply_markup=step_choice_keyboard(),
            parse_mode="HTML"
        )
        await state.set_state(Solving.step_by_step)
    else:
        # Обычный режим: сразу полный ответ
        answer = await query_gigachat(task_text, system_prompt)
        escaped = html.escape(answer)
        await message.answer(
            f"📝 *Ответ:*\n{escaped}",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )
        # Здесь можно добавить запрос на оценку сложности и обновление статистики
        await state.clear()

# ================== ПОШАГОВЫЙ РЕЖИМ (ТОЛЬКО ПОДСКАЗКИ) ==================
@dp.callback_query(Solving.step_by_step)
async def step_handler(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    task = data.get("task")
    step = data.get("step", 1)
    user_id = callback.from_user.id
    user_data = get_user_data(user_id)
    mode = user_data.get("explain_mode", "standard")
    system_prompt = get_system_prompt(mode)

    if callback.data == "step_next":
        step += 1
        # Запрашиваем следующий шаг решения
        prompt = f"Задача: {task}\nДай следующий шаг решения (шаг {step}). Не раскрывай сразу всё решение, только очередную часть."
        next_step = await query_gigachat(prompt, system_prompt)
        escaped = html.escape(next_step)
        await callback.message.edit_text(
            f"🔹 *Шаг {step}:*\n{escaped}\n\nВыбери действие:",
            reply_markup=step_choice_keyboard(),
            parse_mode="HTML"
        )
        await state.update_data(step=step)
    elif callback.data == "step_full":
        # Пользователь запросил полный ответ
        prompt = f"Задача: {task}\nНапиши полное решение."
        full = await query_gigachat(prompt, system_prompt)
        escaped = html.escape(full)
        await callback.message.edit_text(
            f"🔓 *Полное решение:*\n{escaped}",
            parse_mode="HTML"
        )
        await state.clear()
        await callback.message.answer("Что делаем дальше?", reply_markup=main_menu_keyboard())
    elif callback.data == "step_new":
        await state.clear()
        await callback.message.answer("Хорошо, давай новую задачу. Напиши её.", reply_markup=main_menu_keyboard())
        await state.set_state(Solving.waiting_for_task)

    await callback.answer()

# ================== ЗАПУСК ==================
async def main():
    print("🚀 Бот-учитель с GigaChat запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())    
