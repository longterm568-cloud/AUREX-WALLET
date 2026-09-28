import os
import re
import asyncio
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
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

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
            admins = await context.bot.get_chat_administrators(chat.id)
            for admin in admins:
                if not admin.user.is_bot:
                    if admin.user.username:
                        admin_tags.append(f"@{admin.user.username}")
                    elif admin.user.first_name:
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

# ----------------- FORM FILL & AGREE HANDLER ----------------- #
async def handle_deal_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user_handle = (update.effective_user.username or "").lower()

    # 1. jar koni "form" mhatle
    if text.lower() in ["form", "/form"]:
        await send_deal_form_template(update, context)
        return

    # 2. jar user ne "agree" lihile (Reply deun)
    if text.lower() == "agree" and update.message.reply_to_message:
        replied_msg_id = update.message.reply_to_message.message_id
        
        # Form msg id shodha
        target_form_id = None
        for f_id, data in deals_db.items():
            if f_id == replied_msg_id or data.get("bot_reply_id") == replied_msg_id:
                target_form_id = f_id
                break

        if target_form_id:
            deal = deals_db[target_form_id]

            # Deal Creation sathi Agree
            if deal["status"] == "waiting_agreement":
                if user_handle == deal["buyer"]:
                    deal["buyer_agreed"] = True
                elif user_handle == deal["seller"]:
                    deal["seller_agreed"] = True

                b_status = "✅" if deal["buyer_agreed"] else "⏳"
                s_status = "✅" if deal["seller_agreed"] else "⏳"

                if deal["buyer_agreed"] and deal["seller_agreed"]:
                    deal["status"] = "both_agreed"
                    await update.message.reply_text(
                        f"🎉 <b>BOTH PARTIES AGREED!</b>\n\n"
                        f"• Buyer: {deal['buyer_display']} ✅\n"
                        f"• Seller: {deal['seller_display']} ✅\n\n"
                        f"👑 <b>Admin:</b> Please reply to the original form with <code>/ndeal</code> to start the escrow.",
                        parse_mode="HTML"
                    )
                else:
                    await update.message.reply_text(
                        f"📝 <b>Agreement Status:</b>\n"
                        f"• Buyer ({deal['buyer_display']}): {b_status}\n"
                        f"• Seller ({deal['seller_display']}): {s_status}\n"
                        f"👉 <i>Pending party please reply with 'agree'!</i>",
                        parse_mode="HTML"
                    )
                return

            # Release / Refund confirmation sathi Agree
            if deal.get("waiting_action_agree"):
                action = deal.get("action")
                target_user = deal["seller"] if action == "Release" else deal["buyer"]
                
                if user_handle == target_user:
                    deal["waiting_action_agree"] = False
                    admin_tag = deal.get("admin", "Admin")
                    beneficiary = "Seller" if action == "Release" else "Buyer"
                    await update.message.reply_text(
                        f"✅ <b>{action} Confirmed by Both Parties!</b>\n\n"
                        f"👉 <b>{beneficiary}: Please send your UPI ID here!</b>\n\n"
                        f"Escrow Admin: {admin_tag}",
                        parse_mode="HTML"
                    )
                return

    # 3. Form Parsing (Jevha user bharun pathvel)
    amt_match = re.search(r"(?:deal amount|amount)[:\s]*([0-9]+)", text, re.IGNORECASE)
    buyer_match = re.search(r"(?:buyer username|buyer)[:\s]*@?([a-zA-Z0-9_]+)", text, re.IGNORECASE)
    seller_match = re.search(r"(?:seller username|seller)[:\s]*@?([a-zA-Z0-9_]+)", text, re.IGNORECASE)
    prod_match = re.search(r"(?:deal product/service|product|service)[:\s]*(.+)", text, re.IGNORECASE)
    time_match = re.search(r"(?:expected time to complete deal|time)[:\s]*(.+)", text, re.IGNORECASE)

    if amt_match:
        amount = float(amt_match.group(1))
        if amount < 50:
            await update.message.reply_text("❌ Minimum deal amount is 50 ₹!")
            return

        fee, total = calculate_fee(amount)
        buyer = buyer_match.group(1).lower() if buyer_match else ""
        seller = seller_match.group(1).lower() if seller_match else ""
        product = prod_match.group(1).split("\n")[0].strip() if prod_match else "Not Mentioned"
        exp_time = time_match.group(1).split("\n")[0].strip() if time_match else "Not Mentioned"

        buyer_display = f"@{buyer}" if buyer else "Not Mentioned"
        seller_display = f"@{seller}" if seller else "Not Mentioned"

        form_msg_id = update.message.message_id
        
        reply_msg = await update.message.reply_text(
            f"📋 <b>DEAL DETAILS RECEIVED!</b>\n\n"
            f"💰 <b>Deal Amount:</b> ₹{amount}\n"
            f"📊 <b>Escrow Fee:</b> ₹{fee}\n"
            f"💵 <b>Total Amount:</b> ₹{total}\n"
            f"📦 <b>Product/Service:</b> {product}\n"
            f"⏱ <b>Expected Time:</b> {exp_time}\n\n"
            f"👤 <b>Buyer:</b> {buyer_display}\n"
            f"👤 <b>Seller:</b> {seller_display}\n\n"
            f"❓ <b>Both agree for this deal?</b>\n"
            f"👉 <i>Both {buyer_display} and {seller_display} please reply to this message with <code>agree</code> to proceed!</i>",
            parse_mode="HTML"
        )

        deals_db[form_msg_id] = {
            "amount": amount,
            "fee": fee,
            "total": total,
            "product": product,
            "time": exp_time,
            "buyer": buyer,
            "seller": seller,
            "buyer_display": buyer_display,
            "seller_display": seller_display,
            "buyer_agreed": False,
            "seller_agreed": False,
            "admin": None,
            "status": "waiting_agreement",
            "bot_reply_id": reply_msg.message_id,
            "action": None,
            "waiting_action_agree": False
        }

