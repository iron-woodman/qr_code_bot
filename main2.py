"""
Основной файл для Telegram-бота, который генерирует и читает QR-коды.

Этот бот умеет:
- Принимать URL от пользователя и генерировать QR-код.
- Принимать изображение с QR-кодом и декодировать его, возвращая текст.
- Использовать машину состояний (FSM) для управления диалогом.
"""





import asyncio
import logging
import os

import cv2
import numpy as np
import qrcode
from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from pyzbar.pyzbar import decode

# --- Конфигурация ---

# Настройка логирования для вывода информационных сообщений.
logging.basicConfig(level=logging.INFO)

# Загрузка переменных окружения из файла .env.
load_dotenv()

# Получение токена бота из переменных окружения.
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    # Вызов ошибки, если токен не найден.
    raise ValueError("Не найден TELEGRAM_BOT_TOKEN в переменных окружения")

# --- Инициализация бота ---

# Создание экземпляров бота и диспетчера.
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- Машина состояний (FSM) ---

class QRCodeStates(StatesGroup):
    """
    Определяет состояния, в которых может находиться диалог с пользователем.
    """
    # Состояние ожидания URL или фотографии с QR-кодом.
    waiting_for_url_or_photo = State()
    # Состояние ожидания выбора цвета для QR-кода.
    waiting_for_color = State()


