"""
Одноразовая авторизация Telethon.
Запустите: python telethon_auth.py
Введите номер телефона и код из Telegram.
После успешной авторизации файл сессии сохранится и бот сможет
управлять Telegram от вашего имени.
"""
import asyncio
import os
import sys

# Загружаем .env
from pathlib import Path

env_path = Path(__file__).parent / "pds_ultimate" / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION = os.environ.get("TG_SESSION_NAME", "pds_userbot")
PROXY = os.environ.get("TG_PROXY", "")

if not API_ID or not API_HASH:
    print("❌ TG_API_ID и TG_API_HASH не заданы в .env")
    sys.exit(1)

print(f"API ID: {API_ID}")
print(f"Session: {SESSION}")
if PROXY:
    print(f"Proxy: {PROXY}")
print()


async def main():
    from telethon import TelegramClient

    # Прокси для Telethon
    proxy = None
    if PROXY:
        from urllib.parse import urlparse
        p = urlparse(PROXY)
        import socks
        proxy = (socks.HTTP, p.hostname, p.port)

    client = TelegramClient(SESSION, API_ID, API_HASH, proxy=proxy)

    print("🔐 Авторизация Telethon...")
    print("Введите номер телефона (например +99365845508):")

    await client.start()

    me = await client.get_me()
    print("\n✅ Авторизация успешна!")
    print(f"👤 {me.first_name} {me.last_name or ''} (@{me.username or 'N/A'})")
    print(f"📱 ID: {me.id}")
    print(f"💾 Сессия сохранена: {SESSION}.session")
    print("\nТеперь бот может управлять вашим Telegram!")

    await client.disconnect()


asyncio.run(main())
