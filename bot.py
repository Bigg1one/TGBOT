import logging
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.command import Command
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat



# Настройки
API_TOKEN = '7366433284:AAHB6nIivgCuoOxred3GwmU3AJZNUaKkCRI'
ADMIN_IDS = [2071450782,1943086182]  # Укажите ID администраторов
# 1943086182
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
    """Уведомляет всех администраторов о новом тикете."""
    all_admin_ids = set(ADMIN_IDS)
    db_admins = db_session.query(Admin).all()

    for admin in db_admins:
        all_admin_ids.add(admin.id)

    for admin_id in all_admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 <b>Новый тикет #{ticket.id}</b>\n\n"
                f"👤 <b>Пользователь:</b> @{ticket.username or 'Не указано'} (ID: {ticket.user_id})\n"
                f"⚙️ <b>Тема:</b> {ticket.theme}\n\n"
                f"💬 <b>Вопрос:</b> {ticket.question or 'Не указан'}\n\n"
                "🛡 <b>Используйте /admin для просмотра и ответа на тикеты.</b>",
                parse_mode="HTML"
            )
        except TelegramAPIError as e:
            logging.error(f"Ошибка отправки уведомления администратору {admin_id}: {e}")



# Команда /start
@dp.message(Command(commands=["start"]))
async def start_handler(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✍️ Создать тикет")]  # Добавлен стикер ✍️
        ],
        resize_keyboard=True
    )
    await message.answer("Добро пожаловать! Нажмите 'Создать тикет', чтобы задать вопрос.", reply_markup=kb)


# Создание тикета
@dp.message(lambda message: message.text == "✍️ Создать тикет")
async def create_ticket(message: types.Message, state: FSMContext):
    themes = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Техническая проблема", callback_data="theme:Техническая проблема")],
            [InlineKeyboardButton(text="🚫 Спам", callback_data="theme:Спам")],
            [InlineKeyboardButton(text="❓ Общий вопрос", callback_data="theme:Общий вопрос")]
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
        existing_admin = db_session.query(Admin).filter(Admin.id == message.from_user.id).first()
        if not existing_admin:
            await message.answer("У вас нет доступа к этой команде.")
            return

    # Получение открытых тикетов
    tickets = db_session.query(Ticket).filter(Ticket.status != 'closed').all()

    if not tickets:
        await message.answer("🟢 Нет открытых тикетов.")
        return

    for ticket in tickets:
        # Определяем статус тикета
        status = "🟢 Открыт" if ticket.status == 'open' else f"🟡 В процессе (Админ: {ticket.admin_name or 'Неизвестно'})"

        # Инлайн-кнопки для управления тикетом
        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"ticket:{ticket.id}")],
                [InlineKeyboardButton(text="✅ Закрыть", callback_data=f"close:{ticket.id}")]
            ]
        )

        # Сообщение с данными тикета
        await message.answer(
            f"📝 <b>Тикет #{ticket.id}</b>\n\n"
            f"👤 <b>Пользователь:</b> @{ticket.username or 'Не указано'} (ID: {ticket.user_id})\n"
            f"⚙️ <b>Тема:</b> {ticket.theme}\n"
            f"💬 <b>Вопрос:</b> {ticket.question or 'Не указано'}\n\n"
            f"🔒 <b>Статус:</b> {status}",
            reply_markup=inline_kb,
            parse_mode="HTML"
        )




