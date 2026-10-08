import logging
import asyncio
from datetime import datetime, timedelta, timezone
import csv
import os

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, BotCommand
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

# Фоновый веб-сервер для заглушки бесплатного тарифа Render
async def handle(request):
    return web.Response(text="Bot is running!")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CSV_ATTENDANCE = "attendance.csv"
CSV_STUDENTS = "students.csv"  # Хранит Telegram ID, ФИО и Подгруппу

# НАСТРОЙКА СТАРОСТЫ
STAROSTA_USERNAME = "edinoro_g"  # Ваш юзернейм без знака @

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
        writer.writerow(["Telegram ID", "Реальные ФИО", "Подгруппа"])

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния пошаговой регистрации
class Registration(StatesGroup):
    waiting_for_fio = State()
    waiting_for_group = State()

# Получение данных студента из файла
def get_student_data(user_id):
    if not os.path.exists(CSV_STUDENTS):
        return None
    with open(CSV_STUDENTS, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)  # Пропуск заголовка
        for row in reader:
            if row and int(row) == user_id:
                return {"fio": row, "group": row}
    return None

# Удаление студента из базы при изменении данных
def delete_student_data(user_id):
    if not os.path.exists(CSV_STUDENTS):
        return
    rows = []
    with open(CSV_STUDENTS, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
    
    with open(CSV_STUDENTS, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(rows)  # Восстанавливаем заголовок
        for row in rows[1:]:
            if row and int(row) != user_id:
                writer.writerow(row)

# Определение текущей пары ДВФУ с границами (08:15 - 18:20)
def get_current_pair_text():
    now_vlad = datetime.now(VLADIVOSTOK_TZ)
    current_time = now_vlad.time()
    
    def time_in_range(start_str, end_str):
        start = datetime.strptime(start_str, "%H:%M").time()
        end = datetime.strptime(end_str, "%H:%M").time()
        return start <= current_time <= end

    if time_in_range("08:15", "10:00"):
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
    else:
        return None  # Отметка закрыта (до 08:15 или после 18:20)

# Клавиатуры
def get_reg_group_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 подгруппа 👥", callback_data="reg_group_1")],
        [InlineKeyboardButton(text="2 подгруппа 👥", callback_data="reg_group_2")]
    ])

def get_attendance_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Я НА ПАРЕ (ОТМЕТИТЬСЯ)", callback_data="mark_me")],
        [InlineKeyboardButton(text="⚙️ Сменить подгруппу / ФИО", callback_data="edit_profile")]
    ])

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    student = get_student_data(user_id)
    
    if not student:
        await message.answer(
            "👋 Привет! Пройди быструю регистрацию для журнала старосты.\n\n"
            "Шаг 1: **Введи Фамилию и Имя** через пробел (например: *Петров Алексей*):"
        )
        await state.set_state(Registration.waiting_for_fio)
        return

    pair_status = get_current_pair_text()
    
    if not pair_status:
        await message.answer(
            text=f"👤 **Профиль:** {student['fio']} (Подгруппа {student['group']})\n"
                 f"🌙 **Статус:** Прием отметок закрыт.\n\n"
                 f"🔒 Фиксировать присутствие можно только в учебные часы (с 08:15 до 18:20).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Сменить подгруппу / ФИО", callback_data="edit_profile")]
            ])
        )
        return

    await message.answer(
        text=f"👤 **Профиль:** {student['fio']} (Подгруппа {student['group']})\n"
             f"🏫 **Текущий слот:** {pair_status}\n\n"
             f"Нажмите кнопку ниже, чтобы зафиксировать присутствие:",
        reply_markup=get_attendance_keyboard()
    )

