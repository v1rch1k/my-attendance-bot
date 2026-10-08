import logging
import asyncio
from datetime import datetime, timedelta, timezone
import csv
import os

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command

# Новая часть для работы на бесплатном тарифе Render:
from aiohttp import web
async def handle(request):
    return web.Response(text="Bot is running!")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CSV_FILE = "attendance.csv"

# Настройка таймзоны Владивостока (UTC+10)
VLADIVOSTOK_TZ = timezone(timedelta(hours=10))

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Дата", "Время", "ID", "Юзернейм", "Имя", "Подгруппа", "Номер пары"])

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_current_pair_text():
    now_vlad = datetime.now(VLADIVOSTOK_TZ)
    current_time = now_vlad.time()
    
    def time_in_range(start_str, end_str):
        start = datetime.strptime(start_str, "%H:%M").time()
        end = datetime.strptime(end_str, "%H:%M").time()
        return start <= current_time <= end

    if time_in_range("08:30", "10:00"):
        return "1 пара"
    elif time_in_range("10:10", "11:40"):
        return "2 пара"
    elif time_in_range("11:50", "13:20"):
        return "3 пара"
    elif time_in_range("13:30", "15:00"):
        return "4 пара"
    elif time_in_range("15:10", "16:40"):
        return "5 пара"
    elif time_in_range("16:50", "18:20"):
        return "6 пара"
    elif time_in_range("18:30", "20:00"):
        return "7 пара"
    else:
        return f"Перемена ({now_vlad.strftime('%H:%M')})"

def get_group_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 подгруппа 👥", callback_data="group_1")],
        [InlineKeyboardButton(text="2 подгруппа 👥", callback_data="group_2")]
    ])

@dp.message(Command("start"))
async def cmd_start(message: Message):
    pair_status = get_current_pair_text()
    await message.answer(
        text=f"Привет, {message.from_user.full_name}!\n"
             f"🏫 Текущий слот: **{pair_status}**\n\n"
             f"Выбери свою подгруппу для отметки присутствия:",
        reply_markup=get_group_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(Command("report"))
async def cmd_report(message: Message):
    if os.path.exists(CSV_FILE):
        document = FSInputFile(CSV_FILE)
        await message.answer_document(document, caption="📊 Актуальный журнал посещаемости группы")
    else:
        await message.answer("Файл отметок еще не создан. Никто не отмечался.")

@dp.callback_query(F.data.startswith("group_"))
async def process_group(callback: CallbackQuery):
    group_num = callback.data.split("_")[1] 
    pair_status = get_current_pair_text()
    
    now_vlad = datetime.now(VLADIVOSTOK_TZ)
    date_str = now_vlad.strftime("%Y-%m-%d")
    time_str = now_vlad.strftime("%H:%M:%S")
    
    user_id = callback.from_user.id
    username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"
    full_name = callback.from_user.full_name

    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([date_str, time_str, user_id, username, full_name, f"Подгруппа {group_num}", pair_status])

    await callback.message.edit_text(
        text=f"✅ **Присутствие успешно отмечено!**\n\n"
             f"📅 **Дата/Время:** {date_str} {time_str} (ВЛВ)\n"
             f"👥 **Подгруппа:** {group_num}\n"
             f"📖 **Пара:** {pair_status}\n"
             f"👤 **Студент:** {full_name}",
        parse_mode="Markdown"
    )

async def main():
    # Запуск параллельного веб-сервера для заглушки Render
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    # Запускаем сайт в фоне и стартуем бота
    asyncio.create_task(site.start())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
