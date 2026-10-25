import random
import re
from sqlalchemy import func
from initiate_db import Session, Users, Item, InventoryItem, StoryMessage

# global
BASE_HP = 20
HP_PER_LEVEL = 5

def max_hp_for(level: int) -> int:
    return BASE_HP + (level - 1) * HP_PER_LEVEL

def xp_for_next(level: int) -> int:
    return level * 100

# replacing all spec symbols to stop them from being used as LIKE in query
def _esc(s: str) -> str:
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

# dictionary of user data
def _char_dict(u: Users) -> dict:
    return {
        "id": u.id,
        "tg_id": u.tg_id,
        "username": u.username,
        "name": u.name or u.username,
        "gender": u.gender,
        "level": u.level,
        "xp": u.xp,
        "xp_next": xp_for_next(u.level),
        "hp": u.hp,
        "max_hp": max_hp_for(u.level),
        "about": u.about or "",
    }

# fetch character
def get_char_info(tg_id: int):
    with Session() as s:
        u = s.query(Users).filter_by(tg_id=tg_id).first()

        return _char_dict(u) if u else None

# register new user
def register_user(tg_id: int, tg_username, name: str, gender: str) -> dict:
    with Session() as s:
        u = Users(
            tg_id=tg_id,
            username=tg_username or f"user_{tg_id}",
            name=name[:255],
            gender=gender,
            about="",
            level=1,
            xp=0,
            hp=max_hp_for(1),
            last_visit=func.now(),
        )

        s.add(u)
        s.commit()

        return _char_dict(u)

# user login/edit
def touch_user(tg_id: int):
    with Session() as s:
        s.query(Users).filter_by(tg_id=tg_id).update({"last_visit": func.now()})
        s.commit()

# profile update name and about FOR NOW
def update_profile(tg_id: int, name=None, about=None) -> bool:
    with Session() as s:
        u = s.query(Users).filter_by(tg_id=tg_id).first()
        if not u:
            return False
        if name is not None:
            u.name = name[:255]
        if about is not None:
            u.about = about
        s.commit()

        return True

# fetch inventory
# user primary key
def get_inventory(user_pk: int) -> list:
    with Session() as s:
        rows = (s.query(Item.name, Item.about, InventoryItem.quantity)
                .join(InventoryItem, InventoryItem.item_id == Item.id)
                .filter(InventoryItem.user_id == user_pk)
                .order_by(Item.name)
                .all())
        
        return [{"name": r[0], "about": r[1] or "", "quantity": r[2]} for r in rows] # return list of all items

# find item in inv
def find_item(user_pk: int, name: str):
    with Session() as s:
        base = (s.query(Item, InventoryItem.quantity)
                .join(InventoryItem, InventoryItem.item_id == Item.id)
                .filter(InventoryItem.user_id == user_pk))
        # like can return poor result if used with % or _, made a heloer function to avoid that
        # also checks for 1 to 1 name, then with spec symbols
        row = (base.filter(Item.name.ilike(_esc(name), escape='\\')).first()
               or base.filter(Item.name.ilike(f"%{_esc(name)}%", escape='\\')).first())
        if not row:
            return None
        item, qty = row

        return {"name": item.name, "about": item.about or "", "quantity": qty}

# adds a story for context
def add_story(user_pk: int, role: str, content: str):
    with Session() as s:
        s.add(StoryMessage(user_id=user_pk, role=role, content=content))
        s.commit()

# fetches a story from context
def get_story(user_pk: int, limit: int) -> list:
    with Session() as s:
        rows = (s.query(StoryMessage)
                .filter_by(user_id=user_pk)
                .order_by(StoryMessage.id.desc()) # id is int + auto increment, should always pull the latest stories
                .limit(limit)
                .all())
        
        return [{"role": r.role, "content": r.content} for r in reversed(rows)]

# amoutn of stories a player has
def count_story(user_pk: int) -> int:
    with Session() as s:
        return s.query(func.count(StoryMessage.id)).filter_by(user_id=user_pk).scalar() or 0 # scalar to return number (ahuet')

