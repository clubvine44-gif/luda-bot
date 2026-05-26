import asyncio
from telegram import Bot

# Вставь НОВЫЙ токен после revoke в BotFather
BOT_TOKEN = "8638675668:AAHj2aNq2sudn7CiEV2Hz94q9I33itJpUUw"

# Все user_id кто писал боту — добавь вручную если знаешь
# Скрипт попробует получить обновления сам
KNOWN_USERS = []

MESSAGE = """🚨 ВНИМАНИЕ — ВАЖНОЕ СООБЩЕНИЕ

Бот был взломан через сторонний прокси-сервис.

Если вы передавали боту какие-либо личные данные — номера телефонов, адреса, пароли — рекомендуем принять меры предосторожности.

Бот восстановлен и защищён. Старый доступ злоумышленников заблокирован.

Приносим извинения за произошедшее."""

async def main():
    bot = Bot(token=BOT_TOKEN)

    # Пробуем получить список пользователей из обновлений
    user_ids = set(KNOWN_USERS)
    try:
        updates = await bot.get_updates(limit=100, timeout=5)
        for u in updates:
            if u.message and u.message.from_user:
                user_ids.add(u.message.from_user.id)
            if u.callback_query and u.callback_query.from_user:
                user_ids.add(u.callback_query.from_user.id)
        print(f"Найдено пользователей: {len(user_ids)}")
    except Exception as e:
        print(f"Ошибка получения обновлений: {e}")

    if not user_ids:
        print("Пользователей не найдено. Добавь ID вручную в KNOWN_USERS.")
        return

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=MESSAGE)
            print(f"✅ Отправлено: {uid}")
            sent += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"❌ Не удалось {uid}: {e}")
            failed += 1

    print(f"\nГотово. Отправлено: {sent}, ошибок: {failed}")

asyncio.run(main())
