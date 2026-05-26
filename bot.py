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

SYSTEM_PROMPT = """Ты — опытный помощник продажника по имени Люда. Люда продаёт сайты малому бизнесу.

Твоя работа — помогать Люде вести переписку с клиентами. Ты как опытный старший коллега, который сидит рядом и тихо подсказывает что писать.

КАК ТЫ ОБЩАЕШЬСЯ:
- Живо, тепло, по-человечески — не как робот
- Коротко: максимум 2-3 предложения клиенту за раз
- С клиентом ВСЕГДА на "Вы"
- Не задаёшь клиенту несколько вопросов сразу — только один
- Ведёшь клиента плавно: сначала интерес → потом детали → потом цена → потом сделка
- Никогда не раскрываешь что ты ИИ

ЧТО МЫ ПРОДАЁМ:
- Сайт-визитка: 5 000–8 000 руб., 3–5 дней
- Каталог товаров: 8 000–15 000 руб., 5–7 дней
- Интернет-магазин: 15 000–30 000 руб., 7–14 дней
- Telegram Mini App: 10 000–25 000 руб., 5–10 дней
- Лендинг: 4 000–7 000 руб., 2–4 дня

ЭТАПЫ КОТОРЫЕ ТЫ ВЕДЁШЬ:
1. Знакомство и первый контакт
2. Выяснение есть ли сайт и как сейчас работает бизнес
3. Предложение решения под его ситуацию
4. Уточнение деталей сайта (дизайн, функционал, контент)
5. Называние цены и сроков
6. Закрытие на сделку и предоплату

ВАЖНО ПРО ЦЕНУ:
Никогда не называй цену до того как понял что нужно клиенту.
При возражении "дорого" — не снижай сразу, сначала уточни.

ФОРМАТ ОТВЕТА — строго:
[КЛИЕНТУ]: текст который Люда скопирует и отправит
[ЛЮДЕ]: короткая подсказка что сейчас происходит и на что обратить внимание"""

TZ_QUESTIONS = [
    ("Название и сфера", "Как называется бизнес и чем занимается?"),
    ("Целевая аудитория", "Кто клиенты этого бизнеса — кому продаёт?"),
    ("Цель сайта", "Что должен делать сайт — звонки, заявки, продажи, просто визитка?"),
    ("Тип сайта", "Что именно нужно — визитка, каталог, магазин, лендинг?"),
    ("Примеры дизайна", "Есть ли сайты которые нравятся по стилю или дизайну?"),
    ("Цвета и стиль", "Какие цвета и общий стиль хочет — строго, ярко, минимализм?"),
    ("Разделы сайта", "Какие разделы должны быть — о нас, услуги, цены, портфолио, контакты?"),
    ("Контент", "Есть ли готовые фото, тексты, логотип — или нужно делать с нуля?"),
    ("Срок", "Когда нужно готово — есть дедлайн?"),
    ("Бюджет", "Какой бюджет рассматривает клиент?"),
]

sessions = {}

def get_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = {
            "stage": "start",
            "messages": [],
            "tz_data": {},
            "tz_step": 0,
        }
    return sessions[user_id]

def reset_session(user_id):
    sessions[user_id] = {
        "stage": "start",
        "messages": [],
        "tz_data": {},
        "tz_step": 0,
    }

async def ask_groq(messages):
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            max_tokens=500,
            temperature=0.75
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "[КЛИЕНТУ]: Извините, одну секунду.\n[ЛЮДЕ]: Ошибка соединения, попробуй ещё раз."

def format_response(response):
    parts = response.split("[ЛЮДЕ]:")
    client_part = parts[0].replace("[КЛИЕНТУ]:", "").strip()
    advice_part = parts[1].strip() if len(parts) > 1 else ""
    return client_part, advice_part

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")],
        [InlineKeyboardButton("📋 Собрать ТЗ", callback_data="start_tz")],
        [InlineKeyboardButton("📖 Обучение PDF", callback_data="get_pdf")],
    ])

def chat_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ответ клиента", callback_data="client_reply")],
        [InlineKeyboardButton("📋 Собрать ТЗ", callback_data="start_tz")],
        [InlineKeyboardButton("🏁 Закрыть сделку", callback_data="stage_close")],
        [InlineKeyboardButton("🔄 Новый клиент", callback_data="new_client")],
    ])

