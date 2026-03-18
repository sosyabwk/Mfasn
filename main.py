import os
import logging
import random
from datetime import datetime
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import threading
import re

load_dotenv()

# ---------- CONFIG ----------
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
BASE_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://your-app.onrender.com')

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
app = Flask(__name__)

# Session store
active_calls = {}
call_results = {}
user_sessions = {}  # Stores phone numbers per user

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- FLASK WEBHOOKS (for Twilio calls) ----------
@app.route("/voice", methods=['POST'])
def voice():
    call_sid = request.form.get('CallSid')
    logger.info(f"Call initiated: {call_sid}")
    session_id = active_calls.get(call_sid)
    if not session_id:
        resp = VoiceResponse()
        resp.say("Error. Goodbye.")
        resp.hangup()
        return str(resp)
    otp = call_results.get(session_id, {}).get('code', '123456')
    resp = VoiceResponse()
    resp.say("Your verification code is:", voice='alice')
    for d in otp:
        resp.say(d, voice='alice')
        resp.pause(length=0.3)
    gather = Gather(input='dtmf', timeout=10, num_digits=6, action='/gather', method='POST')
    gather.say("Please enter the code on your keypad.", voice='alice')
    resp.append(gather)
    resp.say("No input received. Goodbye.")
    resp.hangup()
    return str(resp)

@app.route("/gather", methods=['POST'])
def gather():
    digits = request.form.get('Digits', '')
    call_sid = request.form.get('CallSid')
    logger.info(f"Digits received: {digits} from {call_sid}")
    session_id = active_calls.get(call_sid)
    if session_id:
        call_results[session_id]['entered_digits'] = digits
        call_results[session_id]['verified'] = True
    resp = VoiceResponse()
    resp.say("Thank you. Your code has been received.", voice='alice')
    resp.hangup()
    return str(resp)

def run_flask():
    app.run(host='0.0.0.0', port=10000)

threading.Thread(target=run_flask, daemon=True).start()

# ---------- TELEGRAM BOT ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = {'step': 'awaiting_phone'}
    await update.message.reply_text(
        "📱 Please send me your phone number with country code.\n"
        "Example: `+18569004568`",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_sessions:
        user_sessions[user_id] = {}

    step = user_sessions[user_id].get('step')

    if step == 'awaiting_phone':
        # Validate phone number
        if re.match(r'^\+\d{10,15}$', text):
            user_sessions[user_id]['phone'] = text
            user_sessions[user_id]['step'] = 'main_menu'
            keyboard = [
                [InlineKeyboardButton("📞 Voice OTP", callback_data='voice')],
                [InlineKeyboardButton("📱 SMS OTP", callback_data='sms')],
                [InlineKeyboardButton("ℹ️ How it works", callback_data='info')]
            ]
            await update.message.reply_text(
                f"✅ Number saved: {text}\nChoose an option:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                "❌ Invalid format. Use: `+18569004568`",
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text("Use /start to begin.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    if user_id not in user_sessions or 'phone' not in user_sessions[user_id]:
        await query.edit_message_text("Please /start and enter your number first.")
        return

    phone = user_sessions[user_id]['phone']

    if query.data == 'voice':
        await send_voice_otp(query, phone, user_id)
    elif query.data == 'sms':
        await send_sms_otp(query, phone, user_id)
    elif query.data == 'info':
        await query.edit_message_text(
            "This bot sends real SMS/calls to the number you provided.\n"
            "Built for education."
        )

async def send_sms_otp(query, phone, user_id):
    otp = str(random.randint(100000, 999999))
    try:
        msg = twilio_client.messages.create(
            body=f"Your OTP code is: {otp}",
            from_=TWILIO_PHONE_NUMBER,
            to=phone
        )
        logger.info(f"SMS sent to {phone}: {msg.sid}")
        await query.edit_message_text(f"✅ SMS sent to {phone}\nCode: {otp}\n(Check your phone)")
    except Exception as e:
        await query.edit_message_text(f"❌ SMS failed: {e}")

async def send_voice_otp(query, phone, user_id):
    otp = str(random.randint(100000, 999999))
    session_id = f"call_{user_id}_{datetime.now().timestamp()}"
    call_results[session_id] = {'code': otp, 'verified': False}
    try:
        call = twilio_client.calls.create(
            url=f"{BASE_URL}/voice",
            to=phone,
            from_=TWILIO_PHONE_NUMBER
        )
        active_calls[call.sid] = session_id
        await query.edit_message_text(f"📞 Calling {phone}...\nCode being spoken: {otp}")
    except Exception as e:
        await query.edit_message_text(f"❌ Call failed: {e}")

# ---------- MAIN ----------
def main():
    app_tele = Application.builder().token(TELEGRAM_TOKEN).build()
    app_tele.add_handler(CommandHandler("start", start))
    app_tele.add_handler(CallbackQueryHandler(button_handler))
    app_tele.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started")
    app_tele.run_polling()

if __name__ == '__main__':
    main()
