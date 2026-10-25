# telegram-bot-dnd-like
DND-like telegram bot with a hook to local OLLAMA model

0. Make a Telegram bot with Botfather
1. py -m pip install -r requirements.txt 
2. Create a .env file with
```
TELEGRAM_TOKEN=<>
DATABASE_LINK=sqlite:///./storygen_ollama_bot/dnd.db
ROOT_PASS=<>

OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=<>
OLLAMA_TIMEOUT=300
HISTORY_LIMIT=30
```
3. From main directory: py ./storygen_ollama_bot/main.py
4. should work!