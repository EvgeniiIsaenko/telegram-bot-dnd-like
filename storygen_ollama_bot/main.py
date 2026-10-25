import asyncio
# for logs
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from functools import wraps

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import ollama
import utilities as db
from initiate_db import init_db

load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
# max user input
MAX_INPUT = 1500

# for logs, on level of info - log
logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s: %(message)s", level=logging.INFO)
# ignore http in the logs (unless it's a wrning or an error)
logging.getLogger("httpx").setLevel(logging.WARNING)
# create logger for the bot
logger = logging.getLogger("rpg-bot")

# only for direct messages
PRIVATE = filters.ChatType.PRIVATE
# async for multiple users to not conflict for the lock
_locks = defaultdict(asyncio.Lock)

# telegram limit of 4096 (?) so it splits into multiple texts
# yield func
def split_text(text: str, limit: int = 4000):
    while len(text) > limit:
        # find the new line
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    if text:
        yield text

# send split_text bits
async def reply_long(update: Update, text: str, **kwargs):
    for chunk in split_text(text):
        await update.effective_message.reply_text(chunk, **kwargs)

# context manager for yield func
# show that the model is thinking/typing
@asynccontextmanager
async def typing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async def loop():
        while True:
            try:
                # call telegram's api to show "typing.." on the top
                await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
            except Exception:
                pass
            await asyncio.sleep(4)

    # set the typing on loop and yield afterwards
    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()

# function to let only registered users play
def registered(handler):
    # wrapper to handle all func inputs
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        char = db.get_char_info(update.effective_user.id)
        if not char:
            await update.effective_message.reply_text("Сначала создайте персонажа: /start")
            return
        db.touch_user(update.effective_user.id)
        return await handler(update, context, char)
    return wrapper

# narration from ollama
async def narrate(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    tg_id = update.effective_user.id
    # using async locks
    async with _locks[tg_id]:
        char = db.get_char_info(tg_id)
        if char["hp"] <= 0:
            await update.effective_message.reply_text(
                "Ваш герой вмер. Начать новую историю: /newgame")
            return

        # adding a story from user
        db.add_story(char["id"], "user", user_text)
        history = db.get_story(char["id"], ollama.HISTORY_LIMIT)
        system = ollama.build_system_prompt(char, db.get_inventory(char["id"]))

        try:
            async with typing(update, context):
                raw = await ollama.chat(system, history)
        except ollama.OllamaError as e:
            # if we have an error - rollback
            db.delete_last_story(char["id"])
            await update.effective_message.reply_text(f"Не можем связаться с рассказчкиом: {e}")
            return

        # parsing
        text, effects = ollama.parse_response(raw)
        if not text:
            db.delete_last_story(char["id"])
            await update.effective_message.reply_text(
                "Расскзчик не смог пропарсить ваше действие")
            return

        db.add_story(char["id"], "assistant", text)
        notes = db.apply_effects(char["id"], effects)

    await reply_long(update, text)
    if notes:
        await update.effective_message.reply_text("\n".join(notes))

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    char = db.get_char_info(update.effective_user.id)
    #if we already have a char
    if char:
        await update.message.reply_text(
            f"С возвращением, {char['name']}! Опишите, что делает ваш герой, и рассказчик продолжит историю.\n"
            "Список команд: /help")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Мужской", callback_data="gender:m"),
        InlineKeyboardButton("Женский", callback_data="gender:f"),
    ]])
    await update.message.reply_text(
        "Добро пожаловать в ДНД-like бота с привязкой к Ollama\n"
        "Для начала создадим героя. Выберите пол персонажа:",
        reply_markup=keyboard)

# after choosing gender
async def on_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg = query.from_user

    if db.get_char_info(tg.id):
        await query.edit_message_text("Персонаж уже создан. Список команд: /help")
        return

    gender = query.data.split(":")[1]
    # default to a tg name
    name = tg.first_name or tg.username or "Странник"
    char = db.register_user(tg.id, tg.username, name, gender)
    await query.edit_message_text(
        f"Герой создан. Вас зовут {char['name']}.\n\n"
        "Сменить имя: /set_name <Имя>\n"
        "Рассказать о себе: /set_about текст\n\n"
        "Чтобы начать просто напишите, что делает ваш герой "
        "(например: «Я просыпаюсь после жестокой пьянки в пабе 18-го века в мире с магией и монстрами»).")

