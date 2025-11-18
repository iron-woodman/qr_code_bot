"""
Основной файл для Telegram-бота, который генерирует и читает QR-коды.

Этот бот умеет:
- Принимать URL или текст от пользователя и генерировать QR-код.
- Принимать изображение с QR-кодом и декодировать его, возвращая текст.
- Проверять подписку на целевой канал.
- Использовать машину состояний (FSM) для управления диалогом.
"""

import asyncio
import logging
import os

import cv2
import numpy as np
import qrcode
from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
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

# Получение токена бота и ID целевого канала из переменных окружения.
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_CHANNEL_ID = os.getenv("TARGET_CHANNEL_ID")

if not BOT_TOKEN or not TARGET_CHANNEL_ID:
    # Вызов ошибки, если токен или ID канала не найдены.
    raise ValueError(
        "Не найден TELEGRAM_BOT_TOKEN или TARGET_CHANNEL_ID в переменных окружения"
    )

# --- Инициализация бота ---

# Создание экземпляров бота и диспетчера.
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- Машина состояний (FSM) ---

class QRCodeStates(StatesGroup):
    """
    Определяет состояния, в которых может находиться диалог с пользователем.
    """
    # Состояние ожидания проверки подписки.
    waiting_for_subscription_check = State()
    # Состояние ожидания URL, текста или фотографии с QR-кодом.
    waiting_for_input = State()
    # Состояние ожидания выбора цвета для QR-кода.
    waiting_for_color = State()


# --- Проверка подписки ---

async def is_user_subscribed(user_id: int) -> bool:
    """
    Проверяет, подписан ли пользователь на целевой канал.

    Args:
        user_id (int): ID пользователя Telegram.

    Returns:
        bool: True, если пользователь подписан, иначе False.
    """
    try:
        # Получение информации о пользователе в канале.
        member = await bot.get_chat_member(
            chat_id=TARGET_CHANNEL_ID, user_id=user_id
        )
        # Проверка статуса пользователя.
        return member.status in ["member", "administrator", "creator"]
    except TelegramBadRequest:
        # Перехват ошибки, если чат не найден (неверный ID или бот не в чате).
        logging.error(f"Ошибка: чат с ID {TARGET_CHANNEL_ID} не найден. "
                      f"Проверьте TARGET_CHANNEL_ID и права бота.")
        # Возвращаем False, но можно добавить отправку сообщения администратору.
        return False
    except Exception as e:
        logging.error(f"Непредвиденная ошибка при проверке подписки: {e}")
        return False


# --- Обработчики команд и сообщений ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """
    Обрабатывает команду /start.

    Проверяет подписку, отправляет приветственное сообщение и переводит
    пользователя в соответствующее состояние.

    Args:
        message (types.Message): Объект сообщения от пользователя.
        state (FSMContext): Контекст машины состояний.
    """
    user_id = message.from_user.id

    if await is_user_subscribed(user_id):
        # Если пользователь подписан.
        await message.answer(
            "Добро пожаловать! Я умею создавать QR-коды из URL или текста, "
            "а так же читать QR-коды. Отправьте мне URL/текст для "
            "генерации QR-кода или изображение с QR-кодом для декодирования."
        )
        # Установка состояния ожидания ввода.
        await state.set_state(QRCodeStates.waiting_for_input)
    else:
        # Если пользователь не подписан.
        try:
            # Получение информации о канале для создания ссылки-приглашения.
            chat = await bot.get_chat(TARGET_CHANNEL_ID)
            invite_link = chat.invite_link
            if not invite_link:
                # Если ссылка-приглашение не найдена, создаем новую.
                invite_link = await bot.export_chat_invite_link(TARGET_CHANNEL_ID)

            # Создание клавиатуры с кнопками "Подписаться" и "Проверить подписку".
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Подписаться",
                    url=invite_link
                )],
                [InlineKeyboardButton(
                    text="Проверить подписку",
                    callback_data="check_subscription"
                )]
            ])
            await message.answer(
                "Для использования бота, пожалуйста, подпишитесь на наш канал.",
                reply_markup=keyboard
            )
            # Установка состояния ожидания проверки подписки.
            await state.set_state(QRCodeStates.waiting_for_subscription_check)

        except TelegramBadRequest:
            logging.error(f"Критическая ошибка: не удалось получить информацию о канале {TARGET_CHANNEL_ID}. "
                          f"Проверьте, что ID канала указан верно и бот имеет права администратора.")
            await message.answer(
                "Произошла ошибка конфигурации бота. Пожалуйста, сообщите администратору: "
                "не удается найти целевой канал для проверки подписки. "
                "Возможно, неверно указан ID канала или у бота нет прав."
            )
        except Exception as e:
            logging.error(f"Непредвиденная ошибка в cmd_start: {e}")
            await message.answer("Произошла непредвиденная ошибка. Попробуйте позже.")


@dp.callback_query(F.data == "check_subscription", QRCodeStates.waiting_for_subscription_check)
async def check_subscription_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает нажатие на кнопку "Проверить подписку".

    Args:
        callback_query (types.CallbackQuery): Объект callback-запроса.
        state (FSMContext): Контекст машины состояний.
    """
    # Отправка пустого ответа для скрытия "часиков".
    await callback_query.answer()
    # Повторный вызов /start для проверки подписки.
    await cmd_start(callback_query.message, state)


@dp.message(QRCodeStates.waiting_for_input, F.text)
async def process_text(message: types.Message, state: FSMContext):
    """
    Обрабатывает текстовое сообщение (URL или текст) от пользователя.

    Запрашивает выбор цвета для QR-кода.

    Args:
        message (types.Message): Объект сообщения от пользователя.
        state (FSMContext): Контекст машины состояний.
    """
    # Сохранение текста в данных состояния.
    await state.update_data(text=message.text)

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


@dp.message(QRCodeStates.waiting_for_input, F.photo)
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
        file_bytes = np.asarray(
            bytearray(downloaded_file.read()), dtype=np.uint8
        )
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
        "Чтобы сгенерировать QR-код, отправьте мне URL/текст. "
        "Чтобы прочитать QR-код - отправьте мне изображение."
    )
    # Установка начального состояния.
    await state.set_state(QRCodeStates.waiting_for_input)


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
    text = user_data.get("text")

    try:
        # Настройка параметров QR-кода.
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(text.encode('utf-8'))
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
        "Чтобы сгенерировать еще один QR-код, отправьте мне URL/текст. "
        "Чтобы прочитать QR-код - отправьте мне изображение."
    )
    # Установка начального состояния.
    await state.set_state(QRCodeStates.waiting_for_input)


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
            logging.warning(
                "Соединение потеряно. Повторная попытка через 5 секунд..."
            )
            await asyncio.sleep(5)
        except asyncio.exceptions.CancelledError:
            # Обработка остановки бота (например, по Ctrl+C).
            logging.info("Бот остановлен пользователем.")
            break


if __name__ == "__main__":
    # Запуск основной функции при исполнении скрипта.
    asyncio.run(main())
