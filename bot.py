import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8638675668:AAHt6PnzmcLbZfMPYsuwPZEbTec96eBy1sQ")

# ─────────────────────────────────────────────
# МОДЕРАТОР — счётчик предупреждений
# ─────────────────────────────────────────────
mod_warnings: dict[int, int] = {}
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")

groq_client = Groq(api_key=GROQ_API_KEY)

SALES_PROMPT = """Ты — опытный помощник продажника Люды. Люда продаёт сайты малому бизнесу.
Люда сама выходит на клиентов — пишет или звонит первой. Клиент Люду не знает.

ВАЖНО ПРО КОНТЕКСТ:
- Это всегда холодный контакт — клиент Люду не ждал
- Первое сообщение должно быть коротким, не навязчивым и с одним вопросом
- Не пиши "приятно познакомиться" и не делай вид что уже знакомы
- Не предполагай что клиент хочет сайт — сначала выясни ситуацию

КАК ОБЩАЕШЬСЯ:
- Живо и по-человечески, коротко
- С клиентом строго на "Вы"
- Максимум 2-3 предложения за раз
- Один вопрос за раз
- Веди плавно: знакомство → интерес → доверие → решение → согласие

ЭТАПЫ:
1. Представиться и зацепить интерес одним вопросом
2. Выяснить есть ли сайт и как сейчас приходят клиенты
3. Показать что без сайта бизнес теряет клиентов
4. Предложить конкретное решение под его бизнес
5. Назвать цену только когда клиент понял ценность
6. Получить "да, давайте"

ПРОДУКТЫ:
- Сайт-визитка: 5 000–8 000 руб., 3–5 дней
- Каталог услуг: 8 000–15 000 руб., 5–7 дней
- Интернет-магазин: 15 000–30 000 руб., 7–14 дней
- Telegram Mini App: 10 000–25 000 руб., 5–10 дней
- Лендинг: 4 000–7 000 руб., 2–4 дня

ЖЁСТКИЕ ПРАВИЛА:
1. Не упоминай договор, реквизиты, оплату, начало работ
2. Не заканчивай диалог сам
3. НИКОГДА не спрашивай про бюджет первым — это отпугивает
4. Цену называй только если клиент сам спросил "сколько стоит" или явно готов
5. Когда клиент сказал "да" на цену или "давайте" — напиши в [ЛЮДЕ]: КЛИЕНТ ГОТОВ
6. При "дорого" — не снижай сразу, сначала уточни что именно смущает
7. Предлагай только то что подходит под бизнес клиента

ФОРМАТ СТРОГО:
[КЛИЕНТУ]: текст который Люда скопирует и отправит
[ЛЮДЕ]: короткая подсказка что сейчас происходит"""

# Вопросы ТЗ — адаптируются под бизнес через ИИ
TZ_QUESTIONS_BASE = [
    ("Название бизнеса",   "узнать точное название бизнеса клиента"),
    ("Цель сайта",         "узнать что должен делать сайт: принимать звонки, заявки, бронирования, показывать услуги"),
    ("Разделы сайта",      "узнать какие разделы нужны на сайте исходя из его бизнеса"),
    ("Стиль и цвета",      "узнать какой стиль и цвета хочет клиент"),
    ("Примеры сайтов",     "узнать есть ли сайты которые нравятся клиенту по дизайну, попросить прислать ссылки"),
    ("Контент",            "узнать есть ли готовые фото, тексты описания услуг, логотип — или нужно делать с нуля"),
    ("Контакты для сайта", "узнать конкретно какие контакты указать: номер телефона, адрес, названия соцсетей и ссылки на них"),
    ("Срок",               "узнать когда нужно готово, есть ли дедлайн"),
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
            "business": "",
            "agreed_price": "",
        }
    return sessions[user_id]

def reset_session(user_id):
    sessions[user_id] = {
        "mode": "start",
        "stage": "start",
        "messages": [],
        "tz_data": {},
        "tz_step": 0,
        "business": "",
        "agreed_price": "",
    }

