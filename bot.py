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

SALES_PROMPT = """Ты — опытный помощник продажника Люды. Люда продаёт сайты малому бизнесу.
Твоя единственная задача: помочь Люде довести клиента до согласия на сделку.

КАК ОБЩАЕШЬСЯ:
- Живо и по-человечески, как опытный коллега рядом
- С клиентом строго на "Вы"
- Максимум 2-3 предложения клиенту за раз
- Один вопрос за раз, никогда не несколько сразу
- Веди плавно: интерес → доверие → решение → согласие

ЭТАПЫ:
1. Тёплое знакомство — узнать чем занимается бизнес
2. Выяснить есть ли сайт и как сейчас приходят клиенты
3. Предложить конкретное решение под его ситуацию
4. Назвать цену только когда клиент понял ценность
5. Довести до "да, давайте"

ПРОДУКТЫ:
- Сайт-визитка: 5 000–8 000 руб., 3–5 дней
- Каталог товаров: 8 000–15 000 руб., 5–7 дней
- Интернет-магазин: 15 000–30 000 руб., 7–14 дней
- Telegram Mini App: 10 000–25 000 руб., 5–10 дней
- Лендинг: 4 000–7 000 руб., 2–4 дня

ЖЁСТКИЕ ПРАВИЛА:
1. Не упоминай договор, реквизиты, оплату, начало работ — это делает Люда сама
2. Не заканчивай диалог сам
3. Когда клиент говорит "да" на цену или соглашается на сделку — напиши в [ЛЮДЕ]: КЛИЕНТ ГОТОВ
4. При возражении "дорого" — не снижай цену сразу, сначала уточни

ФОРМАТ ОТВЕТА строго:
[КЛИЕНТУ]: текст который Люда отправит клиенту
[ЛЮДЕ]: короткая подсказка что происходит"""

# Вопросы для сбора ТЗ — задаются автоматически по цепочке
TZ_QUESTIONS = [
    ("Название бизнеса",   "Как называется Ваш бизнес?"),
    ("Цель сайта",         "Что должен делать сайт — принимать заявки, показывать услуги, продавать товары или что-то другое?"),
    ("Тип сайта",          "Что именно Вам нужно — сайт-визитка, каталог, интернет-магазин или лендинг?"),
    ("Разделы",            "Какие разделы хотите на сайте? Например: о нас, услуги, цены, портфолио, контакты."),
    ("Стиль и цвета",      "Какой стиль и цвета Вам нравятся — строгий, яркий, минимализм? Есть предпочтения?"),
    ("Примеры сайтов",     "Есть ли сайты которые Вам нравятся по внешнему виду? Скиньте ссылки если есть."),
    ("Контент",            "У Вас есть готовые фото, тексты, логотип — или нужно делать с нуля?"),
    ("Контакты",           "Какие контакты указать на сайте — телефон, адрес, соцсети?"),
    ("Срок",               "Когда Вам нужно готово — есть конкретный дедлайн?"),
]

sessions = {}
processing = set()

def get_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = {
            "mode": "start",
            "stage": "start",
            "messages": [],
            "tz_data": {},
            "tz_step": 0,
            "agreed_price": None,
        }
    return sessions[user_id]

def reset_session(user_id):
    sessions[user_id] = {
        "mode": "start",
        "stage": "start",
        "messages": [],
        "tz_data": {},
        "tz_step": 0,
        "agreed_price": None,
    }

async def ask_groq(system, messages):
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=500,
            temperature=0.75
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "[КЛИЕНТУ]: Одну секунду...\n[ЛЮДЕ]: Ошибка соединения, попробуй ещё раз."

def parse(response):
    parts = response.split("[ЛЮДЕ]:")
    client = parts[0].replace("[КЛИЕНТУ]:", "").strip()
    advice = parts[1].strip() if len(parts) > 1 else ""
    return client, advice

def client_ready(advice):
    return "КЛИЕНТ ГОТОВ" in advice.upper()

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")],
        [InlineKeyboardButton("📖 Обучение PDF",  callback_data="get_pdf")],
    ])

def kb_sales():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ввести ответ клиента",  callback_data="sales_reply")],
        [InlineKeyboardButton("✅ Клиент согласился",     callback_data="go_tz")],
        [InlineKeyboardButton("🔄 Новый клиент",          callback_data="new_client")],
    ])

