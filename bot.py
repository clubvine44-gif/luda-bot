import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8638675668:AAEaG5QS-_5dzb3F4AvwevIw0HleL4pDJHU")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")

groq_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """Ты — умный ассистент продажника по имени Люда. Твоя задача помогать продавать сайты малому бизнесу.

Ты работаешь поэтапно:
1. Сначала узнаёшь какой бизнес у клиента
2. Выясняешь есть ли у него сайт и как сейчас принимает заказы
3. Предлагаешь решение (сайт-визитка, каталог, форма заказа)
4. Обсуждаешь дизайн и функционал
5. Называешь цену и сроки
6. Закрываешь на сделку

ВАЖНО:
- Пиши живо, по-человечески, коротко
- Никакой воды и длинных предложений
- Максимум 2-3 предложения за раз
- Не раскрывай что ты ИИ
- Давай пользователю (Люде) точный текст что написать клиенту
- Формат ответа: сначала [ДЛЯ КЛИЕНТА]: текст который Люда отправит, потом [СОВЕТ]: краткая подсказка что происходит

Диапазон цен:
- Сайт-визитка: 5000-8000₽
- Каталог товаров: 8000-15000₽  
- Интернет-магазин: 15000-30000₽
- Telegram Mini App: 10000-25000₽
Срок: 3-7 дней"""

# Хранилище диалогов
sessions = {}

def get_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = {
            "stage": "start",
            "business_type": None,
            "messages": [],
            "client_info": {}
        }
    return sessions[user_id]

def reset_session(user_id):
    sessions[user_id] = {
        "stage": "start",
        "business_type": None,
        "messages": [],
        "client_info": {}
    }

async def ask_groq(messages):
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            max_tokens=500,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "Ошибка. Попробуй ещё раз."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reset_session(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")],
        [InlineKeyboardButton("📋 Итоговое ТЗ", callback_data="get_brief")],
        [InlineKeyboardButton("🔄 Сбросить диалог", callback_data="reset")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 Привет, Люда!\n\nЯ помогу тебе вести переговоры с клиентом.\n\nНажми *Новый клиент* чтобы начать.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id)
    
    if query.data == "new_client":
        reset_session(user_id)
        session = get_session(user_id)
        session["stage"] = "ask_business"
        await query.message.reply_text(
            "Окей! Какой бизнес у клиента?\n\nНапиши мне (например: кафе, база отдыха, салон красоты, магазин одежды...)"
        )
    
    elif query.data == "reset":
        reset_session(user_id)
        keyboard = [[InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")]]
        await query.message.reply_text(
            "✅ Диалог сброшен. Начнём заново?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "get_brief":
        session = get_session(user_id)
        if not session["messages"]:
            await query.message.reply_text("Сначала начни диалог с клиентом.")
            return
        
        brief_messages = session["messages"] + [
            {"role": "user", "content": "Составь итоговое ТЗ по всему что мы обсудили. Формат: Клиент, Бизнес, Что нужно, Дизайн, Функционал, Цена, Срок, Контакт (если есть)."}
        ]
        brief = await ask_groq(brief_messages)
        await query.message.reply_text(
            f"📋 *ИТОГОВОЕ ТЗ:*\n\n{brief}",
            parse_mode="Markdown"
        )
    
    elif query.data.startswith("stage_"):
        stage = query.data.replace("stage_", "")
        session["stage"] = stage
        
        stage_prompts = {
            "design": "Клиент готов обсудить дизайн. Спроси про стиль и цвета.",
            "price": "Переходим к цене. Назови стоимость и срок.",
            "close": "Закрываем сделку. Предложи начать работу."
        }
        
        if stage in stage_prompts:
            session["messages"].append({"role": "user", "content": stage_prompts[stage]})
            response = await ask_groq(session["messages"])
            session["messages"].append({"role": "assistant", "content": response})
            
            parts = response.split("[СОВЕТ]:")
            client_part = parts[0].replace("[ДЛЯ КЛИЕНТА]:", "").strip()
            advice_part = parts[1].strip() if len(parts) > 1 else ""
            
            keyboard = get_stage_keyboard(stage)
            msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
            if advice_part:
                msg += f"\n\n💡 _{advice_part}_"
            
            await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)

def get_stage_keyboard(current_stage):
    stages = {
        "ask_business": [],
        "conversation": [
            [InlineKeyboardButton("🎨 Обсудить дизайн", callback_data="stage_design")],
            [InlineKeyboardButton("💰 Назвать цену", callback_data="stage_price")],
            [InlineKeyboardButton("📋 Итоговое ТЗ", callback_data="get_brief")]
        ],
        "design": [
            [InlineKeyboardButton("💰 Назвать цену", callback_data="stage_price")],
            [InlineKeyboardButton("🤝 Закрыть сделку", callback_data="stage_close")],
            [InlineKeyboardButton("📋 Итоговое ТЗ", callback_data="get_brief")]
        ],
        "price": [
            [InlineKeyboardButton("🤝 Закрыть сделку", callback_data="stage_close")],
            [InlineKeyboardButton("📋 Итоговое ТЗ", callback_data="get_brief")]
        ],
        "close": [
            [InlineKeyboardButton("📋 Итоговое ТЗ", callback_data="get_brief")],
            [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")]
        ]
    }
    buttons = stages.get(current_stage, [[InlineKeyboardButton("📋 Итоговое ТЗ", callback_data="get_brief")]])
    return InlineKeyboardMarkup(buttons) if buttons else None

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    text = update.message.text
    
    if session["stage"] == "start":
        await start(update, context)
        return
    
    if session["stage"] == "ask_business":
        session["business_type"] = text
        session["stage"] = "conversation"
        session["messages"].append({
            "role": "user", 
            "content": f"Клиент занимается: {text}. Дай мне первое сообщение для начала разговора с клиентом."
        })
        response = await ask_groq(session["messages"])
        session["messages"].append({"role": "assistant", "content": response})
        
        parts = response.split("[СОВЕТ]:")
        client_part = parts[0].replace("[ДЛЯ КЛИЕНТА]:", "").strip()
        advice_part = parts[1].strip() if len(parts) > 1 else ""
        
        keyboard = get_stage_keyboard("conversation")
        msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
        if advice_part:
            msg += f"\n\n💡 _{advice_part}_"
        
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        return
    
    # Обычный диалог — клиент что-то ответил
    if session["stage"] == "conversation":
        session["messages"].append({
            "role": "user",
            "content": f"Клиент ответил: {text}. Что мне написать дальше?"
        })
        response = await ask_groq(session["messages"])
        session["messages"].append({"role": "assistant", "content": response})
        
        parts = response.split("[СОВЕТ]:")
        client_part = parts[0].replace("[ДЛЯ КЛИЕНТА]:", "").strip()
        advice_part = parts[1].strip() if len(parts) > 1 else ""
        
        keyboard = get_stage_keyboard("conversation")
        msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
        if advice_part:
            msg += f"\n\n💡 _{advice_part}_"
        
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
