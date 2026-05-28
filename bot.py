import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN    = os.environ.get("BOT_TOKEN",    "8638675668:AAHt6PnzmcLbZfMPYsuwPZEbTec96eBy1sQ")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")

groq_client  = Groq(api_key=GROQ_API_KEY)
mod_warnings: dict[int, int] = {}
sessions: dict = {}

# ─── ПРОМПТ ПРОДАЖ ────────────────────────────────────────────────────────────
SALES_PROMPT = """Ты — опытный помощник продажника Люды. Люда продаёт сайты малому бизнесу.
Люда сама выходит на клиентов — пишет первой. Клиент Люду не знает.

ВАЖНО:
- Холодный контакт — клиент не ждал
- Первое сообщение: коротко, ненавязчиво, один вопрос
- Не делай вид что знакомы
- Не предполагай что клиент хочет сайт — сначала выясни ситуацию

КАК ОБЩАТЬСЯ:
- Живо, по-человечески, коротко
- С клиентом строго на "Вы"
- Максимум 2-3 предложения за раз
- Один вопрос за раз
- Путь: знакомство → интерес → доверие → предложение → согласие

ЭТАПЫ:
1. Представиться и зацепить одним вопросом
2. Выяснить есть ли сайт и как приходят клиенты
3. Показать что без сайта бизнес теряет клиентов
4. Предложить конкретное решение под его бизнес
5. Назвать цену когда клиент понял ценность
6. Получить "да, давайте"

ПРОДУКТЫ:
- Лендинг: 4 000–7 000 руб., 2–4 дня
- Сайт-визитка: 5 000–8 000 руб., 3–5 дней
- Каталог услуг: 8 000–15 000 руб., 5–7 дней
- Интернет-магазин: 15 000–30 000 руб., 7–14 дней
- Telegram Mini App: 10 000–25 000 руб., 5–10 дней

ЖЁСТКИЕ ПРАВИЛА:
1. Не упоминай договор, реквизиты, оплату, начало работ
2. Не заканчивай диалог сам
3. Никогда не спрашивай про бюджет первым
4. Цену называй только если клиент спросил или явно готов
5. Когда клиент согласился на цену — напиши [ЛЮДЕ]: КЛИЕНТ ГОТОВ
6. При "дорого" — уточни что смущает, не снижай сразу
7. Предлагай только подходящее под бизнес клиента

ФОРМАТ СТРОГО:
[КЛИЕНТУ]: текст который Люда скопирует и отправит клиенту
[ЛЮДЕ]: короткая подсказка что сейчас происходит"""

# ─── ВОПРОСЫ ТЗ ───────────────────────────────────────────────────────────────
TZ_QUESTIONS = [
    ("Название бизнеса",   "узнать точное название бизнеса клиента"),
    ("Цель сайта",         "узнать что должен делать сайт: звонки, заявки, бронирования, показывать услуги"),
    ("Разделы сайта",      "узнать какие разделы нужны на сайте исходя из его бизнеса"),
    ("Стиль и цвета",      "узнать какой стиль и цвета хочет клиент"),
    ("Примеры сайтов",     "узнать есть ли сайты которые нравятся по дизайну, попросить ссылки"),
    ("Контент",            "узнать есть ли готовые фото, тексты, логотип — или нужно делать с нуля"),
    ("Контакты для сайта", "узнать конкретно какие контакты указать: телефон, адрес, соцсети со ссылками"),
    ("Срок",               "узнать когда нужно готово, есть ли дедлайн"),
]

# ─── СЕССИИ ───────────────────────────────────────────────────────────────────
def new_session():
    return {
        "mode":         "start",       # start | sales | tz
        "stage":        "start",       # зависит от mode
        "messages":     [],            # история диалога для Groq
        "business":     "",            # бизнес клиента
        "agreed_price": "",            # согласованная цена
        "tz_data":      {},            # собранные данные ТЗ
        "tz_step":      0,             # текущий шаг ТЗ
    }

def get_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = new_session()
    return sessions[user_id]

def reset_session(user_id):
    sessions[user_id] = new_session()

# ─── GROQ ─────────────────────────────────────────────────────────────────────
async def ask_groq(system, messages, temp=0.75, max_tokens=500):
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=max_tokens,
            temperature=temp,
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "[КЛИЕНТУ]: Одну секунду...\n[ЛЮДЕ]: Ошибка соединения, попробуй ещё раз."

def parse_sales(response):
    """Разбирает ответ Groq на часть для клиента и подсказку для Люды."""
    parts = response.split("[ЛЮДЕ]:")
    client = parts[0].replace("[КЛИЕНТУ]:", "").strip()
    advice = parts[1].strip() if len(parts) > 1 else ""
    return client, advice