@dp.message(Command(commands=["closed_tickets"]))
async def closed_tickets(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        existing_admin = db_session.query(Admin).filter(Admin.id == message.from_user.id).first()
        if not existing_admin:
            await message.answer("У вас нет доступа к этой команде.")
            return

    # Получаем закрытые тикеты
    tickets = db_session.query(Ticket).filter(Ticket.status == 'closed').all()

    if not tickets:
        await message.answer("🔴 Нет закрытых тикетов.")
        return

    # Выводим первую страницу
    await send_ticket_page(message, tickets, page=1)


async def send_ticket_page(message, tickets, page):
    """Отправляет страницу с закрытыми тикетами."""
    offset = (page - 1) * TICKETS_PER_PAGE
    paginated_tickets = tickets[offset:offset + TICKETS_PER_PAGE]

    if not paginated_tickets:
        await message.answer("Больше закрытых тикетов нет.")
        return

    for ticket in paginated_tickets:
        await message.answer(
            f"✅ <b>Тикет #{ticket.id}</b>\n\n"
            f"👤 <b>Пользователь:</b> @{ticket.username or 'Не указано'} (ID: {ticket.user_id})\n"
            f"⚙️ <b>Тема:</b> {ticket.theme}\n"
            f"💬 <b>Вопрос:</b> {ticket.question}\n\n"
            f"🔒 <b>Статус:</b> Закрыт\n"
            f"👩🏼‍💻 <b>Ответил:</b> {ticket.admin_name or 'Неизвестно'}\n"
            f"📋 <b>Ответ администратора:</b>\n{ticket.admin_response or 'Ответ отсутствует.'}",
            parse_mode="HTML"
        )

    # Кнопки для навигации по страницам
    navigation_kb = InlineKeyboardMarkup(inline_keyboard=[])

    if page > 1:
        navigation_kb.inline_keyboard.append(
            [InlineKeyboardButton(text="⬅️ Предыдущая страница", callback_data=f"closed_page:{page - 1}")]
        )
    if len(tickets) > offset + TICKETS_PER_PAGE:
        navigation_kb.inline_keyboard.append(
            [InlineKeyboardButton(text="➡️ Следующая страница", callback_data=f"closed_page:{page + 1}")]
        )

    await message.answer(f"📄 Страница {page}", reply_markup=navigation_kb)



@dp.callback_query(lambda c: c.data.startswith("closed_page:"))
async def paginate_closed_tickets(callback_query: types.CallbackQuery):
    page = int(callback_query.data.split(":")[1])
    tickets = db_session.query(Ticket).filter(Ticket.status == 'closed').all()

    await callback_query.answer()  # Закрываем уведомление от нажатия кнопки
    await send_ticket_page(callback_query.message, tickets, page)



@dp.message(TicketStates.answering_ticket)
async def answer_ticket(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    ticket_id = user_data.get('ticket_id')
    ticket = db_session.get(Ticket, ticket_id)

    if not ticket:
        await message.answer("Тикет не найден.")
        logging.warning(f"Тикет с ID {ticket_id} не найден.")
        return

    # Сохраняем ответ администратора и закрываем тикет
    ticket.admin_response = message.text
    ticket.status = 'closed'
    ticket.admin_name = message.from_user.full_name or "Неизвестный администратор"
    try:
        db_session.commit()
        logging.info(f"Ответ на тикет #{ticket.id} сохранён в базе данных.")
    except Exception as e:
        await message.answer("Ошибка при сохранении ответа.")
        logging.error(f"Ошибка при сохранении ответа на тикет #{ticket.id}: {e}")
        return

    # Обновление статистики администратора
    admin = db_session.query(Admin).filter(Admin.username == message.from_user.username).first()
    if admin:
        admin.closed_tickets += 1  # Увеличиваем счётчик закрытых тикетов
        db_session.commit()

    # Уведомляем администратора об успешном ответе
    await message.answer(
        f"✅ Ответ на тикет #{ticket.id} успешно сохранён и отправлен пользователю.\n\n"
        f"ℹ️ Нажмите /closed_tickets, чтобы посмотреть закрытые тикеты."
    )

    # Уведомляем пользователя о закрытии тикета
    try:
        await bot.send_message(
            chat_id=ticket.user_id,  # Отправка сообщения пользователю
            text=(
                f"✅ <b>Ваш тикет #{ticket.id} был закрыт</b>\n\n"
                f"👩🏼‍💻 <b>Администратор:</b> {ticket.admin_name}\n"
                f"💬 <b>Ответ:</b>\n{ticket.admin_response or 'Ответ отсутствует.'}"
            ),
            parse_mode="HTML"
        )
        logging.info(f"Сообщение с ответом успешно отправлено пользователю {ticket.user_id}.")
    except TelegramAPIError as e:
        if "bot was blocked by the user" in str(e):
            logging.warning(f"Пользователь {ticket.user_id} заблокировал бота. Сообщение не доставлено.")
        elif "chat not found" in str(e):
            logging.warning(f"Чат с пользователем {ticket.user_id} не найден. Сообщение не доставлено.")
        else:
            logging.error(f"Ошибка Telegram API при отправке сообщения пользователю {ticket.user_id}: {e}")

    # Завершаем состояние
    await state.clear()







@dp.callback_query(lambda c: c.data.startswith("ticket:"))
async def view_ticket(callback_query: types.CallbackQuery, state: FSMContext):
    ticket_id = int(callback_query.data.split(":")[1])
    ticket = db_session.get(Ticket, ticket_id)

    if not ticket:
        await callback_query.answer("Тикет не найден.", show_alert=True)
        return

    if ticket.status != 'open':
        await callback_query.answer("Этот тикет уже в работе или закрыт.", show_alert=True)
        return

    # Обновляем статус тикета на 'in_progress'
    ticket.status = 'in_progress'
    ticket.admin_id = callback_query.from_user.id
    ticket.admin_name = callback_query.from_user.full_name or "Неизвестный администратор"
    db_session.commit()

    # Уведомляем администратора, взявшего тикет
    await callback_query.answer(f"Вы начали работу над тикетом #{ticket.id}.")

    await bot.send_message(
        callback_query.from_user.id,
        f"💬 <b>Введите ваш ответ на тикет #{ticket.id}</b>",
        parse_mode="HTML"
    )

    # Получаем всех администраторов (из базы данных и из списка ADMIN_IDS)
    all_admin_ids = set(ADMIN_IDS)  # Главные админы
    db_admins = db_session.query(Admin).all()
    for admin in db_admins:
        all_admin_ids.add(admin.id)  # Добавляем обычных администраторов

    # Уведомляем всех администраторов, кроме взявшего тикет
    for admin_id in all_admin_ids:
        if admin_id != callback_query.from_user.id:
            try:
                await bot.send_message(
                    admin_id,
                    f"🛠 <b>Тикет #{ticket.id} принят в работу</b>\n\n"
                    f"👩🏼‍💻 <b>Администратор:</b> {ticket.admin_name}",
                    parse_mode="HTML"
                )
            except TelegramAPIError as e:
                logging.error(f"Ошибка при уведомлении администратора {admin_id}: {e}")

    # Сохраняем ID тикета в состояние администратора, который взял тикет
    await state.update_data(ticket_id=ticket.id)
    await state.set_state(TicketStates.answering_ticket)









@dp.callback_query(lambda c: c.data.startswith("page:"))
async def paginate_tickets(callback_query: types.CallbackQuery):
    page = int(callback_query.data.split(":")[1])
    tickets_per_page = 5  # Количество тикетов на странице
    offset = (page - 1) * tickets_per_page

    tickets = db_session.query(Ticket).filter(Ticket.status != 'closed').limit(tickets_per_page).offset(offset).all()

    if not tickets:
        await callback_query.answer("Больше тикетов нет.")
        return

    for ticket in tickets:
        status = "🟢 Открыт" if ticket.status == 'open' else f"🟡 В процессе (Админ: {ticket.admin_name or 'Неизвестно'})"
        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Ответить", callback_data=f"ticket:{ticket.id}")],
                [InlineKeyboardButton(text="Закрыть", callback_data=f"close:{ticket.id}")]
            ]
        )
        await bot.send_message(
            chat_id=callback_query.from_user.id,
            text=f"Тикет #{ticket.id}\n"
                f"Пользователь: @{ticket.username or 'Не указано'} (ID: {ticket.user_id})\n"
                f"Тема: {ticket.theme}\n"
                f"Вопрос: {ticket.question}\n"
                f"Статус: {status}",
            reply_markup=inline_kb
        )

    # Кнопки для навигации
    navigation_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Предыдущая страница", callback_data=f"page:{page - 1}") if page > 1 else None,
                InlineKeyboardButton(text="Следующая страница", callback_data=f"page:{page + 1}")
            ]
        ]
    )
    await bot.send_message(callback_query.from_user.id, "Страница навигации:", reply_markup=navigation_kb)



