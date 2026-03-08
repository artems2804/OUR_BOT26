from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import asyncio
import aiohttp
from urllib.parse import quote

# Замените на ваш токен
BOT_TOKEN = "8458263203:AAFbvad4bGbz5F7cTMfrMwBj-qqlIOLdg84"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Асинхронный запрос в интернет через Google Custom Search
async def search_web(query: str):
    try:
        # Используем Google Programmable Search Engine (требуется API ключ и Search Engine ID)
        # Замените значения ниже на свои (можно получить в Google Cloud)
        API_KEY = "your_google_api_key"
        SEARCH_ENGINE_ID = "your_search_engine_id"
        
        # Кодируем запрос для URL
        encoded_query = quote(query)
        url = f"https://www.googleapis.com/customsearch/v1?q={encoded_query}&key={API_KEY}&cx={SEARCH_ENGINE_ID}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    items = data.get("items", [])
                    if items:
                        result = items[0]  # Берем первый результат
                        title = result.get("title")
                        link = result.get("link")
                        snippet = result.get("snippet")
                        return f"\n\n📌 <b>{title}</b>\n{snippet}\nПодробнее: <a href=\"{link}\">ссылка</a>"
                    else:
                        return "По вашему запросу ничего не найдено."
                else:
                    return f"Ошибка поиска: {response.status} {response.reason}"
    except Exception as e:
        return f"Не удалось выполнить поиск: {str(e)}"

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет друг! 🎉\nРад тебя видеть в нашем боте.\nЯ умею понимать твои сообщения, отвечать на них и искать информацию в интернете.\n"
        "Просто напиши, что хочешь узнать!"
    )

# Обработчик команды /help
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("Чем могу помочь? Напиши /start, чтобы начать сначала.\nПросто задай вопрос, и я поищу ответ в интернете.")

# Обработчик любого текстового сообщения
@dp.message()
async def echo_message(message: types.Message):
    # Получаем текст сообщения
    text = message.text.lower().strip()

    # Простая логика анализа текста
    if "привет" in text or "здравствуй" in text or "хай" in text:
        response = "Привет! Как дела? 😊\nЗадай мне любой вопрос, и я поищу ответ в интернете!"
    elif "пока" in text or "до свидания" in text or "бай" in text:
        response = "Пока! Хорошего дня! 👋"
    elif "спасибо" in text or "благодарю" in text:
        response = "Пожалуйста! Всегда рад помочь! 💙"
    elif "как дела" in text or "как ты" in text:
        response = "У меня всё отлично, я онлайн и ищу информацию для тебя! А у тебя как дела? 😊"
    elif "что ты умеешь" in text:
        response = (
            "Я умею:\n"
            "• Отвечать на команду /start\n"
            "• Помогать по команде /help\n"
            "• Анализировать твои сообщения\n"
            "• Искать информацию в интернете по твоим запросам\n"
            "Просто напиши, что тебя интересует! 😊"
        )
    else:
        # Отвечаем, что ищем информацию
        await message.answer(f"Ищу в интернете по запросу: <i>{message.text}</i>...", parse_mode="HTML")
        # Выполняем поиск
        result = await search_web(message.text)
        response = f"Вот что я нашёл по запросу <b>\"{message.text}\"</b>:" + result
    
    await message.answer(response, parse_mode="HTML")

# Запуск бота
async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())