# deletes latest story
def delete_last_story(user_pk: int):
    with Session() as s:
        last = (s.query(StoryMessage).filter_by(user_id=user_pk)
                .order_by(StoryMessage.id.desc()).first())
        if last:
            s.delete(last)
            s.commit()

# reset everything !!!!!!!!
def reset_adventure(user_pk: int):
    with Session() as s:
        s.query(StoryMessage).filter_by(user_id=user_pk).delete()
        s.query(InventoryItem).filter_by(user_id=user_pk).delete()
        u = s.get(Users, user_pk)
        u.level, u.xp, u.hp = 1, 0, max_hp_for(1)
        s.commit()

# dungeon master rules and actions
def apply_effects(user_pk: int, effects: dict) -> list:
    # notes are for what transpired during call to this.func
    notes = []
    with Session() as s:
        u = s.get(Users, user_pk)

        for name, about in effects.get("items", []):
            item = s.query(Item).filter(Item.name.ilike(_esc(name), escape='\\')).first()
            if not item:
                item = Item(name=name, about=about or None)
                s.add(item)
                s.flush()
            elif about and not item.about:
                item.about = about
            inv = s.query(InventoryItem).filter_by(user_id=u.id, item_id=item.id).first()
            if inv:
                inv.quantity += 1
            else:
                s.add(InventoryItem(user_id=u.id, item_id=item.id, quantity=1))
            notes.append(f"Получено: {item.name}")

        for name in effects.get("lost", []):
            inv = (s.query(InventoryItem)
                   .join(Item, Item.id == InventoryItem.item_id)
                   .filter(InventoryItem.user_id == u.id, Item.name.ilike(_esc(name), escape='\\'))
                   .first())
            if inv:
                if inv.quantity > 1:
                    inv.quantity -= 1
                else:
                    s.delete(inv)
                notes.append(f"Потеряно: {name}")

        xp = effects.get("xp", 0)
        if xp > 0:
            u.xp += xp
            notes.append(f"Опыт: +{xp}")
            while u.xp >= xp_for_next(u.level):
                u.xp -= xp_for_next(u.level)
                u.level += 1
                u.hp = max_hp_for(u.level)
                notes.append(f"Новый уровень: {u.level}. Здоровье восстановлено.")

        hp = effects.get("hp", 0)
        if hp:
            top = max_hp_for(u.level)
            u.hp = max(0, min(top, u.hp + hp))
            notes.append("Здоровье: {hp:+d} ({u.hp}/{top})")

        if u.hp <= 0:
            notes.append("Ваш герой вмер. Начать заново: /newgame")

        s.commit()
    return notes

# re compile into a pattern
# dice < 99, sides < 9999  
DICE_RE = re.compile(r"^(\d{0,2})[dD](\d{1,4})$")
# coin keywords 
COIN_WORDS = {"coin", "flip", "монета", "монетка", "монетку", "монеты", "орел", "орёл"}

# parse roll that the storyteller made
def parse_roll(args: list) -> dict:
    # if no args were given we just default to a d20
    first = args[0].lower() if args else "d20"
    rest = list(args[1:])

    if first in COIN_WORDS:
        # random choice, either heads ir tails
        return {"kind": "coin", "label": "Монетка", "text": random.choice(["Орёл", "Решка"]),
                "rest": " ".join(rest)}

    # matching input die with the pattern
    m = DICE_RE.match(first)
    # if matches - parsing into count of dice and count of sides
    # else assume a d20
    if m:
        count, sides = int(m.group(1) or 1), int(m.group(2))
    else:
        count, sides, rest = 1, 20, list(args)

    if not (1 <= count <= 20 and 2 <= sides <= 1000):
        raise ValueError("Wrong args for die")

    # rolls work here
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls)
    
    return {
        "kind": "dice",
        "label": f"{count}d{sides}" if count > 1 else f"d{sides}",
        "text": f"{' + '.join(map(str, rolls))} = {total}" if count > 1 else str(total),
        "count": count, "sides": sides, "total": total,
        "rest": " ".join(rest),
    }