class Admin(Base):
    __tablename__ = 'admins'
    id = Column(Integer, primary_key=True)  # ID администратора
    username = Column(String, nullable=False)  # @тег администратора
    closed_tickets = Column(Integer, default=0)  # Количество закрытых тикетов
    

Base.metadata.create_all(engine)




@dp.message(Command(commands=["create_adm"]))
async def create_admin(message: types.Message):
    """Добавить нового администратора."""
    if message.from_user.id not in ADMIN_IDS:  # Проверяем, что инициатор — главный администратор
        await message.answer("У вас нет доступа к этой команде.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Ошибка: укажите @тег пользователя или его ID. Используйте формат: /create_adm @username или /create_adm user_id.")
        return

    identifier = args[1]
    try:
        if identifier.startswith("@"):
            username = identifier[1:]  # Убираем '@'
            user = db_session.query(Ticket).filter(Ticket.username == username).first()
            if not user:
                await message.answer(f"Ошибка: пользователь @{username} не найден.")
                return
            user_id = user.user_id
        else:
            user_id = int(identifier)
            user = db_session.query(Ticket).filter(Ticket.user_id == user_id).first()
            if not user:
                await message.answer(f"Ошибка: пользователь с ID {user_id} не найден.")
                return
            username = user.username or "Неизвестно"

        # Проверяем, существует ли администратор
        existing_admin = db_session.query(Admin).filter(Admin.id == user_id).first()
        if existing_admin:
            await message.answer(f"Администратор с ID {user_id} (@{username}) уже существует.")
            return

        # Добавляем нового администратора
        admin = Admin(id=user_id, username=username)
        db_session.add(admin)
        db_session.commit()

        # Устанавливаем меню для нового администратора
        await bot.set_my_commands(
            commands=[
                BotCommand(command="/admin", description="Панель администратора"),
                BotCommand(command="/closed_tickets", description="Просмотр закрытых тикетов"),
                BotCommand(command="/list_admins", description="Список администраторов"),
            ],
            scope=BotCommandScopeChat(chat_id=user_id)
        )

        await message.answer(f"✅ Администратор @{username} с ID {user_id} успешно добавлен.")
    except ValueError:
        await message.answer("Ошибка: укажите правильный формат @username или user_id.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@dp.message(Command(commands=["delete_adm"]))
async def delete_admin(message: types.Message):
    """Удалить администратора."""
    if message.from_user.id not in ADMIN_IDS:  # Проверяем, что инициатор — главный администратор
        await message.answer("У вас нет доступа к этой команде.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Ошибка: укажите @тег пользователя или его ID. Используйте формат: /delete_adm @username или /delete_adm user_id.")
        return

    identifier = args[1]
    try:
        if identifier.startswith("@"):
            admin = db_session.query(Admin).filter(Admin.username == identifier[1:]).first()
        else:
            user_id = int(identifier)
            admin = db_session.query(Admin).filter(Admin.id == user_id).first()

        if not admin:
            await message.answer(f"Администратор {identifier} не найден.")
            return

        user_id = admin.id

        # Удаляем администратора
        db_session.delete(admin)
        db_session.commit()

        # Устанавливаем меню для обычного пользователя
        await bot.set_my_commands(
            commands=[
                BotCommand(command="/start", description="Начало работы с ботом"),
                BotCommand(command="/help", description="Информация о боте"),
            ],
            scope=BotCommandScopeChat(chat_id=user_id)
        )

        await message.answer(f"❌ Администратор {identifier} успешно удалён.")
    except ValueError:
        await message.answer("Ошибка: укажите правильный формат @username или user_id.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")








@dp.message(Command(commands=["delete_adm"]))
async def delete_admin(message: types.Message):
    # Проверяем, что инициатор команды является главным администратором
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет доступа к этой команде.")
        return

    args = message.text.split()  # Разбиваем текст команды на аргументы
    if len(args) < 2:
        await message.answer("Ошибка: укажите @тег пользователя или его ID. Используйте формат: /delete_adm @username или /delete_adm user_id.")
        return

    identifier = args[1]
    try:
        if identifier.startswith("@"):
            # Если указан @username
            admin = db_session.query(Admin).filter(Admin.username == identifier[1:]).first()
        else:
            # Если указан ID
            user_id = int(identifier)
            admin = db_session.query(Admin).filter(Admin.id == user_id).first()

        if not admin:
            await message.answer(f"Администратор {identifier} не найден.")
            return

        # Удаляем администратора
        db_session.delete(admin)
        db_session.commit()
        await message.answer(f"Администратор {identifier} успешно удален.")
    except ValueError:
        await message.answer("Ошибка: укажите правильный формат @username или user_id.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")




@dp.message(Command(commands=["adm"]))
async def admin_stats(message: types.Message):
    # Проверяем, что инициатор команды является главным администратором
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет доступа к этой команде.")
        return

    args = message.text.split()  # Разбиваем текст команды на аргументы
    if len(args) < 2:
        await message.answer("Ошибка: укажите @тег пользователя или его ID. Используйте формат: /adm @username или /adm user_id.")
        return

    identifier = args[1]
    try:
        if identifier.startswith("@"):
            # Если указан @username
            admin = db_session.query(Admin).filter(Admin.username == identifier[1:]).first()
        else:
            # Если указан ID
            user_id = int(identifier)
            admin = db_session.query(Admin).filter(Admin.id == user_id).first()

        if not admin:
            await message.answer(f"Администратор {identifier} не найден.")
            return

        await message.answer(
            f"Статистика администратора {identifier}:\n"
            f"Закрытые тикеты: {admin.closed_tickets}"
        )
    except ValueError:
        await message.answer("Ошибка: укажите правильный формат @username или user_id.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@dp.message(Command(commands=["list_admins"]))
async def list_admins(message: types.Message):
    # Проверяем, что пользователь является администратором или главным администратором
    if message.from_user.id not in ADMIN_IDS:
        existing_admin = db_session.query(Admin).filter(Admin.id == message.from_user.id).first()
        if not existing_admin:
            await message.answer("У вас нет доступа к этой команде.")
            return

    # Формируем список администраторов
    admins = db_session.query(Admin).all()
    admin_list = "Список администраторов:\n"

    for admin in admins:
        admin_list += f"- @{admin.username} (ID: {admin.id})\n"

    # Добавляем главных администраторов
    admin_list += "\nГлавные администраторы:\n"
    for admin_id in ADMIN_IDS:
        admin_list += f"- ID: {admin_id} (главный админ)\n"

    await message.answer(admin_list)



async def set_default_menu():
    """
    Устанавливает меню команд для обычных пользователей.
    """
    commands = [
        BotCommand(command="/start", description="Начало работы с ботом"),
        BotCommand(command="/help", description="Информация о боте"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

async def set_admin_menu():
    """
    Устанавливает меню команд для обычных администраторов.
    """
    commands = [
        BotCommand(command="/admin", description="Панель администратора"),
        BotCommand(command="/closed_tickets", description="Просмотр закрытых тикетов"),
        BotCommand(command="/list_admins", description="Список администраторов"),
        BotCommand(command="/help",description="Помощь" ),
    ]

    # Устанавливаем меню для всех администраторов из таблицы `Admin`
    db_admins = db_session.query(Admin).all()
    for admin in db_admins:
        try:
            await bot.set_my_commands(
                commands,
                scope=BotCommandScopeChat(chat_id=admin.id),
            )
        except TelegramAPIError as e:
            logging.error(f"Ошибка установки меню для администратора {admin.username} (ID: {admin.id}): {e}")

async def set_main_admin_menu():
    """
    Устанавливает меню команд для главных администраторов.
    """
    commands = [
        BotCommand(command="/admin", description="Панель администратора"),
        BotCommand(command="/create_adm", description="Добавить администратора"),
        BotCommand(command="/delete_adm", description="Удалить администратора"),
        BotCommand(command="/adm", description="Статистика администратора"),
        BotCommand(command="/list_admins", description="Список администраторов"),
        BotCommand(command="/closed_tickets", description="Просмотр закрытых тикетов"),
    ]

    # Устанавливаем меню для главных администраторов
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramAPIError as e:
            logging.error(f"Ошибка установки меню для главного администратора ID {admin_id}: {e}")




@dp.callback_query(lambda c: c.data.startswith("close:"))
async def close_ticket(callback_query: types.CallbackQuery):
    ticket_id = int(callback_query.data.split(":")[1])
    ticket = db_session.get(Ticket, ticket_id)

    if not ticket:
        await callback_query.answer("Тикет не найден.", show_alert=True)
        return

    if ticket.status == 'closed':
        await callback_query.answer("Этот тикет уже закрыт.", show_alert=True)
        return

    # Обновляем статус тикета на "closed"
    ticket.status = 'closed'
    ticket.admin_id = callback_query.from_user.id
    ticket.admin_name = callback_query.from_user.full_name or "Неизвестный администратор"
    
    try:
        db_session.commit()
    except Exception as e:
        logging.error(f"Ошибка при закрытии тикета #{ticket_id}: {e}")
        await callback_query.answer("Ошибка при закрытии тикета.", show_alert=True)
        return

    # Отправляем сообщение админу о закрытии тикета
    await bot.send_message(
        callback_query.from_user.id,
        f"✅ Тикет #{ticket.id} успешно закрыт."
    )

    # Уведомляем пользователя о закрытии тикета
    try:
        await bot.send_message(
            chat_id=ticket.user_id,
            text=(
                f"✅ <b>Ваш тикет #{ticket.id} был закрыт</b>\n\n"
                f"👩🏼‍💻 <b>Администратор:</b> {ticket.admin_name}"
            ),
            parse_mode="HTML"
        )
    except TelegramAPIError as e:
        logging.error(f"Ошибка при отправке уведомления пользователю {ticket.user_id}: {e}")

    # Обновляем сообщение с кнопками, убираем их после закрытия тикета
    try:
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=(
                f"📝 <b>Тикет #{ticket.id}</b>\n\n"
                f"👤 <b>Пользователь:</b> @{ticket.username or 'Не указано'} (ID: {ticket.user_id})\n"
                f"⚙️ <b>Тема:</b> {ticket.theme}\n"
                f"💬 <b>Вопрос:</b> {ticket.question or 'Не указано'}\n\n"
                f"🔒 <b>Статус:</b> Закрыт"
            ),
            parse_mode="HTML"
        )
        await callback_query.answer("Тикет успешно закрыт.")
    except TelegramAPIError as e:
        logging.error(f"Ошибка при обновлении сообщения о тикете #{ticket.id}: {e}")



@dp.message(Command(commands=["help"]))
async def help_handler(message: types.Message):
    await help_handler(message)
async def help_handler(message: types.Message):
    await message.answer(
        "<b>Помощь</b>\n\n"
        "Этот бот предназначен для создания тикетов и взаимодействия с поддержкой.\n\n"
        "<b>Команды для пользователей:</b>\n"
        "1️⃣ /start – Начать работу с ботом.\n"
        "2️⃣ ✍️ <b>Создать тикет</b> – Нажмите кнопку 'Создать тикет', чтобы отправить свой запрос.\n\n"
        "После создания тикета ожидайте ответа от администратора.",
        parse_mode="HTML"
    )
async def help_handler(message: types.Message):
    if message.from_user.id in ADMIN_IDS or db_session.query(Admin).filter(Admin.id == message.from_user.id).first():
        await message.answer(
            "<b>Помощь для администраторов</b>\n\n"
            "Вы можете использовать следующие команды:\n\n"
            "🔧 <b>Основные команды:</b>\n"
            "1️⃣ /admin – Панель администратора для просмотра тикетов.\n"
            "2️⃣ /closed_tickets – Просмотр закрытых тикетов.\n"
            "3️⃣ /list_admins – Список всех администраторов.\n\n"
            "\nДля получения дополнительной помощи свяжитесь с разработчиком.",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "<b>Помощь</b>\n\n"
            "Этот бот позволяет создавать тикеты для поддержки. Используйте следующие команды:\n\n"
            "1️⃣ /start – Начать работу с ботом.\n"
            "2️⃣ ✍️ <b>Создать тикет</b> – Нажмите кнопку 'Создать тикет', чтобы отправить свой запрос.\n\n"
            "После создания тикета ожидайте ответа от администратора.",
            parse_mode="HTML"
        )





TICKETS_PER_PAGE = 5  # Количество тикетов на одной странице


if __name__ == "__main__":
    import asyncio

    async def main():
        print("Бот запускается и ожидает сообщения...")
        # Устанавливаем меню
        await set_default_menu()
        await set_main_admin_menu()
        await set_admin_menu()
        # Запускаем бота
        await dp.start_polling(bot)

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен вручную.")





if __name__ == "__main__":
    import asyncio

    async def main():
        print("Бот запускается и ожидает сообщения...")

        # Устанавливаем меню команд
        await set_default_menu()        # Меню для обычных пользователей
        await set_admin_menu()          # Меню для обычных администраторов
        await set_main_admin_menu()     # Меню для главных администраторов

        # Запускаем бота
        await dp.start_polling(bot)

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен вручную.")






if __name__ == "__main__":
    import asyncio

    try:
        print("Бот запускается и ожидает сообщения...")  # Для отладки
        asyncio.run(dp.start_polling(bot))
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен вручную.")