# help list
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Доступные команды:\n"
        "/start - начать работу бота\n"
        "/help - помощь/команды\n"
        "/about_me - посмотреть информацию о себе\n"
        "/inventory - посмотреть свой инвентарь\n"
        "/item <название> - посмотреть информацию о предмете\n"
        "/context - посмотреть текущий контекст истории\n"
        "/roll - бросить кубик/монетку на проверку\n"
        "\n"
        "Дополнительно:\n"
        "/set_name <имя> - сменить имя героя\n"
        "/set_about <текст> - рассказать о своём герое\n"
        "/newgame - начать приключение заново\n"
        "\n"
        "Примеры /roll: /roll, /roll d6, /roll 2d6, /roll монетка, "
        "/roll d20 взломать замок"
    )

    await update.message.reply_text(help_text)

# shows about_me
@registered
async def about_me(update: Update, context: ContextTypes.DEFAULT_TYPE, char: dict):
    gender = "Мужской" if char["gender"] == "m" else "Женский"
    message = (
        "Ваши данные:\n"
        f"Имя: {char['name']}\n"
        f"Пол: {gender}\n"
        f"Уровень: {char['level']} (опыт {char['xp']}/{char['xp_next']})\n"
        f"Здоровье: {char['hp']}/{char['max_hp']}\n"
        f"О себе: {char['about'] or 'пока ничего (добавить: /set_about текст)'}"
    )
    await update.message.reply_text(message)

# shows inventory
@registered
async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE, char: dict):
    items = db.get_inventory(char["id"])
    if not items:
        await update.message.reply_text("Инвентарь пуст.")
        return
    lines = [f"• {i['name']}" + (f" x{i['quantity']}" if i["quantity"] > 1 else "") for i in items]
    await reply_long(update, "Инвентарь:\n" + "\n".join(lines) + "\n\nПодробнее: /item <название>")

# shows info about an item
@registered
async def item_info(update: Update, context: ContextTypes.DEFAULT_TYPE, char: dict):
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Укажите название предмета: /item <название>")
        return
    item = db.find_item(char["id"], name)
    if not item:
        await update.message.reply_text(f"У вас нет предмета «{name}». Посмотреть вещи: /inventory")
        return
    await reply_long(update, f"{item['name']} (x{item['quantity']})\n\n{item['about'] or 'Описания пока нет.'}")

# shows context
@registered
async def context_command(update: Update, context: ContextTypes.DEFAULT_TYPE, char: dict):
    total = db.count_story(char["id"])
    if total == 0:
        await update.message.reply_text("Контекст пуст.")
        return

    shown = min(total, 6)
    lines = []
    for m in db.get_story(char["id"], shown):
        who = "Вы" if m["role"] == "user" else "Рассказчик"
        content = m["content"]
        if len(content) > 350:
            content = content[:350].rstrip() + "…"
        lines.append(f"{who}: {content}")

    header = (f"Контекст истории: сообщений всего {total}, "
              f"в модель уходят последние {min(total, ollama.HISTORY_LIMIT)}.\n"
              f"Последние {shown}:\n")
    await reply_long(update, header + "\n\n".join(lines))

# roll command
@registered
async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE, char: dict):
    try:
        r = db.parse_roll(context.args)
    except ValueError:
        await update.message.reply_text("Допустимо от 1 до 20 костей и от 2 до 1000 граней, например: /roll 2d6")
        return

    result_line = f"{'coin: ' if r['kind'] == 'coin' else 'dice: '} {r['label']}: {r['text']}"
    await update.message.reply_text(result_line)

    if db.count_story(char["id"]) == 0:
        return

    action = r["rest"] or "проверка в текущей ситуации"
    if r["kind"] == "coin":
        narrator_msg = f"[Подбрасывание монетки] Выпало: {r['text']}. Проверка: {action}. Опиши результат с учётом исхода."
    else:
        note = ""
        if r["kind"] == "dice" and r["count"] == 1 and r["sides"] == 20:
            note = " (1 — критический провал, 20 — критический успех)"
        narrator_msg = (f"[Бросок кубика {r['label']}] Выпало: {r['text']}{note}. "
                        f"Проверка: {action}. Опиши результат с учётом броска.")
    await narrate(update, context, narrator_msg)

