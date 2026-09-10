import os
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

GROW_COOLDOWN = 12 * 3600  # 12 hours in seconds

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
    bot.reply_to(message, "Welcome!\n\nCommands:\n/grow - Grow your score\n/luck - Try luck to reset cooldown\n/fight <amount> - Dice battle\n/give <amount> - Transfer points\n/top - Leaderboard")

@bot.message_handler(commands=['grow'])
def grow_cmd(message):
    user = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    now = time.time()
    diff = now - user['last_grow']

    if diff < GROW_COOLDOWN:
        rem_sec = int(GROW_COOLDOWN - diff)
        hours = rem_sec // 3600
        mins = (rem_sec % 3600) // 60
        
        msg = f"⏳ Cooldown active! Remaining time: {hours}h {mins}m.\n\n"
        if user['can_luck'] == 1:
            msg += "🎲 You can use /luck to try to remove the cooldown!"
        else:
            msg += "❌ You already used your luck chance for this round."
        
        bot.reply_to(message, msg)
        return

    delta = random.randint(-2, 30)
    new_height = max(0, user['height'] + delta)
    update_user(user['user_id'], height=new_height, last_grow=now, can_luck=1)

    if delta >= 0:
        bot.reply_to(message, f"🌱 +{delta} cm! Current size: {new_height} cm")
    else:
        bot.reply_to(message, f"🥀 -{abs(delta)} cm! Current size: {new_height} cm")

@bot.message_handler(commands=['luck', 'chance'])
def luck_cmd(message):
    user = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    now = time.time()
    diff = now - user['last_grow']

    if diff >= GROW_COOLDOWN:
        bot.reply_to(message, "You can already use /grow without luck!")
        return

    if user['can_luck'] == 0:
        bot.reply_to(message, "❌ You have already used your luck chance for this period.")
        return

    luck_msg = bot.reply_to(
        message,
        f"🎲 **Luck Challenge for {user['name']}:**\n\n"
        f"Reply to this message with a dice (🎲) **2 times**.\n"
        f"If the sum is **greater than 8**, your cooldown will be reset!",
        parse_mode="Markdown"
    )

    active_lucks[luck_msg.message_id] = {
        "user_id": user['user_id'],
        "rolls": []
    }

@bot.message_handler(commands=['give'])
def give_cmd(message):
    args = message.text.split()
    sender = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    # By reply: /give <amount>
    if message.reply_to_message:
        if len(args) < 2 or not args[1].isdigit():
            bot.reply_to(message, "Usage: Reply to a user with `/give <amount>`")
            return
        amount = int(args[1])
        target_user = message.reply_to_message.from_user
        receiver = get_user(target_user.id, target_user.username, target_user.first_name)
    # By username/ID: /give <@username/id> <amount>
    elif len(args) >= 3 and args[2].isdigit():
        target = args[1].lstrip('@')
        amount = int(args[2])
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        if target.isdigit():
            c.execute("SELECT user_id, username, name, height, last_grow, can_luck FROM users WHERE user_id = ?", (int(target),))
        else:
            c.execute("SELECT user_id, username, name, height, last_grow, can_luck FROM users WHERE LOWER(username) = LOWER(?)", (target,))
        row = c.fetchone()
        conn.close()
        if not row:
            bot.reply_to(message, "Target user not found.")
            return
        receiver = {"user_id": row[0], "username": row[1], "name": row[2], "height": row[3], "last_grow": row[4], "can_luck": row[5]}
    else:
        bot.reply_to(message, "Usage:\n- Reply: `/give <amount>`\n- Directly: `/give <@username or ID> <amount>`")
        return

    if sender['user_id'] == receiver['user_id']:
        bot.reply_to(message, "You cannot send points to yourself.")
        return
    if amount <= 0:
        bot.reply_to(message, "Amount must be greater than 0.")
        return
    if sender['height'] < amount:
        bot.reply_to(message, "You don't have enough points.")
        return

    update_user(sender['user_id'], height=sender['height'] - amount)
    update_user(receiver['user_id'], height=receiver['height'] + amount)
    bot.reply_to(message, f"🎁 {sender['name']} sent {amount} cm to {receiver['name']}!")

@bot.message_handler(commands=['top'])
def top_players(message):
    top_list = get_top_users(30)
    if not top_list:
        bot.reply_to(message, "Leaderboard is empty.")
        return
    lines = [f"{i+1}| {(name or 'User').strip()} — {height} cm" for i, (name, height) in enumerate(top_list)]
    bot.reply_to(message, "\n".join(lines))

