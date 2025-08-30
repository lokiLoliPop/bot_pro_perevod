import asyncio
import logging
import os
from datetime import datetime, timedelta
from collections import defaultdict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiohttp.web_app import Application

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Получаем переменные окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_GROUP_ID = os.getenv('ADMIN_GROUP_ID')
WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_URL', 'https://your-app.onrender.com')
WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")

if not ADMIN_GROUP_ID:
    raise ValueError("ADMIN_GROUP_ID не найден в переменных окружения!")

# Словарь для хранения состояний пользователей (ожидают ли ответа админам)
waiting_for_admin_message = {}

# Словарь для связывания сообщений админа с пользователями
# Формат: {message_id_от_бота_в_админ_чате: user_id}
admin_message_to_user = {}

# Статистика
stats = {
    'total_users': set(),  # Уникальные пользователи
    'messages_today': 0,   # Сообщения за сегодня
    'messages_this_week': 0,  # Сообщения за неделю
    'daily_messages': defaultdict(int),  # По дням
    'start_time': datetime.now()  # Время запуска бота
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def update_stats(user_id):
    """Обновляет статистику при новом сообщении"""
    now = datetime.now()
    today = now.date()
    
    # Добавляем пользователя в уникальные
    stats['total_users'].add(user_id)
    
    # Увеличиваем счетчики
    stats['daily_messages'][today] += 1
    
    # Пересчитываем сегодняшние сообщения
    stats['messages_today'] = stats['daily_messages'][today]
    
    # Пересчитываем сообщения за неделю
    week_ago = today - timedelta(days=7)
    stats['messages_this_week'] = sum(
        count for date, count in stats['daily_messages'].items() 
        if date >= week_ago
    )

def get_main_keyboard():
    """Создает основную клавиатуру с кнопками"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 Отправить данные")],
            [KeyboardButton(text="📰 Сообщить новость")],
            [KeyboardButton(text="✍️ Написать админам")]
        ],
        resize_keyboard=True,  # Подгоняет размер кнопок
        one_time_keyboard=False,  # Клавиатура остается после нажатия
        persistent=True  # Клавиатура всегда видна
    )
    return keyboard

def get_admin_chat_keyboard():
    """Создает клавиатуру для режима общения с админами"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Закончить общение")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        persistent=True
    )
    return keyboard

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    """Обработчик команды /start"""
    # Работаем только в личных чатах
    if message.chat.type != 'private':
        return
    
    # Обновляем статистику
    update_stats(message.from_user.id)
        
    await message.answer(
        "Привет! 👋\n\nВыберите действие:",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command('stats'))
async def stats_handler(message: types.Message):
    """Обработчик команды /stats - только для админов"""
    # Проверяем, что это админ (сообщение из админского чата или от админа)
    is_admin = (
        str(message.chat.id) == ADMIN_GROUP_ID or  # Сообщение из админской группы
        str(message.from_user.id) == ADMIN_GROUP_ID.replace('-', '')  # Личное сообщение от админа
    )
    
    if not is_admin:
        return  # Игнорируем команду от обычных пользователей
    
    # Формируем статистику
    uptime = datetime.now() - stats['start_time']
    uptime_str = f"{uptime.days} дн. {uptime.seconds // 3600} ч. {(uptime.seconds % 3600) // 60} мин."
    
    # Последние 7 дней
    recent_days = []
    for i in range(6, -1, -1):  # От 6 дней назад до сегодня
        day = datetime.now().date() - timedelta(days=i)
        count = stats['daily_messages'].get(day, 0)
        day_name = "Сегодня" if i == 0 else f"{day.strftime('%d.%m')}"
        recent_days.append(f"  {day_name}: {count}")
    
    stats_text = f"""📊 **Статистика бота**

👥 **Уникальные пользователи:** {len(stats['total_users'])}
📨 **Сообщений сегодня:** {stats['messages_today']}
📈 **Сообщений за неделю:** {stats['messages_this_week']}

📅 **По дням:**
{chr(10).join(recent_days)}

⏱️ **Время работы:** {uptime_str}
🚀 **Запущен:** {stats['start_time'].strftime('%d.%m.%Y %H:%M')}"""
    
    await message.answer(stats_text, parse_mode='Markdown')

