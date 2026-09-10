import os
import html
import random
import time
import sqlite3
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# ----------------- تنظیمات توکن -----------------
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
bot = telebot.TeleBot(BOT_TOKEN)

# ----------------- دیتابیس (SQLite) -----------------
DB_NAME = "database.db"

def init_db():
    """ایجاد جدول کاربران در صورت عدم وجود"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                height INTEGER DEFAULT 0,
                last_grow REAL DEFAULT 0
            )
        """)
        conn.commit()

def get_user(user_id, first_name="", username=""):
    """دریافت اطلاعات کاربر یا ثبت نام جدید"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, first_name, username, height, last_grow FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row:
            cursor.execute("UPDATE users SET first_name = ?, username = ? WHERE user_id = ?", (first_name, username, user_id))
            conn.commit()
            return {"user_id": row[0], "first_name": first_name or row[1], "username": username or row[2], "height": row[3], "last_grow": row[4]}
        else:
            cursor.execute("INSERT INTO users (user_id, first_name, username, height, last_grow) VALUES (?, ?, ?, 0, 0)", (user_id, first_name, username))
            conn.commit()
            return {"user_id": user_id, "first_name": first_name, "username": username, "height": 0, "last_grow": 0}

def update_height(user_id, amount):
    """تغییر قد کاربر (افزایش یا کاهش)"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET height = MAX(0, height + ?) WHERE user_id = ?", (amount, user_id))
        conn.commit()

def set_grow_time(user_id, timestamp):
    """ثبت زمان آخرین رشد"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_grow = ? WHERE user_id = ?", (timestamp, user_id))
        conn.commit()

def get_top_users(limit=10):
    """دریافت لیست برترین کاربران"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT first_name, height FROM users ORDER BY height DESC LIMIT ?", (limit,))
        return cursor.fetchall()

# راه‌اندازی اولیه دیتابیس
init_db()

# متغیر موقت برای مدیریت درخواست‌های فعال نبرد
active_fights = {}

# ----------------- دستورات ربات -----------------

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    help_text = (
        "👑 **به ربات بازی خوش آمدید!**\n\n"
        "📜 **دستورات:**\n"
        "🔹 `/grow` - افزایش قد تصادفی (هر ۱۲ ساعت)\n"
        "🔹 `/fight <مقدار>` - شرط‌بندی و نبرد تاس با دیگران\n"
        "🔹 `/top` - جدول ۱۰ نفر اول بازی\n"
        "🔹 `/myheight` - مشاهده قد فعلی شما"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['myheight'])
def check_height(message):
    user = get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    bot.reply_to(message, f"📏 قد فعلی شما: **{user['height']} سانتی‌متر**", parse_mode="Markdown")

@bot.message_handler(commands=['grow'])
def grow_cmd(message):
    user = get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    now = time.time()
    cooldown = 12 * 3600  # ۱۲ ساعت
    
    if now - user['last_grow'] < cooldown:
        rem_time = int(cooldown - (now - user['last_grow']))
        hours = rem_time // 3600
        mins = (rem_time % 3600) // 60
        bot.reply_to(message, f"⏳ شما قبلاً رشد کرده‌اید! لطفاً **{hours} ساعت و {mins} دقیقه** دیگر دوباره امتحان کنید.")
        return

    added = random.randint(1, 30)
    update_height(user['user_id'], added)
    set_grow_time(user['user_id'], now)
    
    bot.reply_to(message, f"🌱 ماشاالله! قد شما **+{added} سانتی‌متر** رشد کرد!\n📏 قد فعلی: **{user['height'] + added} سانتی‌متر**", parse_mode="Markdown")

@bot.message_handler(commands=['top'])
def top_players(message):
    top_list = get_top_users(10)
    if not top_list:
        bot.reply_to(message, "هنوز رکوردی ثبت نشده است.")
        return
    
    text = "🏆 **جدول برترین‌های بازی:**\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    for i, (name, height) in enumerate(top_list):
        safe_name = html.escape(name or "کاربر بی نام")
        text += f"{medals[i]} {i+1}. {safe_name} ➔ **{height} cm**\n"
        
    bot.reply_to(message, text, parse_mode="HTML")

