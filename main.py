import logging
import asyncio
from datetime import datetime, timedelta, timezone
import csv
import os

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

# Фоновый веб-сервер для заглушки бесплатного тарифа Render
async def handle(request):
    return web.Response(text="Bot is running!")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CSV_ATTENDANCE = "attendance.csv"
CSV_STUDENTS = "students.csv"  # База данных с реальными именами студентов

# Настройка таймзоны Владивостока (UTC+10) для ДВФУ
VLADIVOSTOK_TZ = timezone(offset=timedelta(hours=10))

# Инициализация файлов таблиц
if not os.path.exists(CSV_ATTENDANCE):
    with open(CSV_ATTENDANCE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Дата", "Время", "Telegram ID", "Юзернейм", "Никнейм в TG", "Реальные ФИО", "Подгруппа", "Номер пары"])

if not os.path.exists(CSV_STUDENTS):
    with open(CSV_STUDENTS, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Telegram ID", "Реальные ФИО"])

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния для регистрации ФИО
class Registration(StatesGroup):
    waiting_for_fio = State()

# Функция получения реального ФИО по Telegram ID
def get_student_fio(user_id):
    if not os.path.exists(CSV_STUDENTS):
        return None
    with open(CSV_STUDENTS, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)  # Пропускаем заголовок
        for row in reader:
            if row and int(row[0]) == user_id:
                return row[1]
    return None

# Определение текущей пары ДВФУ
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

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    saved_fio = get_student_fio(user_id)
    
    # Если студент зашел впервые и его нет в базе — отправляем на регистрацию ФИО
    if not saved_fio:
        await message.answer(
            "👋 Привет! Перед тем как отмечаться на парах, давай зарегистрируемся.\n\n"
            "Пожалуйста, **введи свои реальные Фамилию и Имя** (например: *Иванов Иван*).\n"
            "Это нужно, чтобы староста видел тебя в официальном списке группы."
        )
        await state.set_state(Registration.waiting_for_fio)
        return

    pair_status = get_current_pair_text()
    await message.answer(
        text=f"Привет, {saved_fio}!\n"
             f"🏫 Текущий слот: {pair_status}\n\n"
             f"Выбери свою подгруппу для отметки присутствия:",
        reply_markup=get_group_keyboard()
    )

# Хендлер для сохранения ФИО
@dp.message(Registration.waiting_for_fio)
async def process_fio(message: Message, state: FSMContext):
    fio = message.text.strip()
    
    if len(fio) < 3 or " " not in fio:
        await message.answer("❌ Пожалуйста, введи корректные Фамилию и Имя через пробел.")
        return

    user_id = message.from_user.id
    
    # Сохраняем студента в базу данных
    with open(CSV_STUDENTS, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([user_id, fio])
        
    await state.clear()  # Выходим из режима регистрации
    
    pair_status = get_current_pair_text()
    await message.answer(
        text=f"🎉 Регистрация успешна! Бот запомнил тебя как: **{fio}**\n\n"
             f"🏫 Текущий слот: {pair_status}\n"
             f"Теперь ты можешь выбрать подгруппу и отметиться:",
        reply_markup=get_group_keyboard()
    )

# Команда /report для старосты
@dp.message(Command("report"))
async def cmd_report(message: Message):
    if os.path.exists(CSV_ATTENDANCE):
        document = FSInputFile(CSV_ATTENDANCE)
        await message.answer_document(document, caption="📊 Журнал посещаемости с реальными ФИО")
    else:
        await message.answer("Журнал пуст. Никто еще не отмечался.")

# Обработка клика по подгруппе
@dp.callback_query(F.data.startswith("group_"))
async def process_group(callback: CallbackQuery):
    user_id = callback.from_user.id
    saved_fio = get_student_fio(user_id)
    
    # Защитная проверка: если каким-то чудом кнопка нажата без регистрации ФИО
    if not saved_fio:
        await callback.answer("❌ Сначала отправьте команду /start и введите свои ФИО!", show_alert=True)
        return

    parts = callback.data.split("_")
    group_num = parts[1] if len(parts) > 1 else "Неизвестно"
    
    pair_status = get_current_pair_text()
    now_vlad = datetime.now(VLADIVOSTOK_TZ)
    date_str = now_vlad.strftime("%Y-%m-%d")
    time_str = now_vlad.strftime("%H:%M:%S")
    
    username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"
    tg_name = callback.from_user.full_name

    # Записываем в таблицу отметку, включая реальные ФИО
    with open(CSV_ATTENDANCE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([date_str, time_str, user_id, username, tg_name, saved_fio, f"Подгруппа {group_num}", pair_status])

    await callback.message.edit_text(
        text=f"✅ Присутствие успешно отмечено!\n\n"
             f"📅 Дата/Время: {date_str} {time_str} (ВЛВ)\n"
             f"👥 Подгруппа: {group_num}\n"
             f"📖 Пара: {pair_status}\n"
             f"👤 Студент: {saved_fio}"
    )

async def main():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    asyncio.create_task(site.start())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