# --- Обработчики команд и сообщений ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """
    Обрабатывает команду /start.

    Отправляет приветственное сообщение и переводит пользователя
    в состояние ожидания URL или фото.

    Args:
        message (types.Message): Объект сообщения от пользователя.
        state (FSMContext): Контекст машины состояний.
    """
    await message.answer(
        "Добро пожаловать! Я умею создавать QR-коды, а так же читать QR-коды "
        "(извлекать данные из фото с QR-кодом). Отправьте мне URL для "
        "генерации QR-кода или изображение с QR-кодом для декодирования."
    )
    # Установка начального состояния.
    await state.set_state(QRCodeStates.waiting_for_url_or_photo)


@dp.message(QRCodeStates.waiting_for_url_or_photo, F.text)
async def process_url(message: types.Message, state: FSMContext):
    """
    Обрабатывает текстовое сообщение (URL) от пользователя.

    Проверяет, является ли текст валидным URL, и запрашивает выбор
    цвета для QR-кода.

    Args:
        message (types.Message): Объект сообщения от пользователя.
        state (FSMContext): Контекст машины состояний.
    """
    # Проверка, что текст сообщения является URL.
    if not message.text or not message.text.startswith(('http://', 'https://')):
        await message.answer(
            "Это не похоже на URL. Пожалуйста, отправьте URL в виде текста, "
            "начинающийся с 'http://' или 'https://'."
        )
        return

    # Сохранение URL в данных состояния.
    await state.update_data(url=message.text)

    # Создание кнопок для выбора темы QR-кода.
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Светлый", callback_data="light")],
        [InlineKeyboardButton(text="Темный", callback_data="dark")]
    ])

    await message.answer(
        "Пожалуйста, выберите цвет фона для QR-кода:",
        reply_markup=keyboard
    )
    # Перевод в состояние выбора цвета.
    await state.set_state(QRCodeStates.waiting_for_color)


@dp.message(QRCodeStates.waiting_for_url_or_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    """
    Обрабатывает сообщение с фотографией от пользователя.

    Скачивает изображение, пытается распознать на нем QR-код и отправляет
    результат пользователю.

    Args:
        message (types.Message): Объект сообщения от пользователя.
        state (FSMContext): Контекст машины состояний.
    """
    try:
        # Получение информации о файле (выбираем фото лучшего качества).
        file_info = await bot.get_file(message.photo[-1].file_id)
        # Скачивание файла.
        downloaded_file = await bot.download_file(file_info.file_path)

        # Преобразование скачанного файла в формат, понятный для OpenCV.
        file_bytes = np.asarray(bytearray(downloaded_file.read()), dtype=np.uint8)
        img = cv2.imdecode(file_bytes, cv2.IMREAD_GRAYSCALE)

        # Попытка декодирования оригинального изображения.
        decoded_objects = decode(img)

        # Если не удалось, инвертируем изображение и пробуем снова.
        if not decoded_objects:
            img = cv2.bitwise_not(img)
            decoded_objects = decode(img)

        if decoded_objects:
            # Если QR-код найден, отправляем его содержимое.
            for obj in decoded_objects:
                decoded_text = obj.data.decode('utf-8')
                await message.answer(f"Распознанный текст: {decoded_text}")
        else:
            # Если QR-код не найден ни в одном из вариантов.
            await message.answer("QR-код не найден на изображении.")

    except Exception as e:
        logging.error(f"Ошибка при обработке изображения: {e}")
        await message.answer(
            "Извините, что-то пошло не так при обработке изображения."
        )

    # Сброс состояния пользователя.
    await state.clear()
    await message.answer(
        "Чтобы сгенерировать еще один QR-код, отправьте мне новый URL. "
        "Чтобы прочитать QR-код - отправьте мне изображение."
    )
    # Установка начального состояния.
    await state.set_state(QRCodeStates.waiting_for_url_or_photo)


@dp.callback_query(QRCodeStates.waiting_for_color)
async def process_color_choice(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает нажатие на инлайн-кнопку выбора цвета.

    Генерирует QR-код с выбранными параметрами и отправляет его пользователю.

    Args:
        callback_query (types.CallbackQuery): Объект callback-запроса.
        state (FSMContext): Контекст машины состояний.
    """
    # Ответ на callback-запрос, чтобы убрать "часики" в интерфейсе.
    await callback_query.answer()

    color = callback_query.data
    user_data = await state.get_data()
    url = user_data.get("url")

    try:
        # Настройка параметров QR-кода.
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        # Определение цветов в зависимости от выбора пользователя.
        back_color = "white" if color == "light" else "black"
        fill_color = "black" if color == "light" else "white"

        # Создание изображения QR-кода.
        img = qr.make_image(fill_color=fill_color, back_color=back_color)

        # Сохранение изображения во временный файл.
        img_path = f"qr_code_{callback_query.from_user.id}.jpeg"
        img.save(img_path, "JPEG")

        # Отправка изображения пользователю.
        await bot.send_photo(
            callback_query.from_user.id, types.FSInputFile(img_path)
        )

        # Удаление временного файла.
        os.remove(img_path)

    except Exception as e:
        logging.error(f"Ошибка при генерации QR-кода: {e}")
        await callback_query.message.answer(
            "Извините, что-то пошло не так при генерации QR-кода."
        )

    # Сброс состояния.
    await state.clear()
    await callback_query.message.answer(
        "Чтобы сгенерировать еще один QR-код, отправьте мне новый URL. "
        "Чтобы прочитать QR-код - отправьте мне изображение."
    )
    # Установка начального состояния.
    await state.set_state(QRCodeStates.waiting_for_url_or_photo)


# --- Запуск бота ---

async def main():
    """
    Основная асинхронная функция для запуска бота.

    Обеспечивает непрерывную работу и обработку ошибок сети.
    """
    while True:
        try:
            # Запуск опроса (polling) для получения обновлений от Telegram.
            await dp.start_polling(bot)
        except TelegramNetworkError:
            # Обработка проблем с сетью.
            logging.warning("Соединение потеряно. Повторная попытка через 5 секунд...")
            await asyncio.sleep(5)
        except asyncio.exceptions.CancelledError:
            # Обработка остановки бота (например, по Ctrl+C).
            logging.info("Бот остановлен пользователем.")
            break


if __name__ == "__main__":
    # Запуск основной функции при исполнении скрипта.
    asyncio.run(main())