def tz_keyboard(step):
    if step >= len(TZ_QUESTIONS):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Получить ТЗ", callback_data="get_brief")],
            [InlineKeyboardButton("🔄 Новый клиент", callback_data="new_client")],
        ])
    label, _ = TZ_QUESTIONS[step]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"❓ Спросить про: {label}", callback_data=f"tz_ask_{step}")],
        [InlineKeyboardButton("⏭ Пропустить", callback_data=f"tz_skip_{step}")],
        [InlineKeyboardButton("📄 Готово — дай ТЗ", callback_data="get_brief")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reset_session(user_id)
    await update.message.reply_text(
        "👋 Привет, Люда!\n\n"
        "Я твой помощник по продажам сайтов.\n\n"
        "Помогу написать клиенту от первого «здравствуйте» до получения оплаты — "
        "просто говори мне что происходит, я подскажу что писать.\n\n"
        "Начнём? 👇",
        reply_markup=main_keyboard()
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
            "Напиши чем занимается клиент:\n\n"
            "_Например: кафе, салон красоты, база отдыха, стоматология..._",
            parse_mode="Markdown"
        )

    elif query.data == "client_reply":
        session["stage"] = "waiting_reply"
        await query.message.reply_text("Напечатай что ответил клиент:")

    elif query.data == "stage_close":
        session["messages"].append({
            "role": "user",
            "content": "Клиент готов. Помоги мне закрыть сделку и договориться о предоплате. Сделай это мягко и естественно."
        })
        response = await ask_groq(session["messages"])
        session["messages"].append({"role": "assistant", "content": response})
        client_part, advice_part = format_response(response)
        msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
        if advice_part:
            msg += f"\n\n💡 _{advice_part}_"
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=chat_keyboard())

    elif query.data == "start_tz":
        session["tz_step"] = 0
        session["stage"] = "collecting_tz"
        label, _ = TZ_QUESTIONS[0]
        await query.message.reply_text(
            "📋 *Собираем ТЗ*\n\n"
            "Буду давать вопросы по одному. Нажимай кнопку — получишь фразу для клиента, "
            "потом введи его ответ и перейдём к следующему.\n\n"
            f"Первый вопрос — про *{label.lower()}*:",
            parse_mode="Markdown",
            reply_markup=tz_keyboard(0)
        )

    elif query.data.startswith("tz_ask_"):
        step = int(query.data.replace("tz_ask_", ""))
        label, question = TZ_QUESTIONS[step]
        session["stage"] = f"tz_answer_{step}"
        prompt = f"Сформулируй один живой вопрос клиенту на Вы, коротко и естественно, чтобы узнать: {question}"
        resp = await ask_groq([{"role": "user", "content": prompt}])
        client_part, _ = format_response(resp)
        if not client_part:
            client_part = resp.strip()
        await query.message.reply_text(
            f"✉️ *Спроси клиента:*\n\n_{client_part}_\n\n"
            f"Введи ответ клиента:",
            parse_mode="Markdown"
        )

    elif query.data.startswith("tz_skip_"):
        step = int(query.data.replace("tz_skip_", ""))
        next_step = step + 1
        session["tz_step"] = next_step
        session["stage"] = "collecting_tz"
        if next_step >= len(TZ_QUESTIONS):
            await query.message.reply_text("Все вопросы пройдены 👌", reply_markup=tz_keyboard(next_step))
        else:
            label, _ = TZ_QUESTIONS[next_step]
            await query.message.reply_text(
                f"Следующий — про *{label.lower()}*:",
                parse_mode="Markdown",
                reply_markup=tz_keyboard(next_step)
            )

    elif query.data == "get_brief":
        tz = session.get("tz_data", {})
        history = session.get("messages", [])
        tz_text = "\n".join([f"- {k}: {v}" for k, v in tz.items()]) if tz else "данных нет"
        brief_prompt = (
            f"Составь итоговое техническое задание.\n\nДанные:\n{tz_text}\n\n"
            f"Формат:\nКЛИЕНТ: ...\nБИЗНЕС: ...\nЦЕЛЬ САЙТА: ...\nТИП САЙТА: ...\n"
            f"РАЗДЕЛЫ: ...\nДИЗАЙН: ...\nКОНТЕНТ: ...\nСРОК: ...\nБЮДЖЕТ: ...\nПРИМЕЧАНИЯ: ..."
        )
        messages = history + [{"role": "user", "content": brief_prompt}]
        brief = await ask_groq(messages)
        clean = brief.replace("[КЛИЕНТУ]:", "").replace("[ЛЮДЕ]:", "").strip()
        await query.message.reply_text(
            f"📄 *ТЕХНИЧЕСКОЕ ЗАДАНИЕ:*\n\n{clean}\n\n_Скопируй и передай разработчику_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")]
            ])
        )

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
            await query.message.reply_text("⚠️ Файл обучения не найден на сервере.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    text = update.message.text

    if session["stage"] == "start":
        await start(update, context)
        return

    if session["stage"] == "ask_business":
        session["stage"] = "conversation"
        session["messages"].append({
            "role": "user",
            "content": (
                f"Клиент занимается: {text}. "
                f"Дай мне первое сообщение для начала разговора. "
                f"Тепло, живо, без занудства. Обращайся на Вы."
            )
        })
        response = await ask_groq(session["messages"])
        session["messages"].append({"role": "assistant", "content": response})
        client_part, advice_part = format_response(response)
        msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
        if advice_part:
            msg += f"\n\n💡 _{advice_part}_"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=chat_keyboard())
        return

    if session["stage"] in ("conversation", "waiting_reply"):
        session["stage"] = "conversation"
        session["messages"].append({
            "role": "user",
            "content": f"Клиент написал: «{text}». Что мне ответить? Обращайся к клиенту на Вы."
        })
        response = await ask_groq(session["messages"])
        session["messages"].append({"role": "assistant", "content": response})
        client_part, advice_part = format_response(response)
        msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
        if advice_part:
            msg += f"\n\n💡 _{advice_part}_"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=chat_keyboard())
        return

    if session["stage"].startswith("tz_answer_"):
        step = int(session["stage"].replace("tz_answer_", ""))
        label, _ = TZ_QUESTIONS[step]
        session["tz_data"][label] = text
        next_step = step + 1
        session["tz_step"] = next_step
        session["stage"] = "collecting_tz"
        if next_step >= len(TZ_QUESTIONS):
            await update.message.reply_text(
                "✅ Всё записал! Можешь получить ТЗ:",
                reply_markup=tz_keyboard(next_step)
            )
        else:
            label_next, _ = TZ_QUESTIONS[next_step]
            await update.message.reply_text(
                f"✅ Записал. Следующий — про *{label_next.lower()}*:",
                parse_mode="Markdown",
                reply_markup=tz_keyboard(next_step)
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