async def ask_groq(system, messages, temp=0.75):
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=500,
            temperature=temp
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "[КЛИЕНТУ]: Одну секунду...\n[ЛЮДЕ]: Ошибка соединения, попробуй ещё раз."

def parse_sales(response):
    parts = response.split("[ЛЮДЕ]:")
    client = parts[0].replace("[КЛИЕНТУ]:", "").strip()
    advice = parts[1].strip() if len(parts) > 1 else ""
    return client, advice

def client_ready(advice):
    return "КЛИЕНТ ГОТОВ" in advice.upper()

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Новый клиент",        callback_data="new_client")],
        [InlineKeyboardButton("📖 Обучение PDF",         callback_data="get_pdf")],
        [InlineKeyboardButton("🔧 Проверить бота",       callback_data="diagnostics")],
    ])

def kb_sales():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ввести ответ клиента", callback_data="sales_reply")],
        [InlineKeyboardButton("✅ Клиент согласился",    callback_data="go_tz")],
        [InlineKeyboardButton("🔄 Новый клиент",         callback_data="new_client")],
    ])

def kb_tz_answer():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ввести ответ клиента", callback_data="tz_reply")],
        [InlineKeyboardButton("⏭ Клиент не знает",      callback_data="tz_skip")],
    ])

async def make_tz_question(business, label, topic, prev_answers):
    """Генерирует живой вопрос адаптированный под конкретный бизнес"""
    context = f"Бизнес клиента: {business}.\n"
    if prev_answers:
        context += f"Уже известно: {prev_answers}\n"

    system = (
        "Ты помогаешь собрать информацию для разработки сайта. "
        "Сформулируй один короткий живой вопрос клиенту на Вы. "
        "Вопрос должен быть адаптирован под конкретный бизнес — "
        "не задавай лишних вариантов которые не подходят этому бизнесу. "
        "Только вопрос без предисловий."
    )
    prompt = f"{context}\nНужно узнать: {topic}\nДай один вопрос:"
    resp = await ask_groq(system, [{"role": "user", "content": prompt}], temp=0.6)
    return resp.replace("[КЛИЕНТУ]:", "").strip()

async def clarify_answer(business, label, answer):
    """Проверяет расплывчатый ответ и уточняет если нужно"""
    system = (
        "Ты анализируешь ответ клиента при сборе данных для сайта. "
        "Если ответ расплывчатый, неполный или непонятный — верни УТОЧНИ: и напиши уточняющий вопрос. "
        "Если ответ нормальный и конкретный — верни ОК: и повтори ответ своими словами кратко. "
        "Например: 'все' на вопрос про контакты — это расплывчато, нужно уточнить какие именно. "
        "'89001234567, Instagram @myshop, ул. Ленина 5' — это конкретно, ОК."
    )
    prompt = f"Бизнес: {business}\nВопрос был про: {label}\nОтвет клиента: {answer}"
    resp = await ask_groq(system, [{"role": "user", "content": prompt}], temp=0.3)
    return resp.strip()