# ==================== BATTLE LOGIC ====================

@bot.message_handler(commands=['fight'])
def create_fight(message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        bot.reply_to(message, "Usage: /fight <amount>")
        return

    amount = int(args[1])
    if amount <= 0:
        bot.reply_to(message, "Amount must be greater than 0.")
        return

    user = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if user['height'] < amount:
        bot.reply_to(message, "You don't have enough points for this bet.")
        return

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⚔️ Accept Challenge", callback_data=f"accept_{message.from_user.id}_{amount}"))

    bot.reply_to(
        message,
        f"🥊 Dice battle created by {user['name']}!\n💰 Bet: {amount} cm\nClick below to accept:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("accept_"))
def accept_fight(call):
    _, creator_id_str, amount_str = call.data.split("_")
    creator_id = int(creator_id_str)
    amount = int(amount_str)
    joiner_id = call.from_user.id

    if joiner_id == creator_id:
        bot.answer_callback_query(call.id, "You cannot fight yourself!", show_alert=True)
        return

    creator = get_user(creator_id)
    joiner = get_user(joiner_id, call.from_user.username, call.from_user.first_name)

    if creator['height'] < amount:
        bot.answer_callback_query(call.id, "Creator no longer has enough points.", show_alert=True)
        return
    if joiner['height'] < amount:
        bot.answer_callback_query(call.id, "You don't have enough points.", show_alert=True)
        return

    battle_msg = bot.send_message(
        call.message.chat.id,
        f"⚔️ Battle started between {creator['name']} and {joiner['name']}!\n"
        f"💰 Bet: {amount} cm\n\n"
        f"📌 Both players must reply to this message with a dice (🎲)."
    )

    active_battles[battle_msg.message_id] = {
        "creator_id": creator_id,
        "joiner_id": joiner_id,
        "amount": amount,
        "rolls": {}
    }
    bot.answer_callback_query(call.id)

# ==================== DICE HANDLER ====================

@bot.message_handler(content_types=['dice'])
def handle_dice(message):
    if not message.reply_to_message:
        return
    
    reply_id = message.reply_to_message.message_id

    # 1. Battle handler
    if reply_id in active_battles:
        battle = active_battles[reply_id]
        user_id = message.from_user.id

        if user_id not in [battle["creator_id"], battle["joiner_id"]]:
            return

        if user_id in battle["rolls"]:
            bot.reply_to(message, "You already rolled!")
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
                res = f"🏆 {c_user['name']} won with {c_val} vs {j_val} (+{amount} cm)!"
            elif j_val > c_val:
                update_user(j_id, height=j_user['height'] + amount)
                update_user(c_id, height=max(0, c_user['height'] - amount))
                res = f"🏆 {j_user['name']} won with {j_val} vs {c_val} (+{amount} cm)!"
            else:
                res = f"🤝 Draw! ({c_val} - {c_val}). No points changed."

            bot.send_message(message.chat.id, f"🏁 **Battle Ended:**\n{res}", parse_mode="Markdown")
            del active_battles[reply_id]
        return

    # 2. Luck handler
    if reply_id in active_lucks:
        luck = active_lucks[reply_id]
        if message.from_user.id != luck["user_id"]:
            bot.reply_to(message, "This luck challenge belongs to someone else!")
            return

        luck["rolls"].append(message.dice.value)
        count = len(luck["rolls"])

        if count == 1:
            bot.reply_to(
                message,
                f"🎲 First roll: **{luck['rolls'][0]}**\nNow roll your second dice by replying again!",
                parse_mode="Markdown"
            )
        elif count == 2:
            val1, val2 = luck["rolls"][0], luck["rolls"][1]
            total = val1 + val2

            if total > 8:
                update_user(luck["user_id"], last_grow=0, can_luck=0)
                bot.reply_to(
                    message,
                    f"🎉 **Success!** Rolls: {val1} + {val2} = **{total}** (> 8)\n"
                    f"Cooldown removed! You can now use /grow.",
                    parse_mode="Markdown"
                )
            else:
                update_user(luck["user_id"], can_luck=0)
                bot.reply_to(
                    message,
                    f"😢 **Failed!** Rolls: {val1} + {val2} = **{total}** (<= 8)\n"
                    f"Your chance is used. Please wait for the cooldown to finish.",
                    parse_mode="Markdown"
                )
            del active_lucks[reply_id]

# ==================== HEALTH CHECK ====================

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
