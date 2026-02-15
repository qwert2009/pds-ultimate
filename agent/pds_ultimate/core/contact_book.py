"""
PDS-Ultimate Contact Book — Умная адресная книга
====================================================
Привязка имён к контактам (telegram, phone, email).
«Напиши Милане привет» → resolve("Милана") → @milana_sagomonyan

Возможности:
- Fuzzy-поиск по имени (опечатки, падежи, уменьшительные)
- Автоматическое обновление контактных данных
- Быстрый resolve: имя → telegram/phone/email
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pds_ultimate.config import logger

CONTACT_BOOK_PATH = Path(
    "/home/slavik/lessons.py.itea.2026/101/agent/data/contact_book.json"
)

# Уменьшительные → полные имена (расширяемый)
NICKNAME_MAP: dict[str, list[str]] = {
    "саша": ["александр", "александра"],
    "миша": ["михаил"],
    "маша": ["мария"],
    "даша": ["дарья"],
    "лёша": ["алексей"],
    "алёша": ["алексей"],
    "вова": ["владимир"],
    "серёга": ["сергей"],
    "серёж": ["сергей"],
    "серый": ["сергей"],
    "кирюха": ["кирилл"],
    "кирюш": ["кирилл"],
    "русик": ["руслан"],
    "рус": ["руслан"],
    "дима": ["дмитрий"],
    "женя": ["евгений", "евгения"],
    "катя": ["екатерина"],
    "наташа": ["наталья", "наталия"],
    "оля": ["ольга"],
    "ира": ["ирина"],
    "таня": ["татьяна"],
    "юля": ["юлия"],
    "света": ["светлана"],
    "лена": ["елена"],
    "аня": ["анна"],
    "коля": ["николай"],
    "петя": ["пётр", "петр"],
    "ваня": ["иван"],
    "костя": ["константин"],
    "макс": ["максим"],
    "паша": ["павел"],
    "рома": ["роман"],
    "стас": ["станислав"],
    "толя": ["анатолий"],
    "витя": ["виктор"],
    "гена": ["геннадий"],
    "боря": ["борис"],
    "валера": ["валерий"],
    "андрюха": ["андрей"],
    "андрюш": ["андрей"],
}


class ContactBook:
    """
    Умная адресная книга с fuzzy-резолвом.

    Использование:
        contact_book.link("Милана", telegram="@milana_sagomonyan")
        info = contact_book.resolve("Милане")  # → {"telegram": "@milana_sagomonyan"}
    """

    def __init__(self):
        self._contacts: dict[str, dict[str, Any]] = {}
        self._session_factory = None
        self._load()

    def set_session_factory(self, session_factory) -> None:
        self._session_factory = session_factory

    def link(
        self,
        name: str,
        telegram: str = "",
        phone: str = "",
        email: str = "",
        telegram_id: int = 0,
        whatsapp: str = "",
        notes: str = "",
        db_session=None,
    ) -> dict[str, Any]:
        """
        Привязать контактные данные к имени.

        contact_book.link("Милана", telegram="@milana_sagomonyan")
        contact_book.link("Кирилл", phone="+79001234567", email="kirill@mail.ru")
        """
        key = self._normalize(name)
        if not key:
            return {"error": "Пустое имя"}

        existing = self._contacts.get(key, {
            "name": name,
            "aliases": [],
        })

        # Обновляем оригинальное написание имени
        existing["name"] = name

        # Обновляем данные (не перезаписываем пустым)
        if telegram:
            existing["telegram"] = telegram.lstrip("@")
        if phone:
            existing["phone"] = phone
        if email:
            existing["email"] = email
        if telegram_id:
            existing["telegram_id"] = telegram_id
        if whatsapp:
            existing["whatsapp"] = whatsapp
        if notes:
            old_notes = existing.get("notes", "")
            existing["notes"] = f"{old_notes}\n{notes}".strip(
            ) if old_notes else notes

        self._contacts[key] = existing
        self._save()

        # Sync to DB if possible
        if db_session or self._session_factory:
            self._sync_to_db(key, existing, db_session)

        return existing

    def resolve(
        self,
        query: str,
        db_session=None,
    ) -> dict[str, Any] | None:
        """
        Найти контакт по имени/нику/падежу.

        resolve("Милане") → {"name": "Милана", "telegram": "milana_sagomonyan"}
        resolve("Серёга") → {"name": "Сергей", "telegram": "..."}
        """
        if not query:
            return None

        norm = self._normalize(query)

        # 1. Точное совпадение по ключу
        if norm in self._contacts:
            return self._contacts[norm]

        # 2. Поиск по падежам (убираем окончания)
        stem = self._stem(norm)
        for key, contact in self._contacts.items():
            if self._stem(key) == stem:
                return contact

        # 3. Поиск по алиасам
        for key, contact in self._contacts.items():
            aliases = contact.get("aliases", [])
            for alias in aliases:
                if self._normalize(alias) == norm or self._stem(self._normalize(alias)) == stem:
                    return contact

        # 4. Поиск по никнеймам
        nickname_matches = NICKNAME_MAP.get(norm, [])
        for full_name in nickname_matches:
            full_norm = self._normalize(full_name)
            if full_norm in self._contacts:
                return self._contacts[full_norm]
            # Stem match
            full_stem = self._stem(full_norm)
            for key, contact in self._contacts.items():
                if self._stem(key) == full_stem:
                    return contact

        # 5. Substring match
        for key, contact in self._contacts.items():
            if norm in key or key in norm:
                return contact
            name_norm = self._normalize(contact.get("name", ""))
            if norm in name_norm or name_norm in norm:
                return contact

        # 6. Поиск по telegram username
        query_clean = query.lstrip("@").lower()
        for key, contact in self._contacts.items():
            tg = contact.get("telegram", "").lower()
            if tg and (tg == query_clean or query_clean in tg):
                return contact

        # 7. Поиск в БД
        if db_session or self._session_factory:
            db_result = self._search_db(query, db_session)
            if db_result:
                return db_result

        return None

    def resolve_telegram(self, query: str, db_session=None) -> str:
        """Resolve name → telegram username. Returns '@username' or ''."""
        contact = self.resolve(query, db_session)
        if not contact:
            return ""
        tg = contact.get("telegram", "")
        return f"@{tg}" if tg and not tg.startswith("@") else tg

    def resolve_telegram_id(self, query: str, db_session=None) -> int:
        """Resolve name → telegram chat_id. Returns 0 if not found."""
        contact = self.resolve(query, db_session)
        if not contact:
            return 0
        return contact.get("telegram_id", 0)

    def resolve_phone(self, query: str, db_session=None) -> str:
        """Resolve name → phone number."""
        contact = self.resolve(query, db_session)
        if not contact:
            return ""
        return contact.get("phone", "")

    def resolve_email(self, query: str, db_session=None) -> str:
        """Resolve name → email."""
        contact = self.resolve(query, db_session)
        if not contact:
            return ""
        return contact.get("email", "")

    def add_alias(self, name: str, alias: str) -> bool:
        """Add an alias for a contact."""
        norm = self._normalize(name)
        if norm not in self._contacts:
            # Try fuzzy
            contact = self.resolve(name)
            if contact:
                norm = self._normalize(contact.get("name", ""))
            else:
                return False

        if norm in self._contacts:
            aliases = self._contacts[norm].get("aliases", [])
            if alias not in aliases:
                aliases.append(alias)
                self._contacts[norm]["aliases"] = aliases
                self._save()
            return True
        return False

    def list_all(self) -> list[dict[str, Any]]:
        """List all contacts."""
        return list(self._contacts.values())

    def get_stats(self) -> dict[str, Any]:
        total = len(self._contacts)
        with_tg = sum(1 for c in self._contacts.values() if c.get("telegram"))
        with_phone = sum(1 for c in self._contacts.values() if c.get("phone"))
        with_email = sum(1 for c in self._contacts.values() if c.get("email"))
        return {
            "total": total,
            "with_telegram": with_tg,
            "with_phone": with_phone,
            "with_email": with_email,
        }

    # ─── Internal ────────────────────────────────────────────────────────

    def _normalize(self, text: str) -> str:
        """Normalize name: lowercase, strip, remove extra spaces."""
        return re.sub(r"\s+", " ", text.strip().lower())

    def _stem(self, word: str) -> str:
        """
        Primitive Russian stemming — strip common endings.
        "милане" → "милан", "сергея" → "серге"
        """
        word = word.strip()
        # Common Russian case endings (sorted by length, longest first)
        endings = [
            "ому", "ему", "ами", "ями", "ами",
            "ой", "ей", "ий", "ый", "ая", "яя", "ое", "ее",
            "ам", "ям", "ов", "ев", "ий",
            "ом", "ем", "им",
            "ах", "ях",
            "у", "ю", "а", "я", "е", "и", "о", "ы",
        ]
        if len(word) > 3:
            for ending in endings:
                if word.endswith(ending) and len(word) - len(ending) >= 2:
                    return word[:-len(ending)]
        return word

    def _sync_to_db(self, key: str, data: dict, db_session=None) -> None:
        """Sync contact to database."""
        try:
            from pds_ultimate.core.database import Contact, ContactType

            session = db_session
            should_close = False
            if not session and self._session_factory:
                session = self._session_factory()
                should_close = True

            if not session:
                return

            name = data.get("name", key)
            contact = session.query(Contact).filter(
                Contact.name.ilike(f"%{name}%")
            ).first()

            if not contact:
                contact = Contact(name=name, contact_type=ContactType.OTHER)
                session.add(contact)

            if data.get("telegram"):
                contact.telegram_username = data["telegram"]
            if data.get("telegram_id"):
                contact.telegram_id = data["telegram_id"]
            if data.get("phone"):
                contact.phone = data["phone"]
            if data.get("email"):
                contact.email = data["email"]
            if data.get("whatsapp"):
                contact.whatsapp_id = data["whatsapp"]

            session.commit()

            if should_close:
                session.close()
        except Exception as e:
            logger.debug(f"ContactBook DB sync error: {e}")

    def _search_db(self, query: str, db_session=None) -> dict[str, Any] | None:
        """Search contact in database."""
        try:
            from pds_ultimate.core.database import Contact

            session = db_session
            should_close = False
            if not session and self._session_factory:
                session = self._session_factory()
                should_close = True

            if not session:
                return None

            contact = session.query(Contact).filter(
                Contact.name.ilike(f"%{query}%")
            ).first()

            if contact:
                result = {
                    "name": contact.name,
                    "db_id": contact.id,
                }
                if contact.telegram_username:
                    result["telegram"] = contact.telegram_username
                if contact.telegram_id:
                    result["telegram_id"] = contact.telegram_id
                if contact.phone:
                    result["phone"] = contact.phone
                if contact.email:
                    result["email"] = contact.email
                if contact.whatsapp_id:
                    result["whatsapp"] = contact.whatsapp_id

                # Cache locally
                key = self._normalize(contact.name)
                self._contacts[key] = result
                self._save()

                if should_close:
                    session.close()
                return result

            if should_close:
                session.close()
        except Exception as e:
            logger.debug(f"ContactBook DB search error: {e}")

        return None

    def _save(self) -> None:
        try:
            CONTACT_BOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONTACT_BOOK_PATH.write_text(
                json.dumps(self._contacts, ensure_ascii=False, indent=2)
            )
        except Exception as e:
            logger.debug(f"ContactBook save error: {e}")

    def _load(self) -> None:
        try:
            if CONTACT_BOOK_PATH.exists():
                self._contacts = json.loads(
                    CONTACT_BOOK_PATH.read_text(encoding="utf-8")
                )
                logger.info(
                    f"ContactBook: loaded {len(self._contacts)} contacts"
                )
        except Exception as e:
            logger.debug(f"ContactBook load error: {e}")


contact_book = ContactBook()
