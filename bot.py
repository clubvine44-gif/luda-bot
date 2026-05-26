import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8638675668:AAEaG5QS-_5dzb3F4AvwevIw0HleL4pDJHU")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")

groq_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """Ты — умный ИИ-ассистент для продажника по имени Люда. Люда продаёт сайты малому бизнесу.

Твоя задача: помогать Люде вести переписку с клиентами профессионально и результативно.

ПРАВИЛА ОБЩЕНИЯ С КЛИЕНТАМИ (очень важно!):
- ВСЕГДА обращайся к клиенту на "Вы" (с большой буквы)
- Пиши живо и по-человечески, без канцелярита
- Максимум 2-3 предложения за раз — не грузи клиента
- Будь тёплой но профессиональной
- Никогда не раскрывай что ты ИИ

ЭТАПЫ ПРОДАЖИ:
1. Знакомство — узнать какой бизнес у клиента
2. Потребность — есть ли сайт, как принимает заказы, откуда клиенты
3. Решение — предложить подходящий тип сайта
4. Дизайн — обсудить стиль, цвета, примеры
5. Цена — назвать диапазон и сроки
6. Закрытие — предложить начать и взять предоплату

ПРОДУКТЫ И ЦЕНЫ:
- Сайт-визитка: 5 000–8 000 руб., 3–5 дней
- Каталог товаров: 8 000–15 000 руб., 5–7 дней
- Интернет-магазин: 15 000–30 000 руб., 7–14 дней
- Telegram Mini App: 10 000–25 000 руб., 5–10 дней
- Лендинг (1 страница): 4 000–7 000 руб., 2–4 дня

ФОРМАТ ОТВЕТА — строго такой:
[ДЛЯ КЛИЕНТА]: точный текст который Люда скопирует и отправит клиенту
[СОВЕТ]: краткая подсказка для Люды что сейчас происходит и что важно

ВАЖНО: цену называй только когда клиент готов и понимает что получит. Никогда не снижай цену сразу при возражении."""

sessions = {}

def get_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = {
            "stage": "start",
            "business_type": None,
            "messages": [],
            "client_name": None,
        }
    return sessions[user_id]

def reset_session(user_id):
    sessions[user_id] = {
        "stage": "start",
        "business_type": None,
        "messages": [],
        "client_name": None,
    }

async def ask_groq(messages):
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            max_tokens=600,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "Ошибка соединения. Попробуй ещё раз."

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")],
        [InlineKeyboardButton("📖 Обучение (PDF)", callback_data="get_pdf")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ])

def conversation_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Клиент ответил", callback_data="client_replied")],
        [InlineKeyboardButton("🎨 Обсудить дизайн", callback_data="stage_design")],
        [InlineKeyboardButton("💰 Назвать цену", callback_data="stage_price")],
        [InlineKeyboardButton("🤝 Закрыть сделку", callback_data="stage_close")],
        [InlineKeyboardButton("⚡ Работа с возражением", callback_data="stage_objection")],
        [InlineKeyboardButton("📋 Итоговое ТЗ", callback_data="get_brief")],
        [InlineKeyboardButton("🔄 Новый клиент", callback_data="new_client")],
    ])

def after_price_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Клиент ответил", callback_data="client_replied")],
        [InlineKeyboardButton("🤝 Закрыть сделку", callback_data="stage_close")],
        [InlineKeyboardButton("⚡ Работа с возражением", callback_data="stage_objection")],
        [InlineKeyboardButton("📋 Итоговое ТЗ", callback_data="get_brief")],
        [InlineKeyboardButton("🔄 Новый клиент", callback_data="new_client")],
    ])

