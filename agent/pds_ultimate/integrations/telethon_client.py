"""
PDS-Ultimate Telethon Integration
=======================================
Userbot через Telethon для анализа стиля.

По ТЗ:
- 7 чатов Telegram для анализа стиля
- Чтение истории сообщений
- Анализ стиля переписки владельца
- Сбор данных для StyleAnalyzer
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from pds_ultimate.config import config, logger


class TelethonClient:
    """
    Userbot для анализа стиля переписки.

    Жизненный цикл:
        client = TelethonClient()
        await client.start()          # Авторизация (телефон + код)
        msgs = await client.get_messages("username", 100)
        await client.scan_for_style()
        await client.stop()
    """

    def __init__(self):
        self._client = None
        self._started = False

    async def start(self) -> None:
        """Запуск Telethon клиента."""
        if self._started:
            return

        if not config.telethon.api_id or not config.telethon.api_hash:
            logger.warning(
                "Telethon: api_id/api_hash не заданы — клиент не запущен"
            )
            return

        try:
            import python_socks
            from telethon import TelegramClient

            # Прокси для обхода блокировок
            # Telethon использует MTProto (TCP) — нужен SOCKS5, НЕ HTTP
            # HTTP прокси (порт 10809) не работает для MTProto
            # SOCKS5 обычно на порту 10808 (V2Ray/Clash стандарт)
            proxy = None
            if config.telegram.proxy:
                from urllib.parse import urlparse
                parsed = urlparse(config.telegram.proxy)
                host = parsed.hostname or "127.0.0.1"
                # Переключаемся на SOCKS5 порт (10808 для V2Ray)
                socks_port = (parsed.port or 10809) - 1  # 10809 → 10808
                proxy = (
                    python_socks.ProxyType.SOCKS5,
                    host,
                    socks_port,
                )
                logger.info(f"Telethon SOCKS5 proxy: {host}:{socks_port}")

            self._client = TelegramClient(
                config.telethon.session_name,
                config.telethon.api_id,
                config.telethon.api_hash,
                proxy=proxy,
            )

            # Сначала пробуем connect — если сессия есть, код не нужен
            await self._client.connect()

            if await self._client.is_user_authorized():
                me = await self._client.get_me()
                self._started = True
                logger.info(
                    f"Telethon подключён (сессия): "
                    f"{me.first_name} {me.last_name or ''} "
                    f"(@{me.username or 'N/A'})"
                )
            else:
                # Сессия не авторизована — нужен код
                # start() с phone отправит код и запросит ввод
                phone = config.telethon.phone or None
                if phone:
                    await self._client.start(phone=phone)
                    me = await self._client.get_me()
                    self._started = True
                    logger.info(
                        f"Telethon авторизован: "
                        f"{me.first_name} {me.last_name or ''} "
                        f"(@{me.username or 'N/A'})"
                    )
                else:
                    logger.warning(
                        "Telethon: сессия не авторизована и TG_PHONE не задан"
                    )

        except Exception as e:
            logger.error(f"Ошибка запуска Telethon: {e}", exc_info=True)

    async def stop(self) -> None:
        """Остановка клиента."""
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._started = False
        logger.info("Telethon отключён")

    # ═══════════════════════════════════════════════════════════════════════
    # Чтение сообщений
    # ═══════════════════════════════════════════════════════════════════════

    async def get_messages(
        self,
        chat_identifier: str,
        limit: int = 100,
        offset_days: int = 30,
    ) -> list[dict]:
        """
        Получить последние сообщения из чата.

        Args:
            chat_identifier: username, phone, или ID чата
            limit: Максимальное количество сообщений
            offset_days: За сколько дней брать (фильтр после получения)

        Returns:
            [{"text", "date", "from_id", "is_owner", "reply_to"}, ...]
        """
        if not self._started:
            logger.warning("Telethon не запущен — get_messages пропускается")
            return []

        try:
            # Resolve entity — try multiple methods
            entity = await self._resolve_entity(chat_identifier)
            if not entity:
                logger.warning(f"Не удалось найти чат: {chat_identifier}")
                return []

            me = await self._client.get_me()

            # Get latest messages WITHOUT offset_date
            # (offset_date in Telethon = messages OLDER than date, not newer)
            messages = await self._client.get_messages(
                entity,
                limit=limit,
            )

            # Filter by date range manually
            cutoff = datetime.utcnow() - timedelta(days=offset_days)
            cutoff = cutoff.replace(
                tzinfo=messages[0].date.tzinfo) if messages and messages[0].date else cutoff

            result = []
            for msg in messages:
                # Skip non-text
                if not msg.text:
                    continue

                # Filter by date
                if msg.date and msg.date.replace(tzinfo=None) < cutoff.replace(tzinfo=None):
                    continue

                sender_name = ""
                try:
                    if msg.sender:
                        sender_name = getattr(
                            msg.sender, "first_name", "") or ""
                        last = getattr(msg.sender, "last_name", "") or ""
                        if last:
                            sender_name = f"{sender_name} {last}"
                except Exception:
                    pass

                result.append({
                    "text": msg.text,
                    "date": msg.date.isoformat() if msg.date else "",
                    "from_id": msg.sender_id,
                    "from_name": sender_name,
                    "is_owner": msg.sender_id == me.id,
                    "reply_to": msg.reply_to_msg_id,
                    "chat": str(chat_identifier),
                })

            logger.info(
                f"Telethon: получено {len(result)} сообщений "
                f"из {chat_identifier} (всего загружено {len(messages)})"
            )
            return result

        except Exception as e:
            logger.error(
                f"Ошибка чтения чата {chat_identifier}: {e}",
                exc_info=True,
            )
            return []

    async def _resolve_entity(self, identifier: str):
        """
        Умный поиск entity — пробует несколько методов.
        username, phone, id, поиск по имени в диалогах.
        """
        if not identifier:
            return None

        # 1. Try direct resolve (username, phone, numeric id)
        for variant in [identifier, f"@{identifier}" if not identifier.startswith("@") else identifier]:
            try:
                return await self._client.get_entity(variant)
            except Exception:
                continue

        # 2. Try numeric ID
        try:
            num_id = int(identifier)
            return await self._client.get_entity(num_id)
        except (ValueError, Exception):
            pass

        # 3. Search in dialogs by name (fuzzy)
        try:
            search_lower = identifier.lower().replace("@", "")
            async for dialog in self._client.iter_dialogs(limit=200):
                name = (dialog.name or "").lower()
                if search_lower in name or name in search_lower:
                    logger.info(
                        f"Telethon: найден диалог '{dialog.name}' для '{identifier}'")
                    return dialog.entity
        except Exception as e:
            logger.warning(f"Telethon dialog search error: {e}")

        return None

    async def get_my_messages(
        self,
        chat_identifier: str,
        limit: int = 100,
    ) -> list[str]:
        """
        Получить только МОИ сообщения из чата.
        Для анализа стиля нужны только сообщения владельца.
        """
        all_msgs = await self.get_messages(chat_identifier, limit)
        return [m["text"] for m in all_msgs if m["is_owner"]]

    # ═══════════════════════════════════════════════════════════════════════
    # Сканирование для анализа стиля
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_for_style(
        self,
        chats: Optional[list[str]] = None,
    ) -> dict[str, list[str]]:
        """
        Сканировать чаты для анализа стиля переписки.

        По ТЗ: 7 чатов Telegram, config.telethon.style_analysis_chat_count

        Args:
            chats: Список чатов (username/phone/id).
                   Если None — берём из конфига.

        Returns:
            {"chat_identifier": ["msg1", "msg2", ...], ...}
        """
        if not self._started:
            logger.warning("Telethon не запущен — scan_for_style пропускается")
            return {}

        if chats is None:
            chats = config.telethon.style_chats

        if not chats:
            logger.warning("Telethon: нет чатов для анализа стиля")
            return {}

        # Ограничиваем количество чатов
        max_chats = config.telethon.style_analysis_chat_count
        chats_to_scan = chats[:max_chats]
        msgs_per_chat = config.telethon.messages_per_chat

        result: dict[str, list[str]] = {}

        for chat_id in chats_to_scan:
            try:
                my_msgs = await self.get_my_messages(chat_id, msgs_per_chat)
                if my_msgs:
                    result[str(chat_id)] = my_msgs
                    logger.info(
                        f"  ✓ {chat_id}: {len(my_msgs)} сообщений владельца"
                    )
                else:
                    logger.info(f"  ✗ {chat_id}: нет сообщений владельца")

                # Пауза между чатами (анти-флуд)
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"Ошибка сканирования {chat_id}: {e}")

        total = sum(len(v) for v in result.values())
        logger.info(
            f"Telethon: стиль-сканирование завершено — "
            f"{len(result)} чатов, {total} сообщений"
        )

        return result

    async def get_dialogs(self, limit: int = 30) -> list[dict]:
        """
        Список диалогов (для выбора чатов при настройке).

        Returns:
            [{"id", "name", "type", "unread_count"}, ...]
        """
        if not self._started:
            return []

        try:
            dialogs = await self._client.get_dialogs(limit=limit)
            result = []

            for d in dialogs:
                dtype = "unknown"
                if d.is_user:
                    dtype = "user"
                elif d.is_group:
                    dtype = "group"
                elif d.is_channel:
                    dtype = "channel"

                result.append({
                    "id": d.entity.id,
                    "name": d.name or "(Без имени)",
                    "type": dtype,
                    "unread_count": d.unread_count,
                    "username": getattr(d.entity, "username", None),
                })

            return result

        except Exception as e:
            logger.error(f"Ошибка получения диалогов: {e}")
            return []


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

telethon_client = TelethonClient()
