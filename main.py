import os
import html
import random
import time
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# ----------------- تنظیمات توکن -----------------
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
bot = telebot.TeleBot(BOT_TOKEN)

# ----------------- دیتابیس (SQLite) -----------------
DB_NAME = "database.db"

def init_db():
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
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, first_name, username, height, last_grow FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        clean_username = username.lstrip('@') if username else ""
        if row:
            cursor.execute("UPDATE users SET first_name = ?, username = ? WHERE user_id = ?", (first_name, clean_username, user_id))
            conn.commit()
            return {"user_id": row[0], "first_name": first_name or row[1], "username": clean_username or row[2], "height": row[3], "last_grow": row[4]}
        else:
            cursor.execute("INSERT INTO users (user_id, first_name, username, height, last_grow) VALUES (?, ?, ?, 0, 0)", (user_id, first_name, clean_username))
            conn.commit()
            return {"user_id": user_id, "first_name": first_name, "username": clean_username, "height": 0, "last_grow": 0}

def get_user_by_username(username):
    clean_username = username.lstrip('@').lower()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, first_name, username, height, last_grow FROM users WHERE LOWER(username) = ?", (clean_username,))
        row = cursor.fetchone()
        if row:
            return {"user_id": row[0], "first_name": row[1], "username": row[2], "height": row[3], "last_grow": row[4]}
        return None

def update_height(user_id, amount):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET height = MAX(0, height + ?) WHERE user_id = ?", (amount, user_id))
        conn.commit()

def set_grow_time(user_id, timestamp):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_grow = ? WHERE user_id = ?", (timestamp, user_id))
        conn.commit()

def get_top_users(limit=30):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT first_name, height FROM users ORDER BY height DESC LIMIT ?", (limit,))
        return cursor.fetchall()

init_db()

# ----------------- حافظه نبردها -----------------
# ساختار: { battle_msg_id: { p1_id, p2_id, p1_name, p2_name, amount, p1_dice, p2_dice } }
active_battles = {}

# ----------------- دستورات عمومی -----------------

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    help_text = (
        "👑 <b>به ربات بازی خوش آمدید!</b>\n\n"
        "📜 <b>راهنمای دستورات:</b>\n"
        "🔹 <code>/grow</code> — افزایش قد تصادفی (هر ۱۲ ساعت)\n"
        "🔹 <code>/fight &lt;مقدار&gt;</code> — شرط‌بندی و مبارزه دستی تاس با ریپلای\n"
        "🔹 <code>/give &lt;آیدی یا یوزرنیم&gt; &lt;مقدار&gt;</code> — هدیه دادن قد\n"
        "🔹 <code>/top</code> — رتبه‌بندی برترین‌ها\n"
        "🔹 <code>/myheight</code> — مشاهده قد فعلی"
    )
    bot.reply_to(message, help_text, parse_mode="HTML")

@bot.message_handler(commands=['myheight'])
def check_height(message):
    user = get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    bot.reply_to(message, f"📏 قد فعلی شما: <b>{user['height']} سانتی‌متر</b>", parse_mode="HTML")

@bot.message_handler(commands=['grow'])
def grow_cmd(message):
    user = get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    now = time.time()
    cooldown = 12 * 3600
    
    if now - user['last_grow'] < cooldown:
        rem_time = int(cooldown - (now - user['last_grow']))
        hours = rem_time // 3600
        mins = (rem_time % 3600) // 60
        bot.reply_to(message, f"⏳ شما قبلاً رشد کرده‌اید! لطفاً <b>{hours} ساعت و {mins} دقیقه</b> دیگر امتحان کنید.", parse_mode="HTML")
        return

    added = random.randint(1, 30)
    update_height(user['user_id'], added)
    set_grow_time(user['user_id'], now)
    
    bot.reply_to(message, f"🌱 قد شما <b>+{added} سانتی‌متر</b> رشد کرد!\n📏 قد فعلی: <b>{user['height'] + added} سانتی‌متر</b>", parse_mode="HTML")

@bot.message_handler(commands=['top'])
def top_players(message):
    top_list = get_top_users(30)
    if not top_list:
        bot.reply_to(message, "لیست خالی است.")
        return
    lines = [f"{i+1}|{(name or 'User').strip()} — {height} cm" for i, (name, height) in enumerate(top_list)]
    bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=['give', 'gift', 'send'])
