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

# ─── ПРОМПТ РЕЖИМА ПРОДАЖИ ───────────────────────────────────────────────────
SALES_PROMPT = """Ты — опытный помощник продажника Люды. Люда продаёт сайты малому бизнесу.
Твоя единственная задача в этом режиме: помочь Люде довести клиента до согласия на сделку.

КАК ОБЩАЕШЬСЯ:
- Живо и по-человечески, как опытный коллега рядом
- С клиентом строго на "Вы"
- Максимум 2-3 предложения клиенту за раз — не грузи
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

ЖЁСТКИЕ ПРАВИЛА — никогда не нарушай:
1. Не упоминай договор, реквизиты, оплату, начало работ — это делает Люда сама
2. Не заканчивай диалог сам — только Люда решает когда всё
3. Когда клиент говорит "да" или соглашается на цену — твоя работа закончена,
   напиши [ЛЮДЕ]: КЛИЕНТ ГОТОВ — это сигнал для Люды переходить к сбору ТЗ
4. При возражении "дорого" — не снижай цену сразу, сначала уточни

ФОРМАТ ОТВЕТА строго:
[КЛИЕНТУ]: текст который Люда скопирует и отправит клиенту
[ЛЮДЕ]: короткая подсказка что происходит и что важно"""

# ─── ПРОМПТ РЕЖИМА СБОРА ТЗ ─────────────────────────────────────────────────
TZ_PROMPT = """Ты помогаешь собрать техническое задание на сайт. Клиент уже согласился на сделку.
Твоя задача — сформулировать живой вопрос для клиента по теме которую тебе дадут.
Один вопрос, коротко, на Вы, по-человечески — не анкетно.

ФОРМАТ:
[КЛИЕНТУ]: вопрос который Люда отправит клиенту"""

# ─── ВОПРОСЫ ТЗ ─────────────────────────────────────────────────────────────
TZ_QUESTIONS = [
    ("Название бизнеса",     "Как называется бизнес клиента?"),
    ("Цель сайта",           "Что должен делать сайт — звонки, заявки, продажи, бронирование?"),
    ("Тип сайта",            "Что именно нужно — визитка, каталог, магазин, лендинг?"),
    ("Разделы",              "Какие разделы должны быть на сайте?"),
    ("Стиль и цвета",        "Какой стиль и цвета хочет — строго, ярко, минимализм?"),
    ("Примеры",              "Есть ли сайты которые нравятся по дизайну?"),
    ("Контент",              "Есть готовые фото, тексты, логотип — или делаем с нуля?"),
    ("Контакты",             "Телефон, адрес, соцсети которые нужно указать на сайте?"),
    ("Срок",                 "Есть ли дедлайн — когда нужно готово?"),
    ("Согласованная цена",   "Какую цену озвучили и клиент согласился?"),
]

sessions = {}

def get_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = {
            "mode": "start",       # start | sales | tz
            "stage": "start",      # внутри режима
            "messages": [],        # история для продажи
            "tz_data": {},         # собранные данные ТЗ
            "tz_step": 0,
        }
    return sessions[user_id]

def reset_session(user_id):
    sessions[user_id] = {
        "mode": "start",
        "stage": "start",
        "messages": [],
        "tz_data": {},
        "tz_step": 0,
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
    """Достаёт [КЛИЕНТУ] и [ЛЮДЕ] из ответа"""
    parts = response.split("[ЛЮДЕ]:")
    client = parts[0].replace("[КЛИЕНТУ]:", "").strip()
    advice = parts[1].strip() if len(parts) > 1 else ""
    return client, advice

def client_ready(advice):
    """Проверяет что ИИ дал сигнал — клиент готов"""
    return "КЛИЕНТ ГОТОВ" in advice.upper()

# ─── КЛАВИАТУРЫ ─────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")],
        [InlineKeyboardButton("📖 Обучение PDF",  callback_data="get_pdf")],
    ])

def kb_sales():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ввести ответ клиента",   callback_data="sales_reply")],
        [InlineKeyboardButton("📋 Клиент согласен → ТЗ",  callback_data="go_tz")],
        [InlineKeyboardButton("🔄 Новый клиент",           callback_data="new_client")],
    ])

def kb_tz(step):
    if step >= len(TZ_QUESTIONS):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Сформировать ТЗ", callback_data="get_brief")],
            [InlineKeyboardButton("🔄 Новый клиент",     callback_data="new_client")],
        ])
    label, _ = TZ_QUESTIONS[step]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"❓ {label}", callback_data=f"tz_ask_{step}")],
        [InlineKeyboardButton("⏭ Пропустить",           callback_data=f"tz_skip_{step}")],
        [InlineKeyboardButton("📄 Сформировать ТЗ",     callback_data="get_brief")],
    ])