async def send_tz_question(bot, chat_id, session):
    step = session["tz_step"]
    if step >= len(TZ_QUESTIONS_BASE):
        await generate_brief(bot, chat_id, session)
        return

    label, topic = TZ_QUESTIONS_BASE[step]
    total = len(TZ_QUESTIONS_BASE)
    session["stage"] = f"tz_answer_{step}"

    # Собираем контекст предыдущих ответов
    prev = ", ".join([f"{k}: {v}" for k, v in session["tz_data"].items()]) if session["tz_data"] else ""

    question = await make_tz_question(session["business"], label, topic, prev)

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
    tz = session.get("tz_data", {})
    business = session.get("business", "не указан")
    price = session.get("agreed_price", "не указана")

    tz_text = "\n".join([f"{k}: {v}" for k, v in tz.items()]) if tz else "нет данных"

    system = (
        "Ты составляешь техническое задание для разработчика сайта. "
        "Пиши только ТЗ — чётко, конкретно, без предисловий и лишних фраз."
    )
    prompt = (
        f"Составь техническое задание на разработку сайта.\n\n"
        f"Бизнес: {business}\n"
        f"Согласованная цена: {price}\n"
        f"Данные от клиента:\n{tz_text}\n\n"
        f"Формат строго по разделам:\n"
        f"КЛИЕНТ: ...\n"
        f"БИЗНЕС: ...\n"
        f"ЦЕЛЬ САЙТА: ...\n"
        f"ТИП САЙТА: ...\n"
        f"РАЗДЕЛЫ: ...\n"
        f"ДИЗАЙН И СТИЛЬ: ...\n"
        f"КОНТЕНТ: ...\n"
        f"КОНТАКТЫ: ...\n"
        f"СРОК: ...\n"
        f"БЮДЖЕТ: {price}\n"
        f"ПРИМЕЧАНИЯ: ..."
    )
    brief = await ask_groq(system, [{"role": "user", "content": prompt}])
    clean = brief.replace("[КЛИЕНТУ]:", "").replace("[ЛЮДЕ]:", "").strip()

    await bot.send_message(
        chat_id=chat_id,
        text=f"📄 *ТЕХНИЧЕСКОЕ ЗАДАНИЕ:*\n\n{clean}\n\n_Скопируй и отправь разработчику_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 Новый клиент", callback_data="new_client")]
        ])
    )

async def run_diagnostics(bot, chat_id):
    """Быстрая проверка всех компонентов бота"""
    results = []

    # 1. Telegram Bot API
    try:
        me = await bot.get_me()
        results.append(f"✅ Telegram API — @{me.username}")
    except Exception as e:
        results.append(f"❌ Telegram API — {e}")

    # 2. Groq API — только соединение, без генерации текста
    try:
        models = groq_client.models.list()
        names = [m.id for m in models.data if "llama" in m.id]
        if names:
            results.append(f"✅ Groq API — подключён, модель доступна")
        else:
            results.append("⚠️ Groq API — подключён, но нужная модель не найдена")
    except Exception as e:
        results.append(f"❌ Groq API — {e}")

    # 3. PDF файл
    pdf_path = os.path.join(os.path.dirname(__file__), "lyuda_training.pdf")
    if os.path.exists(pdf_path):
        size_kb = os.path.getsize(pdf_path) // 1024
        results.append(f"✅ PDF обучение — найден ({size_kb} КБ)")
    else:
        results.append("❌ PDF обучение — файл не найден на сервере")

    # 4. Переменные окружения
    token_ok = bool(os.environ.get("BOT_TOKEN"))
    groq_ok  = bool(os.environ.get("GROQ_API_KEY"))
    if token_ok and groq_ok:
        results.append("✅ Переменные окружения — BOT_TOKEN и GROQ_API_KEY заданы")
    else:
        missing = []
        if not token_ok: missing.append("BOT_TOKEN")
        if not groq_ok:  missing.append("GROQ_API_KEY")
        results.append(f"⚠️ Токены из кода ({', '.join(missing)} не заданы в Railway)")

    # 5. Сессии в памяти
    results.append(f"✅ Сессии — активных диалогов: {len(sessions)}")

    # 6. Промпты загружены
    if SALES_PROMPT and TZ_QUESTIONS_BASE:
        results.append(f"✅ Промпты — загружены ({len(TZ_QUESTIONS_BASE)} вопросов ТЗ)")
    else:
        results.append("❌ Промпты — не загружены")

    # Итог
    errors   = [r for r in results if r.startswith("❌")]
    warnings = [r for r in results if r.startswith("⚠️")]
    ok       = [r for r in results if r.startswith("✅")]

    if errors:
        status = "🔴 Есть критические ошибки"
    elif warnings:
        status = "🟡 Работает с замечаниями"
    else:
        status = "🟢 Всё работает нормально"

    text = f"🔧 *Диагностика бота*\n\n"
    text += "\n".join(results)
    text += f"\n\n*Итог:* {status}"
    text += f"\n✅ {len(ok)}  ⚠️ {len(warnings)}  ❌ {len(errors)}"

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=kb_main()
    )

