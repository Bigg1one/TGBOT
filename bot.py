import logging
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from aiogram.exceptions import TelegramAPIError



# Настройки
API_TOKEN = '7366433284:AAHB6nIivgCuoOxred3GwmU3AJZNUaKkCRI'
ADMIN_IDS = [2071450782]  # Укажите ID администраторов

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация бота и базы данных
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
engine = create_engine('sqlite:///tickets.db')
Base = declarative_base()
Session = sessionmaker(bind=engine)
db_session = Session()

# Определение таблицы для тикетов
class Ticket(Base):
    __tablename__ = 'tickets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    theme = Column(String, nullable=False)
    question = Column(String, nullable=False)
    status = Column(String, default='open')  # open, in_progress, closed
    admin_id = Column(Integer, nullable=True)
    admin_name = Column(String, nullable=True)  # Имя администратора
    admin_response = Column(String, nullable=True)  # Ответ администратора


Base.metadata.create_all(engine)

# FSM States
class TicketStates(StatesGroup):
    selecting_theme = State()
    entering_question = State()
    answering_ticket = State()

# Вспомогательная функция: Уведомление администраторов
async def notify_admins(ticket: Ticket):
    """Уведомляет администраторов о новом тикете."""
    for admin_id in ADMIN_IDS:
        await bot.send_message(
            admin_id,
            f"Новый тикет #{ticket.id}\n"
            f"Пользователь: @{ticket.username or 'Не указано'} (ID: {ticket.user_id})\n"
            f"Тема: {ticket.theme}\n"
            f"Вопрос: {ticket.question}\n\n"
            "Используйте /admin для просмотра и ответа на тикеты."
        )

# Команда /start
@dp.message(Command(commands=["start"]))
async def start_handler(message: types.Message):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Создать тикет"))
    await message.answer("Добро пожаловать! Нажмите 'Создать тикет', чтобы задать вопрос.", reply_markup=kb)

# Создание тикета
@dp.message(lambda message: message.text == "Создать тикет")
async def create_ticket(message: types.Message, state: FSMContext):
    themes = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Техническая проблема", callback_data="theme:Техническая проблема")],
            [InlineKeyboardButton(text="Спам", callback_data="theme:Спам")],
            [InlineKeyboardButton(text="Общий вопрос", callback_data="theme:Общий вопрос")]
        ]
    )
    await message.answer("Выберите тему тикета:", reply_markup=themes)
    await state.set_state(TicketStates.selecting_theme)

@dp.callback_query(lambda c: c.data.startswith("theme:"), TicketStates.selecting_theme)
async def set_theme(callback_query: types.CallbackQuery, state: FSMContext):
    theme = callback_query.data.split(":")[1]
    await state.update_data(theme=theme)
    await bot.send_message(callback_query.from_user.id, "Опишите ваш вопрос:")
    await state.set_state(TicketStates.entering_question)

@dp.message(TicketStates.entering_question)
async def save_question(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    ticket = Ticket(
        user_id=message.from_user.id,
        username=message.from_user.username or "Не указано",
        theme=user_data['theme'],
        question=message.text
    )
    db_session.add(ticket)
    db_session.commit()
    
    # Уведомляем пользователя
    await message.answer("Ваш тикет успешно создан. Ожидайте ответа администратора.")
    
    # Уведомляем администраторов
    await notify_admins(ticket)
    
    await state.clear()

# Панель администратора
@dp.message(Command(commands=["admin"]))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет доступа к этой команде.")
        return

    tickets = db_session.query(Ticket).filter(Ticket.status != 'closed').all()

    if not tickets:
        await message.answer("Нет открытых тикетов.")
        return

    for ticket in tickets:
        # Информация о статусе, администраторе и ответе
        status = "🟢 Открыт" if ticket.status == 'open' else "🟡 В процессе"
        admin_info = f"\nАдминистратор: {ticket.admin_name or 'Неизвестно'}" if ticket.admin_name else ""
        response_info = f"\nОтвет: {ticket.admin_response}" if ticket.admin_response else ""

        # Инлайн-кнопки для ответа и закрытия тикета
        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Ответить", callback_data=f"ticket:{ticket.id}")],
                [InlineKeyboardButton(text="Закрыть", callback_data=f"close:{ticket.id}")]
            ]
        )
        await message.answer(
            f"Тикет #{ticket.id}\n"
            f"Пользователь: @{ticket.username}\n"
            f"Тема: {ticket.theme}\n"
            f"Вопрос: {ticket.question}\n"
            f"Статус: {status}{admin_info}{response_info}",
            reply_markup=inline_kb
        )


