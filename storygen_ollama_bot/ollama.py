import os
import re
import httpx
from dotenv import load_dotenv

load_dotenv()
OLLAMA_URL = os.getenv('OLLAMA_URL')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL')
OLLAMA_TIMEOUT = float(os.getenv('OLLAMA_TIMEOUT'))
HISTORY_LIMIT = int(os.getenv('HISTORY_LIMIT'))

# to skip all errors, since all we need is an exception to show up, not actually have it fixed
class OllamaError(Exception):
    pass

# generated this with claude
SYSTEM_TEMPLATE = """Ты — Рассказчик (мастер игры) в текстовой фэнтезийной RPG. Ты ведёшь историю для одного игрока.

ПРАВИЛА ПОВЕСТВОВАНИЯ
- Отвечай на русском языке, от второго лица («Вы входите в таверну...»), живо и образно, 1–3 абзаца (не длиннее ~1200 символов).
- Описывай мир, NPC и последствия действий героя. Никогда не принимай решения за героя и не говори от его имени.
- Заканчивай ответ ситуацией, в которой игроку нужно выбрать действие.
- Следи за логикой мира и инвентарём: герой не может использовать предметы, которых у него нет, и не может просто объявить себя победителем или получить предмет по своему желанию.
- Если игрок прислал результат броска кубика или монетки, честно учитывай его: низкие значения — провал или осложнение, высокие — успех; максимум на d20 — критический успех, единица — критический провал.
- Не выходи из роли и не упоминай, что ты ИИ или языковая модель.

СЛУЖЕБНЫЕ ТЕГИ
Когда в игровой механике что-то меняется, добавь в самый конец ответа теги, каждый на новой строке:
[[ITEM: Название | краткое описание]] — герой получил предмет
[[LOSE_ITEM: Название]] — герой потерял или израсходовал предмет (название точно как в инвентаре)
[[HP: -5]] или [[HP: +3]] — изменение здоровья героя
[[XP: 15]] — награда опытом за достижение (от 5 до 30)
Не упоминай теги в тексте и не объясняй их. Если ничего не изменилось — теги не нужны.

ГЕРОЙ
Имя: {name}
Пол: {gender}
Уровень: {level} (здоровье {hp}/{max_hp})
О герое: {about}
Инвентарь: {inventory}
"""

# char template, stats, info and inventory
def build_system_prompt(char: dict, inventory: list) -> str:
    inv = ", ".join(
        f"{i['name']} x{i['quantity']}" if i['quantity'] > 1 else i['name'] for i in inventory
    ) or "пусто"
    return SYSTEM_TEMPLATE.format(
        name=char["name"],
        gender="мужской" if char["gender"] == "m" else "женский",
        level=char["level"],
        hp=char["hp"],
        max_hp=char["max_hp"],
        about=char["about"] or "не указано",
        inventory=inv,
    )

# api calls to ollama
async def chat(system: str, history: list) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        # sending char template and history of chat
        "messages": [{"role": "system", "content": system}, *history],
        # stream the text the moment it is produced. 
        # I didnt find it possible to impelemnt in Telegram so I've disabled it
        "stream": False,
        # the higher the temp the more creative the answer (lol), by drfault is 0.8
        "options": {"temperature": 0.8},
    }
    # errors
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
    except httpx.ConnectError:
        raise OllamaError(f"Cannot connect to ({OLLAMA_URL})")
    except httpx.TimeoutException:
        raise OllamaError("Model took to long to send a response")
    except httpx.HTTPError as e:
        raise OllamaError(f"Connection error: {e}")

    # great success!
    if r.status_code != 200:
        raise OllamaError(f"Ollama came back with {r.status_code}: {r.text[:200]}")

    # what we got as a response
    content = (r.json().get("message") or {}).get("content", "")
    if not content.strip():
        raise OllamaError("Empty response :(")
    return content

# to find structs of [[]], items hp, exp
TAG_RE = re.compile(r"\[\[\s*([A-Za-z_]+)\s*:\s*(.*?)\s*\]\]", re.S)
# to find numbers
NUM_RE = re.compile(r"([+\-−]?)\s*(\d+)")

# helper to return a number
def _num(val: str):
    m = NUM_RE.search(val)
    if not m:
        return None
    #num_re returns a sign AND a number, groups of 2
    n = int(m.group(2))
    return -n if m.group(1) in ("-", "−") else n

# parse response by trimming all the unneded stuff to get clear text in return
def parse_response(text: str):
    effects = {"items": [], "lost": [], "hp": 0, "xp": 0}

    # parses the tags and fills the effects
    def handle(m):
        key, val = m.group(1).upper(), m.group(2).strip()
        if key == "ITEM":
            name, _, about = val.partition("|")
            name = name.strip()[:255]
            if name:
                effects["items"].append((name, about.strip()))
        elif key == "LOSE_ITEM":
            if val:
                effects["lost"].append(val[:255])
        elif key == "HP":
            n = _num(val)
            if n is not None:
                effects["hp"] += n
        elif key == "XP":
            n = _num(val)
            if n is not None:
                effects["xp"] += n
        return ""

    # "cleans" all of the tags from the response
    clean = TAG_RE.sub(handle, text)
    # to get rid of multiple \n left after a clean
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()

    # avoid killing the character if model goes postal
    effects["hp"] = max(-20, min(20, effects["hp"]))
    # avoid stripping the character of their xp
    effects["xp"] = max(0, min(50, effects["xp"]))
    # 3 items max
    effects["items"] = effects["items"][:3]
    
    return clean, effects