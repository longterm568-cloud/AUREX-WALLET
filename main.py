import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------- FAKE WEB SERVER FOR RENDER ----------------- #
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# ----------------- CONFIGURATION ----------------- #
BOT_TOKEN = "8835753597:AAEhs24IHryPIiTfovdOinrNqYvuX3eJIis"

deals_db = {}

# ----------------- FEES CALCULATOR ----------------- #
def calculate_fee(amount: float):
    if amount < 50:
        return None, None
    elif 50 <= amount <= 300:
        fee = 10.0
    elif 300 < amount <= 1000:
        fee = round((amount * 0.02), 2)
    else:
        fee = round((amount * 0.03), 2)
    total = amount + fee
    return fee, total

# ----------------- RULES COMMAND (/rules) ----------------- #
async def send_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules_text = (
        "📜 <b>AURA VAULT ESCROW RULES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "• Both parties start screen recording must.\n"
        "• Confirm that escrower is admin in @aurexescrows before paying.\n"
        "• Don't tag admins without any reasons.\n"
        "• Don't spam refund/release till your buyer/seller agrees.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <i>Please follow all rules for safe trading!</i>"
    )
    await update.message.reply_text(rules_text, parse_mode="HTML")

# ----------------- SEND CUSTOM FORM ----------------- #
async def send_deal_form_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    admin_tags = []

    if chat.type in ["group", "supergroup"]:
        try:
            admins = await chat.get_administrators()
            for admin in admins:
                if not admin.user.is_bot:
                    if admin.user.username:
                        admin_tags.append(f"@{admin.user.username}")
                    else:
                        admin_tags.append(admin.user.first_name)
        except Exception as e:
            print(f"Admin fetch error: {e}")

    admin_str = " ".join(admin_tags) if admin_tags else "@aurexescrows admins"

    form_template = (
        "📋 <b>AURA VAULT ESCROW FORM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<code>Deal amount : \n"
        "Buyer username : \n"
        "Seller username : \n"
        "Deal product/service : \n"
        "Expected time to complete deal : </code>\n\n"
        "Note : ⚠️ <b>escrow fees are non refundable</b> ⚠️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Admins:</b> {admin_str}\n\n"
        "👉 <i>Copy this form, fill in the details, and send it in this group.</i>"
    )
    await update.message.reply_text(form_template, parse_mode="HTML")

# ----------------- FORM FILL HANDLER ----------------- #
async def handle_deal_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    clean_text = text.strip().lower()
    if clean_text in ["form", "/form"]:
        await send_deal_form_template(update, context)
        return

    amt_match = re.search(r"(?:deal amount|amount)[:\s]*([0-9]+)", text, re.IGNORECASE)
    buyer_match = re.search(r"(?:buyer username|buyer)[:\s]*(@?\w+)", text, re.IGNORECASE)
    seller_match = re.search(r"(?:seller username|seller)[:\s]*(@?\w+)", text, re.IGNORECASE)

    if amt_match:
        amount = float(amt_match.group(1))
        if amount < 50:
            await update.message.reply_text("❌ Minimum deal amount is 50 ₹!")
            return

        fee, total = calculate_fee(amount)
        buyer = buyer_match.group(1) if buyer_match else "Not Mentioned"
        seller = seller_match.group(1) if seller_match else "Not Mentioned"

        form_msg_id = update.message.message_id
        deals_db[form_msg_id] = {
            "amount": amount,
            "fee": fee,
            "total": total,
            "buyer": buyer,
            "seller": seller,
            "admin": None,
            "status": "pending_admin_approval",
            "action": None
        }

        fee_info = (
            f"✅ <b>FORM RECEIVED!</b>\n\n"
            f"💰 <b>Deal Amount:</b> ₹{amount}\n"
            f"📊 <b>Escrow Fee:</b> ₹{fee}\n"
            f"💵 <b>Total Amount:</b> ₹{total}\n\n"
            f"👤 <b>Buyer:</b> {buyer}\n"
            f"👤 <b>Seller:</b> {seller}\n\n"
            f"⏳ <i>Waiting for Admin confirmation. Admin must reply to this form with <code>/ndeal</code> to initiate.</i>"
        )
        await update.message.reply_text(fee_info, parse_mode="HTML")

