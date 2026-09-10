import os
import html
import random
import time
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
bot = telebot.TeleBot(BOT_TOKEN)
DB_NAME = "database.db"

GROW_COOLDOWN = 12 * 3600  # 12 ساعت به ثانیه

# ==================== DATABASE ====================

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            height INTEGER DEFAULT 10,
            last_grow REAL DEFAULT 0,
            can_luck INTEGER DEFAULT 1
        )
    ''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN can_luck INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def get_user(user_id, username=None, name=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, username, name, height, last_grow, can_luck FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row is None:
        c.execute(
            "INSERT INTO users (user_id, username, name, height, last_grow, can_luck) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, name or "User", 10, 0, 1)
        )
        conn.commit()
        c.execute("SELECT user_id, username, name, height, last_grow, can_luck FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
    else:
        if username or name:
            c.execute("UPDATE users SET username = COALESCE(?, username), name = COALESCE(?, name) WHERE user_id = ?", (username, name, user_id))
            conn.commit()
    conn.close()
    return {
        "user_id": row[0],
        "username": row[1],
        "name": row[2],
        "height": row[3],
        "last_grow": row[4],
        "can_luck": row[5]
    }

def update_user(user_id, height=None, last_grow=None, can_luck=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if height is not None:
        c.execute("UPDATE users SET height = ? WHERE user_id = ?", (height, user_id))
    if last_grow is not None:
        c.execute("UPDATE users SET last_grow = ? WHERE user_id = ?", (last_grow, user_id))
    if can_luck is not None:
        c.execute("UPDATE users SET can_luck = ? WHERE user_id = ?", (can_luck, user_id))
    conn.commit()
    conn.close()

def get_top_users(limit=30):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name, height FROM users ORDER BY height DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# ==================== ACTIVE PROCESSES ====================
active_battles = {}
active_lucks = {}

# ==================== COMMANDS ====================

@bot.message_handler(commands=['start'])
def start_cmd(message):
    get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    bot.reply_to(message, "سلام! به ربات خوش آمدید.\n\nدستورات:\n/grow - افزایش امتیاز\n/luck - امتحان شانس برای لغو زمان انتظار\n/fight <مقدار> - نبرد با تاس\n/top - برترین‌ها")

@bot.message_handler(commands=['grow'])
def grow_cmd(message):
    user = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    now = time.time()
    diff = now - user['last_grow']

    if diff < GROW_COOLDOWN:
        rem_sec = int(GROW_COOLDOWN - diff)
        hours = rem_sec // 3600
        mins = (rem_sec % 3600) // 60
        
        msg = f"⏳ شما قبلاً رشد کرده‌اید! زمان باقی‌مانده: {hours} ساعت و {mins} دقیقه.\n\n"
        if user['can_luck'] == 1:
            msg += "🎲 **فرصت امتحان شانس:**\nمی‌توانید با دستور /luck شانس خود را امتحان کنید! ۲ بار تاس می‌اندازید؛ اگر مجموع بیشتر از ۸ شد، می‌توانید فوراً دوباره /grow بزنید!"
        else:
            msg += "❌ شما شانس این دوره خود را قبلاً امتحان کرده‌اید."
        
        bot.reply_to(message, msg, parse_mode="Markdown")
        return

    delta = random.randint(-2, 10)
    new_height = max(0, user['height'] + delta)
    update_user(user['user_id'], height=new_height, last_grow=now, can_luck=1)

    if delta >= 0:
        bot.reply_to(message, f"🌱 امتیاز شما {delta} سانتی‌متر افزایش یافت!\nاندازه فعلی: {new_height} cm")
    else:
        bot.reply_to(message, f"🥀 متاسفانه {abs(delta)} سانتی‌متر کاهش یافت!\nاندازه فعلی: {new_height} cm")

@bot.message_handler(commands=['luck', 'chance'])
def luck_cmd(message):
    user = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    now = time.time()
    diff = now - user['last_grow']

    if diff >= GROW_COOLDOWN:
        bot.reply_to(message, "شما در حال حاضر بدون نیاز به شانس می‌توانید از دستور /grow استفاده کنید!")
        return

    if user['can_luck'] == 0:
        bot.reply_to(message, "❌ شما قبلاً شانس خود را برای این دوره ۱۲ ساعته امتحان کرده‌اید.")
        return

    luck_msg = bot.reply_to(
        message,
        f"🎲 **امتحان شانس برای {user['name']}:**\n\n"
        f"لطفاً **۲ بار پشت سر هم** روی همین پیام ایموجی تاس (🎲) را ریپلای کنید.\n"
        f"اگر مجموع ۲ تاس شما **بیشتر از ۸** شد، زمان انتظار شما لغو می‌شود!",
        parse_mode="Markdown"
    )

    active_lucks[luck_msg.message_id] = {
        "user_id": user['user_id'],
        "rolls": []
    }

@bot.message_handler(commands=['top'])
def top_players(message):
    top_list = get_top_users(30)
    if not top_list:
        bot.reply_to(message, "لیست خالی است.")
        return
    lines = [f"{i+1}|{(name or 'User').strip()} — {height} cm" for i, (name, height) in enumerate(top_list)]
    bot.reply_to(message, "\n".join(lines))

# ==================== FIGHT / BATTLE LOGIC ====================

@bot.message_handler(commands=['fight'])
def create_fight(message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        bot.reply_to(message, "نحوه استفاده: /fight <مقدار>")
        return

    amount = int(args[1])
    if amount <= 0:
        bot.reply_to(message, "مقدار باید بیشتر از 0 باشد.")
        return

    user = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if user['height'] < amount:
        bot.reply_to(message, "امتیاز شما برای این شرط‌بندی کافی نیست.")
        return

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⚔️ قبول چالش", callback_data=f"accept_{message.from_user.id}_{amount}"))

    bot.reply_to(
        message,
        f"🥊 چالش نبرد تاس توسط {user['name']} ایجاد شد!\n💰 مبلغ شرط: {amount} cm\nبرای قبول روی دکمه زیر بزنید:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("accept_"))
def accept_fight(call):
    _, creator_id_str, amount_str = call.data.split("_")
    creator_id = int(creator_id_str)
    amount = int(amount_str)
    joiner_id = call.from_user.id

    if joiner_id == creator_id:
        bot.answer_callback_query(call.id, "نمی‌توانید با خودتان مبارزه کنید!", show_alert=True)
        return

    creator = get_user(creator_id)
    joiner = get_user(joiner_id, call.from_user.username, call.from_user.first_name)

    if creator['height'] < amount:
        bot.answer_callback_query(call.id, "امتیاز سازنده چالش دیگر کافی نیست.", show_alert=True)
        return
    if joiner['height'] < amount:
        bot.answer_callback_query(call.id, "امتیاز شما برای این چالش کافی نیست.", show_alert=True)
        return

    battle_msg = bot.send_message(
        call.message.chat.id,
        f"⚔️ نبرد بین {creator['name']} و {joiner['name']} آغاز شد!\n"
        f"💰 مبلغ شرط: {amount} cm\n\n"
        f"📌 هر دو بازیکن لطفاً روی همین پیام ایموجی تاس (🎲) ریپلای کنید."
    )

    active_battles[battle_msg.message_id] = {
        "creator_id": creator_id,
        "joiner_id": joiner_id,
        "amount": amount,
        "rolls": {}
    }
    bot.answer_callback_query(call.id)

# ==================== DICE HANDLER (FIGHT & LUCK) ====================

@bot.message_handler(content_types=['dice'])
def handle_dice(message):
    if not message.reply_to_message:
        return
    
    reply_id = message.reply_to_message.message_id

    # 1. پردازش نبرد
    if reply_id in active_battles:
        battle = active_battles[reply_id]
        user_id = message.from_user.id

        if user_id not in [battle["creator_id"], battle["joiner_id"]]:
            return

        if user_id in battle["rolls"]:
            bot.reply_to(message, "شما قبلاً تاس انداخته‌اید!")
            return

        battle["rolls"][user_id] = message.dice.value

        if len(battle["rolls"]) == 2:
            c_id = battle["creator_id"]
            j_id = battle["joiner_id"]
            c_val = battle["rolls"][c_id]
            j_val = battle["rolls"][j_id]
            amount = battle["amount"]

            c_user = get_user(c_id)
            j_user = get_user(j_id)

            if c_val > j_val:
                update_user(c_id, height=c_user['height'] + amount)
                update_user(j_id, height=max(0, j_user['height'] - amount))
                res = f"🏆 {c_user['name']} با تاس {c_val} در برابر {j_val} برنده شد (+{amount} cm)!"
            elif j_val > c_val:
                update_user(j_id, height=j_user['height'] + amount)
                update_user(c_id, height=max(0, c_user['height'] - amount))
                res = f"🏆 {j_user['name']} با تاس {j_val} در برابر {c_val} برنده شد (+{amount} cm)!"
            else:
                res = f"🤝 مساوی شد! ({c_val} - {c_val}) امتیازی کسر نشد."

            bot.send_message(message.chat.id, f"🏁 **پایان نبرد:**\n{res}", parse_mode="Markdown")
            del active_battles[reply_id]
        return

    # 2. پردازش امتحان شانس
    if reply_id in active_lucks:
        luck = active_lucks[reply_id]
        if message.from_user.id != luck["user_id"]:
            bot.reply_to(message, "این پیام مربوط به امتحان شانس شخص دیگری است!")
            return

        luck["rolls"].append(message.dice.value)
        count = len(luck["rolls"])

        if count == 1:
            bot.reply_to(
                message,
                f"🎲 تاس اول شما: **{luck['rolls'][0]}**\nحالا تاس دوم را هم روی پیام اصلی ریپلای کنید!",
                parse_mode="Markdown"
            )
        elif count == 2:
            val1, val2 = luck["rolls"][0], luck["rolls"][1]
            total = val1 + val2

            if total > 8:
                update_user(luck["user_id"], last_grow=0, can_luck=0)
                bot.reply_to(
                    message,
                    f"🎉 **تبریک!** تاس اول: {val1} | تاس دوم: {val2}\n"
                    f"مجموع: **{total}** (بیشتر از ۸)\n"
                    f"محدودیت ۱۲ ساعته شما حذف شد! همین حالا می‌توانید دستور /grow را بزنید!",
                    parse_mode="Markdown"
                )
            else:
                update_user(luck["user_id"], can_luck=0)
                bot.reply_to(
                    message,
                    f"😢 **متاسفانه نشد!** تاس اول: {val1} | تاس دوم: {val2}\n"
                    f"مجموع: **{total}** (کمتر یا مساوی ۸)\n"
                    f"شانس این دوره شما مصرف شد. لطفاً تا پایان زمان انتظار صبر کنید.",
                    parse_mode="Markdown"
                )
            del active_lucks[reply_id]

# ==================== HEALTH CHECK SERVER ====================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_health_server, daemon=True).start()
    bot.infinity_polling()