# Обработка команды /relogin и инлайн-кнопки изменения профиля
@dp.message(Command("relogin"))
@dp.callback_query(F.data == "edit_profile")
async def cmd_relogin(event: Message | CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    delete_student_data(user_id)
    await state.clear()
    
    text_msg = "🔄 Данные профиля удалены.\n\nДавай зарегистрируемся заново. **Введи Фамилию и Имя** через пробел:"
    
    if isinstance(event, CallbackQuery):
        await event.message.answer(text_msg)
        await event.answer()
    else:
        await event.answer(text_msg)
        
    await state.set_state(Registration.waiting_for_fio)

# Хендлер ввода ФИО
@dp.message(Registration.waiting_for_fio)
async def process_fio(message: Message, state: FSMContext):
    fio = message.text.strip()
    if len(fio) < 3 or " " not in fio:
        await message.answer("❌ Пожалуйста, введите имя и фамилию через пробел!")
        return
    
    await state.update_data(chosen_fio=fio)
    await state.set_state(Registration.waiting_for_group)
    await message.answer(
        text=f"Принято: **{fio}**\n\nШаг 2: Выбери свою учебную подгруппу:",
        reply_markup=get_reg_group_keyboard()
    )

# Хендлер выбора подгруппы при регистрации
@dp.callback_query(Registration.waiting_for_group, F.data.startswith("reg_group_"))
async def process_reg_group(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    group_num = parts if len(parts) > 2 else "1"
    user_data = await state.get_data()
    fio = user_data.get("chosen_fio")
    user_id = callback.from_user.id
    
    with open(CSV_STUDENTS, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([user_id, fio, group_num])
        
    await state.clear()
    pair_status = get_current_pair_text()
    
    if not pair_status:
        await callback.message.edit_text(
            text=f"🎉 Регистрация успешно завершена!\n\n"
                 f"👤 Профиль: **{fio}**\n"
                 f"👥 Подгруппа: **{group_num}**\n\n"
                 f"🔒 **Отметка сейчас недоступна** (учебное время завершено).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Сменить подгруппу / ФИО", callback_data="edit_profile")]
            ])
        )
        return

    await callback.message.edit_text(
        text=f"🎉 Регистрация успешно завершена!\n\n"
                 f"👤 Профиль: **{fio}**\n"
                 f"👥 Подгруппа: **{group_num}**\n"
                 f"🏫 Текущий слот: {pair_status}\n\n"
                 f"Теперь вы можете отмечаться одной большой кнопкой:",
        reply_markup=get_attendance_keyboard()
    )

# Хендлер нажатия на кнопку «ОТМЕТИТЬ ПРИСУТСТВИЕ»
@dp.callback_query(F.data == "mark_me")
async def process_attendance(callback: CallbackQuery):
    user_id = callback.from_user.id
    student = get_student_data(user_id)
    
    if not student:
        await callback.answer("❌ Вы не зарегистрированы! Используйте синее меню для перевхода.", show_alert=True)
        return

    pair_status = get_current_pair_text()
    
    if not pair_status:
        await callback.answer("🔒 Время приема отметок вышло (после 18:20)!", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Сменить подгруппу / ФИО", callback_data="edit_profile")]
        ]))
        return

    now_vlad = datetime.now(VLADIVOSTOK_TZ)
    date_str = now_vlad.strftime("%Y-%m-%d")
    time_str = now_vlad.strftime("%H:%M:%S")
    
    username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"
    tg_name = callback.from_user.full_name

    with open(CSV_ATTENDANCE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([date_str, time_str, user_id, username, tg_name, student['fio'], f"Подгруппа {student['group']}", pair_status])

    await callback.message.edit_text(
        text=f"✅ **Присутствие успешно отмечено!**\n\n"
             f"📅 Дата/Время: {date_str} {time_str} (ВЛВ)\n"
             f"👤 Студент: {student['fio']}\n"
             f"👥 Подгруппа: {student['group']}\n"
             f"📖 Пара: {pair_status}\n\n"
             f"Запись внесена в общий файл журнала.",
        reply_markup=get_attendance_keyboard()
    )

# Команда /report для старосты (без уязвимых блоков 'if')
@dp.message(Command("report"))
async def cmd_report(message: Message):
    user_username = message.from_user.username or ""
    
    if user_username.lower() == STAROSTA_USERNAME.lower():