def is_client_ready(advice):
    return "КЛИЕНТ ГОТОВ" in advice.upper()

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Новый клиент",  callback_data="new_client")],
        [InlineKeyboardButton("📖 Обучение PDF",  callback_data="get_pdf")],
        [InlineKeyboardButton("🔧 Диагностика",   callback_data="diagnostics")],
    ])

def kb_sales():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Клиент согласился — собрать ТЗ", callback_data="go_tz")],
        [InlineKeyboardButton("🔄 Новый клиент",                   callback_data="new_client")],
    ])

def kb_tz():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Клиент не знает — пропустить", callback_data="tz_skip")],
    ])

# ─── ТЗ ───────────────────────────────────────────────────────────────────────
async def make_tz_question(business, topic, prev):
    system = (
        "Ты помогаешь собрать данные для разработки сайта. "
        "Напиши один короткий живой вопрос клиенту на Вы. "
        "Адаптируй под конкретный бизнес. Только вопрос без предисловий."
    )
    context = f"Бизнес: {business}."
    if prev:
        context += f" Уже известно: {prev}."
    prompt = f"{context}\nНужно узнать: {topic}\nВопрос:"
    resp = await ask_groq(system, [{"role": "user", "content": prompt}], temp=0.6, max_tokens=100)
    return resp.replace("[КЛИЕНТУ]:", "").strip()

async def check_answer(business, label, answer):
    """Проверяет ответ на конкретность. Возвращает (ok: bool, text: str)."""
    system = (
        "Ты проверяешь ответ клиента при сборе данных для сайта. "
        "Если ответ расплывчатый или непонятный — верни строго: УТОЧНИ: <уточняющий вопрос>. "
        "Если ответ конкретный — верни строго: ОК: <краткий пересказ своими словами>. "
        "Никаких других слов."
    )
    prompt = f"Бизнес: {business}\nВопрос был про: {label}\nОтвет клиента: {answer}"
    resp = await ask_groq(system, [{"role": "user", "content": prompt}], temp=0.2, max_tokens=150)
    resp = resp.strip()
    if resp.upper().startswith("УТОЧНИ:"):
        return False, resp[7:].strip()
    clean = resp[3:].strip() if resp.upper().startswith("ОК:") else answer
    return True, clean

async def send_tz_question(bot, chat_id, session):
    step = session["tz_step"]
    if step >= len(TZ_QUESTIONS):
        await generate_tz(bot, chat_id, session)
        return

    label, topic = TZ_QUESTIONS[step]
    total = len(TZ_QUESTIONS)
    prev = ", ".join([f"{k}: {v}" for k, v in session["tz_data"].items()])
    question = await make_tz_question(session["business"], topic, prev)

    session["stage"] = f"tz_{step}"
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"📝 *Вопрос {step + 1} из {total} — {label}*\n\n"
            f"✉️ *Спроси клиента:*\n\n_{question}_\n\n"
            f"Напечатай что ответил клиент:"
        ),
        parse_mode="Markdown",
        reply_markup=kb_tz()
    )

async def generate_tz(bot, chat_id, session):
    tz_text = "\n".join([f"{k}: {v}" for k, v in session["tz_data"].items()]) or "нет данных"
    price   = session["agreed_price"] or "не указана"
    business = session["business"] or "не указан"

    system = "Ты составляешь техническое задание для разработчика сайта. Чётко, конкретно, без предисловий."
    prompt = (
        f"Составь ТЗ на разработку сайта.\n\n"
        f"Бизнес: {business}\nЦена: {price}\n"
        f"Данные:\n{tz_text}\n\n"
        f"Формат строго по разделам:\n"
        f"КЛИЕНТ: ...\nБИЗНЕС: ...\nЦЕЛЬ: ...\nТИП САЙТА: ...\n"
        f"РАЗДЕЛЫ: ...\nДИЗАЙН: ...\nКОНТЕНТ: ...\n"
        f"КОНТАКТЫ: ...\nСРОК: ...\nБЮДЖЕТ: {price}\nПРИМЕЧАНИЯ: ..."
    )
    result = await ask_groq(system, [{"role": "user", "content": prompt}], temp=0.3, max_tokens=1000)
    clean  = result.replace("[КЛИЕНТУ]:", "").replace("[ЛЮДЕ]:", "").strip()

    session["mode"]  = "start"
    session["stage"] = "start"

    await bot.send_message(
        chat_id=chat_id,
        text=f"📄 *ТЕХНИЧЕСКОЕ ЗАДАНИЕ:*\n\n{clean}\n\n_Скопируй и передай разработчику_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")]
        ])
    )