@bot.message_handler(commands=['fight'])
def create_fight(message):
    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, "⚠️ این دستور فقط در گروه‌ها کار می‌کند!")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        bot.reply_to(message, "❌ فرمت نادرست! مثال: `/fight 20` (شرط‌بندی ۲۰ سانتی‌متر)", parse_mode="Markdown")
        return

    amount = int(args[1])
    if amount <= 0:
        bot.reply_to(message, "❌ مقدار شرط باید بزرگتر از صفر باشد.")
        return

    user = get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    if user['height'] < amount:
        bot.reply_to(message, f"❌ شما قد کافی ندارید! قد شما: {user['height']} سانتی‌متر")
        return

    markup = InlineKeyboardMarkup()
    btn = InlineKeyboardButton(text=f"⚔️ قبول چالش ({amount} cm)", callback_data=f"accept_{message.from_user.id}_{amount}")
    markup.add(btn)

    safe_name = html.escape(message.from_user.first_name)
    msg = bot.send_message(
        message.chat.id,
        f"🥊 <b>{safe_name}</b> چالش مبارزه با شرط <b>{amount} سانتی‌متر</b> راه انداخت!\nچه کسی جرئت رقابت دارد؟",
        reply_markup=markup,
        parse_mode="HTML"
    )
    
    active_fights[msg.message_id] = {
        "p1_id": message.from_user.id,
        "p1_name": safe_name,
        "amount": amount,
        "status": "pending"
    }

@bot.callback_query_handler(func=lambda call: call.data.startswith("accept_"))
def accept_fight(call):
    _, p1_id, amount = call.data.split("_")
    p1_id = int(p1_id)
    amount = int(amount)
    p2_id = call.from_user.id

    if p2_id == p1_id:
        bot.answer_callback_query(call.id, "❌ نمی‌توانید با خودتان مبارزه کنید!", show_alert=True)
        return

    p2 = get_user(p2_id, call.from_user.first_name, call.from_user.username)
    if p2['height'] < amount:
        bot.answer_callback_query(call.id, f"❌ قد شما کافی نیست! (حداقل {amount} سانتی‌متر نیاز است)", show_alert=True)
        return

    p1 = get_user(p1_id)
    if p1['height'] < amount:
        bot.answer_callback_query(call.id, "❌ سازنده چالش دیگر قد کافی ندارد!", show_alert=True)
        return

    msg_id = call.message.message_id
    if msg_id in active_fights:
        active_fights[msg_id]["p2_id"] = p2_id
        active_fights[msg_id]["p2_name"] = html.escape(call.from_user.first_name)
        active_fights[msg_id]["status"] = "rolling"
        active_fights[msg_id]["p1_score"] = None
        active_fights[msg_id]["p2_score"] = None

    p1_name = active_fights[msg_id]["p1_name"]
    p2_name = active_fights[msg_id]["p2_name"]

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=msg_id,
        text=(
            f"🔥 نبرد بین <b>{p1_name}</b> و <b>{p2_name}</b> با شرط <b>{amount} سانتی‌متر</b> آغاز شد!\n\n"
            f"🎲 هر دو بازیکن باید ایموجی 🎲 را <b>روی همین پیام ریپلای</b> کنند."
        ),
        parse_mode="HTML"
    )

@bot.message_handler(content_types=['dice'])
def handle_dice(message):
    if not message.reply_to_message:
        return

    target_msg_id = message.reply_to_message.message_id
    if target_msg_id not in active_fights:
        return

    fight = active_fights[target_msg_id]
    if fight["status"] != "rolling":
        return

    sender_id = message.from_user.id
    dice_val = message.dice.value

    if sender_id == fight["p1_id"] and fight["p1_score"] is None:
        fight["p1_score"] = dice_val
        bot.reply_to(message, f"🎯 تاس {fight['p1_name']}: **{dice_val}**", parse_mode="Markdown")
    elif sender_id == fight["p2_id"] and fight["p2_score"] is None:
        fight["p2_score"] = dice_val
        bot.reply_to(message, f"🎯 تاس {fight['p2_name']}: **{dice_val}**", parse_mode="Markdown")

    if fight["p1_score"] is not None and fight["p2_score"] is not None:
        p1_score = fight["p1_score"]
        p2_score = fight["p2_score"]
        amount = fight["amount"]

        if p1_score > p2_score:
            winner_id, winner_name = fight["p1_id"], fight["p1_name"]
            loser_id, loser_name = fight["p2_id"], fight["p2_name"]
        elif p2_score > p1_score:
            winner_id, winner_name = fight["p2_id"], fight["p2_name"]
            loser_id, loser_name = fight["p1_id"], fight["p1_name"]
        else:
            bot.send_message(message.chat.id, f"🤝 نتیجه مساوی شد ({p1_score} - {p2_score})! هیچ قدی کم یا زیاد نشد.")
            del active_fights[target_msg_id]
            return

        update_height(winner_id, amount)
        update_height(loser_id, -amount)

        result_text = (
            f"🏆 <b>{winner_name}</b> با نتیجه ({max(p1_score, p2_score)} به {min(p1_score, p2_score)}) پیروز شد!\n\n"
            f"➕ <b>+{amount} cm</b> به {winner_name} اضافه شد.\n"
            f"➖ <b>-{amount} cm</b> از {loser_name} کسر شد."
        )
        bot.send_message(message.chat.id, result_text, parse_mode="HTML")
        del active_fights[target_msg_id]

# ----------------- اجرای ربات -----------------
if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling()