@dp.message(TicketStates.answering_ticket)
async def answer_ticket(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    ticket_id = user_data.get('ticket_id')
    ticket = db_session.query(Ticket).get(ticket_id)

    if not ticket:
        await message.answer("Тикет не найден.")
        logging.warning(f"Тикет с ID {ticket_id} не найден.")
        return

    # Сохраняем ответ администратора и закрываем тикет
    ticket.admin_response = message.text
    ticket.status = 'closed'

    try:
        db_session.commit()  # Сохраняем изменения в базе данных
        logging.info(f"Ответ на тикет #{ticket.id} сохранён в базе данных.")
    except Exception as e:
        await message.answer("Ошибка при сохранении ответа.")
        logging.error(f"Ошибка при сохранении ответа на тикет #{ticket.id}: {e}")
        return

    # Уведомляем администратора об успешном ответе
    await message.answer(f"Ответ отправлен пользователю, тикет #{ticket.id} закрыт.")

    # Попытка отправить сообщение пользователю с именем администратора и ответом
    try:
        await bot.send_message(
            chat_id=ticket.user_id,
            text=f"Ваш тикет #{ticket.id} был закрыт.\n\n"
                 f"Администратор: {ticket.admin_name}\n"
                 f"Ответ:\n{message.text}"
        )
        logging.info(f"Сообщение с ответом на тикет #{ticket.id} отправлено пользователю {ticket.user_id}.")
    except TelegramAPIError as e:
        error_message = str(e)
        if "bot was blocked by the user" in error_message:
            logging.error(f"Пользователь {ticket.user_id} заблокировал бота. Сообщение не доставлено.")
        elif "chat not found" in error_message:
            logging.error(f"Чат с пользователем {ticket.user_id} не найден. Сообщение не доставлено.")
        else:
            logging.error(f"Ошибка Telegram API при отправке сообщения пользователю {ticket.user_id}: {error_message}")
    finally:
        await state.clear()









@dp.callback_query(lambda c: c.data.startswith("ticket:"))
async def view_ticket(callback_query: types.CallbackQuery, state: FSMContext):
    ticket_id = int(callback_query.data.split(":")[1])
    ticket = db_session.query(Ticket).get(ticket_id)

    if not ticket:
        await callback_query.answer("Тикет не найден.")
        return

    ticket.status = 'in_progress'
    ticket.admin_id = callback_query.from_user.id
    ticket.admin_name = callback_query.from_user.full_name or "Неизвестный администратор"
    db_session.commit()

    await state.update_data(ticket_id=ticket.id)
    await bot.send_message(callback_query.from_user.id, f"Введите ваш ответ на тикет #{ticket.id}:")
    await callback_query.answer()  # Закрыть уведомление после нажатия кнопки
    await state.set_state(TicketStates.answering_ticket)


@dp.callback_query(lambda c: c.data.startswith("close:"))
async def close_ticket(callback_query: types.CallbackQuery):
    ticket_id = int(callback_query.data.split(":")[1])
    ticket = db_session.query(Ticket).get(ticket_id)

    if not ticket:
        await callback_query.answer("Тикет не найден.")
        return

    ticket.status = 'closed'
    db_session.commit()

    await callback_query.answer("Тикет закрыт.")
    await bot.send_message(callback_query.from_user.id, f"Тикет #{ticket.id} был успешно закрыт.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(bot))