@dp.message(lambda message: message.text == "📤 Отправить данные")
async def send_file_handler(message: types.Message):
    """Обработчик кнопки 'Отправить данные'"""
    # Работаем только в личных чатах
    if message.chat.type != 'private':
        return
        
    await message.answer(
        "Чтобы опубликовать ваши новеллы, нам нужна информация.\n\n<b>Заполните 2 формы:</b>\n"
        "1. Анкету по новеллам: https://tally.so/r/3qQZg2\n"
        "2. Карточку переводчика: https://tally.so/r/wAexoN\n\n"
        "Это займет всего пару минут ✨",
        parse_mode='HTML',
        disable_web_page_preview=True,
        reply_markup=get_main_keyboard()
    )

@dp.message(lambda message: message.text == "📰 Сообщить новость")
async def news_handler(message: types.Message):
    """Обработчик кнопки 'Сообщить новость'"""
    # Работаем только в личных чатах
    if message.chat.type != 'private':
        return
        
    await message.answer(
        "Здесь вы можете сообщить любую новость. Например, что взяли новый перевод или закончили текущий.\n\n"
        "Чтобы отправить новость, заполните анкету: https://tally.so/r/wkBjBd",
        disable_web_page_preview=True,
        reply_markup=get_main_keyboard()
    )

@dp.message(lambda message: message.text == "✍️ Написать админам")
async def contact_admin_handler(message: types.Message):
    """Обработчик кнопки 'Написать админам'"""
    # Работаем только в личных чатах
    if message.chat.type != 'private':
        return
    
    # Помечаем пользователя как ожидающего ввода сообщения для админов
    waiting_for_admin_message[message.from_user.id] = True
    
    # Обновляем статистику
    update_stats(message.from_user.id)
        
    await message.answer(
        "💬 Режим общения с админами активирован!\n"
        "Теперь все ваши сообщения будут пересылаться админам.",
        reply_markup=get_admin_chat_keyboard()
    )

@dp.message(lambda message: message.text == "❌ Закончить общение")
async def end_admin_chat_handler(message: types.Message):
    """Обработчик кнопки 'Закончить общение'"""
    # Работаем только в личных чатах
    if message.chat.type != 'private':
        return
    
    # Убираем пометку ожидания сообщений для админов
    waiting_for_admin_message[message.from_user.id] = False
        
    await message.answer(
        "✅ Общение с админами закончено.",
        reply_markup=get_main_keyboard()
    )