def close_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Итоговое ТЗ", callback_data="get_brief")],
        [InlineKeyboardButton("💬 Клиент ответил", callback_data="client_replied")],
        [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reset_session(user_id)

    welcome = (
        "👋 Привет, Люда!\n\n"
        "Я твой ИИ-помощник по продажам сайтов.\n\n"
        "🤖 *Что я умею:*\n"
        "• Подсказываю точные фразы для клиента\n"
        "• Веду тебя по этапам продажи\n"
        "• Помогаю отработать возражения\n"
        "• Составляю итоговое ТЗ для разработчика\n\n"
        "📖 Рекомендую начать с обучения — там всё что нужно знать.\n\n"
        "Готова начать? 👇"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown", reply_markup=main_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id)

    # ── НОВЫЙ КЛИЕНТ ──────────────────────────────────────────────────────
    if query.data == "new_client":
        reset_session(user_id)
        session = get_session(user_id)
        session["stage"] = "ask_business"
        await query.message.reply_text(
            "📝 *Новый клиент*\n\n"
            "Напиши мне: какой бизнес у клиента?\n\n"
            "_Например: кафе, салон красоты, база отдыха, магазин одежды, стоматология..._",
            parse_mode="Markdown"
        )

    # ── PDF ОБУЧЕНИЕ ──────────────────────────────────────────────────────
    elif query.data == "get_pdf":
        await query.message.reply_text(
            "📖 Отправляю обучающий материал...",
        )
        try:
            pdf_path = os.path.join(os.path.dirname(__file__), "lyuda_training.pdf")
            with open(pdf_path, "rb") as f:
                await query.message.reply_document(
                    document=f,
                    filename="Люда_Обучение_Продажи.pdf",
                    caption=(
                        "📚 *Твоё руководство по продажам*\n\n"
                        "Здесь:\n"
                        "• Как вести клиента по этапам\n"
                        "• Ответы на возражения\n"
                        "• Готовые фразы для переписки\n"
                        "• Частые ошибки\n\n"
                        "Прочитай один раз — и продавать станет намного легче!"
                    ),
                    parse_mode="Markdown"
                )
        except FileNotFoundError:
            await query.message.reply_text(
                "⚠️ Файл обучения не найден на сервере.\n"
                "Попроси разработчика загрузить файл lyuda_training.pdf в папку с ботом."
            )

    # ── ПОМОЩЬ ────────────────────────────────────────────────────────────
    elif query.data == "help":
        help_text = (
            "❓ *Как пользоваться ботом:*\n\n"
            "1️⃣ Нажми *Новый клиент* и напиши чем занимается клиент\n"
            "2️⃣ Получи готовый текст — скопируй и отправь клиенту\n"
            "3️⃣ Когда клиент ответил — нажми *Клиент ответил* и напечатай его ответ\n"
            "4️⃣ Используй кнопки чтобы перейти к дизайну, цене или закрытию\n"
            "5️⃣ В конце нажми *Итоговое ТЗ* — получишь документ для разработчика\n\n"
            "💡 *Важно:* все тексты написаны на 'Вы' — профессионально и вежливо"
        )
        await query.message.reply_text(help_text, parse_mode="Markdown", reply_markup=main_keyboard())

    # ── КЛИЕНТ ОТВЕТИЛ ────────────────────────────────────────────────────
    elif query.data == "client_replied":
        session["stage"] = "waiting_client_reply"
        await query.message.reply_text(
            "💬 Напечатай что ответил клиент:",
        )

    # ── ЭТАПЫ ─────────────────────────────────────────────────────────────
    elif query.data in ("stage_design", "stage_price", "stage_close", "stage_objection"):
        stage_map = {
            "stage_design": ("design", "Клиент готов обсудить дизайн. Спроси про стиль, цвета, примеры сайтов которые ему нравятся. Обращайся на Вы."),
            "stage_price": ("price", "Переходим к цене. Назови стоимость и сроки для этого типа проекта. Обращайся на Вы."),
            "stage_close": ("close", "Закрываем сделку. Предложи конкретный следующий шаг — обсуждение деталей или предоплату. Обращайся на Вы."),
            "stage_objection": ("objection", "Клиент возражает или сомневается. Помоги Люде отработать возражение мягко и профессионально. Обращайся на Вы."),
        }
        stage_key, prompt = stage_map[query.data]
        session["stage"] = stage_key
        session["messages"].append({"role": "user", "content": prompt})
        response = await ask_groq(session["messages"])
        session["messages"].append({"role": "assistant", "content": response})

        parts = response.split("[СОВЕТ]:")
        client_part = parts[0].replace("[ДЛЯ КЛИЕНТА]:", "").strip()
        advice_part = parts[1].strip() if len(parts) > 1 else ""

        kb = after_price_keyboard() if stage_key == "price" else (close_keyboard() if stage_key == "close" else conversation_keyboard())

        msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
        if advice_part:
            msg += f"\n\n💡 *Совет:* _{advice_part}_"

        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)

    # ── ИТОГОВОЕ ТЗ ───────────────────────────────────────────────────────
    elif query.data == "get_brief":
        session = get_session(user_id)
        if not session["messages"]:
            await query.message.reply_text("Сначала начни диалог с клиентом — нажми 'Новый клиент'.")
            return

        brief_prompt = (
            "Составь итоговое техническое задание по всему что мы обсудили.\n"
            "Формат строго такой:\n"
            "КЛИЕНТ: (имя если известно)\n"
            "БИЗНЕС: (чем занимается)\n"
            "ЧТО НУЖНО: (тип сайта)\n"
            "ФУНКЦИОНАЛ: (что должно быть на сайте)\n"
            "ДИЗАЙН: (стиль, цвета, пожелания)\n"
            "ЦЕНА: (согласованная сумма)\n"
            "СРОК: (дней)\n"
            "КОНТАКТ: (если есть)\n"
            "ПРИМЕЧАНИЯ: (всё важное что обсудили)"
        )
        brief_messages = session["messages"] + [{"role": "user", "content": brief_prompt}]
        brief = await ask_groq(brief_messages)

        clean_brief = brief.replace("[ДЛЯ КЛИЕНТА]:", "").replace("[СОВЕТ]:", "").strip()

        await query.message.reply_text(
            f"📋 *ИТОГОВОЕ ТЗ:*\n\n{clean_brief}\n\n"
            f"_Скопируй и отправь разработчику_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")]
            ])
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    text = update.message.text

    # Старт без команды
    if session["stage"] == "start":
        await start(update, context)
        return

    # Ввод бизнеса клиента
    if session["stage"] == "ask_business":
        session["business_type"] = text
        session["stage"] = "conversation"
        session["messages"].append({
            "role": "user",
            "content": f"Клиент занимается: {text}. Дай мне первое приветственное сообщение для начала разговора с этим клиентом. Обращайся к клиенту на Вы."
        })
        response = await ask_groq(session["messages"])
        session["messages"].append({"role": "assistant", "content": response})

        parts = response.split("[СОВЕТ]:")
        client_part = parts[0].replace("[ДЛЯ КЛИЕНТА]:", "").strip()
        advice_part = parts[1].strip() if len(parts) > 1 else ""

        msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
        if advice_part:
            msg += f"\n\n💡 *Совет:* _{advice_part}_"

        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=conversation_keyboard())
        return

    # Ответ клиента
    if session["stage"] in ("conversation", "waiting_client_reply", "design", "price", "close", "objection"):
        session["stage"] = "conversation"
        session["messages"].append({
            "role": "user",
            "content": f"Клиент ответил: {text}. Что мне написать дальше? Обращайся к клиенту на Вы."
        })
        response = await ask_groq(session["messages"])
        session["messages"].append({"role": "assistant", "content": response})

        parts = response.split("[СОВЕТ]:")
        client_part = parts[0].replace("[ДЛЯ КЛИЕНТА]:", "").strip()
        advice_part = parts[1].strip() if len(parts) > 1 else ""

        msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
        if advice_part:
            msg += f"\n\n💡 *Совет:* _{advice_part}_"

        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=conversation_keyboard())

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Luda Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