def kb_tz_answer():
    """Кнопка во время сбора ТЗ — только ввести ответ"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ввести ответ клиента", callback_data="tz_reply")],
        [InlineKeyboardButton("⏭ Клиент не знает",      callback_data="tz_skip")],
    ])

async def send_tz_question(bot, chat_id, session):
    """Отправляет текущий вопрос ТЗ клиенту"""
    step = session["tz_step"]
    if step >= len(TZ_QUESTIONS):
        await generate_brief(bot, chat_id, session)
        return

    label, question = TZ_QUESTIONS[step]
    total = len(TZ_QUESTIONS)
    session["stage"] = f"tz_answer_{step}"

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"📝 *Вопрос {step + 1} из {total} — {label}*\n\n"
            f"✉️ *Спроси клиента:*\n\n_{question}_\n\n"
            f"Введи ответ клиента:"
        ),
        parse_mode="Markdown",
        reply_markup=kb_tz_answer()
    )

async def generate_brief(bot, chat_id, session):
    """Генерирует итоговое ТЗ"""
    tz = session.get("tz_data", {})
    tz_text = "\n".join([f"{k}: {v}" for k, v in tz.items()]) if tz else "нет данных"

    brief_prompt = (
        f"Составь чёткое техническое задание на разработку сайта.\n\n"
        f"Данные от клиента:\n{tz_text}\n\n"
        f"Оформи строго по разделам без лишних слов и предисловий:\n"
        f"КЛИЕНТ: ...\n"
        f"БИЗНЕС: ...\n"
        f"ЦЕЛЬ САЙТА: ...\n"
        f"ТИП САЙТА: ...\n"
        f"РАЗДЕЛЫ: ...\n"
        f"ДИЗАЙН И СТИЛЬ: ...\n"
        f"КОНТЕНТ: ...\n"
        f"КОНТАКТЫ: ...\n"
        f"СРОК: ...\n"
        f"БЮДЖЕТ: ...\n"
        f"ПРИМЕЧАНИЯ: ..."
    )

    brief = await ask_groq(
        "Ты составляешь техническое задание для разработчика сайта. "
        "Пиши только ТЗ — чётко, конкретно, без предисловий и лишних фраз.",
        [{"role": "user", "content": brief_prompt}]
    )
    clean = brief.replace("[КЛИЕНТУ]:", "").replace("[ЛЮДЕ]:", "").strip()

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"📄 *ТЕХНИЧЕСКОЕ ЗАДАНИЕ ГОТОВО:*\n\n{clean}\n\n"
            f"_Скопируй и отправь разработчику_"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")]
        ])
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reset_session(user_id)
    await update.message.reply_text(
        "👋 Привет, Люда!\n\n"
        "Я веду клиента от первого «здравствуйте» до готового ТЗ для разработчика.\n\n"
        "🔹 Сначала помогу довести клиента до согласия\n"
        "🔹 Потом автоматически соберу все детали для сайта\n\n"
        "Начнём? 👇",
        reply_markup=kb_main()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    key = f"btn_{user_id}_{query.data}_{query.id}"
    if key in processing:
        return
    processing.add(key)

    try:
        session = get_session(user_id)
        chat_id = query.message.chat_id

        if query.data == "new_client":
            reset_session(user_id)
            session = get_session(user_id)
            session["mode"] = "sales"
            session["stage"] = "ask_business"
            await query.message.reply_text(
                "Напиши чем занимается клиент:\n"
                "_Например: кафе, салон красоты, база отдыха..._",
                parse_mode="Markdown"
            )

        elif query.data == "sales_reply":
            session["stage"] = "waiting_reply"
            await query.message.reply_text("Напечатай что написал клиент:")

        elif query.data == "go_tz":
            session["mode"] = "tz"
            session["tz_step"] = 0
            await query.message.reply_text(
                "✅ *Клиент согласился — отлично!*\n\n"
                "Теперь собираем детали для сайта.\n"
                "Я буду давать вопросы один за другим — "
                "ты копируешь и отправляешь клиенту, потом вводишь его ответ.\n\n"
                "Поехали 👇",
                parse_mode="Markdown"
            )
            await send_tz_question(context.bot, chat_id, session)

        elif query.data == "tz_reply":
            session["stage"] = f"tz_answer_{session['tz_step']}"
            await query.message.reply_text("Напечатай ответ клиента:")

        elif query.data == "tz_skip":
            step = session["tz_step"]
            label, _ = TZ_QUESTIONS[step]
            session["tz_data"][label] = "не указано"
            session["tz_step"] += 1
            await send_tz_question(context.bot, chat_id, session)

        elif query.data == "get_pdf":
            try:
                pdf_path = os.path.join(os.path.dirname(__file__), "lyuda_training.pdf")
                with open(pdf_path, "rb") as f:
                    await query.message.reply_document(
                        document=f,
                        filename="Люда_Обучение.pdf",
                        caption="📖 Твоё руководство по продажам сайтов"
                    )
            except FileNotFoundError:
                await query.message.reply_text("⚠️ Файл обучения не найден.")

    finally:
        processing.discard(key)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg_id = update.message.message_id
    key = f"msg_{user_id}_{msg_id}"
    if key in processing:
        return
    processing.add(key)

    try:
        session = get_session(user_id)
        text = update.message.text
        chat_id = update.message.chat_id

        if session["mode"] == "start":
            await start(update, context)
            return

        # ── РЕЖИМ ПРОДАЖИ ─────────────────────────────────────────────────
        if session["mode"] == "sales":
            if session["stage"] == "ask_business":
                session["stage"] = "conversation"
                session["messages"].append({
                    "role": "user",
                    "content": f"Клиент занимается: {text}. Дай первое тёплое сообщение для начала разговора. На Вы."
                })
            elif session["stage"] in ("conversation", "waiting_reply"):
                session["stage"] = "conversation"
                session["messages"].append({
                    "role": "user",
                    "content": f"Клиент написал: «{text}». Что мне ответить? На Вы."
                })
            else:
                return

            response = await ask_groq(SALES_PROMPT, session["messages"])
            session["messages"].append({"role": "assistant", "content": response})
            client_part, advice_part = parse(response)

            msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
            if advice_part:
                msg += f"\n\n💡 _{advice_part}_"

            if client_ready(advice_part):
                msg += "\n\n🟢 *Клиент готов!*"
                await update.message.reply_text(
                    msg,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 Собрать детали для сайта", callback_data="go_tz")],
                        [InlineKeyboardButton("💬 Продолжить диалог",        callback_data="sales_reply")],
                    ])
                )
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_sales())
            return

        # ── РЕЖИМ СБОРА ТЗ ────────────────────────────────────────────────
        if session["mode"] == "tz" and session["stage"].startswith("tz_answer_"):
            step = int(session["stage"].replace("tz_answer_", ""))
            label, _ = TZ_QUESTIONS[step]
            session["tz_data"][label] = text
            session["tz_step"] = step + 1
            await send_tz_question(context.bot, chat_id, session)

    finally:
        processing.discard(key)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Luda Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