@dp.message()
async def message_handler(message: types.Message):
    """Обработчик всех остальных сообщений"""
    
    # Если сообщение из админского чата и это ответ на сообщение бота
    if str(message.chat.id) == ADMIN_GROUP_ID and message.reply_to_message and message.reply_to_message.from_user.id == bot.id:
        # Ищем пользователя для ответа
        original_message_id = message.reply_to_message.message_id
        target_user_id = admin_message_to_user.get(original_message_id)
        
        if target_user_id:
            try:
                # Определяем клавиатуру для пользователя
                keyboard = get_admin_chat_keyboard() if waiting_for_admin_message.get(target_user_id, False) else get_main_keyboard()
                
                # Отправляем ответ пользователю в зависимости от типа сообщения админа
                if message.text:
                    # Текстовое сообщение от админа
                    await bot.send_message(
                        chat_id=target_user_id,
                        text=f"💬 Ответ от админов:\n\n{message.text}",
                        reply_markup=keyboard
                    )
                elif message.sticker:
                    # Стикер от админа
                    await bot.send_message(
                        chat_id=target_user_id,
                        text="💬 Ответ от админов:",
                        reply_markup=keyboard
                    )
                    await bot.send_sticker(
                        chat_id=target_user_id,
                        sticker=message.sticker.file_id
                    )
                elif message.animation:
                    # Гифка от админа
                    await bot.send_message(
                        chat_id=target_user_id,
                        text="💬 Ответ от админов:",
                        reply_markup=keyboard
                    )
                    await bot.send_animation(
                        chat_id=target_user_id,
                        animation=message.animation.file_id,
                        caption=message.caption
                    )
                elif message.photo:
                    # Фото от админа
                    caption = "💬 Ответ от админов"
                    if message.caption:
                        caption += f":\n\n{message.caption}"
                    await bot.send_photo(
                        chat_id=target_user_id,
                        photo=message.photo[-1].file_id,
                        caption=caption,
                        reply_markup=keyboard
                    )
                elif message.video:
                    # Видео от админа
                    caption = "💬 Ответ от админов"
                    if message.caption:
                        caption += f":\n\n{message.caption}"
                    await bot.send_video(
                        chat_id=target_user_id,
                        video=message.video.file_id,
                        caption=caption,
                        reply_markup=keyboard
                    )
                elif message.voice:
                    # Голосовое от админа
                    await bot.send_message(
                        chat_id=target_user_id,
                        text="💬 Ответ от админов:",
                        reply_markup=keyboard
                    )
                    await bot.send_voice(
                        chat_id=target_user_id,
                        voice=message.voice.file_id
                    )
                else:
                    # Другие типы сообщений
                    await bot.send_message(
                        chat_id=target_user_id,
                        text="💬 Админ отправил ответ (неподдерживаемый тип сообщения)",
                        reply_markup=keyboard
                    )
                
                # Подтверждаем админу
                await message.reply("✅ Ответ отправлен пользователю!")
                
                # НЕ удаляем связь - теперь можно отвечать много раз на одно сообщение
                # del admin_message_to_user[original_message_id]
                
            except Exception as e:
                logging.error(f"Ошибка при отправке ответа пользователю: {e}")
                await message.reply("❌ Ошибка при отправке ответа.")
        else:
            await message.reply("❌ Отвечайте именно на стикер.")
        return
    
    # Работаем только в личных чатах для обычных пользователей
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    # Проверяем, ожидает ли пользователь ввода сообщения для админов
    if waiting_for_admin_message.get(user_id, False):
        # НЕ убираем пометку - пользователь остается в режиме общения с админами
        
        # Пересылаем сообщение админам
        try:
            # Формируем сообщение для админов
            user_info = f"👤 Пользователь: {message.from_user.full_name}"
            if message.from_user.username:
                user_info += f" (@{message.from_user.username})"
            user_info += f"\n🆔 ID: {message.from_user.id}"
            
            # Определяем тип сообщения и отправляем соответственно
            if message.text:
                # Текстовое сообщение
                admin_message = f"{user_info}\n\n📝 Сообщение:\n{message.text}"
                result = await bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=admin_message
                )
            elif message.sticker:
                # Стикер
                await bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=f"{user_info}\n\n🎭 Отправил стикер:"
                )
                result = await bot.send_sticker(
                    chat_id=ADMIN_GROUP_ID,
                    sticker=message.sticker.file_id
                )
            elif message.animation:
                # Гифка (анимация)
                caption = f"{user_info}\n\n🎬 Отправил гифку"
                if message.caption:
                    caption += f":\n{message.caption}"
                result = await bot.send_animation(
                    chat_id=ADMIN_GROUP_ID,
                    animation=message.animation.file_id,
                    caption=caption
                )
            else:
                # Неподдерживаемый тип
                await message.answer(
                    "К сожалению, такое сообщение отправить нельзя. Только текст, стикер или гифку.",
                    reply_markup=get_admin_chat_keyboard()
                )
                return  # Выходим, не отправляя админам
            
            # Сохраняем связь между сообщением админа и пользователем
            admin_message_to_user[result.message_id] = user_id
            
            logging.info(f"Сообщение отправлено успешно: {result.message_id}")
            
            # Подтверждаем отправку пользователю с напоминанием о режиме
            await message.answer(
                "✅ Сообщение отправлено админам!\n"
                "Режим общения активен, можете писать ещё.\n",
                reply_markup=get_admin_chat_keyboard()
            )
            
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения админам: {e}")
            await message.answer(
                "❌ Произошла ошибка при отправке сообщения. Попробуйте позже.",
                reply_markup=get_admin_chat_keyboard()
            )
    else:
        # Обычное сообщение - показываем дружелюбное предложение
        await message.answer(
            "Есть вопрос? Нажмите «Написать админам» 👀",
            reply_markup=get_main_keyboard()
        )

async def on_startup():
    """Настройка webhook при запуске"""
    logging.info(f"Настройка webhook: {WEBHOOK_URL}")
    await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)

async def on_shutdown():
    """Очистка при завершении"""
    logging.info("Удаление webhook...")
    await bot.delete_webhook()
    await bot.session.close()

async def health_check(request):
    """Health check endpoint для мониторинга"""
    return web.Response(text="Bot is running!")

def main():
    """Основная функция запуска приложения"""
    
    # Создаем веб-приложение
    app = Application()
    
    # Добавляем health check
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    # Настраиваем webhook handler
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    
    # Настраиваем приложение
    setup_application(app, dp, bot=bot)
    
    # Добавляем обработчики запуска и завершения
    app.on_startup.append(lambda app: asyncio.create_task(on_startup()))
    app.on_shutdown.append(lambda app: asyncio.create_task(on_shutdown()))
    
    # Запускаем веб-сервер
    port = int(os.getenv('PORT', 10000))
    logging.info(f"Запуск сервера на порту {port}")
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