# ----------------- ADMIN COMMAND /ndeal ----------------- #
async def approve_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to the original deal form with /ndeal!")
        return

    form_msg = update.message.reply_to_message
    form_id = form_msg.message_id
    admin_user = update.effective_user.mention_html()

    if form_id not in deals_db:
        await update.message.reply_text("❌ Deal details not recognized. Please fill the valid form.")
        return

    deal = deals_db[form_id]

    if not (deal.get("buyer_agreed") and deal.get("seller_agreed")):
        await update.message.reply_text("⚠️ Cannot approve! Both Buyer and Seller must reply 'agree' first.")
        return

    deal["admin"] = admin_user
    deal["status"] = "active"

    # Form pin karne
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
        f"• <b>Buyer:</b> Click <b>Release</b> once you receive your product/service.\n"
        f"• <b>Seller:</b> Click <b>Refund</b> in case of deal cancellation.",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

# ----------------- BUTTON CALLBACK ----------------- #
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    action, form_id_str = data.split("_")
    form_id = int(form_id_str)

    deal = deals_db.get(form_id)
    if not deal:
        await query.answer("❌ Deal not found or expired.", show_alert=True)
        return

    user_username = (query.from_user.username or "").lower()
    buyer_username = deal.get("buyer", "")
    seller_username = deal.get("seller", "")

    is_admin = False
    try:
        member = await query.message.chat.get_member(query.from_user.id)
        if member.status in ["administrator", "creator"]:
            is_admin = True
    except Exception:
        pass

    if action == "rel":
        if buyer_username and user_username != buyer_username and not is_admin:
            await query.answer("⚠️ Only the BUYER can initiate Release!", show_alert=True)
            return

        await query.answer()
        deal["action"] = "Release"
        deal["waiting_action_agree"] = True
        
        await query.message.reply_text(
            f"📢 <b>Release Requested by Buyer!</b>\n\n"
            f"👉 <b>Seller ({deal['seller_display']}):</b> Are you agree for Release?\n"
            f"<i>Please reply to this message with <code>agree</code> to proceed!</i>",
            parse_mode="HTML"
        )

    elif action == "ref":
        if seller_username and user_username != seller_username and not is_admin:
            await query.answer("⚠️ Only the SELLER can initiate Refund!", show_alert=True)
            return

        await query.answer()
        deal["action"] = "Refund"
        deal["waiting_action_agree"] = True

        await query.message.reply_text(
            f"📢 <b>Refund Requested by Seller!</b>\n\n"
            f"👉 <b>Buyer ({deal['buyer_display']}):</b> Are you agree for Refund?\n"
            f"<i>Please reply to this message with <code>agree</code> to proceed!</i>",
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
        "fee": "N/A",
        "total": "N/A",
        "product": "N/A",
        "time": "N/A",
        "buyer_display": "Buyer",
        "seller_display": "Seller"
    })

    admin_name = update.effective_user.mention_html()

    # 1. Juna filled form UNPIN karne
    try:
        await context.bot.unpin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=target_id
        )
    except Exception as e:
        print(f"Unpin Error: {e}")

    # 2. Form chi sarv mahiti aslela Deal Card
    card_text = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎖 <b>AURA VAULT ESCROW DEAL CARD</b> 🎖\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 <b>DEAL NUMBER :</b> #{deal_number}\n"
        f"💰 <b>DEAL AMOUNT :</b> ₹{deal.get('amount', 'N/A')}\n"
        f"📊 <b>ESCROW FEE :</b> ₹{deal.get('fee', 'N/A')}\n"
        f"💵 <b>TOTAL AMOUNT :</b> ₹{deal.get('total', 'N/A')}\n"
        f"📦 <b>PRODUCT/SERVICE :</b> {deal.get('product', 'N/A')}\n"
        f"⏱ <b>EXPECTED TIME :</b> {deal.get('time', 'N/A')}\n"
        f"👤 <b>BUYER :</b> {deal.get('buyer_display', 'Buyer')}\n"
        f"👤 <b>SELLER :</b> {deal.get('seller_display', 'Seller')}\n"
        f"👑 <b>ESCROWER :</b> {admin_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>THANKS FOR DEALING & TRUSTING US</b>\n"
        f"<b>YOURS - @AUREXESCROWS</b>"
    )

    # 3. Form la reply karun card send karne
    card_msg = await update.message.reply_to_message.reply_text(card_text, parse_mode="HTML")

    # 4. Deal card PIN karne
    try:
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=card_msg.message_id
        )
    except Exception as e:
        print(f"Pin Card Error: {e}")

# ----------------- MAIN RUNNER ----------------- #
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    threading.Thread(target=run_web_server, daemon=True).start()

    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("rules", send_rules))
    bot_app.add_handler(CommandHandler("form", send_deal_form_template))
    bot_app.add_handler(CommandHandler("ndeal", approve_deal))
    bot_app.add_handler(MessageHandler(filters.Regex(r"^/deal\d+"), deal_card_command))
    bot_app.add_handler(CallbackQueryHandler(button_callback))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deal_messages))

    print("Escrow Bot is running smoothly and ready for messages...")
    bot_app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