def gift_height(message):
    sender = get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    args = message.text.split()
    target_user = None

    if message.reply_to_message:
        if len(args) < 2 or not args[1].isdigit():
            bot.reply_to(message, "❌ لطفاً مقدار را وارد کنید. مثال: <code>/give 20</code>", parse_mode="HTML")
            return
        amount = int(args[1])
        target_tg_user = message.reply_to_message.from_user
        if target_tg_user.is_bot:
            bot.reply_to(message, "❌ نمی‌توانید به ربات امتیاز دهید!")
            return
        target_user = get_user(target_tg_user.id, target_tg_user.first_name, target_tg_user.username)
    else:
        if len(args) < 3:
            bot.reply_to(message, "❌ <b>فرمت:</b>\n<code>/give @username 20</code>\n<code>/give 123456789 20</code>", parse_mode="HTML")
            return
        target_identifier = args[1]
        if not args[2].isdigit():
            bot.reply_to(message, "❌ مقدار باید عدد باشد.", parse_mode="HTML")
            return
        amount = int(args[2])
        target_user = get_user(int(target_identifier)) if target_identifier.isdigit() else get_user_by_username(target_identifier)

    if not target_user:
        bot.reply_to(message, "❌ کاربر مورد نظر یافت نشد.")
        return

    if amount <= 0 or target_user['user_id'] == sender['user_id']:
        bot.reply_to(message, "❌ درخواست نامعتبر است.")
        return

    if sender['height'] < amount:
        bot.reply_to(message, f"❌ موجودی قد شما کافی نیست! (قد شما: {sender['height']} cm)")
        return

    update_height(sender['user_id'], -amount)
    update_height(target_user['user_id'], amount)
    bot.reply_to(message, f"🎁 <b>{amount} cm</b> به {html.escape(target_user['first_name'])} منتقل شد.", parse_mode="HTML")

# ----------------- سیستم نبرد دستی با تاس و ریپلای -----------------

@bot.message_handler(commands=['fight'])
def create_fight(message):
    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, "⚠️ این دستور فقط در گروه‌ها کار می‌کند!")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        bot.reply_to(message, "❌ فرمت نادرست! مثال: <code>/fight 20</code>", parse_mode="HTML")
        return

    amount = int(args[1])
    if amount <= 0:
        bot.reply_to(message, "❌ مقدار شرط باید بزرگتر از صفر باشد.")
        return

    user = get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    if user['height'] < amount:
        bot.reply_to(message, f"❌ شما قد کافی ندارید! (قد فعلی: {user['height']} cm)")
        return

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text=f"⚔️ قبول چالش ({amount} cm)", callback_data=f"accept_{message.from_user.id}_{amount}"))

    bot.send_message(
        message.chat.id,
        f"🥊 <b>{html.escape(message.from_user.first_name)}</b> یک نبرد با شرط <b>{amount} سانتی‌متر</b> راه انداخت!\nچه کسی چالش را قبول می‌کند؟",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("accept_"))
def accept_fight(call):
    _, p1_id_str, amount_str = call.data.split("_")
    p1_id = int(p1_id_str)
    amount = int(amount_str)
    p2_id = call.from_user.id

    if p2_id == p1_id:
        bot.answer_callback_query(call.id, "❌ نمی‌توانید با خودتان مبارزه کنید!", show_alert=True)
        return

    p1 = get_user(p1_id)
    p2 = get_user(p2_id, call.from_user.first_name, call.from_user.username)

    if p1['height'] < amount:
        bot.answer_callback_query(call.id, "❌ ایجادکننده چالش قد کافی ندارد!", show_alert=True)
        return

    if p2['height'] < amount:
        bot.answer_callback_query(call.id, f"❌ شما قد کافی ندارید! (نیاز: {amount} cm)", show_alert=True)
        return

    p1_name = html.escape(p1['first_name'] or "بازیکن ۱")
    p2_name = html.escape(p2['first_name'] or "بازیکن ۲")

    # ویرایش پیام چالش برای شروع نبرد و حذف دکمه
    battle_msg = bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            f"🔥 <b>نبرد آغاز شد!</b>\n\n"
            f"👤 {p1_name} 🆚 👤 {p2_name}\n"
            f"💰 شرط: <b>{amount} سانتی‌متر</b>\n\n"
            f"📌 <b>هر دو بازیکن باید روی همین پیام ریپلای کرده و یک تاس (🎲) بیندازند!</b>\n"
            f"▫️ وضعیت تاس {p1_name}: ⏳ منتظر پرتاب\n"
            f"▫️ وضعیت تاس {p2_name}: ⏳ منتظر پرتاب"
        ),
        parse_mode="HTML"
    )

    # ثبت اطلاعات نبرد
    active_battles[battle_msg.message_id] = {
        "chat_id": call.message.chat.id,
        "p1_id": p1_id,
        "p2_id": p2_id,
        "p1_name": p1_name,
        "p2_name": p2_name,
        "amount": amount,
        "p1_dice": None,
        "p2_dice": None
    }
    bot.answer_callback_query(call.id)

