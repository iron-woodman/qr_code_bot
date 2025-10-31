
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

# Set up logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env file
load_dotenv()

# Bot token from environment variable
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No TELEGRAM_BOT_TOKEN found in environment variables")

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Define states
class QRCodeStates(StatesGroup):
    waiting_for_url = State()
    waiting_for_color = State()

# Start command handler
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("Welcome! Please send me a URL to generate a QR code.")
    await state.set_state(QRCodeStates.waiting_for_url)

# URL handler
@dp.message(QRCodeStates.waiting_for_url)
async def process_url(message: types.Message, state: FSMContext):
    if not message.text or not message.text.startswith(('http://', 'https://')):
        await message.answer("That doesn't look like a valid URL. Please send a URL as text, starting with 'http://' or 'https://'.")
        return

    await state.update_data(url=message.text)
    
    # Create inline keyboard for color choice
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Light", callback_data="light")],
        [InlineKeyboardButton(text="Dark", callback_data="dark")]
    ])
    
    await message.answer("Please choose a background color for the QR code:", reply_markup=keyboard)
    await state.set_state(QRCodeStates.waiting_for_color)

# Callback query handler for color choice
@dp.callback_query(QRCodeStates.waiting_for_color)
async def process_color_choice(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    color = callback_query.data
    user_data = await state.get_data()
    url = user_data.get("url")

    # Generate QR code
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
        
        # Save the image
        img_path = f"qr_code_{callback_query.from_user.id}.jpeg"
        img.save(img_path, "JPEG")

        # Send the image
        await bot.send_photo(callback_query.from_user.id, types.FSInputFile(img_path))
        
        # Clean up the file
        os.remove(img_path)

    except Exception as e:
        logging.error(f"Error generating QR code: {e}")
        await callback_query.message.answer("Sorry, something went wrong while generating the QR code.")
    
    await state.clear()
    await callback_query.message.answer("To generate another QR code, send me a new URL.")
    await state.set_state(QRCodeStates.waiting_for_url)




# Main function to start the bot
async def main():
    while True:
        try:
            await dp.start_polling(bot)
        except TelegramNetworkError:
            logging.warning("Connection lost. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except asyncio.exceptions.CancelledError:
            logging.info("Bot stopped by user.")
            break

if __name__ == "__main__":
    asyncio.run(main())