# Флаг — уведомление о взломе уже отправлено этому пользователю
hack_notified = set()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reset_session(user_id)

    # Уведомление о взломе — отправляем один раз каждому
    if user_id not in hack_notified:
        hack_notified.add(user_id)
        await update.message.reply_text(
            "🚨 *ВАЖНОЕ УВЕДОМЛЕНИЕ*\n\n"
            "Бот был временно взломан через сторонний прокси-сервис.\n"
            "Злоумышленники имели доступ к переписке в боте.\n\n"
            "✅ Проблема устранена — токен заменён, доступ заблокирован.\n\n"
            "⚠️ Если вы передавали боту личные данные — будьте осторожны.",
            parse_mode="Markdown"
        )

    await update.message.reply_text(
        "👋 Привет, Люда!\n\n"
        "Я веду клиента от первого «здравствуйте» до готового ТЗ для разработчика.\n\n"
        "🔹 Помогу написать клиенту с нуля\n"
        "🔹 Доведу до согласия\n"
        "🔹 Соберу все детали для сайта\n\n"
        "Начнём? 👇",
        reply_markup=kb_main()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    key = f"btn_{user_id}_{query.id}"
    if key in processing:
        return
    processing.add(key)

    try:
        session = get_session(user_id)
        chat_id = query.message.chat_id

        if query.data == "diagnostics":
            await query.message.reply_text("🔧 Запускаю проверку, подожди...")
            await run_diagnostics(context.bot, chat_id)
            return

        elif query.data == "new_client":
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
            # Пытаемся извлечь согласованную цену из истории диалога
            history_text = " ".join([m["content"] for m in session["messages"]])
            for word in ["5000", "6000", "7000", "8000", "10000", "12000", "15000", "20000", "25000", "30000"]:
                if word in history_text.replace(" ", "").replace("–", ""):
                    session["agreed_price"] = word + " руб."
                    break

            await query.message.reply_text(
                "✅ *Отлично — клиент готов!*\n\n"
                "Теперь собираем детали для сайта.\n"
                "Копируй вопрос → отправляй клиенту → вводи его ответ.\n\n"
                "Поехали 👇",
                parse_mode="Markdown"
            )
            await send_tz_question(context.bot, chat_id, session)

        elif query.data == "tz_reply":
            step = session.get("tz_step", 0)
            session["stage"] = f"tz_answer_{step}"
            await query.message.reply_text("Напечатай ответ клиента:")

        elif query.data == "tz_skip":
            step = session["tz_step"]
            label, _ = TZ_QUESTIONS_BASE[step]
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
            # Не сбрасываем на старт — просто показываем меню
            await update.message.reply_text(
                "Нажми *Новый клиент* чтобы начать 👇",
                parse_mode="Markdown",
                reply_markup=kb_main()
            )
            return

        # ── РЕЖИМ ПРОДАЖИ ─────────────────────────────────────────────────
        if session["mode"] == "sales":
            if session["stage"] == "ask_business":
                session["business"] = text
                session["stage"] = "conversation"
                session["messages"].append({
                    "role": "user",
                    "content": (
                        f"Клиент занимается: {text}. "
                        f"Люда пишет этому клиенту первой — он её не знает. "
                        f"Дай первое короткое сообщение: представься и зацепи интерес одним вопросом. "
                        f"Не делай вид что знакомы. На Вы."
                    )
                })
            elif session["stage"] in ("conversation", "waiting_reply"):
                session["stage"] = "conversation"
                session["messages"].append({
                    "role": "user",
                    "content": f"Клиент написал: «{text}». Что мне ответить? На Вы."
                })
            else:
                # Любой другой текст — воспринимаем как ответ клиента
                session["stage"] = "conversation"
                session["messages"].append({
                    "role": "user",
                    "content": f"Клиент написал: «{text}». Что мне ответить? На Вы."
                })

            response = await ask_groq(SALES_PROMPT, session["messages"])
            session["messages"].append({"role": "assistant", "content": response})
            client_part, advice_part = parse_sales(response)

            msg = f"✉️ *Отправь клиенту:*\n\n_{client_part}_"
            if advice_part and "КЛИЕНТ ГОТОВ" not in advice_part.upper():
                msg += f"\n\n💡 _{advice_part}_"

            if client_ready(advice_part):
                msg += "\n\n🟢 *Клиент готов — переходи к деталям сайта!*"
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
            label, _ = TZ_QUESTIONS_BASE[step]

            # Проверяем расплывчатость ответа
            check = await clarify_answer(session["business"], label, text)

            if check.startswith("УТОЧНИ:"):
                # Ответ расплывчатый — просим уточнить
                clarify_q = check.replace("УТОЧНИ:", "").strip()
                await update.message.reply_text(
                    f"⚠️ *Ответ нечёткий — уточни у клиента:*\n\n_{clarify_q}_\n\n"
                    f"Введи уточнённый ответ:",
                    parse_mode="Markdown",
                    reply_markup=kb_tz_answer()
                )
                # Остаёмся на том же вопросе
                return

            # Ответ нормальный — сохраняем и идём дальше
            clean_answer = check.replace("ОК:", "").strip()
            session["tz_data"][label] = clean_answer if clean_answer else text
            session["tz_step"] = step + 1
            await send_tz_question(context.bot, chat_id, session)

    finally:
        processing.discard(key)

async def ai_moderate(text: str) -> str | None:
    """Отправляет сообщение в Groq для анализа. Возвращает тип нарушения или None."""
    system = (
        "Ты модератор Telegram-группы. Анализируй сообщение и определи нарушение.\n"
        "Отвечай СТРОГО одним словом:\n"
        "МАТ — если есть мат, оскорбления, нецензурная лексика (в том числе завуалированная: х*й, б**дь, f*ck и т.п.)\n"
        "РЕКЛАМА — если есть реклама, спам, ссылки на каналы/сайты, призывы подписаться, упоминания чужих аккаунтов с целью продвижения, предложения заработка, казино, ставки\n"
        "ОК — если сообщение нормальное\n"
        "Только одно слово. Никаких объяснений."
    )
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Сообщение: {text}"}
            ],
            max_tokens=10,
            temperature=0.0,
        )
        result = response.choices[0].message.content.strip().upper()
        if "МАТ" in result:
            return "мат"
        elif "РЕКЛАМА" in result:
            return "реклама"
        return None
    except Exception as e:
        logger.error(f"Groq moderation error: {e}")
        return None


async def moderator_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Модератор группы — анализирует сообщения через ИИ."""
    msg = update.message
    if not msg or not msg.text:
        return
    user = msg.from_user
    if not user:
        return
    chat_id = msg.chat_id

    # Пропускаем администраторов
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        admin_ids = {a.user.id for a in admins}
        if user.id in admin_ids:
            return
    except Exception:
        return

    # ИИ-анализ сообщения
    violation = await ai_moderate(msg.text)
    if not violation:
        return

    # Удаляем сообщение
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение: {e}")

    mention = f"@{user.username}" if user.username else f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    mod_warnings[user.id] = mod_warnings.get(user.id, 0) + 1
    count = mod_warnings[user.id]

    if count == 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ {mention}, предупреждение! Причина: <b>{violation}</b>. Следующее нарушение — бан.",
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
            logger.error(f"Не удалось забанить {user.id}: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, moderator_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, message_handler))
    logger.info("Luda Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