# ─── ДИАГНОСТИКА ──────────────────────────────────────────────────────────────
async def run_diagnostics(bot, chat_id):
    results = []
    try:
        me = await bot.get_me()
        results.append(f"✅ Telegram API — @{me.username}")
    except Exception as e:
        results.append(f"❌ Telegram API — {e}")

    try:
        models = groq_client.models.list()
        has_llama = any("llama" in m.id for m in models.data)
        results.append("✅ Groq API — подключён" if has_llama else "⚠️ Groq API — модель не найдена")
    except Exception as e:
        results.append(f"❌ Groq API — {e}")

    pdf = os.path.join(os.path.dirname(__file__), "lyuda_training.pdf")
    if os.path.exists(pdf):
        results.append(f"✅ PDF — найден ({os.path.getsize(pdf)//1024} КБ)")
    else:
        results.append("❌ PDF — файл не найден")

    token_ok = bool(os.environ.get("BOT_TOKEN"))
    groq_ok  = bool(os.environ.get("GROQ_API_KEY"))
    if token_ok and groq_ok:
        results.append("✅ Переменные окружения — заданы")
    else:
        missing = [k for k, v in [("BOT_TOKEN", token_ok), ("GROQ_API_KEY", groq_ok)] if not v]
        results.append(f"⚠️ Не заданы в Railway: {', '.join(missing)}")

    results.append(f"✅ Активных сессий: {len(sessions)}")

    errors = sum(1 for r in results if r.startswith("❌"))
    warns  = sum(1 for r in results if r.startswith("⚠️"))
    status = "🔴 Есть ошибки" if errors else ("🟡 Есть замечания" if warns else "🟢 Всё работает")

    await bot.send_message(
        chat_id=chat_id,
        text=f"🔧 *Диагностика*\n\n" + "\n".join(results) + f"\n\n*{status}*",
        parse_mode="Markdown",
        reply_markup=kb_main()
    )

# ─── МОДЕРАТОР ГРУППЫ ─────────────────────────────────────────────────────────
async def ai_moderate(text: str) -> str | None:
    system = (
        "Ты модератор Telegram-группы. Анализируй сообщение.\n"
        "Отвечай СТРОГО одним словом:\n"
        "МАТ — мат, оскорбления, нецензурная лексика включая завуалированную\n"
        "РЕКЛАМА — реклама, спам, ссылки на каналы/сайты, призывы подписаться, "
        "продвижение чужих аккаунтов, заработок, казино, ставки\n"
        "ОК — нормальное сообщение\n"
        "Только одно слово."
    )
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": f"Сообщение: {text}"}
            ],
            max_tokens=5, temperature=0.0,
        )
        result = resp.choices[0].message.content.strip().upper()
        if "МАТ"    in result: return "мат"
        if "РЕКЛАМА" in result: return "реклама"
        return None
    except Exception as e:
        logger.error(f"Moderate error: {e}")
        return None

async def moderator_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    if not msg or not msg.text:
        return
    user = msg.from_user
    if not user:
        return
    chat_id = msg.chat_id

    try:
        admins     = await context.bot.get_chat_administrators(chat_id)
        admin_ids  = {a.user.id for a in admins}
        if user.id in admin_ids:
            return
    except Exception:
        return

    violation = await ai_moderate(msg.text)
    if not violation:
        return

    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Не удалось удалить: {e}")

    mention = (
        f"@{user.username}" if user.username
        else f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    )
    mod_warnings[user.id] = mod_warnings.get(user.id, 0) + 1

    if mod_warnings[user.id] == 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ {mention}, предупреждение! Причина: <b>{violation}</b>. Следующий раз — бан.",
            parse_mode="HTML",
        )
    else:
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            mod_warnings.pop(user.id, None)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🚫 {mention} заблокирован. Причина: повторное нарушение (<b>{violation}</b>).",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Бан не удался: {e}")

