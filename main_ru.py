
import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramNetworkError

import qrcode
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Загрузка переменных окружения из .env файла
load_dotenv()

# Токен бота из переменной окружения
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Не найден TELEGRAM_BOT_TOKEN в переменных окружения")

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Определение состояний
class QRCodeStates(StatesGroup):
    waiting_for_url = State()
    waiting_for_color = State()

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("Добро пожаловать! Отправьте мне URL для генерации QR-кода.")
    await state.set_state(QRCodeStates.waiting_for_url)

# Обработчик URL
@dp.message(QRCodeStates.waiting_for_url)
async def process_url(message: types.Message, state: FSMContext):
    if not message.text or not message.text.startswith(('http://', 'https://')):
        await message.answer("Это не похоже на URL. Пожалуйста, отправьте URL в виде текста, начинающийся с 'http://' или 'https://'.")
        return

    await state.update_data(url=message.text)
    
    # Создание инлайн-клавиатуры для выбора цвета
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Светлый", callback_data="light")],
        [InlineKeyboardButton(text="Темный", callback_data="dark")]
    ])
    
    await message.answer("Пожалуйста, выберите цвет фона для QR-кода:", reply_markup=keyboard)
    await state.set_state(QRCodeStates.waiting_for_color)

# Обработчик callback-запроса для выбора цвета
@dp.callback_query(QRCodeStates.waiting_for_color)
async def process_color_choice(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    color = callback_query.data
    user_data = await state.get_data()
    url = user_data.get("url")

    # Генерация QR-кода
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        back_color = "white" if color == "light" else "black"
        fill_color = "black" if color == "light" else "white"

        img = qr.make_image(fill_color=fill_color, back_color=back_color)
        
        # Сохранение изображения
        img_path = f"qr_code_{callback_query.from_user.id}.jpeg"
        img.save(img_path, "JPEG")

        # Отправка изображения
        await bot.send_photo(callback_query.from_user.id, types.FSInputFile(img_path))
        
        # Удаление файла
        os.remove(img_path)

    except Exception as e:
        logging.error(f"Ошибка при генерации QR-кода: {e}")
        await callback_query.message.answer("Извините, что-то пошло не так при генерации QR-кода.")
    
    await state.clear()
    await callback_query.message.answer("Чтобы сгенерировать еще один QR-код, отправьте мне новый URL.")
    await state.set_state(QRCodeStates.waiting_for_url)



# ... (existing code)

# Основная функция для запуска бота
async def main():
    while True:
        try:
            await dp.start_polling(bot)
        except TelegramNetworkError:
            logging.warning("Соединение потеряно. Повторная попытка через 5 секунд...")
            await asyncio.sleep(5)
        except asyncio.exceptions.CancelledError:
            logging.info("Бот остановлен пользователем.")
            break

if __name__ == "__main__":
    asyncio.run(main())
