"""Сообщения оператору (владельцу бота): en/ru, выбор через operator_language в config.json."""

MESSAGES = {
    "en": {
        "model_down": "⚠️ Ollama is not responding or model «{model}» was not found. Replies will use fallbacks.",
        "deliver_ok": "🟢 Delivery mode is running. Quest goes out {when}, recipient {recipient}, model {model}, images {have}/{need}.",
        "deliver_problem": "⚠️ Delivery mode is running, but: {problems}. (Quest goes out {when}, recipient {recipient}, model {model}.)",
        "p_recipient": "recipient_id in config.json is empty or equals your ID",
        "p_model": "Ollama/model unavailable",
        "p_images": "missing images: {names}",
        "recipient_started": "Recipient pressed /start, ID: {uid} (config recipient_id = {configured}). {verdict}",
        "id_match": "Match ✅",
        "id_mismatch": "MISMATCH ⚠️ — fix config.json",
        "sent_ok": "✅ Quest sent to the recipient.",
        "forbidden": "⚠️ Telegram won't let the bot write to the recipient: they never pressed /start. "
                     "Ask them to press it, restart the bot, and the quest will go out by itself.",
        "failed": "⚠️ Could not send the quest after 6 attempts, see data/bot.log.",
        "token_rejected": "Telegram rejected the bot token ({source}, bot id {bot_id}): it is wrong or revoked. If you set TELEGRAM_TOKEN earlier (setx), remove that variable or put the right token into .env (the .env value wins).",
        "no_recipient": "⚠️ Launch time, but recipient_id is not configured (empty or equals your ID). Quest not sent.",
    },
    "ru": {
        "model_down": "⚠️ Ollama не отвечает или модель «{model}» не найдена. Ответы будут заготовками.",
        "deliver_ok": "🟢 Режим доставки запущен. Квест уйдёт {when}, получатель {recipient}, модель {model}, картинки {have}/{need}.",
        "deliver_problem": "⚠️ Режим доставки запущен, но: {problems}. (Квест уйдёт {when}, получатель {recipient}, модель {model}.)",
        "p_recipient": "recipient_id в config.json пуст или равен твоему ID",
        "p_model": "Ollama/модель недоступны",
        "p_images": "нет картинок: {names}",
        "recipient_started": "Получатель нажал /start, его ID: {uid} (в config.json recipient_id = {configured}). {verdict}",
        "id_match": "Совпадает ✅",
        "id_mismatch": "НЕ СОВПАДАЕТ ⚠️ — поправь config.json",
        "sent_ok": "✅ Квест отправлен получателю.",
        "forbidden": "⚠️ Telegram не даёт написать получателю: он не нажимал /start у бота. "
                     "Пусть нажмёт и перезапусти бота — квест уйдёт сам.",
        "failed": "⚠️ Не удалось отправить квест за 6 попыток, смотри data/bot.log.",
        "token_rejected": "Telegram отклонил токен бота ({source}, id бота {bot_id}): он неверный или отозван. Если раньше задавали TELEGRAM_TOKEN через setx, удалите эту переменную или впишите верный токен в .env (значение из .env главнее).",
        "no_recipient": "⚠️ Час X, но recipient_id не настроен (пусто или равен твоему ID). Квест не отправлен.",
    },
}


def t(lang: str, key: str, **kw) -> str:
    table = MESSAGES.get(lang) or MESSAGES["en"]
    return table[key].format(**kw)