# ─── ХЭНДЛЕРЫ ────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reset_session(user_id)
    await update.message.reply_text(
        "👋 Привет, Люда!\n\n"
        "Я веду клиента от первого «здравствуйте» до согласия на сделку — "
        "подсказываю что писать на каждом шаге.\n\n"
        "Когда клиент согласится — переключаемся на сбор ТЗ для разработчика.\n\n"
        "Начнём? 👇",
        reply_markup=kb_main()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = get_session(user_id)

    # ── НОВЫЙ КЛИЕНТ ─────────────────────────────────────────────────────
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

    # ── ВВЕСТИ ОТВЕТ КЛИЕНТА (продажа) ───────────────────────────────────
    elif query.data == "sales_reply":
        session["stage"] = "waiting_reply"
        await query.message.reply_text("Напечатай что написал клиент:")

    # ── КЛИЕНТ СОГЛАСЕН → ПЕРЕХОД К ТЗ ──────────────────────────────────
    elif query.data == "go_tz":
        session["mode"] = "tz"
        session["tz_step"] = 0
        session["stage"] = "collecting_tz"
        label, _ = TZ_QUESTIONS[0]
        await query.message.reply_text(
            "✅ *Отлично — клиент готов!*\n\n"
            "Теперь собираем ТЗ. Нажимай кнопку — получишь вопрос для клиента, "
            "вводи его ответ и идём дальше.\n\n"
            f"Первый вопрос — *{label}*:",
            parse_mode="Markdown",
            reply_markup=kb_tz(0)
        )

    # ── ВОПРОС ТЗ ────────────────────────────────────────────────────────
    elif query.data.startswith("tz_ask_"):
        step = int(query.data.replace("tz_ask_", ""))
        _, question = TZ_QUESTIONS[step]
        session["stage"] = f"tz_answer_{step}"
        resp = await ask_groq(TZ_PROMPT, [{"role": "user", "content": question}])
        client_part, _ = parse(resp)
        if not client_part:
            client_part = resp.strip()
        await query.message.reply_text(
            f"✉️ *Спроси клиента:*\n\n_{client_part}_\n\nВведи его ответ:",
            parse_mode="Markdown"
        )

    # ── ПРОПУСТИТЬ ВОПРОС ТЗ ─────────────────────────────────────────────
    elif query.data.startswith("tz_skip_"):
        step = int(query.data.replace("tz_skip_", ""))
        next_step = step + 1
        session["tz_step"] = next_step
        session["stage"] = "collecting_tz"
        if next_step >= len(TZ_QUESTIONS):
            await query.message.reply_text(
                "Все вопросы пройдены 👌",
                reply_markup=kb_tz(next_step)
            )
        else:
            label, _ = TZ_QUESTIONS[next_step]
            await query.message.reply_text(
                f"Следующий — *{label}*:",
                parse_mode="Markdown",
                reply_markup=kb_tz(next_step)
            )

    # ── СФОРМИРОВАТЬ ТЗ ──────────────────────────────────────────────────
    elif query.data == "get_brief":
        tz = session.get("tz_data", {})
        tz_text = "\n".join([f"{k}: {v}" for k, v in tz.items()]) if tz else "данные не собраны"

        brief_prompt = (
            f"Составь чёткое техническое задание на разработку сайта.\n\n"
            f"Собранные данные:\n{tz_text}\n\n"
            f"Оформи структурированно под этим заголовком — ТЕХНИЧЕСКОЕ ЗАДАНИЕ.\n"
            f"Разделы: Клиент, Бизнес, Цель сайта, Тип сайта, Разделы, "
            f"Дизайн и стиль, Контент, Контакты, Срок, Бюджет, Примечания.\n"
            f"Пиши конкретно, без воды."
        )
        brief = await ask_groq(SALES_PROMPT, [{"role": "user", "content": brief_prompt}])
        clean = brief.replace("[КЛИЕНТУ]:", "").replace("[ЛЮДЕ]:", "").strip()

        await query.message.reply_text(
            f"📄 {clean}\n\n_Скопируй и отправь разработчику_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")]
            ])
        )

    # ── PDF ───────────────────────────────────────────────────────────────
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

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    text = update.message.text

    if session["mode"] == "start":
        await start(update, context)
        return

    # ── РЕЖИМ ПРОДАЖИ ────────────────────────────────────────────────────
    if session["mode"] == "sales":

        # Ввод бизнеса
        if session["stage"] == "ask_business":
            session["stage"] = "conversation"
            session["messages"].append({
                "role": "user",
                "content": f"Клиент занимается: {text}. Дай первое тёплое сообщение для начала разговора. На Вы."
            })

        # Ответ клиента
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

        # Если ИИ дал сигнал что клиент готов
        if client_ready(advice_part):
            msg += "\n\n🟢 *Клиент готов — переходи к сбору ТЗ!*"
            await update.message.reply_text(msg, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Перейти к сбору ТЗ", callback_data="go_tz")],
                    [InlineKeyboardButton("💬 Продолжить диалог",  callback_data="sales_reply")],
                ])
            )
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_sales())
        return

    # ── РЕЖИМ СБОРА ТЗ ───────────────────────────────────────────────────
    if session["mode"] == "tz" and session["stage"].startswith("tz_answer_"):
        step = int(session["stage"].replace("tz_answer_", ""))
        label, _ = TZ_QUESTIONS[step]
        session["tz_data"][label] = text

        next_step = step + 1
        session["tz_step"] = next_step
        session["stage"] = "collecting_tz"

        if next_step >= len(TZ_QUESTIONS):
            await update.message.reply_text(
                "✅ Все данные собраны!",
                reply_markup=kb_tz(next_step)
            )
        else:
            label_next, _ = TZ_QUESTIONS[next_step]
            await update.message.reply_text(
                f"✅ Записал. Следующий — *{label_next}*:",
                parse_mode="Markdown",
                reply_markup=kb_tz(next_step)
            )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Luda Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