# ----------------- هندلر دریافت تاس ریپلای شده -----------------
@bot.message_handler(content_types=['dice'])
def handle_dice(message):
    # بررسی اینکه آیا تاس است و آیا روی پیامی ریپلای شده یا خیر
    if message.dice.emoji != '🎲' or not message.reply_to_message:
        return

    battle_id = message.reply_to_message.message_id
    if battle_id not in active_battles:
        return

    battle = active_battles[battle_id]
    sender_id = message.from_user.id
    dice_val = message.dice.value

    # آیا ارسال‌کننده بازیکن ۱ است؟
    if sender_id == battle["p1_id"]:
        if battle["p1_dice"] is not None:
            bot.reply_to(message, "⚠️ شما قبلاً تاس انداخته‌اید!")
            return
        battle["p1_dice"] = dice_val
    # آیا ارسال‌کننده بازیکن ۲ است؟
    elif sender_id == battle["p2_id"]:
        if battle["p2_dice"] is not None:
            bot.reply_to(message, "⚠️ شما قبلاً تاس انداخته‌اید!")
            return
        battle["p2_dice"] = dice_val
    else:
        return  # شخصی که در نبرد نیست تاس انداخته

    # وضعیت‌ها
    p1_status = f"🎲 {battle['p1_dice']}" if battle['p1_dice'] is not None else "⏳ منتظر پرتاب"
    p2_status = f"🎲 {battle['p2_dice']}" if battle['p2_dice'] is not None else "⏳ منتظر پرتاب"

    # آپدیت متن پیام نبرد با وضعیت جدید
    try:
        bot.edit_message_text(
            chat_id=battle["chat_id"],
            message_id=battle_id,
            text=(
                f"🔥 <b>نبرد در جریان است!</b>\n\n"
                f"👤 {battle['p1_name']} 🆚 👤 {battle['p2_name']}\n"
                f"💰 شرط: <b>{battle['amount']} سانتی‌متر</b>\n\n"
                f"▫️ وضعیت تاس {battle['p1_name']}: {p1_status}\n"
                f"▫️ وضعیت تاس {battle['p2_name']}: {p2_status}"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    # بررسی پایان بازی (هر دو نفر تاس انداخته باشند)
    if battle["p1_dice"] is not None and battle["p2_dice"] is not None:
        p1_val = battle["p1_dice"]
        p2_val = battle["p2_dice"]
        amt = battle["amount"]

        time.sleep(2)  # صبر کوتاه تا انیمیشن تاس تمام شود

        if p1_val > p2_val:
            update_height(battle["p1_id"], amt)
            update_height(battle["p2_id"], -amt)
            res_text = (
                f"🏆 <b>{battle['p1_name']} پیروز شد!</b>\n\n"
                f"🎲 {battle['p1_name']}: <b>{p1_val}</b>\n"
                f"🎲 {battle['p2_name']}: <b>{p2_val}</b>\n\n"
                f"➕ <b>+{amt} cm</b> به {battle['p1_name']}\n"
                f"➖ <b>-{amt} cm</b> از {battle['p2_name']}"
            )
        elif p2_val > p1_val:
            update_height(battle["p2_id"], amt)
            update_height(battle["p1_id"], -amt)
            res_text = (
                f"🏆 <b>{battle['p2_name']} پیروز شد!</b>\n\n"
                f"🎲 {battle['p1_name']}: <b>{p1_val}</b>\n"
                f"🎲 {battle['p2_name']}: <b>{p2_val}</b>\n\n"
                f"➕ <b>+{amt} cm</b> به {battle['p2_name']}\n"
                f"➖ <b>-{amt} cm</b> از {battle['p1_name']}"
            )
        else:
            res_text = (
                f"🤝 <b>نتیجه مساوی شد!</b>\n\n"
                f"🎲 {battle['p1_name']}: <b>{p1_val}</b>\n"
                f"🎲 {battle['p2_name']}: <b>{p2_val}</b>\n\n"
                f"هیچ قدی کسر یا اضافه نشد."
            )

        bot.send_message(battle["chat_id"], res_text, reply_to_message_id=battle_id, parse_mode="HTML")
        # حذف نبرد از حافظه پس از اتمام
        del active_battles[battle_id]

# ----------------- وب‌سرور برای Render -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# ----------------- اجرای اصلی -----------------
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    print("Bot is running...")
    bot.infinity_polling()
