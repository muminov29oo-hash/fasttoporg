# main.py
import telebot
from telebot import types
from flask import Flask, request, jsonify
from flask_cors import CORS
from threading import Thread
import json
import os
import re
import uuid
import time
import logging
from datetime import datetime

# === BOT SOZLAMALARI ===
TOKEN = "8004752628:AAGoyB4Frc7d_OzXeZS4SybtddLpeXm5LPk"
ADMIN_ID = 7214885905
ADMIN_USERNAME = "@Muminovv_vv"
ADMIN_SECRET_KEY = "yangieskibot"
DB_FILE = "users.json"
SETTINGS_FILE = "settings.json"

# Kanallar
DEFAULT_REQUIRED_CHANNELS = ["@extra_konkurss"]
PAYMENTS_CHANNEL = "@chektekshirbot"
PAYMENTS_INFO = "@fasttoporgchek"

# Bonuslar
REFERRAL_BONUS = 300
WITHDRAW_MIN = 2000

# === LOGGING ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)
CORS(app)

# === GLOBAL O'ZGARUVCHILAR ===
pending_referrals = {}
_users = {}
_states = {}
REQUIRED_CHANNELS = DEFAULT_REQUIRED_CHANNELS.copy()
bot_username = None

# === SETTINGS FUNKSIYALARI ===
def load_settings():
    global REQUIRED_CHANNELS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                chs = data.get("REQUIRED_CHANNELS", DEFAULT_REQUIRED_CHANNELS)
                REQUIRED_CHANNELS = [ch for ch in chs if isinstance(ch, str) and ch.startswith("@")]
        except Exception:
            REQUIRED_CHANNELS = DEFAULT_REQUIRED_CHANNELS.copy()

def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"REQUIRED_CHANNELS": REQUIRED_CHANNELS}, f, indent=4, ensure_ascii=False)
    except Exception:
        logging.exception("Settingsni saqlashda xato.")

# === DB FUNKSIYALARI ===
def load_data():
    global _users
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                _users = json.load(f)
        except Exception:
            _users = {}
    else:
        _users = {}

def save_data():
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(_users, f, indent=4, ensure_ascii=False)
    except Exception:
        logging.exception("DB saqlashda xato.")