# ----------------- ADMIN COMMAND /ndeal ----------------- #
async def approve_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to the deal form message with /ndeal!")
        return

    form_msg = update.message.reply_to_message
    form_id = form_msg.message_id
    admin_user = update.effective_user.mention_html()

    if form_id not in deals_db:
        deals_db[form_id] = {
            "amount": "N/A",
            "fee": "N/A",
            "total": "N/A",
            "buyer": "Buyer",
            "seller": "Seller",
            "admin": admin_user,
            "status": "active"
        }
    else:
        deals_db[form_id]["admin"] = admin_user
        deals_db[form_id]["status"] = "active"

    try:
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=form_id
        )
    except Exception as e:
        print(f"Pin Error: {e}")

    keyboard = [
        [
            InlineKeyboardButton("✅ Release", callback_data=f"rel_{form_id}"),
            InlineKeyboardButton("❌ Refund", callback_data=f"ref_{form_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🔒 <b>Deal Approved & Pinned by {admin_user}!</b>\n\n"
        f"• <b>Buyer:</b> Click <b>Release</b> after receiving the product/service.\n"
        f"• <b>Seller:</b> Click <b>Refund</b> in case of any cancellation.",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

# ----------------- BUTTON CALLBACK ----------------- #
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    action, form_id_str = data.split("_")
    form_id = int(form_id_str)
    user = query.from_user.mention_html()

    deal = deals_db.get(form_id)
    if not deal:
        await query.edit_message_text("❌ Deal not found or expired.")
        return

    admin_tag = deal.get("admin", "Admin")

    if action == "rel":
        deal["action"] = "Release"
        await query.message.reply_text(
            f"📢 <b>Payment Release Requested!</b>\n\n"
            f"{user} clicked <b>Release</b>.\n"
            f"👉 <b>Seller: Please send your UPI ID here!</b>\n\n"
            f"Escrow Admin: {admin_tag}",
            parse_mode="HTML"
        )
    elif action == "ref":
        deal["action"] = "Refund"
        await query.message.reply_text(
            f"📢 <b>Payment Refund Requested!</b>\n\n"
            f"{user} clicked <b>Refund</b>.\n"
            f"👉 <b>Buyer: Please send your UPI ID here!</b>\n\n"
            f"Escrow Admin: {admin_tag}",
            parse_mode="HTML"
        )

# ----------------- DEAL CARD (/deal<number>) ----------------- #
async def deal_card_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = update.message.text.strip()
    match = re.match(r"^/deal(\d+)$", msg_text, re.IGNORECASE)
    if not match:
        return

    deal_number = match.group(1)

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to the original deal form with this command!")
        return

    target_id = update.message.reply_to_message.message_id
    deal = deals_db.get(target_id, {
        "amount": "N/A",
        "buyer": "Buyer",
        "seller": "Seller"
    })

    admin_name = update.effective_user.mention_html()

    card_text = (
        f"𝗗𝗘𝗔𝗟 𝗡𝗨𝗠𝗕𝗘𝗥 : #{deal_number}\n"
        f"𝗔𝗠𝗢𝗨𝗡𝗧 : ₹{deal['amount']}\n"
        f"𝗘𝗦𝗖𝗥𝗢𝗪𝗘𝗥 : {admin_name}\n"
        f"𝗕𝗨𝗬𝗘𝗥 : {deal['buyer']}\n"
        f"𝗦𝗘𝗟𝗟𝗘𝗥 : {deal['seller']}\n\n"
        f"𝗧𝗛𝗔𝗡𝗞𝗦 𝗙𝗢𝗥 𝗗𝗘𝗔𝗟𝗜𝗡𝗚 & 𝗧𝗥𝗨𝗦𝗧𝗜𝗡𝗚 𝗧𝗢 𝗨𝗦\n"
        f"𝗬𝗢𝗨𝗥𝗦  - @AUREXESROWS"
    )

    await update.message.reply_text(card_text, parse_mode="HTML")

# ----------------- MAIN RUNNER ----------------- #
def main():
    threading.Thread(target=run_web_server, daemon=True).start()

    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("rules", send_rules))
    bot_app.add_handler(CommandHandler("form", send_deal_form_template))
    bot_app.add_handler(CommandHandler("ndeal", approve_deal))
    bot_app.add_handler(MessageHandler(filters.Regex(r"^/deal\d+"), deal_card_command))
    bot_app.add_handler(CallbackQueryHandler(button_callback))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deal_form))

    print("Escrow Bot is running smoothly...")
    bot_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