# name setter
@registered
async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE, char: dict):
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Использование: /set_name <имя>")
        return
    if len(name) > 60:
        await update.message.reply_text("Слишком длинное имя (максимум 60 символов).")
        return
    db.update_profile(update.effective_user.id, name=name)
    await update.message.reply_text(f"Теперь вашего героя зовут {name}.")

# about setter
@registered
async def set_about(update: Update, context: ContextTypes.DEFAULT_TYPE, char: dict):
    about = " ".join(context.args).strip()
    if not about:
        await update.message.reply_text("Использование: /set_about <текст о вашем герое>")
        return
    if len(about) > 1000:
        await update.message.reply_text("Слишком длинный текст (максимум 1000 символов).")
        return
    db.update_profile(update.effective_user.id, about=about)
    await update.message.reply_text("Записано.")

# newgame start
@registered
async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE, char: dict):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Да, начать заново", callback_data="newgame:yes"),
        InlineKeyboardButton("Отмена", callback_data="newgame:no"),
    ]])
    await update.message.reply_text(
        "Начать приключение заново? История и инвентарь будут удалены, уровень сбросится до 1. "
        "Имя и описание героя сохранятся.",
        reply_markup=keyboard)

# after newgame start
async def on_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    char = db.get_char_info(query.from_user.id)
    if not char:
        await query.edit_message_text("Сначала создайте персонажа: /start")
        return
    if query.data.endswith(":yes"):
        async with _locks[query.from_user.id]:
            db.reset_adventure(char["id"])
        await query.edit_message_text("Напишите, что делает ваш герой.")
    else:
        await query.edit_message_text("Новая игра отменена.")

# any text is a command to the bot, just not too many symbols
@registered
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE, char: dict):
    text = update.message.text.strip()
    if len(text) > MAX_INPUT:
        await update.message.reply_text(f"Слишком длинное сообщение (максимум {MAX_INPUT} символов).")
        return
    # immediate call to narrate that
    await narrate(update, context, text)

# error handler
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Can't update for some reason!", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Попробуйте еще раз, столкнулись с ошибкой.")
        except Exception:
            pass

# init add commands
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "начать работу бота"),
        BotCommand("help", "помощь/команды"),
        BotCommand("about_me", "информация о герое"),
        BotCommand("inventory", "инвентарь"),
        BotCommand("item", "информация о предмете"),
        BotCommand("context", "контекст истории"),
        BotCommand("roll", "бросить кубик/монетку"),
        BotCommand("set_name", "сменить имя героя"),
        BotCommand("set_about", "рассказать о герое"),
        BotCommand("newgame", "начать заново"),
    ])

# main func! finally
def main():
    # should always have a telegram token
    if not TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN не задан в .env")

    # init_db starts up the database, shouldn't reset it, just start it up again
    init_db()
    # concurrent to not wait for another person to finish, not as useful on a local host obviously
    app = (Application.builder()
           .token(TELEGRAM_TOKEN)
           .concurrent_updates(True)
           .post_init(post_init)
           .build())

    commands = {
        "start": start,
        "help": help_command,
        "about_me": about_me,
        "inventory": inventory,
        "item": item_info,
        "context": context_command,
        "roll": roll,
        "set_name": set_name,
        "set_about": set_about,
        "newgame": newgame,
    }

    for name, handler in commands.items():
        app.add_handler(CommandHandler(name, handler, filters=PRIVATE))

    # handlers for actions (on_gender, on_newgame..)
    # most important is the message handler, we need it to actually call for Ollama
    app.add_handler(CallbackQueryHandler(on_gender, pattern=r"^gender:"))
    app.add_handler(CallbackQueryHandler(on_newgame, pattern=r"^newgame:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & PRIVATE, on_text))
    app.add_error_handler(on_error)

    logger.info("Бот запущен (модель: %s, Ollama: %s)", ollama.OLLAMA_MODEL, ollama.OLLAMA_URL)
    # run polling to start
    app.run_polling()

# py main.py
if __name__ == "__main__":
    main()