def get_user(uid):
    uid_s = str(uid)
    if uid_s not in _users:
        _users[uid_s] = {
            "username": "Noma'lum",
            "balans": 0,
            "spent": 0,
            "referallar": [],
            "joined_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "transactions": [],
            "total_earned": 0,
            "total_withdrawn": 0,
            "last_active": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_data()
    return _users[uid_s]

def add_balance(uid, amount, reason=""):
    try:
        u = get_user(uid)
        old_balance = u.get("balans", 0)
        u["balans"] = old_balance + amount
        u["total_earned"] = u.get("total_earned", 0) + amount
        u["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if "transactions" not in u:
            u["transactions"] = []
        
        transaction = {
            "type": "deposit",
            "amount": amount,
            "reason": reason,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "old_balance": old_balance,
            "new_balance": u["balans"]
        }
        u["transactions"].append(transaction)
        
        save_data()
        return u["balans"]
    except Exception as e:
        logging.error(f"add_balance xatosi: {e}")
        return None

def subtract_balance(uid, amount, reason=""):
    try:
        u = get_user(uid)
        current = u.get("balans", 0)
        if current >= amount:
            old_balance = current
            u["balans"] = current - amount
            u["spent"] = u.get("spent", 0) + amount
            u["total_withdrawn"] = u.get("total_withdrawn", 0) + amount
            u["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if "transactions" not in u:
                u["transactions"] = []
            
            transaction = {
                "type": "withdraw",
                "amount": amount,
                "reason": reason,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "old_balance": old_balance,
                "new_balance": u["balans"]
            }
            u["transactions"].append(transaction)
            
            save_data()
            return u["balans"]
        return -1
    except Exception as e:
        logging.error(f"subtract_balance xatosi: {e}")
        return None

def fmt_curr(n):
    return f"{int(n):,}".replace(",", " ") + " so'm"

def get_user_display(user_data, user_id):
    username = user_data.get("username", "Noma'lum")
    if username != "Noma'lum":
        return f'<a href="https://t.me/{username}">@{username}</a>'
    return f'<a href="tg://user?id={user_id}">{user_id}</a>'

# === XABAR FUNKSIYALARI ===
def safe_send_message(chat_id, text, **kwargs):
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logging.error(f"Xabar yuborishda xato: {e}")
        return None

def safe_send_channel(channel, text, **kwargs):
    try:
        result = bot.send_message(channel, text, **kwargs)
        logging.info(f"Xabar {channel} kanaliga muvaffaqiyatli yuborildi")
        return result
    except Exception as e:
        logging.error(f"Kanalga xabar yuborishda xato: {e}")
        return None

# === YANGI: REFERAL BONUSNI TO'G'RI TEKSHIRISH ===
def check_and_reward_referral(new_user_id):
    """Yangi foydalanuvchi kanalga obuna bo'lganda referal bonusini tekshiradi"""
    try:
        if new_user_id in pending_referrals:
            referrer_id = pending_referrals[new_user_id]
            new_user = get_user(new_user_id)
            username = new_user.get("username", "Noma'lum")
            
            # Kanalga obuna bo'lganligini tekshiramiz
            if check_subscription(new_user_id):
                # Bonus beramiz
                send_referral_success_message(referrer_id, new_user_id, username)
                pending_referrals.pop(new_user_id, None)
                return True
            else:
                # Obuna bo'lmaganligi haqida refererga xabar
                new_user_display = get_user_display({"username": username}, new_user_id)
                message = (
                    f"👋 <b>Yangi referal!</b>\n\n"
                    f"👤 <b>Yangi foydalanuvchi:</b> {new_user_display}\n"
                    f"💰 <b>Bonus miqdori:</b> {fmt_curr(REFERRAL_BONUS)}\n\n"
                    f"⚠️ <i>U hali kanallarga obuna bo'lmagan. Agar u quyidagi kanallarga obuna bo'lsa, sizga {fmt_curr(REFERRAL_BONUS)} bonus beriladi:</i>\n"
                )
                
                for ch in REQUIRED_CHANNELS:
                    message += f"• {ch}\n"
                    
                safe_send_message(referrer_id, message)
                return False
        return False
    except Exception as e:
        logging.error(f"Referal tekshirishda xato: {e}")
        return False

def send_referral_success_message(referrer_id, new_user_id, new_user_username):
    """Referal bonus muvaffaqiyatli berilganda xabar yuboradi"""
    try:
        # Yangi foydalanuvchi kanalga obuna bo'lganligini qayta tekshiramiz
        if not check_subscription(new_user_id):
            # Agar hali obuna bo'lmagan bo'lsa
            new_user_display = get_user_display({"username": new_user_username}, new_user_id)
            message = (
                f"👋 <b>referalingiz orqali yangi foydalanuvchi tashrif buyurdi </b>\n\n"
                f"👤 <b>Yangi foydalanuvchi:</b> {new_user_display}\n"
                f"⚠️ <i> Agar kanalimizga obuna bo'lsa, sizga {fmt_curr(REFERRAL_BONUS)} referal bonus beriladi:</i>\n"
                f"💰 <b>Bonus miqdori:</b> {fmt_curr(REFERRAL_BONUS)} qo'shilmadi !\n\n"
            )
            
            for ch in REQUIRED_CHANNELS:
                message += f"• {ch}\n"
                
            safe_send_message(referrer_id, message)
            return

        # Agar obuna bo'lgan bo'lsa, bonus beramiz
        new_balance = add_balance(referrer_id, REFERRAL_BONUS, "Referal bonus")
        new_user_display = get_user_display({"username": new_user_username}, new_user_id)
        
        message = (
              f"🎉 <b>sizning referalingiz orqali yangi foydalanuvchi qo'shildi</b>\n\n"

            f"🎉 <b>Tabriklaymiz! Sizga bonus qo'shildi</b>\n\n"
            f"👤 <b>Yangi foydalanuvchi:</b> {new_user_display}\n"
            f"💰 <b>Bonus miqdori:</b> {fmt_curr(REFERRAL_BONUS)}\n"
            f"📊 <b>Yangi balans:</b> {fmt_curr(new_balance)}\n\n"
           
        )
        
        safe_send_message(referrer_id, message)
        
        referrer = get_user(referrer_id)
        if new_user_id not in referrer["referallar"]:
            referrer["referallar"].append(new_user_id)
        save_data()
        
    except Exception as e:
        logging.error(f"Referal muvaffaqiyat xabarida xato: {e}")

# === BOT HANDLERLARI ===
@bot.message_handler(commands=["start"])
def start_cmd(m):
    uid = m.chat.id
    username = m.from_user.username or m.from_user.first_name or "Noma'lum"
    args = m.text.split()
    ref = args[1] if len(args) > 1 else None
    
    u = get_user(uid)
    u["username"] = username
    u["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_data()

    # Referalni qayd etamiz
    if ref and ref != str(uid):
        try:
            referrer_id = int(ref)
            if str(referrer_id) in _users:
                pending_referrals[uid] = referrer_id
                logging.info(f"Yangi referal: {uid} -> {referrer_id}")
                
                # Darhol tekshiramiz, agar obuna bo'lgan bo'lsa
                check_and_reward_referral(uid)
        except ValueError:
            pass

    if REQUIRED_CHANNELS and not check_subscription(uid):
        ask_to_subscribe(uid)
        return

    show_menu(uid)
    _states[str(uid)] = "menu"

def check_subscription(user_id):
    try:
        if not REQUIRED_CHANNELS:
            return True
        for ch in REQUIRED_CHANNELS:
            try:
                member = bot.get_chat_member(ch, user_id)
                if member.status in ["member", "creator", "administrator"]:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False

def ask_to_subscribe(uid):
    if not REQUIRED_CHANNELS:
        show_menu(uid)
        return
        
    markup = types.InlineKeyboardMarkup()
    for ch in REQUIRED_CHANNELS[:5]:
        markup.add(types.InlineKeyboardButton(f"📢 {ch} kanaliga obuna bo'lish", url=f"https://t.me/{ch[1:]}"))
    markup.add(types.InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub"))
    
    safe_send_message(uid, 
        "👋 <b>Botdan to'liq foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>", 
        reply_markup=markup)

def show_menu(uid):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.row("💰 Pul ishlash", "🔗 Referal havola")
    markup.row("📊 Mening balansim", "💸 Pul yechish")
    markup.row("📈 To'lovlar tarixi", "📢 Yangiliklar")
    markup.row("🛠 Xizmatlar", "👤 Adminga murojaat")
    markup.row("📦 To'lovlar kanali", "ℹ️ Yordam")
    
    safe_send_message(uid, 
        "🤖 <b>Asosiy menyu</b>\n\n"
        "Quyidagi tugmalardan birini tanlang:", 
        reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def check_sub(call):
    uid = call.from_user.id
    try:
        if check_subscription(uid):
            bot.answer_callback_query(call.id, "✅ Obuna tasdiqlandi!")
            show_menu(uid)
            _states[str(uid)] = "menu"
            
            # Agar referal bo'lsa, bonus beramiz
            if check_and_reward_referral(uid):
                bot.answer_callback_query(call.id, "✅ Obuna tasdiqlandi va bonus berildi!")
            else:
                bot.answer_callback_query(call.id, "✅ Obuna tasdiqlandi!")
                
        else:
            bot.answer_callback_query(call.id, "❌ Hali obuna bo'lmagansiz.")
                
    except Exception as e:
        logging.error(f"check_sub: xatolik yuz berdi: {e}")

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    uid = m.chat.id
    u = get_user(uid)
    state = _states.get(str(uid), "menu")
    text = (m.text or "").strip()

    # Faollik vaqtini yangilash
    u["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_data()

    if REQUIRED_CHANNELS and not check_subscription(uid):
        ask_to_subscribe(uid)
        return

    if state.startswith("withdraw_"):
        handle_withdraw_state(uid, u, state, text)
        return

    handle_main_menu(uid, u, text)

def handle_withdraw_state(uid, u, state, text):
    try:
        if state == "withdraw_amount":
            if text.lower() == "bekor qilish":
                _states[str(uid)] = "menu"
                safe_send_message(uid, "❌ So'rov bekor qilindi.")
                return show_menu(uid)
            if not text.isdigit():
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                markup.add("Bekor qilish")
                msg = safe_send_message(uid, "❌ Faqat raqam kiriting:", reply_markup=markup)
                return bot.register_next_step_handler(msg, handle_message)
            amount = int(text)
            if amount < WITHDRAW_MIN:
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                markup.add("Bekor qilish")
                msg = safe_send_message(uid, f"❌ Minimal yechish: {fmt_curr(WITHDRAW_MIN)}:", reply_markup=markup)
                return bot.register_next_step_handler(msg, handle_message)
            if amount > u["balans"]:
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                markup.add("Bekor qilish")
                msg = safe_send_message(uid, f"❌ Balans yetarli emas ({fmt_curr(u['balans'])}):", reply_markup=markup)
                return bot.register_next_step_handler(msg, handle_message)
            
            u["pending_withdraw"] = amount
            save_data()
            
            # PUL YECHISH TURINI TANLASH
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add("💳 Karta raqamiga pul yechish")
            markup.add("📱 Telefon raqamiga pul yechish")
            markup.add("Bekor qilish")
            
            msg = safe_send_message(uid, 
                f"<b>💸 Pul yechish turini tanlang</b>\n\n"
                f"💰 Summa: <code>{fmt_curr(amount)}</code>\n\n"
                f"<i>Qaysi usulda pul yechmoqchisiz?</i>", 
                reply_markup=markup)
            _states[str(uid)] = "withdraw_type"
            return bot.register_next_step_handler(msg, handle_message)

        elif state == "withdraw_type":
            if text.lower() == "bekor qilish":
                _states[str(uid)] = "menu"
                safe_send_message(uid, "❌ So'rov bekor qilindi.")
                return show_menu(uid)
                
            if text == "💳 Karta raqamiga pul yechish":
                u["withdraw_type"] = "card"
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                markup.add("Bekor qilish")
                msg = safe_send_message(uid, "💳 Karta raqamingizni kiriting: misol (9860************)", reply_markup=markup)
                _states[str(uid)] = "withdraw_account"
                return bot.register_next_step_handler(msg, handle_message)
                
            elif text == "📱 Telefon raqamiga pul yechish":
                u["withdraw_type"] = "phone"
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                markup.add("Bekor qilish")
                msg = safe_send_message(uid, "📱 Telefon raqamingizni kiriting: misol (+998XXXXXXXXX):", reply_markup=markup)
                _states[str(uid)] = "withdraw_account"
                return bot.register_next_step_handler(msg, handle_message)
            else:
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
                markup.add("💳 Karta raqamiga pul yechish")
                markup.add("📱 Telefon raqamiga pul yechish")
                markup.add("Bekor qilish")
                msg = safe_send_message(uid, "❌ Iltimos, tugmalardan birini tanlang:", reply_markup=markup)
                return bot.register_next_step_handler(msg, handle_message)

        elif state == "withdraw_account":
            if text.lower() == "bekor qilish":
                _states[str(uid)] = "menu"
                safe_send_message(uid, "❌ So'rov bekor qilindi.")
                return show_menu(uid)
                
            withdraw_type = u.get("withdraw_type")
            amount = u.get("pending_withdraw")
            
            if withdraw_type == "card":
                card = re.sub(r"\s|-", "", text)
                if not card.isdigit() or len(card) < 12:
                    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                    markup.add("Bekor qilish")
                    msg = safe_send_message(uid, "❌ Noto'g'ri karta raqami. Qayta kiriting:", reply_markup=markup)
                    return bot.register_next_step_handler(msg, handle_message)
                u["pending_account"] = card
                account_text = f"💳 Karta: <code>{card}</code>"
                
            else:  # phone
                phone = re.sub(r"[^\d\+]", "", text)
                if not re.match(r"^\+998\d{9}$", phone):
                    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                    markup.add("Bekor qilish")
                    msg = safe_send_message(uid, "❌ Noto'g'ri telefon raqami. Qayta kiriting:", reply_markup=markup)
                    return bot.register_next_step_handler(msg, handle_message)
                u["pending_account"] = phone
                account_text = f"📱 Telefon: <code>{phone}</code>"
            
            save_data()
            
            # TASDIQLASH TUGMALARI
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_withdraw"),
                types.InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_withdraw")
            )
            
            safe_send_message(uid, 
                f"<b>💰 Pul yechish so'rovi</b>\n\n"
                f"💵 Summa: <code>{fmt_curr(amount)}</code>\n"
                f"{account_text}\n\n"
                f"<i>Pul yechishni tasdiqlaysizmi?</i>\n\n"
                f"⚠️ <b>Eslatma:</b> To'lov 1-24 soat ichida amalga oshiriladi", 
                reply_markup=markup)
            
            _states[str(uid)] = "menu"
            
    except Exception as e:
        logging.error(f"Withdraw xatosi: {e}")
        safe_send_message(uid, "❌ Xatolik yuz berdi.")
        _states[str(uid)] = "menu"
        show_menu(uid)

def handle_main_menu(uid, u, text):
    try:
        if text == "💰 Pul ishlash":
            total_bonus = len(u['referallar']) * REFERRAL_BONUS
            total_earned = u.get('total_earned', 0)
            
            safe_send_message(uid,
                f"<b>💰 Pul ishlash</b>\n\n"
                f"💵 <b>Balans:</b> <code>{fmt_curr(u['balans'])}</code>\n"
                f"👥 <b>Taklif qilinganlar:</b> <code>{len(u['referallar'])} ta</code>\n"
                f"🎁 <b>Referal bonus:</b> <code>{fmt_curr(REFERRAL_BONUS)}</code>\n"
                f"💰 <b>Jami bonus:</b> <code>{fmt_curr(total_bonus)}</code>\n"
                f"📈 <b>Umumiy topilgan:</b> <code>{fmt_curr(total_earned)}</code>\n\n"
                f"<i>Har bir do'stingiz obuna bo'lganda sizga {fmt_curr(REFERRAL_BONUS)} bonus beriladi!</i>"
            )
            
        elif text == "🔗 Referal havola":
            bot_un = bot_username or "bot"
            link = f"https://t.me/{bot_un}?start={uid}"
            total_referrals = len(u['referallar'])
            total_bonus = total_referrals * REFERRAL_BONUS
            
            safe_send_message(uid,
                f"<b>🔗 Referal havola</b>\n\n"
                f"📎 <b>Havola:</b>\n<code>{link}</code>\n\n"
                f"📊 <b>Statistika:</b>\n"
                f"• Taklif qilinganlar: <code>{total_referrals} ta</code>\n"
                f"• Jami bonus: <code>{fmt_curr(total_bonus)}</code>\n"
                f"• Bonus har bir do'st uchun: <code>{fmt_curr(REFERRAL_BONUS)}</code>\n\n"
                f"📢 <b>Qanday ishlaydi?</b>\n"
                f"1. Havolani do'stlaringizga yuboring\n"
                f"2 Ular botga kirib kanallarga obuna bo'ladi\n"
                f"3 Sizga avtomatik bonus qo'shiladi!"
            )
            
        elif text == "📊 Mening balansim":
            total_earned = u.get('total_earned', 0)
            total_withdrawn = u.get('total_withdrawn', 0)
            total_referrals = len(u['referallar'])
            referral_income = total_referrals * REFERRAL_BONUS
            
            safe_send_message(uid,
                f"<b>📊 Balans ma'lumotlari</b>\n\n"
                f"👤 <b>ID:</b> <code>{uid}</code>\n"
                f"💵 <b>Joriy balans:</b> <code>{fmt_curr(u['balans'])}</code>\n"
                f"📈 <b>Umumiy topilgan:</b> <code>{fmt_curr(total_earned)}</code>\n"
                f"💸 <b>Umumiy yechilgan:</b> <code>{fmt_curr(total_withdrawn)}</code>\n"
                f"👥 <b>Taklif qilinganlar:</b> <code>{total_referrals} ta</code>\n"
                f"🎁 <b>Referal daromad:</b> <code>{fmt_curr(referral_income)}</code>\n"
                f"📅 <b>Oxirgi faollik:</b> <code>{u.get('last_active', 'Noma lum')}</code>"
            )
            
        elif text == "💸 Pul yechish":
            if u["balans"] < WITHDRAW_MIN:
                safe_send_message(uid, 
                    f"<b>❌ Pul yechish</b>\n\n"
                    f"💵 <b>Joriy balans:</b> <code>{fmt_curr(u['balans'])}</code>\n"
                    f"💰 <b>Minimal yechish:</b> <code>{fmt_curr(WITHDRAW_MIN)}</code>\n"
                    f"📊 <b>Yetarli emas:</b> <code>{fmt_curr(WITHDRAW_MIN - u['balans'])}</code>\n\n"
                    f"<i>Pul ishlash bo'limida ko'proq pul ishlashingiz mumkin!</i>")
                return
                
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("Bekor qilish")
            msg = safe_send_message(uid, 
                f"<b>💸 Pul yechish</b>\n\n"
                f"💵 <b>Balans:</b> <code>{fmt_curr(u['balans'])}</code>\n"
                f"💰 <b>Minimal:</b> <code>{fmt_curr(WITHDRAW_MIN)}</code>\n"
                f"⏰ <b>To'lov vaqti:</b> 1-24 soat\n\n"
                f"<i>Yechiladigan summani kiriting:</i>", 
                reply_markup=markup)
            _states[str(uid)] = "withdraw_amount"
            bot.register_next_step_handler(msg, handle_message)
            
        elif text == "📈 To'lovlar tarixi":
            transactions = u.get("transactions", [])
            if not transactions:
                safe_send_message(uid, 
                    f"<b>📈 To'lovlar tarixi</b>\n\n"
                    f"❌ Hozircha hech qanday operatsiya yo'q.\n\n"
                    f"<i>Pul ishlash yoki pul yechish orqali operatsiyalar yaratishingiz mumkin!</i>")
            else:
                safe_send_message(uid, f"<b>📈 So'ngi 10 ta operatsiya:</b>")
                for tx in reversed(transactions[-10:]):
                    if tx["type"] == "deposit":
                        icon = "💰 QO'SHILDI"
                        color = "🟢"
                    else:
                        icon = "💸 YECHILDI" 
                        color = "🔴"
                    
                    safe_send_message(uid, 
                        f"{color} <b>{icon}</b>\n"
                        f"💵 Summa: <code>{fmt_curr(tx['amount'])}</code>\n"
                        f"📝 Sabab: {tx['reason']}\n"
                        f"📅 Sana: <code>{tx['date']}</code>\n"
                        f"📊 Oldingi: <code>{fmt_curr(tx['old_balance'])}</code>\n"
                        f"📈 Yangi: <code>{fmt_curr(tx['new_balance'])}</code>")
                
        elif text == "🛠 Xizmatlar":
            safe_send_message(uid, 
                "<b>🛠 Xizmatlar</b>\n\n"
                "🚀 <b>Mavjud xizmatlar:</b>\n"
                "• 💰 Pul ishlash - Do'stlaringizni taklif qiling\n"
                "• 💸 Pul yechish - Balansingizdan pul yeching\n"
                "• 📊 Statistika - Batafsil ma'lumotlar\n"
                "• 📈 Tarix - Barcha operatsiyalaringiz\n\n"
                "📢 <b>Tez orada:</b>\n"
                "• 🤖 Avto-pul ishlash\n"
                "• 🎮 Mini o'yinlar\n"
                "• 📊 Kripto valyutalar\n\n"
                "<i>Takliflaringiz bo'lsa adminga murojaat qiling!</i>")
                
        elif text == "📢 Yangiliklar":
            safe_send_message(uid, 
                "<b>📢 Yangiliklar</b>\n\n"
                "🎉 <b>Bot yangilandi!</b>\n"
                "• 📊 Yangi statistika tizimi\n"
                "• 💰 Balans boshqaruvi\n"
                "• 📈 Batafsil operatsiyalar tarixi\n"
                "• 🛠 Ko'proq funksiyalar\n\n"
                "📢 <b>Eslatma:</b>\n"
                "• Har bir do'st uchun bonus: 300 so'm\n"
                "• Minimal yechish: 2,000 so'm\n"
                "• To'lov vaqti: 1-24 soat\n\n"
                "<i>Do'stlaringizni taklif qiling va ko'proq pul ishlang!</i>")
                
        elif text == "👤 Adminga murojaat":
            markup = types.InlineKeyboardMarkup()
            url = f"https://t.me/{ADMIN_USERNAME[1:]}" if ADMIN_USERNAME else f"https://t.me/{ADMIN_ID}"
            markup.add(types.InlineKeyboardButton("✉️ Adminga yozish", url=url))
            safe_send_message(uid, 
                "<b>👤 Adminga murojaat</b>\n\n"
                "❓ <b>Savol yoki taklifingiz bormi?</b>\n\n"
                "📞 Quyidagi tugma orqali adminga yozishingiz mumkin:\n"
                "• Hisob muammolari\n"
                "• To'lov masalahari\n"
                "• Taklif va shikoyatlar\n"
                "• Boshqa savollar", 
                reply_markup=markup)
                
        elif text == "📦 To'lovlar kanali":
            markup = types.InlineKeyboardMarkup()
            url = f"https://t.me/{PAYMENTS_INFO[1:]}" if PAYMENTS_INFO.startswith("@") else f"https://t.me/{PAYMENTS_INFO}"
            markup.add(types.InlineKeyboardButton("📦 Kanalga o'tish", url=url))
            safe_send_message(uid, 
                "<b>📦 To'lovlar kanali</b>\n\n"
                "💰 <b>To'lovlar kanaliga obuna bo'ling:</b>\n"
                "• Barcha to'lovlar haqida ma'lumot\n"
                "• Yangi yangiliklar\n"
                "• Aksiyalar va bonuslar\n"
                "• Muhim e'lonlar\n\n"
                "<i>Kanalda barcha to'lovlar tasdiqlanadi!</i>", 
                reply_markup=markup)
                
        elif text == "ℹ️ Yordam":
            safe_send_message(uid,
                "<b>ℹ️ Yordam va Ko'p so'raladigan savollar</b>\n\n"
                "❓ <b>Qanday pul ishlayman?</b>\n"
                "• Referal havola orqali do'stlaringizni taklif qiling\n"
                "• Har bir do'st uchun 300 so'm bonus olasiz\n\n"
                "❓ <b>Pulni qanday yechaman?</b>\n"
                "• Balansingiz kamida 2,000 so'm bo'lishi kerak\n"
                "• Karta raqami yoki telefon raqamingizni kiriting\n"
                "• To'lov 1-24 soat ichida amalga oshiriladi\n\n"
                "❓ <b>Bonus qachon beriladi?</b>\n"
                "• Do'stingiz botga kirganda\n"
                "• U kanallarga obuna bo'lganda\n"
                "• Bonus avtomatik hisoblanadi\n\n"
                "📞 <b>Qo'shimcha savollar?</b>\n"
                "Adminga murojaat qiling!"
            )
                
        else:
            show_menu(uid)
            
    except Exception as e:
        logging.error(f"Menu xatosi: {e}")
        safe_send_message(uid, "❌ Xatolik yuz berdi.")
        show_menu(uid)

# === CALLBACK HANDLERLARI ===
@bot.callback_query_handler(func=lambda c: c.data in ["confirm_withdraw", "cancel_withdraw"])
def handle_withdraw_confirm(call):
    uid = call.from_user.id
    u = get_user(uid)
    try:
        if "pending_withdraw" not in u:
            bot.answer_callback_query(call.id, "⚠️ So'rov mavjud emas.")
            return

        if call.data == "cancel_withdraw":
            u.pop("pending_withdraw", None)
            u.pop("withdraw_type", None)
            u.pop("pending_account", None)
            save_data()
            bot.answer_callback_query(call.id, "❌ So'rov bekor qilindi.")
            bot.edit_message_text("❌ So'rov bekor qilindi.", uid, call.message.message_id)
            show_menu(uid)
            return

        # Tasdiqlash bosilganda
        amount = u.get("pending_withdraw")
        withdraw_type = u.get("withdraw_type")
        account = u.get("pending_account")
        user_display = get_user_display(u, uid)

        if withdraw_type == "card":
            type_text = "💳 Karta orqali"
            account_text = f"💳 Karta: <code>{account}</code>"
        else:
            type_text = "📱 Telefon orqali"
            account_text = f"📱 Telefon: <code>{account}</code>"

        # KANALGA XABAR YUBORAMIZ
        msg_text = (
            f"💸 <b>YANGI PUL YECHISH SO'ROVI</b>\n"
            f"┌─────────────────────────\n"
            f"├ 👤 Foydalanuvchi: {user_display}\n"
            f"├ 💰 Summa: <code>{fmt_curr(amount)}</code>\n"
            f"├ {account_text}\n"
            f"├ 📊 Balans: <code>{fmt_curr(u['balans'])}</code>\n"
            f"├ ⏰ Vaqt: <code>{datetime.now().strftime('%H:%M:%S')}</code>\n"
            f"└─────────────────────────"
        )

        markup_channel = types.InlineKeyboardMarkup()
        markup_channel.add(
            types.InlineKeyboardButton("✅ To'landi", callback_data=f"paid_{uid}_{amount}"),
            types.InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancelpay_{uid}_{amount}")
        )

        # KANALGA XABAR YUBORISH
        channel_result = safe_send_channel(PAYMENTS_CHANNEL, msg_text, reply_markup=markup_channel)
        
        # Foydalanuvchiga xabar yuboramiz
        if channel_result:
            bot.edit_message_text(
                f"✅ <b>So'rovingiz adminga yuborildi!</b>\n\n"
                f"💰 Summa: <code>{fmt_curr(amount)}</code>\n"
                f"{account_text}\n\n"
                f"⏰ <i>To'lov 1-24 soat ichida amalga oshiriladi</i>", 
                uid, call.message.message_id)
        else:
            bot.edit_message_text(
                f"⚠️ <b>So'rovingiz adminga yuborildi, lekin kanalga xabar yuborish muvaffaqiyatsiz</b>\n\n"
                f"💰 Summa: <code>{fmt_curr(amount)}</code>\n"
                f"{account_text}\n\n"
                f"⏰ <i>To'lov 1-24 soat ichida amalga oshiriladi</i>", 
                uid, call.message.message_id)

        bot.answer_callback_query(call.id, "✅ So'rovingiz adminga yuborildi!")
        
        # Holatni menu ga o'zgartirish va menyuni ko'rsatish
        _states[str(uid)] = "menu"
        show_menu(uid)

    except Exception as e:
        logging.error(f"Withdraw confirm xatosi: {e}")
        bot.answer_callback_query(call.id, "❌ Xatolik yuz berdi.")
        _states[str(uid)] = "menu"
        show_menu(uid)

@bot.callback_query_handler(func=lambda c: c.data.startswith(("paid_", "cancelpay_")))
def handle_payment_action(call):
    try:
        parts = call.data.split("_")
        action = parts[0]
        uid = int(parts[1])
        amount = int(parts[2])
    except Exception:
        bot.answer_callback_query(call.id, "❌ Xato ma'lumot.")
        return

    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Ruxsat yo'q.")
        return

    user = get_user(uid)
    if not user:
        bot.answer_callback_query(call.id, "❌ Foydalanuvchi topilmadi.")
        return

    if action == "paid":
        bot.answer_callback_query(call.id, "✅ To'lov tasdiqlandi.")
        new_balance = subtract_balance(uid, amount, "Pul yechish")
        
        if new_balance != -1:
            user['spent'] = user.get('spent', 0) + amount
            user.pop('pending_withdraw', None)
            user.pop('withdraw_type', None)
            user.pop('pending_account', None)
            save_data()

            safe_send_message(uid,
                f"<b>✅ TO'LOV AMALGA OSHIRILDI</b>\n\n"
                f"💰 Summa: <code>{fmt_curr(amount)}</code>\n"
                f"📊 Yangi balans: <code>{fmt_curr(new_balance)}</code>\n\n"
                f"💸 <i>Pul tez orada tushadi!</i>"
            )
            
            # ASOSIY MENYUGA O'TISH
            _states[str(uid)] = "menu"
            show_menu(uid)

            user_display = get_user_display(user, uid)
            
            # FASTTOPORGCHEK KANALIGA XABAR
            safe_send_channel(PAYMENTS_INFO,
                f"<b>✅ TO'LOV TASDIQLANDI</b>\n"
                f"👤 Foydalanuvchi: {user_display}\n"
                f"💰 Summa: <code>{fmt_curr(amount)}</code>\n"
                f"📊 Yangi balans: <code>{fmt_curr(new_balance)}</code>\n"
                f"⏰ Vaqt: <code>{datetime.now().strftime('%H:%M:%S')}</code>"
            )

            try:
                new_text = call.message.text + "\n\n✅ <b>TO'LOV AMALGA OSHIRILDI</b>"
                bot.edit_message_text(new_text, chat_id=call.message.chat.id, message_id=call.message.message_id)
            except Exception:
                pass

    elif action == "cancelpay":
        bot.answer_callback_query(call.id, "❌ To'lov bekor qilindi.")
        user.pop('pending_withdraw', None)
        user.pop('withdraw_type', None)
        user.pop('pending_account', None)
        save_data()

        safe_send_message(uid, 
            f"❌ <b>TO'LOV BEKOR QILINDI</b>\n\n"
            f"💰 Summa: <code>{fmt_curr(amount)}</code>\n"
            f"📊 Joriy balans: <code>{fmt_curr(user['balans'])}</code>\n\n"
            f"ℹ️ <i>Sabab: Admin tomonidan bekor qilindi</i>")
            
        # ASOSIY MENYUGA O'TISH
        _states[str(uid)] = "menu"
        show_menu(uid)

        try:
            new_text = call.message.text + "\n\n❌ <b>TO'LOV BEKOR QILINDI</b>"
            bot.edit_message_text(new_text, chat_id=call.message.chat.id, message_id=call.message.message_id)
        except Exception:
            pass

# === FLASK API ===
@app.route("/")
def home():
    return jsonify({"status": "Bot is running", "users_count": len(_users)})

# === BARCHAGA XABAR YUBORISH ===
@app.route("/admin/broadcast", methods=["OPTIONS", "POST"])
def admin_broadcast():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    data = request.get_json(force=True)
    if data.get("secret_key") != ADMIN_SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    message = data.get("message")
    if not message:
        return jsonify({"success": False, "error": "Xabar matni yo'q"}), 400

    try:
        sent_count = 0
        total_users = len(_users)
        
        for user_id in _users:
            try:
                result = safe_send_message(int(user_id), message)
                if result:
                    sent_count += 1
                # Har 10 ta xabardan keyin biroz kutish (limitlardan qochish uchun)
                if sent_count % 10 == 0:
                    time.sleep(0.1)
            except Exception as e:
                logging.error(f"Foydalanuvchi {user_id} ga xabar yuborishda xato: {e}")
                continue

        # Kanalga xabar yuborish
        channel_msg = (
            f"📢 <b>BARCHAGA XABAR YUBORILDI</b>\n\n"
            f"💬 <b>Xabar:</b>\n{message}\n\n"
            f"👥 <b>Yuborildi:</b> {sent_count}/{total_users} foydalanuvchiga\n"
            f"⏰ <b>Vaqt:</b> {datetime.now().strftime('%H:%M:%S')}"
        )
        safe_send_channel(PAYMENTS_CHANNEL, channel_msg)

        return jsonify({
            "success": True,
            "sent_count": sent_count,
            "total_users": total_users,
            "message": f"Xabar {sent_count} foydalanuvchiga yuborildi"
        }), 200

    except Exception as e:
        logging.error(f"Broadcast xatosi: {e}")
        return jsonify({
            "success": False, 
            "error": f"Xabar yuborishda xato: {str(e)}"
        }), 500

# === KANALGA XABAR YUBORISH ===
@app.route("/admin/send_channel_message", methods=["OPTIONS", "POST"])
def admin_send_channel_message():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    data = request.get_json(force=True)
    if data.get("secret_key") != ADMIN_SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    message = data.get("message")
    channel = data.get("channel", PAYMENTS_CHANNEL)

    if not message:
        return jsonify({"success": False, "error": "Xabar matni yo'q"}), 400

    try:
        result = safe_send_channel(channel, message)
        if result:
            return jsonify({
                "success": True, 
                "message": f"Xabar {channel} kanaliga yuborildi",
                "message_id": result.message_id
            }), 200
        else:
            return jsonify({
                "success": False, 
                "error": f"Xabar {channel} kanaliga yuborish muvaffaqiyatsiz"
            }), 500
    except Exception as e:
        logging.error(f"Kanalga xabar yuborishda xato: {e}")
        return jsonify({
            "success": False, 
            "error": f"Xabar yuborishda xato: {str(e)}"
        }), 500

# === PUL YUBORISH ===
@app.route("/admin/add_balance", methods=["OPTIONS", "POST"])
def admin_add_balance_options():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    data = request.get_json(force=True)
    if data.get("secret_key") != ADMIN_SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    uid = data.get("user_id")
    try:
        amount = int(data.get("amount", 0))
    except Exception:
        return jsonify({"success": False, "error": "Invalid amount"}), 400
    
    if not uid or amount <= 0:
        return jsonify({"success": False, "error": "Invalid data"}), 400
    
    user = get_user(uid)
    new_balance = add_balance(uid, amount, "Admin tomonidan qo'shildi")
    
    if new_balance is None:
        return jsonify({"success": False, "error": "Xatolik yuz berdi"}), 500
    
    # Foydalanuvchiga xabar yuborish
    safe_send_message(int(uid),
        f"<b>💰 BALANSINGIZGA PUL QO'SHILDI</b>\n\n"
        f"💰 Qo'shilgan: <code>+{fmt_curr(amount)}</code>\n"
        f"📊 Yangi balans: <code>{fmt_curr(new_balance)}</code>\n"
        f"📅 Sana: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
        f"🎉 <i>Tabriklaymiz! Hisobingiz to'ldirildi</i>"
    )
    
    # KANALGA XABAR YUBORISH - YANGI FORMAT
    username = user.get("username", "Noma'lum")
    if username != "Noma'lum":
        user_display = f'<a href="https://t.me/{username}">@{username}</a>'
    else:
        user_display = f'<a href="tg://user?id={uid}">{uid}</a>'
    
    channel_message = (
        f"💰 <b>PUL QO'SHILDI</b>\n\n"
        f"👤 <b>Foydalanuvchi:</b> {user_display}\n"
        f"💵 <b>Qo'shildi:</b> +{fmt_curr(amount)}\n"
        f"📊 <b>Yangi balans:</b> {fmt_curr(new_balance)}\n"
        f"⏰ <b>Vaqt:</b> {datetime.now().strftime('%H:%M:%S')}"
    )
    
    channel_result = safe_send_channel(PAYMENTS_CHANNEL, channel_message)
    
    return jsonify({
        "success": True, 
        "new_balance": new_balance,
        "message": f"Foydalanuvchi {uid} ga {fmt_curr(amount)} qo'shildi",
        "channel_sent": channel_result is not None
    }), 200

# === PUL AYIRISH ===
@app.route("/admin/subtract_balance", methods=["OPTIONS", "POST"])
def admin_subtract_balance_options():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    data = request.get_json(force=True)
    if data.get("secret_key") != ADMIN_SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    uid = data.get("user_id")
    try:
        amount = int(data.get("amount", 0))
    except Exception:
        return jsonify({"success": False, "error": "Invalid amount"}), 400
    
    if not uid or amount <= 0:
        return jsonify({"success": False, "error": "Invalid data"}), 400
    
    user = get_user(uid)
    old_balance = user.get("balans", 0)
    
    if old_balance < amount:
        return jsonify({
            "success": False, 
            "error": f"Balans yetarli emas: {fmt_curr(old_balance)}"
        }), 400
    
    new_balance = subtract_balance(uid, amount, "Admin tomonidan ayirildi")
    
    if new_balance is None:
        return jsonify({"success": False, "error": "Xatolik yuz berdi"}), 500
    
    # Foydalanuvchiga xabar yuborish
    safe_send_message(int(uid),
        f"<b>❌ BALANSINGIZDAN PUL AYIRILDI</b>\n\n"
        f"💰 Ayirildi: <code>-{fmt_curr(amount)}</code>\n"
        f"📊 Yangi balans: <code>{fmt_curr(new_balance)}</code>\n"
        f"📅 Sana: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
        f"ℹ️ <i>Sabab: Admin tomonidan amalga oshirildi</i>"
    )
    
    # KANALGA XABAR YUBORISH - YANGI FORMAT
    username = user.get("username", "Noma'lum")
    if username != "Noma'lum":
        user_display = f'<a href="https://t.me/{username}">@{username}</a>'
    else:
        user_display = f'<a href="tg://user?id={uid}">{uid}</a>'
    
    channel_message = (
        f"❌ <b>PUL AYIRILDI</b>\n\n"
        f"👤 <b>Foydalanuvchi:</b> {user_display}\n"
        f"💵 <b>Ayirildi:</b> -{fmt_curr(amount)}\n"
        f"📊 <b>Yangi balans:</b> {fmt_curr(new_balance)}\n"
        f"⏰ <b>Vaqt:</b> {datetime.now().strftime('%H:%M:%S')}"
    )
    
    channel_result = safe_send_channel(PAYMENTS_CHANNEL, channel_message)
    
    return jsonify({
        "success": True, 
        "new_balance": new_balance,
        "message": f"Foydalanuvchi {uid} dan {fmt_curr(amount)} ayirildi",
        "channel_sent": channel_result is not None
    }), 200

# === BIR KISHIGA XABAR YUBORISH ===
@app.route("/admin/send_to_user", methods=["OPTIONS", "POST"])
def admin_send_to_user():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    data = request.get_json(force=True)
    if data.get("secret_key") != ADMIN_SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    user_id = data.get("user_id")
    message = data.get("message")

    if not user_id or not message:
        return jsonify({"success": False, "error": "User ID va xabar matni kerak"}), 400

    try:
        user = get_user(user_id)
        result = safe_send_message(int(user_id), message)
        if result:
            # Kanalga xabar yuborish
            username = user.get("username", "Noma'lum")
            if username != "Noma'lum":
                user_display = f'<a href="https://t.me/{username}">@{username}</a>'
            else:
                user_display = f'<a href="tg://user?id={user_id}">{user_id}</a>'
                
            channel_msg = (
                f"📨 <b>BIR KISHIGA XABAR</b>\n\n"
                f"👤 <b>Foydalanuvchi:</b> {user_display}\n"
                f"💬 <b>Xabar:</b>\n{message}\n\n"
                f"⏰ <b>Vaqt:</b> {datetime.now().strftime('%H:%M:%S')}"
            )
            safe_send_channel(PAYMENTS_CHANNEL, channel_msg)
            
            return jsonify({
                "success": True, 
                "message": f"Xabar foydalanuvchi {user_id} ga yuborildi"
            }), 200
        else:
            return jsonify({
                "success": False, 
                "error": f"Xabar {user_id} ga yuborish muvaffaqiyatsiz"
            }), 500
    except Exception as e:
        logging.error(f"Foydalanuvchiga xabar yuborishda xato: {e}")
        return jsonify({
            "success": False, 
            "error": f"Xabar yuborishda xato: {str(e)}"
        }), 500

# === FOYDALANUVCHI MA'LUMOTLARI ===
@app.route("/admin/user_info", methods=["GET", "OPTIONS"])
def admin_user_info():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    if request.args.get("secret_key") != ADMIN_SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "User ID yo'q"}), 400

    try:
        user = get_user(user_id)
        if not user:
            return jsonify({"success": False, "error": "Foydalanuvchi topilmadi"}), 404

        # Kanalga xabar yuborish
        username = user.get("username", "Noma'lum")
        if username != "Noma'lum":
            user_display = f'<a href="https://t.me/{username}">@{username}</a>'
        else:
            user_display = f'<a href="tg://user?id={user_id}">{user_id}</a>'
            
        channel_msg = (
            f"👤 <b>FOYDALANUVCHI MA'LUMOTLARI</b>\n\n"
            f"👤 <b>Foydalanuvchi:</b> {user_display}\n"
            f"💰 <b>Balans:</b> {fmt_curr(user.get('balans', 0))}\n"
            f"💸 <b>Yechilgan:</b> {fmt_curr(user.get('spent', 0))}\n"
            f"👥 <b>Referallar:</b> {len(user.get('referallar', []))} ta\n\n"
            f"⏰ <b>Vaqt:</b> {datetime.now().strftime('%H:%M:%S')}"
        )
        safe_send_channel(PAYMENTS_CHANNEL, channel_msg)

        return jsonify({
            "success": True,
            "user": {
                "id": user_id,
                "username": user.get("username", "Noma'lum"),
                "balance": fmt_curr(user.get("balans", 0)),
                "withdrawn": fmt_curr(user.get("spent", 0)),
                "referrals": len(user.get("referallar", [])),
                "joined_date": user.get("joined_date", "Noma'lum"),
                "total_earned": fmt_curr(user.get("total_earned", 0)),
                "total_withdrawn": fmt_curr(user.get("total_withdrawn", 0)),
                "last_active": user.get("last_active", "Noma'lum")
            }
        }), 200
    except Exception as e:
        logging.error(f"Foydalanuvchi ma'lumotlarini olishda xato: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# === KANALLARNI O'QISH ===
@app.route("/admin/get_channel", methods=["GET", "OPTIONS"])
def admin_get_channel():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    if request.args.get("secret_key") != ADMIN_SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    return jsonify({
        "success": True,
        "channels": REQUIRED_CHANNELS
    }), 200

# === KANALLARNI SAQLASH ===
@app.route("/admin/set_channel", methods=["OPTIONS", "POST"])
def admin_set_channel():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    data = request.get_json(force=True)
    if data.get("secret_key") != ADMIN_SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    channels = data.get("channels", [])
    if not isinstance(channels, list):
        return jsonify({"success": False, "error": "Channels must be a list"}), 400

    # Faqat @ bilan boshlanadigan kanallarni saqlaymiz
    valid_channels = [ch for ch in channels if isinstance(ch, str) and ch.startswith("@")]
    
    # Maksimal 5 ta kanal
    if len(valid_channels) > 5:
        valid_channels = valid_channels[:5]

    global REQUIRED_CHANNELS
    REQUIRED_CHANNELS = valid_channels
    save_settings()

    # Kanalga xabar yuborish
    channel_msg = (
        f"🔗 <b>MAJBURIY KANALLAR YANGILANDI</b>\n\n"
        f"📋 <b>Yangi kanallar:</b>\n" + "\n".join([f"• {ch}" for ch in valid_channels]) + f"\n\n"
        f"👥 <b>Jami:</b> {len(valid_channels)} ta kanal\n"
        f"⏰ <b>Vaqt:</b> {datetime.now().strftime('%H:%M:%S')}"
    )
    safe_send_channel(PAYMENTS_CHANNEL, channel_msg)

    return jsonify({
        "success": True,
        "channels": REQUIRED_CHANNELS,
        "message": f"{len(valid_channels)} ta kanal saqlandi"
    }), 200

# === STATISTIKA ===
@app.route("/admin/stats", methods=["GET", "OPTIONS"])
def admin_stats():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    
    if request.args.get("secret_key") != ADMIN_SECRET_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    try:
        total_users = len(_users)
        active_users = 0
        total_balance = 0
        total_withdrawn = 0
        total_earned = 0
        total_referrals = 0

        for user_data in _users.values():
            total_balance += user_data.get("balans", 0)
            total_withdrawn += user_data.get("total_withdrawn", 0)
            total_earned += user_data.get("total_earned", 0)
            total_referrals += len(user_data.get("referallar", []))

        # Kanalga xabar yuborish
        channel_msg = (
            f"📊 <b>BOT STATISTIKASI</b>\n\n"
            f"👥 <b>Foydalanuvchilar:</b> {total_users} ta\n"
            f"💰 <b>Umumiy balans:</b> {fmt_curr(total_balance)}\n"
            f"💸 <b>Yechilgan summa:</b> {fmt_curr(total_withdrawn)}\n"
            f"📈 <b>Umumiy topilgan:</b> {fmt_curr(total_earned)}\n"
            f"👥 <b>Jami referallar:</b> {total_referrals} ta\n\n"
            f"⏰ <b>Vaqt:</b> {datetime.now().strftime('%H:%M:%S')}"
        )
        safe_send_channel(PAYMENTS_CHANNEL, channel_msg)

        return jsonify({
            "success": True,
            "total_users": total_users,
            "active_users": active_users,
            "total_balance": total_balance,
            "total_withdrawn": total_withdrawn,
            "total_earned": total_earned,
            "total_referrals": total_referrals,
            "formatted": {
                "total_balance": fmt_curr(total_balance),
                "total_withdrawn": fmt_curr(total_withdrawn),
                "total_earned": fmt_curr(total_earned)
            }
        }), 200

    except Exception as e:
        logging.error(f"Statistika olishda xato: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# === HTML ADMIN PANEL ===
@app.route("/admin", methods=["GET"])
def admin_panel():
    return """
<!doctype html>
<html lang="uz">
<head>
  <meta charset="utf-8">
  <title>🤖 Bot Admin Panel</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      min-height: 100vh;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    .navbar-brand {
      font-weight: bold;
    }
    .card {
      border: none;
      border-radius: 15px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.1);
      transition: transform 0.3s ease;
    }
    .card:hover {
      transform: translateY(-5px);
    }
    .btn-primary {
      background: linear-gradient(45deg, #667eea, #764ba2);
      border: none;
      border-radius: 10px;
    }
    .btn-success {
      background: linear-gradient(45deg, #56ab2f, #a8e6cf);
      border: none;
      border-radius: 10px;
    }
    .btn-danger {
      background: linear-gradient(45deg, #ff6b6b, #ee5a52);
      border: none;
      border-radius: 10px;
    }
    .stat-card {
      background: white;
      border-radius: 15px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 5px 15px rgba(0,0,0,0.1);
    }
    .form-control {
      border-radius: 10px;
      border: 2px solid #e9ecef;
      padding: 12px 15px;
    }
    .form-control:focus {
      border-color: #667eea;
      box-shadow: 0 0 0 0.2rem rgba(102, 126, 234, 0.25);
    }
  </style>
</head>
<body>
  <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
    <div class="container">
      <a class="navbar-brand" href="#">
        <i class="fas fa-robot"></i> Bot Admin Panel
      </a>
    </div>
  </nav>

  <div class="container mt-4">
    <div class="row">
      <div class="col-md-3">
        <div class="card mb-4">
          <div class="card-body">
            <h5 class="card-title">📊 Statistika</h5>
            <div id="statsInfo">
              <p>Yuklanmoqda...</p>
            </div>
            <button class="btn btn-primary w-100 mt-3" onclick="loadStats()">
              <i class="fas fa-sync-alt"></i> Yangilash
            </button>
          </div>
        </div>

        <div class="card">
          <div class="card-body">
            <h5 class="card-title">⚙️ Sozlamalar</h5>
            <div class="mb-3">
              <label class="form-label">Kanal ID si</label>
              <input type="text" class="form-control" id="channelInput" placeholder="@channel">
            </div>
            <button class="btn btn-success w-100 mb-2" onclick="addChannel()">
              <i class="fas fa-plus"></i> Kanal qo'shish
            </button>
            <button class="btn btn-info w-100 mb-2" onclick="getChannels()">
              <i class="fas fa-list"></i> Kanallarni ko'rish
            </button>
            <button class="btn btn-warning w-100" onclick="clearChannels()">
              <i class="fas fa-trash"></i> Kanallarni tozalash
            </button>
          </div>
        </div>
      </div>

      <div class="col-md-9">
        <div class="card mb-4">
          <div class="card-body">
            <h5 class="card-title">📢 Barchaga xabar yuborish</h5>
            <div class="mb-3">
              <textarea class="form-control" id="broadcastMessage" rows="4" placeholder="Xabar matnini kiriting..."></textarea>
            </div>
            <button class="btn btn-primary w-100" onclick="sendBroadcast()">
              <i class="fas fa-paper-plane"></i> Xabarni yuborish
            </button>
          </div>
        </div>

        <div class="row">
          <div class="col-md-6">
            <div class="card mb-4">
              <div class="card-body">
                <h5 class="card-title">💰 Pul qo'shish</h5>
                <div class="mb-3">
                  <input type="number" class="form-control" id="addUserId" placeholder="Foydalanuvchi ID">
                </div>
                <div class="mb-3">
                  <input type="number" class="form-control" id="addAmount" placeholder="Summa">
                </div>
                <button class="btn btn-success w-100" onclick="addBalance()">
                  <i class="fas fa-plus-circle"></i> Pul qo'shish
                </button>
              </div>
            </div>
          </div>

          <div class="col-md-6">
            <div class="card mb-4">
              <div class="card-body">
                <h5 class="card-title">💸 Pul ayirish</h5>
                <div class="mb-3">
                  <input type="number" class="form-control" id="subtractUserId" placeholder="Foydalanuvchi ID">
                </div>
                <div class="mb-3">
                  <input type="number" class="form-control" id="subtractAmount" placeholder="Summa">
                </div>
                <button class="btn btn-danger w-100" onclick="subtractBalance()">
                  <i class="fas fa-minus-circle"></i> Pul ayirish
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="card mb-4">
          <div class="card-body">
            <h5 class="card-title">👤 Bir kishiga xabar</h5>
            <div class="row">
              <div class="col-md-6">
                <div class="mb-3">
                  <input type="number" class="form-control" id="singleUserId" placeholder="Foydalanuvchi ID">
                </div>
              </div>
              <div class="col-md-6">
                <div class="mb-3">
                  <textarea class="form-control" id="singleMessage" rows="2" placeholder="Xabar matni..."></textarea>
                </div>
              </div>
            </div>
            <button class="btn btn-info w-100" onclick="sendToUser()">
              <i class="fas fa-user"></i> Xabarni yuborish
            </button>
          </div>
        </div>

        <div class="card">
          <div class="card-body">
            <h5 class="card-title">🔍 Foydalanuvchi ma'lumotlari</h5>
            <div class="row">
              <div class="col-md-8">
                <div class="mb-3">
                  <input type="number" class="form-control" id="searchUserId" placeholder="Foydalanuvchi ID">
                </div>
              </div>
              <div class="col-md-4">
                <button class="btn btn-primary w-100" onclick="getUserInfo()">
                  <i class="fas fa-search"></i> Qidirish
                </button>
              </div>
            </div>
            <div id="userInfo"></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const SECRET_KEY = "yangieskibot";
    const API_BASE = window.location.origin;

    async function apiCall(endpoint, data = null) {
      const options = {
        method: data ? 'POST' : 'GET',
        headers: {
          'Content-Type': 'application/json',
        }
      };
      
      if (data) {
        options.body = JSON.stringify({...data, secret_key: SECRET_KEY});
      } else {
        endpoint += `?secret_key=${SECRET_KEY}`;
      }

      try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        return await response.json();
      } catch (error) {
        console.error('API xatosi:', error);
        alert('Xatolik yuz berdi: ' + error.message);
        return {success: false, error: error.message};
      }
    }

    function showAlert(message, type = 'success') {
      const alert = document.createElement('div');
      alert.className = `alert alert-${type} alert-dismissible fade show mt-3`;
      alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
      `;
      document.querySelector('.container').prepend(alert);
      setTimeout(() => alert.remove(), 5000);
    }

    // Funksiyalar
    async function loadStats() {
      const result = await apiCall('/admin/stats');
      if (result.success) {
        document.getElementById('statsInfo').innerHTML = `
          <p><strong>👥 Foydalanuvchilar:</strong> ${result.total_users} ta</p>
          <p><strong>💰 Umumiy balans:</strong> ${result.formatted.total_balance}</p>
          <p><strong>💸 Yechilgan:</strong> ${result.formatted.total_withdrawn}</p>
          <p><strong>📈 Topilgan:</strong> ${result.formatted.total_earned}</p>
          <p><strong>👥 Referallar:</strong> ${result.total_referrals} ta</p>
        `;
        showAlert('Statistika yangilandi!');
      }
    }

    async function sendBroadcast() {
      const message = document.getElementById('broadcastMessage').value;
      if (!message) {
        alert('Xabar matnini kiriting!');
        return;
      }

      const result = await apiCall('/admin/broadcast', {message});
      if (result.success) {
        showAlert(`Xabar ${result.sent_count} foydalanuvchiga yuborildi!`);
        document.getElementById('broadcastMessage').value = '';
      }
    }

    async function addBalance() {
      const userId = document.getElementById('addUserId').value;
      const amount = document.getElementById('addAmount').value;
      
      if (!userId || !amount) {
        alert('Foydalanuvchi ID va summani kiriting!');
        return;
      }

      const result = await apiCall('/admin/add_balance', {user_id: userId, amount: parseInt(amount)});
      if (result.success) {
        showAlert(`Foydalanuvchi ${userId} ga ${result.message}`);
        document.getElementById('addUserId').value = '';
        document.getElementById('addAmount').value = '';
      }
    }

    async function subtractBalance() {
      const userId = document.getElementById('subtractUserId').value;
      const amount = document.getElementById('subtractAmount').value;
      
      if (!userId || !amount) {
        alert('Foydalanuvchi ID va summani kiriting!');
        return;
      }

      const result = await apiCall('/admin/subtract_balance', {user_id: userId, amount: parseInt(amount)});
      if (result.success) {
        showAlert(`Foydalanuvchi ${userId} dan ${result.message}`);
        document.getElementById('subtractUserId').value = '';
        document.getElementById('subtractAmount').value = '';
      }
    }

    async function sendToUser() {
      const userId = document.getElementById('singleUserId').value;
      const message = document.getElementById('singleMessage').value;
      
      if (!userId || !message) {
        alert('Foydalanuvchi ID va xabar matnini kiriting!');
        return;
      }

      const result = await apiCall('/admin/send_to_user', {user_id: userId, message});
      if (result.success) {
        showAlert(result.message);
        document.getElementById('singleUserId').value = '';
        document.getElementById('singleMessage').value = '';
      }
    }

    async function getUserInfo() {
      const userId = document.getElementById('searchUserId').value;
      if (!userId) {
        alert('Foydalanuvchi ID ni kiriting!');
        return;
      }

      const result = await apiCall(`/admin/user_info?user_id=${userId}`);
      if (result.success) {
        document.getElementById('userInfo').innerHTML = `
          <div class="stat-card">
            <p><strong>👤 Username:</strong> ${result.user.username}</p>
            <p><strong>💰 Balans:</strong> ${result.user.balance}</p>
            <p><strong>💸 Yechilgan:</strong> ${result.user.withdrawn}</p>
            <p><strong>👥 Referallar:</strong> ${result.user.referrals} ta</p>
            <p><strong>📅 Qo'shilgan:</strong> ${result.user.joined_date}</p>
            <p><strong>📈 Umumiy topilgan:</strong> ${result.user.total_earned}</p>
            <p><strong>💸 Umumiy yechilgan:</strong> ${result.user.total_withdrawn}</p>
            <p><strong>⏰ Oxirgi faollik:</strong> ${result.user.last_active}</p>
          </div>
        `;
      }
    }

    async function addChannel() {
      const channel = document.getElementById('channelInput').value;
      if (!channel.startsWith('@')) {
        alert('Kanal @ bilan boshlanishi kerak!');
        return;
      }

      const currentChannels = await apiCall('/admin/get_channel');
      let channels = currentChannels.channels || [];
      channels.push(channel);
      
      const result = await apiCall('/admin/set_channel', {channels});
      if (result.success) {
        showAlert('Kanal qo\'shildi!');
        document.getElementById('channelInput').value = '';
      }
    }

    async function getChannels() {
      const result = await apiCall('/admin/get_channel');
      if (result.success) {
        alert('Mavjud kanallar:\n' + result.channels.join('\n'));
      }
    }

    async function clearChannels() {
      if (confirm('Barcha kanallarni o\'chirishni tasdiqlaysizmi?')) {
        const result = await apiCall('/admin/set_channel', {channels: []});
        if (result.success) {
          showAlert('Barcha kanallar o\'chirildi!');
        }
      }
    }

    // Dastlabki statistika yuklash
    loadStats();
  </script>
</body>
</html>
    """

# === SERVER ISHGA TUSHIRISH ===
def run_flask():
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    load_data()
    load_settings()

    try:
        me = bot.get_me()
        bot_username = me.username
        logging.info(f"Bot username: {bot_username}")
    except Exception as e:
        logging.error(f"Bot ma'lumotini olishda xato: {e}")

    Thread(target=run_flask, daemon=True).start()
    logging.info("Bot va Flask server ishga tushdi...")

    bot.infinity_polling(timeout=60, long_polling_timeout=60)