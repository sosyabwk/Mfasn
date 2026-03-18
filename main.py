import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()  # This loads your token from .env or environment variables

TOKEN = os.getenv('TELEGRAM_TOKEN')  # Gets token from .env file

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running!")

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))

print("Bot started...")
app.run_polling()