# ─── ЛИЧКА — ЛЮДА ─────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_session(update.effective_user.id)
    await update.message.reply_text(
        "👋 Привет, Люда!\n\n"
        "Я веду клиента от первого «здравствуйте» до готового ТЗ.\n\n"
        "🔹 Напишу первое сообщение клиенту\n"
        "🔹 Доведу до согласия\n"
        "🔹 Соберу все детали для сайта\n\n"
        "Начнём? 👇",
        reply_markup=kb_main()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    session = get_session(user_id)

    if query.data == "new_client":
        reset_session(user_id)
        session = get_session(user_id)
        session["mode"]  = "sales"
        session["stage"] = "ask_business"
        await query.message.reply_text(
            "Напиши чем занимается клиент:\n"
            "_Например: кафе, салон красоты, стройматериалы..._",
            parse_mode="Markdown"
        )

    elif query.data == "go_tz":
        # Извлекаем цену из истории если есть
        history = " ".join(m["content"] for m in session["messages"])
        for p in ["5000","6000","7000","8000","10000","12000","15000","20000","25000","30000"]:
            if p in history.replace(" ", "").replace("–", ""):
                session["agreed_price"] = p + " руб."
                break
        session["mode"]    = "tz"
        session["tz_step"] = 0
        session["tz_data"] = {}
        await query.message.reply_text(
            "✅ *Клиент готов! Собираем детали.*\n\n"
            "Копируй вопрос → отправляй клиенту → пиши его ответ сюда.\n\n"
            "Поехали 👇",
            parse_mode="Markdown"
        )
        await send_tz_question(context.bot, chat_id, session)

    elif query.data == "tz_skip":
        step  = session["tz_step"]
        label = TZ_QUESTIONS[step][0]
        session["tz_data"][label] = "не указано"
        session["tz_step"] += 1
        await send_tz_question(context.bot, chat_id, session)

    elif query.data == "diagnostics":
        await query.message.reply_text("🔧 Проверяю, подожди...")
        await run_diagnostics(context.bot, chat_id)

    elif query.data == "get_pdf":
        pdf = os.path.join(os.path.dirname(__file__), "lyuda_training.pdf")
        try:
            with open(pdf, "rb") as f:
                await query.message.reply_document(
                    document=f,
                    filename="Люда_Обучение.pdf",
                    caption="📖 Твоё руководство по продажам сайтов"
                )
        except FileNotFoundError:
            await query.message.reply_text("⚠️ PDF файл не найден на сервере.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text
    chat_id = update.message.chat_id
    session = get_session(user_id)
    mode    = session["mode"]
    stage   = session["stage"]

    # ── Стартовый экран ───────────────────────────────────────────────────────
    if mode == "start":
        await update.message.reply_text(
            "Нажми *Новый клиент* чтобы начать 👇",
            parse_mode="Markdown",
            reply_markup=kb_main()
        )
        return

    # ── Режим продажи ─────────────────────────────────────────────────────────
    if mode == "sales":
        if stage == "ask_business":
            # Люда ввела бизнес клиента
            session["business"] = text
            session["stage"]    = "conversation"
            session["messages"].append({
                "role": "user",
                "content": (
                    f"Клиент занимается: {text}. "
                    f"Люда пишет первой — клиент её не знает. "
                    f"Дай первое короткое сообщение: представься и зацепи одним вопросом. "
                    f"На Вы."
                )
            })
        else:
            # stage == "conversation" — любой текст это ответ клиента
            session["messages"].append({
                "role": "user",
                "content": f"Клиент написал: «{text}». Что мне ответить? На Вы."
            })

        response = await ask_groq(SALES_PROMPT, session["messages"])
        session["messages"].append({"role": "assistant", "content": response})
        client_part, advice_part = parse_sales(response)

        msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
        if advice_part and not is_client_ready(advice_part):
            msg += f"\n\n💡 _{advice_part}_"

        if is_client_ready(advice_part):
            msg += "\n\n🟢 *Клиент готов — переходи к деталям сайта!*"
            await update.message.reply_text(
                msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Собрать детали сайта", callback_data="go_tz")],
                    [InlineKeyboardButton("🔄 Новый клиент",         callback_data="new_client")],
                ])
            )
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_sales())
        return

    # ── Режим сбора ТЗ ────────────────────────────────────────────────────────
    if mode == "tz" and stage.startswith("tz_"):
        step  = int(stage.replace("tz_", ""))
        label = TZ_QUESTIONS[step][0]

        ok, result = await check_answer(session["business"], label, text)
        if not ok:
            # Ответ расплывчатый — просим уточнить, остаёмся на том же вопросе
            await update.message.reply_text(
                f"⚠️ *Уточни у клиента:*\n\n_{result}_\n\nВведи уточнённый ответ:",
                parse_mode="Markdown",
                reply_markup=kb_tz()
            )
            return

        session["tz_data"][label] = result
        session["tz_step"] = step + 1
        await send_tz_question(context.bot, chat_id, session)

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    # Группы — модератор
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS, moderator_handler
    ))
    # Личка — помощник Люды
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, message_handler
    ))
    logger.info("Luda Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
