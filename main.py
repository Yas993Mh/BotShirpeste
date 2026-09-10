import os
import random
import time
import html
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
bot = telebot.TeleBot(BOT_TOKEN)
DB_NAME = "database.db"
GROW_COOLDOWN = 12 * 3600  # 12 hours in seconds

# ==================== DUMMY WEB SERVER (FOR RENDER) ====================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")

    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# ==================== DATABASE & MIGRATION ====================
def init_db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS group_users (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            name TEXT,
            height INTEGER DEFAULT 0,
            last_grow REAL DEFAULT 0,
            can_luck INTEGER DEFAULT 1,
            PRIMARY KEY (chat_id, user_id)
        )''')
    
    # بررسی و اضافه کردن خودکار ستون‌های جدید به دیتابیس قدیمی
    c.execute("PRAGMA table_info(group_users)")
    existing_columns = [col[1] for col in c.fetchall()]
    
    if "last_grow" not in existing_columns:
        c.execute("ALTER TABLE group_users ADD COLUMN last_grow REAL DEFAULT 0")
    if "can_luck" not in existing_columns:
        c.execute("ALTER TABLE group_users ADD COLUMN can_luck INTEGER DEFAULT 1")
        
    conn.commit()
    conn.close()

def get_user(chat_id, user_id, username=None, name=None):
    conn = sqlite3.connect(DB_NAME, timeout=10)
    c = conn.cursor()
    c.execute(
        "SELECT chat_id, user_id, username, name, height, last_grow, can_luck FROM group_users WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id)
    )
    row = c.fetchone()
    if row is None:
        safe_name = name or "User"
        c.execute(
            "INSERT INTO group_users (chat_id, user_id, username, name, height, last_grow, can_luck) VALUES (?, ?, ?, ?, 0, 0, 1)",
            (chat_id, user_id, username, safe_name)
        )
        conn.commit()
        c.execute(
            "SELECT chat_id, user_id, username, name, height, last_grow, can_luck FROM group_users WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        row = c.fetchone()
    else:
        if username or name:
            c.execute(
                "UPDATE group_users SET username = COALESCE(?, username), name = COALESCE(?, name) WHERE chat_id = ? AND user_id = ?",
                (username, name, chat_id, user_id)
            )
            conn.commit()
    conn.close()
    return {
        "chat_id": row[0],
        "user_id": row[1],
        "username": row[2],
        "name": row[3],
        "height": row[4],
        "last_grow": row[5],
        "can_luck": row[6]
    }

def update_user(chat_id, user_id, height=None, last_grow=None, can_luck=None):
    conn = sqlite3.connect(DB_NAME, timeout=10)
    c = conn.cursor()
    if height is not None:
        c.execute("UPDATE group_users SET height = ? WHERE chat_id = ? AND user_id = ?", (height, chat_id, user_id))
    if last_grow is not None:
        c.execute("UPDATE group_users SET last_grow = ? WHERE chat_id = ? AND user_id = ?", (last_grow, chat_id, user_id))
    if can_luck is not None:
        c.execute("UPDATE group_users SET can_luck = ? WHERE chat_id = ? AND user_id = ?", (can_luck, chat_id, user_id))
    conn.commit()
    conn.close()

# ==================== STATE MANAGEMENT ====================
active_battles = {}
active_lucks = {}

# ==================== COMMAND HANDLERS ====================
@bot.message_handler(commands=['start', 'help'])
def start_cmd(message):
    get_user(message.chat.id, message.from_user.id, message.from_user.username, message.from_user.first_name)
    text = (
        "👋 <b>Welcome to the Bot!</b>\n\n"
        "📜 <b>Commands:</b>\n"
        "🌱 <code>/grow</code> - Increase your points (12-hour cooldown)\n"
        "🎲 <code>/luck</code> - Roll dice to reset your cooldown\n"
        "⚔️ <code>/fight &lt;amount&gt;</code> - Challenge another player with dice\n"
        "🎁 <code>/give &lt;amount&gt;</code> - Transfer points (reply to a message)\n"
        "🏆 <code>/top</code> - Leaderboard for this group"
    )
    bot.reply_to(message, text, parse_mode="HTML")

@bot.message_handler(commands=['grow'])
def grow_cmd(message):
    chat_id = message.chat.id
    user = get_user(chat_id, message.from_user.id, message.from_user.username, message.from_user.first_name)
    now = time.time()
    elapsed = now - user['last_grow']

    if elapsed < GROW_COOLDOWN:
        remaining = int(GROW_COOLDOWN - elapsed)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        bot.reply_to(
            message,
            f"⏳ You are on cooldown! Time left: <b>{hours}h {minutes}m</b>.\nTry <code>/luck</code> to attempt a cooldown reset.",
            parse_mode="HTML"
        )
        return

    growth = random.randint(1, 10)
    new_height = user['height'] + growth
    update_user(chat_id, user['user_id'], height=new_height, last_grow=now, can_luck=1)

    bot.reply_to(
        message,
        f"✨ You grew <b>+{growth} cm</b>!\n📏 Total in this group: <b>{new_height} cm</b>",
        parse_mode="HTML"
    )

@bot.message_handler(commands=['luck'])
def luck_cmd(message):
    chat_id = message.chat.id
    user = get_user(chat_id, message.from_user.id, message.from_user.username, message.from_user.first_name)
    now = time.time()
    elapsed = now - user['last_grow']

    if elapsed >= GROW_COOLDOWN:
        bot.reply_to(message, "✅ No cooldown active! You can use <code>/grow</code> right now.", parse_mode="HTML")
        return

    if user['can_luck'] == 0:
        bot.reply_to(message, "❌ You have already used your luck attempt for this cycle.")
        return

    msg = bot.reply_to(
        message,
        "🎲 Reply to this message <b>twice</b> with a dice emoji (🎲)!\nIf the sum is greater than 8, your cooldown resets instantly.",
        parse_mode="HTML"
    )
    active_lucks[msg.message_id] = {
        "chat_id": chat_id,
        "user_id": user['user_id'],
        "rolls": []
    }

@bot.message_handler(commands=['fight'])
def fight_cmd(message):
    chat_id = message.chat.id
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        bot.reply_to(message, "⚠️ Usage: <code>/fight &lt;amount&gt;</code>", parse_mode="HTML")
        return

    amount = int(args[1])
    if amount <= 0:
        bot.reply_to(message, "❌ Bet amount must be greater than zero.")
        return

    user = get_user(chat_id, message.from_user.id, message.from_user.username, message.from_user.first_name)
    if user['height'] < amount:
        bot.reply_to(message, f"❌ You do not have enough points. (Your balance: {user['height']} cm)")
        return

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⚔️ Accept Challenge", callback_data=f"accept_{amount}_{user['user_id']}"))

    safe_name = html.escape(user['name'])
    bot.reply_to(
        message,
        f"🥊 <b>{safe_name}</b> created a duel challenge!\n"
        f"💰 Bet: <b>{amount} cm</b>\n"
        f"Click below to accept:",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("accept_"))
def accept_fight(call):
    chat_id = call.message.chat.id
    parts = call.data.split("_")
    amount = int(parts[1])
    creator_id = int(parts[2])
    joiner_id = call.from_user.id

    if joiner_id == creator_id:
        bot.answer_callback_query(call.id, "You cannot fight against yourself!", show_alert=True)
        return

    creator = get_user(chat_id, creator_id)
    joiner = get_user(chat_id, joiner_id, call.from_user.username, call.from_user.first_name)

    if creator['height'] < amount:
        bot.answer_callback_query(call.id, "The host no longer has enough points!", show_alert=True)
        return

    if joiner['height'] < amount:
        bot.answer_callback_query(call.id, f"You don't have enough points! (Balance: {joiner['height']})", show_alert=True)
        return

    bot.answer_callback_query(call.id, "Challenge accepted!")
    try:
        bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=None)
    except Exception:
        pass

    creator_name = html.escape(creator['name'])
    joiner_name = html.escape(joiner['name'])

    battle_msg = bot.send_message(
        chat_id,
        f"⚔️ <b>Battle started!</b>\n"
        f"👤 {creator_name} vs {joiner_name}\n"
        f"💰 Bet: <b>{amount} cm</b>\n\n"
        f"👉 Both players must reply to this message with a dice emoji (🎲)!",
        parse_mode="HTML"
    )

    active_battles[battle_msg.message_id] = {
        "chat_id": chat_id,
        "creator_id": creator_id,
        "joiner_id": joiner_id,
        "creator_name": creator['name'],
        "joiner_name": joiner['name'],
        "amount": amount,
        "rolls": {}
    }

@bot.message_handler(content_types=['dice'])
def handle_dice(message):
    if not message.reply_to_message:
        return
    reply_id = message.reply_to_message.message_id
    sender_id = message.from_user.id
    val = message.dice.value

    # --- Battle Duel ---
    if reply_id in active_battles:
        b = active_battles[reply_id]
        if sender_id not in [b["creator_id"], b["joiner_id"]]:
            return
        if sender_id in b["rolls"]:
            bot.reply_to(message, "You have already rolled your dice!")
            return

        b["rolls"][sender_id] = val
        bot.reply_to(message, f"🎲 Recorded roll: {val}")

        if len(b["rolls"]) == 2:
            c_score = b["rolls"][b["creator_id"]]
            j_score = b["rolls"][b["joiner_id"]]
            amt = b["amount"]
            c_user = get_user(b["chat_id"], b["creator_id"])
            j_user = get_user(b["chat_id"], b["joiner_id"])
            c_name = html.escape(b['creator_name'])
            j_name = html.escape(b['joiner_name'])

            if c_score > j_score:
                update_user(b["chat_id"], b["creator_id"], height=c_user['height'] + amt)
                update_user(b["chat_id"], b["joiner_id"], height=max(0, j_user['height'] - amt))
                result_text = f"🏆 <b>{c_name}</b> won ({c_score} vs {j_score}) and earned <b>+{amt} cm</b>!"
            elif j_score > c_score:
                update_user(b["chat_id"], b["joiner_id"], height=j_user['height'] + amt)
                update_user(b["chat_id"], b["creator_id"], height=max(0, c_user['height'] - amt))
                result_text = f"🏆 <b>{j_name}</b> won ({j_score} vs {c_score}) and earned <b>+{amt} cm</b>!"
            else:
                result_text = f"🤝 It's a draw! ({c_score} vs {c_score}) - No points transferred."

            bot.send_message(b["chat_id"], result_text, parse_mode="HTML")
            del active_battles[reply_id]

    # --- Luck Cooldown Reset ---
    elif reply_id in active_lucks:
        luck = active_lucks[reply_id]
        if sender_id != luck["user_id"]:
            return

        luck["rolls"].append(val)
        if len(luck["rolls"]) == 1:
            bot.reply_to(message, f"🎲 First roll: {val} — Roll one more time!")
        elif len(luck["rolls"]) == 2:
            total = sum(luck["rolls"])
            if total > 8:
                update_user(luck["chat_id"], luck["user_id"], last_grow=0, can_luck=0)
                bot.reply_to(message, f"🎉 Total: <b>{total}</b> (&gt; 8)! Cooldown reset. You can now <code>/grow</code>!", parse_mode="HTML")
            else:
                update_user(luck["chat_id"], luck["user_id"], can_luck=0)
                bot.reply_to(message, f"😢 Total: <b>{total}</b> (&le; 8). Luck attempt failed.", parse_mode="HTML")
            del active_lucks[reply_id]

@bot.message_handler(commands=['give'])
def give_cmd(message):
    chat_id = message.chat.id
    if not message.reply_to_message or not message.reply_to_message.from_user:
        bot.reply_to(message, "⚠️ Please reply to the user's message to transfer points.")
        return

    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        bot.reply_to(message, "⚠️ Usage: <code>/give &lt;amount&gt;</code> (by replying)", parse_mode="HTML")
        return

    amount = int(args[1])
    if amount <= 0:
        bot.reply_to(message, "❌ Transfer amount must be positive.")
        return

    sender_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id

    if sender_id == target_id:
        bot.reply_to(message, "You cannot transfer points to yourself.")
        return

    sender = get_user(chat_id, sender_id, message.from_user.username, message.from_user.first_name)
    target = get_user(chat_id, target_id, message.reply_to_message.from_user.username, message.reply_to_message.from_user.first_name)

    if sender['height'] < amount:
        bot.reply_to(message, f"❌ Insufficient points. (Your balance: {sender['height']} cm)")
        return

    update_user(chat_id, sender_id, height=sender['height'] - amount)
    update_user(chat_id, target_id, height=target['height'] + amount)

    target_name = html.escape(target['name'])
    bot.reply_to(message, f"🎁 Successfully transferred <b>{amount} cm</b> to <b>{target_name}</b>.", parse_mode="HTML")

@bot.message_handler(commands=['top'])
def top_cmd(message):
    chat_id = message.chat.id
    conn = sqlite3.connect(DB_NAME, timeout=10)
    c = conn.cursor()
    c.execute("SELECT name, height FROM group_users WHERE chat_id = ? ORDER BY height DESC LIMIT 10", (chat_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        bot.reply_to(message, "No player data in this group yet.")
        return

    medals = ["🥇", "🥈", "🥉"]
    text = "🏆 <b>Group Leaderboard:</b>\n\n"
    for i, (name, height) in enumerate(rows, 1):
        rank_icon = medals[i - 1] if i <= 3 else f"{i}."
        safe_name = html.escape(name or "User")
        text += f"{rank_icon} <b>{safe_name}</b>: {height} cm\n"

    bot.reply_to(message, text, parse_mode="HTML")

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_health_server, daemon=True).start()
    bot.infinity_polling(allowed_updates=['message', 'callback_query'])
