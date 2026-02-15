"""
PDS-Ultimate Universal Handler
=================================
Единственный хэндлер текстовых сообщений.
Никаких кнопок, никаких шаблонов — только /start и свободный чат.

Архитектура v2.0 — Agent-Driven:
1. Пользователь пишет ЛЮБОЙ текст
2. Smart Router определяет: нужны ли инструменты?
3. Если да → ReAct Agent (Think → Act → Observe → Reflect)
4. Если нет → прямой ответ LLM
5. Stateful flow (ввод заказа, подтверждение) → как раньше
6. Background Memory Extraction → фоновое запоминание фактов

Вдохновлено: Manus AI, ReAct, MemGPT, Phidata.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.orm import Session

from pds_ultimate.bot.conversation import (
    ConversationContext,
    ConversationState,
    conversation_manager,
)
from pds_ultimate.config import config, logger
from pds_ultimate.core.agent import agent
from pds_ultimate.core.database import (
    AgentThought,
    ArchivedOrderItem,
    Contact,
    ContactType,
    ConversationHistory,
    ItemStatus,
    Order,
    OrderItem,
    OrderStatus,
    Transaction,
    TransactionType,
)
from pds_ultimate.core.llm_engine import llm_engine
from pds_ultimate.core.persona_engine import persona_engine
from pds_ultimate.core.user_manager import user_manager

router = Router(name="universal")


# ═══════════════════════════════════════════════════════════════════════════════
# /start — Единственная команда
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, db_session: Session) -> None:
    """
    /start — Точка входа. Multi-user регистрация.

    Логика:
    1. Если пользователь уже зарегистрирован → приветствие по имени
    2. Если нет → просим ввести имя для регистрации
    """
    chat_id = message.chat.id
    ctx = conversation_manager.get(chat_id)

    # Проверяем: уже зарегистрирован?
    profile = user_manager.get_profile(chat_id, db_session)

    if profile:
        # Зарегистрированный пользователь — приветствие
        ctx.reset()

        name = profile["name"].split()[0].capitalize(
        ) if profile.get("name") else "друг"
        is_owner = profile["role"] == "owner"

        greeting = (
            f"Салам, {name}! 👋\n"
            f"Я — PDS-Ultimate, твой персональный ассистент.\n\n"
        )

        if is_owner:
            greeting += (
                "Все твои API подключены и готовы к работе. 🔧\n\n"
                "Я умею:\n"
                "• Вести заказы и логистику\n"
                "• Считать финансы и прибыль\n"
                "• Работать с файлами (Excel, Word, PDF)\n"
                "• Переводить тексты\n"
                "• Отвечать на любые вопросы\n"
                "• И вообще всё что скажешь\n\n"
                "Давай начинать! 💪"
            )
        else:
            # Обычный пользователь — показываем подключённые API
            apis_msg = user_manager.get_connected_apis_message(
                chat_id, db_session)
            greeting += (
                "Просто пиши мне что нужно — я пойму.\n\n"
                f"{apis_msg}\n\n"
                "💡 Чтобы подключить новый API, просто отправь мне API-ключ "
                "или напиши «подключить API»."
            )

        await message.answer(greeting)
        _save_to_db(db_session, chat_id, "assistant", greeting)
    else:
        # Новый пользователь — просим имя
        ctx.set_state(ConversationState.AWAITING_NAME)

        welcome = (
            "👋 Привет! Я — PDS-Ultimate, AI-ассистент.\n\n"
            "Для начала, представься — как тебя зовут?\n"
            "Напиши своё имя и фамилию."
        )

        await message.answer(welcome)
        _save_to_db(db_session, chat_id, "assistant", welcome)


# ═══════════════════════════════════════════════════════════════════════════════
# Обработка ЛЮБОГО текстового сообщения
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(F.text)
async def handle_text(message: Message, db_session: Session) -> None:
    """
    Обработка любого текстового сообщения.
    Маршрутизация через LLM (определение намерения).
    """
    text = message.text.strip()
    if not text:
        return

    chat_id = message.chat.id
    ctx = conversation_manager.get(chat_id)

    # Сохраняем сообщение пользователя
    ctx.add_user_message(text)
    _save_to_db(db_session, chat_id, "user", text)

    # Persona learning per user
    try:
        profile = user_manager.get_profile(chat_id, db_session)
        display_name = profile.get("name") if profile else ""
        if not display_name:
            display_name = getattr(message.from_user, "full_name", "") or ""
        persona_engine.learn_from_message(
            chat_id=chat_id,
            text=text,
            is_owner=chat_id == config.telegram.owner_id,
            display_name=display_name,
        )
    except Exception as e:
        logger.debug(f"Persona learn error: {e}")

    # Показываем "печатает..."
    await message.bot.send_chat_action(chat_id, "typing")

    try:
        # ─── Проверка: ожидаем ли конкретный ответ? ──────────────────
        if ctx.state != ConversationState.FREE:
            response = await _handle_stateful(ctx, text, db_session)
        else:
            response = await _handle_free(ctx, text, db_session)

        # Отправляем ответ
        if response:
            # Safety net: если LLM вернул сырой JSON — извлекаем ответ
            response = _extract_answer_from_json(response)

            # Telegram ограничение: 4096 символов
            for chunk in _split_message(response):
                await message.answer(chunk)

            ctx.add_assistant_message(response)
            _save_to_db(db_session, chat_id, "assistant", response)

        # Отправляем файлы, если агент создал их
        pending_files = getattr(ctx, '_pending_files', [])
        if pending_files:
            from aiogram.types import FSInputFile
            for file_info in pending_files:
                filepath = file_info.get("filepath", "")
                filename = file_info.get("filename", "")
                if filepath and os.path.exists(filepath):
                    try:
                        doc = FSInputFile(filepath, filename=filename)
                        await message.answer_document(doc, caption=f"📎 {filename}")
                    except Exception as fe:
                        logger.error(f"Ошибка отправки файла: {fe}")
                        await message.answer(f"❌ Не удалось отправить файл: {filename}")
            ctx._pending_files = []

    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)
        error_msg = "Произошла ошибка при обработке. Попробуй ещё раз."
        await message.answer(error_msg)
        ctx.add_assistant_message(error_msg)


# ═══════════════════════════════════════════════════════════════════════════════
# Обработка состояний (когда агент ожидает конкретный ответ)
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_stateful(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Обработка сообщений, когда агент в определённом состоянии."""

    state = ctx.state

    # ─── Ожидание имени (регистрация) ────────────────────────────────
    if state == ConversationState.AWAITING_NAME:
        return await _state_awaiting_name(ctx, text, db_session)

    # ─── Настройка API (onboarding) ──────────────────────────────────
    if state == ConversationState.AWAITING_API_SETUP:
        return await _state_awaiting_api_setup(ctx, text, db_session)

    # ─── Ввод позиций заказа ─────────────────────────────────────────
    if state == ConversationState.ORDER_INPUT:
        return await _state_order_input(ctx, text, db_session)

    # ─── Подтверждение заказа ────────────────────────────────────────
    if state == ConversationState.ORDER_CONFIRM:
        return await _state_order_confirm(ctx, text, db_session)

    # ─── Сколько заплатили МНЕ ───────────────────────────────────────
    if state == ConversationState.AWAITING_INCOME:
        return await _state_awaiting_income(ctx, text, db_session)

    # ─── Сколько Я заплатил поставщику ───────────────────────────────
    if state == ConversationState.AWAITING_EXPENSE:
        return await _state_awaiting_expense(ctx, text, db_session)

    # ─── Ожидание трек-номера ────────────────────────────────────────
    if state == ConversationState.AWAITING_TRACK:
        return await _state_awaiting_track(ctx, text, db_session)

    # ─── Ожидание статуса позиции ────────────────────────────────────
    if state == ConversationState.AWAITING_STATUS:
        return await _state_awaiting_status(ctx, text, db_session)

    # ─── Ожидание типа ввода доставки ────────────────────────────────
    if state == ConversationState.AWAITING_DELIVERY_TYPE:
        return await _state_delivery_type(ctx, text, db_session)

    # ─── Ожидание стоимости доставки ─────────────────────────────────
    if state == ConversationState.AWAITING_DELIVERY:
        return await _state_delivery_cost(ctx, text, db_session)

    # ─── Неизвестное состояние — сбрасываем ──────────────────────────
    ctx.clear_temp()
    return await _handle_free(ctx, text, db_session)


# ═══════════════════════════════════════════════════════════════════════════════
# Свободный режим — LLM определяет что делать
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_free(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """
    Свободный режим — AI Agent определяет что делать.

    v2.0: ReAct Agent с инструментами, памятью и рефлексией.
    Простые запросы → прямой ответ LLM (быстрее).
    Сложные задачи → ReAct loop с tool calling.
    """

    # ─── Проверка кодового слова безопасности ────────────────────────
    # (отключено по запросу пользователя)

    # ─── Проверка: пользователь отправил API-ключ? ───────────────────
    if _looks_like_api_key(text):
        result = await user_manager.detect_and_save_api(
            ctx.chat_id, text, db_session)
        if result:
            is_valid, valid_msg = await user_manager.validate_api(
                ctx.chat_id, result["api_type"], db_session
            )
            status = f"✅ {valid_msg}" if is_valid else f"⚠️ {valid_msg}"
            return (
                f"🔑 Обнаружен API-ключ!\n\n"
                f"API: <b>{result.get('api_name', result['api_type'])}</b>\n"
                f"Ключ: {result.get('masked_value', '***')}\n"
                f"Статус: {status}\n\n"
                f"API подключён и готов к использованию."
            )

    # ─── Запрос на подключение API (текстовая команда) ────────────────
    api_trigger_words = {
        "подключить api", "добавить api", "connect api", "add api",
        "настроить api", "setup api", "подключить апи", "добавить апи",
    }
    if text.strip().lower() in api_trigger_words:
        ctx.set_state(ConversationState.AWAITING_API_SETUP)
        from pds_ultimate.core.user_manager import SUPPORTED_APIS

        apis_list = ""
        for api_type, info in SUPPORTED_APIS.items():
            apis_list += f"\n• <b>{info['name']}</b> — {info['category']}"

        return (
            "🔧 Настройка API\n\n"
            f"Доступные API:{apis_list}\n\n"
            "Отправь API-ключ — я автоматически определю тип.\n"
            "Или напиши название API для инструкции.\n"
            "Напиши «пропустить» чтобы отменить."
        )

    # ─── Smart Routing: нужны ли инструменты? ────────────────────────
    needs_tools = await agent.should_use_tools(text)
    style_guide = persona_engine.get_style_guide(ctx.chat_id)

    if needs_tools:
        # ─── ReAct Agent Loop ────────────────────────────────────────
        logger.info(f"Agent: ReAct mode для '{text[:50]}...'")

        result = await agent.process(
            message=text,
            chat_id=ctx.chat_id,
            history=ctx.get_history_for_llm(),
            db_session=db_session,
            style_guide=style_guide,
        )

        # Логируем мышление агента
        logger.info(
            f"Agent: {result.total_iterations} итераций, "
            f"{len(result.tools_used)} tools, "
            f"{result.total_time_ms}ms"
        )

        # Сохраняем лог мышления в БД
        try:
            thought_log = AgentThought(
                chat_id=ctx.chat_id,
                user_query=text[:2000],
                iterations=result.total_iterations,
                tools_used=json.dumps(
                    result.tools_used, ensure_ascii=False) if result.tools_used else None,
                final_answer=result.answer[:5000] if result.answer else None,
                processing_time_ms=result.total_time_ms,
                memories_created=result.memory_entries_created,
                plan_used=result.plan_used,
            )
            db_session.add(thought_log)
        except Exception as e:
            logger.warning(f"Не удалось сохранить AgentThought: {e}")

        # Фоновое извлечение фактов из диалога
        try:
            dialogue = f"user: {text}\nassistant: {result.answer}"
            asyncio.create_task(
                agent.background_extract_memories(dialogue, db_session)
            )
        except Exception:
            pass

        # Если агент создал файлы — сохраняем для отправки
        if result.files_to_send:
            ctx._pending_files = result.files_to_send

        return result.answer

    else:
        # ─── Прямой ответ LLM (простые запросы) ──────────────────────
        return await agent.direct_response(
            message=text,
            history=ctx.get_history_for_llm(),
            style_guide=style_guide,
            chat_id=ctx.chat_id,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# РЕГИСТРАЦИЯ: Ожидание имени и настройка API
# ═══════════════════════════════════════════════════════════════════════════════

async def _state_awaiting_name(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """
    Состояние: ожидание имени пользователя (регистрация).

    Логика:
    - Если имя = владелец (Вячеслав Амбарцумов) → полный доступ + все API
    - Если другое имя → регистрация как обычный user + onboarding
    """
    name = text.strip()

    # Валидация: минимум 2 символа, не цифры
    if len(name) < 2 or name.isdigit():
        return (
            "🤔 Это не похоже на имя. Напиши своё имя и фамилию.\n"
            "Например: Иван Петров"
        )

    # Регистрируем пользователя
    profile = await user_manager.register_user(ctx.chat_id, name, db_session)

    if profile["role"] == "owner":
        # Владелец — полный доступ, все API уже подключены
        ctx.reset()

        return (
            f"🎉 С возвращением, {name.split()[0].capitalize()}!\n\n"
            "Я узнал тебя — все твои API и инструменты подключены автоматически:\n"
            "• 🤖 DeepSeek AI (reasoning + chat)\n"
            "• 📱 Telegram Bot\n"
            "• 💬 WhatsApp (Green-API)\n"
            "• 📧 Gmail (2 аккаунта)\n\n"
            "Готов к работе! Пиши что нужно — я пойму. 💪"
        )
    else:
        # Обычный пользователь — onboarding
        ctx.set_state(ConversationState.AWAITING_API_SETUP)

        first_name = name.split()[0].capitalize()
        onboarding = (
            f"🎉 Добро пожаловать, {first_name}!\n\n"
            + user_manager.get_onboarding_message()
        )
        return onboarding


async def _state_awaiting_api_setup(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """
    Состояние: настройка API (onboarding).

    Пользователь может:
    1. Отправить API-ключ → автодетект + сохранение
    2. Написать «пропустить» / «skip» → перейти к работе без API
    3. Написать «помощь» / «help» → подробная инструкция
    4. Написать название API → получить гайд по подключению
    """
    text_lower = text.strip().lower()

    # Пропустить настройку
    skip_words = {"пропустить", "skip", "нет", "потом",
                  "позже", "не хочу", "не надо", "нет спасибо"}
    if text_lower in skip_words:
        ctx.reset()
        # Отмечаем onboarding завершённым
        from pds_ultimate.core.database import UserProfile
        db_profile = db_session.query(UserProfile).filter_by(
            chat_id=ctx.chat_id, is_active=True
        ).first()
        if db_profile:
            db_profile.onboarding_complete = True
        user_manager.invalidate_cache(ctx.chat_id)

        return (
            "👍 Хорошо! Ты можешь подключить API в любой момент — "
            "просто отправь мне API-ключ, и я автоматически определю тип.\n\n"
            "А пока я могу отвечать на вопросы, переводить тексты, "
            "работать с файлами и многое другое!\n\n"
            "Пиши что нужно — начинаем! 🚀"
        )

    # Запрос помощи
    help_words = {"помощь", "help",
                  "что подключить", "какие api", "инструкция"}
    if text_lower in help_words:
        from pds_ultimate.core.user_manager import SUPPORTED_APIS

        apis_list = ""
        for api_type, info in SUPPORTED_APIS.items():
            apis_list += f"\n• <b>{info['name']}</b> — {info['category']}"

        return (
            "📋 Доступные API для подключения:\n"
            f"{apis_list}\n\n"
            "Чтобы узнать как подключить конкретный API, напиши его название.\n"
            "Например: «deepseek» или «openai»\n\n"
            "Или просто отправь API-ключ — я автоматически определю тип! 🔮\n\n"
            "Напиши «пропустить» чтобы продолжить без API."
        )

    # Запрос гайда по конкретному API
    from pds_ultimate.core.user_manager import SUPPORTED_APIS
    for api_type, info in SUPPORTED_APIS.items():
        if api_type in text_lower or info["name"].lower() in text_lower:
            guide = user_manager.get_api_setup_guide(api_type)
            return (
                f"{guide}\n\n"
                "Отправь API-ключ когда будет готов, "
                "или напиши «пропустить»."
            )

    # Попытка автодетекта API-ключа из текста
    result = await user_manager.detect_and_save_api(ctx.chat_id, text, db_session)

    if result:
        # Успешно определили и сохранили API
        api_name = result.get("api_name", result.get("api_type", "Unknown"))
        api_type = result["api_type"]

        # Валидируем API
        is_valid, valid_msg = await user_manager.validate_api(
            ctx.chat_id, api_type, db_session
        )

        if is_valid:
            response = (
                f"✅ API подключён: <b>{api_name}</b>\n"
                f"Ключ: {result.get('masked_value', '***')}\n"
                f"Статус: {valid_msg}\n\n"
            )
        else:
            response = (
                f"⚠️ API сохранён: <b>{api_name}</b>\n"
                f"Ключ: {result.get('masked_value', '***')}\n"
                f"Статус: {valid_msg}\n\n"
            )

        response += (
            "Хочешь подключить ещё один API? Отправь ключ.\n"
            "Или напиши «пропустить» чтобы начать работу."
        )
        return response    # Не распознали — предлагаем помощь
    return (
        "🤔 Не удалось распознать API-ключ.\n\n"
        "Варианты:\n"
        "• Отправь API-ключ (я автоматически определю тип)\n"
        "• Напиши название API для инструкции (deepseek, openai...)\n"
        "• Напиши «помощь» для списка доступных API\n"
        "• Напиши «пропустить» чтобы начать без API"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# РЕАЛИЗАЦИЯ: Новый заказ
# ═══════════════════════════════════════════════════════════════════════════════

async def _start_new_order(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Начало создания нового заказа."""
    from pds_ultimate.utils.parsers import parser

    # Пробуем распарсить позиции из текста
    result = await parser.parse_text_smart(text)

    if result.items:
        # Позиции найдены — сохраняем и показываем
        ctx.set_state(
            ConversationState.ORDER_CONFIRM,
            parsed_items=[item.to_dict() for item in result.items],
        )

        items_text = _format_items_list(result.items)
        return (
            f"📦 Распознал позиции:\n\n{items_text}\n\n"
            f"Всё верно? Можешь поправить текстом или скажи «готово»."
        )
    else:
        # Позиции не распознаны — просим ввести
        ctx.set_state(ConversationState.ORDER_INPUT)
        return (
            "📦 Новый заказ! Введи список позиций.\n"
            "Можно текстом: «Балаклавы 100 шт, маски 50 шт»\n"
            "Или скинь файл (Excel, Word, PDF, фото)."
        )


async def _state_order_input(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Состояние: ввод позиций заказа."""
    from pds_ultimate.utils.parsers import parser

    result = await parser.parse_text_smart(text)

    if result.items:
        existing = ctx.get_temp("parsed_items", [])
        new_items = [item.to_dict() for item in result.items]
        all_items = existing + new_items

        ctx.set_state(ConversationState.ORDER_CONFIRM, parsed_items=all_items)

        items_text = _format_items_list_from_dicts(all_items)
        return (
            f"📦 Позиции:\n\n{items_text}\n\n"
            f"Всё верно? Поправь текстом или скажи «готово»."
        )
    else:
        return (
            "Не удалось распознать позиции. Попробуй в формате:\n"
            "«Балаклавы 100 шт, маски 50 шт по 2$»"
        )


async def _state_order_confirm(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Состояние: подтверждение списка позиций."""
    lower = text.lower().strip()

    # Подтверждение
    if lower in ("готово", "да", "ок", "ладно", "подтверждаю", "всё верно", "верно", "гоу", "го"):
        return await _create_order_in_db(ctx, db_session)

    # Отмена
    if lower in ("отмена", "нет", "отменить", "стоп"):
        ctx.clear_temp()
        return "❌ Заказ отменён."

    # Дополнение или правка — парсим новый текст
    from pds_ultimate.utils.parsers import parser
    result = await parser.parse_text_smart(text)

    if result.items:
        new_items = [item.to_dict() for item in result.items]
        # Спрашиваем LLM: это замена или дополнение?
        intent = await llm_engine.chat(
            f"Пользователь сказал: «{text}». Он хочет ЗАМЕНИТЬ весь список позиций "
            f"или ДОБАВИТЬ новые к существующим? Ответь одним словом: ЗАМЕНИТЬ или ДОБАВИТЬ.",
            task_type="simple_answer",
            temperature=0.1,
            max_tokens=20,
        )

        if "замен" in intent.lower():
            ctx.set_temp("parsed_items", new_items)
        else:
            existing = ctx.get_temp("parsed_items", [])
            ctx.set_temp("parsed_items", existing + new_items)

        all_items = ctx.get_temp("parsed_items", [])
        items_text = _format_items_list_from_dicts(all_items)
        return (
            f"📦 Обновлённый список:\n\n{items_text}\n\n"
            f"Всё верно? Скажи «готово» или поправь."
        )

    # Не распознано как позиции — может текстовая правка
    return await _general_response(ctx, text)


async def _create_order_in_db(
    ctx: ConversationContext,
    db_session: Session,
) -> str:
    """Создать заказ в БД из подтверждённых позиций."""
    items_data = ctx.get_temp("parsed_items", [])
    if not items_data:
        ctx.clear_temp()
        return "Нет позиций для создания заказа."

    # Генерируем номер заказа
    order_count = db_session.query(Order).count()
    order_number = f"ORD-{order_count + 1:04d}"

    # Создаём заказ
    order = Order(
        order_number=order_number,
        status=OrderStatus.CONFIRMED,
        order_date=date.today(),
    )
    db_session.add(order)
    db_session.flush()  # Получаем order.id

    # Создаём позиции
    for item_data in items_data:
        first_check = date.today() + timedelta(days=config.logistics.first_status_check_days)

        item = OrderItem(
            order_id=order.id,
            name=item_data["name"],
            quantity=item_data["quantity"],
            unit=item_data.get("unit", "шт"),
            unit_price=item_data.get("unit_price"),
            price_currency=item_data.get("currency", "USD"),
            weight=item_data.get("weight"),
            status=ItemStatus.PENDING,
            next_check_date=first_check,
        )
        db_session.add(item)

    db_session.commit()

    # Переходим к вводу финансов
    ctx.set_state(ConversationState.AWAITING_INCOME, order_id=order.id)

    return (
        f"✅ Заказ {order_number} создан! ({len(items_data)} позиций)\n\n"
        f"💰 Сколько тебе заплатили за этот заказ (сумма в $, ¥ или манатах)?"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# РЕАЛИЗАЦИЯ: Финансовый поток (Доход → Расход → Остаток)
# ═══════════════════════════════════════════════════════════════════════════════

async def _state_awaiting_income(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Сколько заплатили МНЕ за заказ."""
    amount, currency = _parse_amount(text)

    if amount is None:
        return "Не понял сумму. Напиши число, например: «5000$» или «35000 манат»."

    order_id = ctx.get_temp("order_id")
    order = db_session.query(Order).get(order_id)
    if not order:
        ctx.clear_temp()
        return "Заказ не найден. Что-то пошло не так."

    order.income = amount
    order.income_currency = currency

    # Записываем транзакцию
    db_session.add(Transaction(
        order_id=order.id,
        transaction_type=TransactionType.INCOME,
        amount=amount,
        currency=currency,
        amount_usd=_convert_to_usd(amount, currency),
        description=f"Оплата за заказ {order.order_number}",
        transaction_date=date.today(),
    ))

    db_session.commit()

    ctx.set_state(ConversationState.AWAITING_EXPENSE, order_id=order.id)

    return (
        f"✅ Доход: {amount} {currency}\n\n"
        f"💸 Сколько ты заплатил поставщику за товар?"
    )


async def _state_awaiting_expense(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Сколько Я заплатил поставщику."""
    amount, currency = _parse_amount(text)

    if amount is None:
        return "Не понял сумму. Напиши число, например: «3000$» или «21000 юань»."

    order_id = ctx.get_temp("order_id")
    order = db_session.query(Order).get(order_id)
    if not order:
        ctx.clear_temp()
        return "Заказ не найден."

    order.expense_goods = amount
    order.expense_goods_currency = currency

    db_session.add(Transaction(
        order_id=order.id,
        transaction_type=TransactionType.EXPENSE_GOODS,
        amount=amount,
        currency=currency,
        amount_usd=_convert_to_usd(amount, currency),
        description=f"Оплата поставщику за заказ {order.order_number}",
        transaction_date=date.today(),
    ))

    # Считаем остаток
    income_usd = _convert_to_usd(order.income, order.income_currency)
    expense_usd = _convert_to_usd(amount, currency)
    remainder = income_usd - expense_usd

    # Переводим заказ в фазу трекинга
    order.status = OrderStatus.TRACKING
    db_session.commit()

    ctx.clear_temp()

    return (
        f"✅ Расход на товар: {amount} {currency}\n\n"
        f"📊 Остаток: ${remainder:.2f}\n"
        f"(Из него потом вычтется доставка)\n\n"
        f"Заказ {order.order_number} переведён в режим отслеживания 📦\n"
        f"Через {config.logistics.first_status_check_days} дня спрошу статус каждой позиции."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# РЕАЛИЗАЦИЯ: Трекинг позиций
# ═══════════════════════════════════════════════════════════════════════════════

async def _state_awaiting_status(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Ответ на вопрос 'позиция пришла?'."""
    item_id = ctx.get_temp("current_item_id")
    item = db_session.query(OrderItem).get(item_id) if item_id else None

    if not item:
        ctx.clear_temp()
        return "Позиция не найдена. Напиши что нужно."

    lower = text.lower().strip()

    if lower in ("да", "пришло", "пришла", "есть", "получил", "доставлено", "yes"):
        item.status = ItemStatus.ARRIVED
        item.arrival_date = date.today()
        db_session.commit()

        ctx.set_state(ConversationState.AWAITING_TRACK,
                      current_item_id=item.id)
        return f"✅ {item.name} — прибыло!\nСкинь трек-номер (текстом или фото)."

    elif lower in ("нет", "не пришло", "не пришла", "нету", "no", "ещё нет"):
        # Ставим следующую проверку на вторник
        next_tuesday = _next_weekday(config.logistics.recurring_check_weekday)
        item.next_check_date = next_tuesday
        item.reminder_count += 1
        db_session.commit()

        ctx.clear_temp()

        # Проверяем следующую позицию
        return await _check_next_pending_item(item.order_id, db_session, ctx)

    else:
        return "Пришло или нет? Скажи «да» или «нет»."


async def _state_awaiting_track(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Ввод трек-номера."""
    item_id = ctx.get_temp("current_item_id")
    item = db_session.query(OrderItem).get(item_id) if item_id else None

    if not item:
        ctx.clear_temp()
        return "Позиция не найдена."

    track = text.strip()
    if len(track) < 3:
        return "Слишком короткий трек. Введи полный номер."

    item.tracking_number = track
    item.tracking_source = "manual"
    db_session.commit()

    ctx.clear_temp()

    # Проверяем: все ли позиции заказа прибыли?
    order = db_session.query(Order).get(item.order_id)
    pending = db_session.query(OrderItem).filter_by(
        order_id=item.order_id,
        status=ItemStatus.PENDING,
    ).count()

    if pending == 0:
        # Все прибыло — переходим к расчёту доставки
        return await _all_items_arrived(order, db_session, ctx)

    return (
        f"✅ Трек {track} сохранён для «{item.name}».\n\n"
        f"Осталось ожидать: {pending} позиций."
    )


async def _all_items_arrived(
    order: Order,
    db_session: Session,
    ctx: ConversationContext,
) -> str:
    """Все позиции прибыли — запускаем расчёт доставки."""
    order.status = OrderStatus.DELIVERY_CALC
    db_session.commit()

    ctx.set_state(ConversationState.AWAITING_DELIVERY_TYPE, order_id=order.id)

    return (
        f"🎉 Все позиции заказа {order.order_number} прибыли!\n\n"
        f"📦 Как вводим доставку?\n"
        f"• «Общей суммой» — я сам распределю по позициям\n"
        f"• «По каждой» — введёшь стоимость для каждой позиции"
    )


async def _state_delivery_type(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Выбор типа ввода доставки."""
    lower = text.lower().strip()

    order_id = ctx.get_temp("order_id")
    order = db_session.query(Order).get(order_id) if order_id else None
    if not order:
        ctx.clear_temp()
        return "Заказ не найден."

    if any(w in lower for w in ("общ", "всего", "вместе", "одной суммой", "общей")):
        order.delivery_input_type = "total"
        db_session.commit()
        ctx.set_state(ConversationState.AWAITING_DELIVERY, order_id=order.id)
        return "Введи общую стоимость доставки:"

    elif any(w in lower for w in ("кажд", "отдельно", "по позици", "по каждой")):
        order.delivery_input_type = "per_item"
        db_session.commit()
        # Берём первую позицию
        items = db_session.query(OrderItem).filter_by(order_id=order.id).all()
        if items:
            ctx.set_state(
                ConversationState.AWAITING_DELIVERY,
                order_id=order.id,
                delivery_items=[i.id for i in items],
                delivery_index=0,
            )
            return f"Стоимость доставки для «{items[0].name}» ({items[0].quantity} {items[0].unit}):"
        ctx.clear_temp()
        return "Нет позиций в заказе."

    return "Скажи «общей суммой» или «по каждой позиции»."


async def _state_delivery_cost(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Ввод стоимости доставки."""
    amount, currency = _parse_amount(text)
    if amount is None:
        return "Не понял сумму. Напиши число, например: «500$»."

    order_id = ctx.get_temp("order_id")
    order = db_session.query(Order).get(order_id) if order_id else None
    if not order:
        ctx.clear_temp()
        return "Заказ не найден."

    if order.delivery_input_type == "total":
        # Общая доставка — распределяем пропорционально
        order.delivery_cost = amount
        order.delivery_currency = currency

        items = db_session.query(OrderItem).filter_by(order_id=order.id).all()
        total_qty = sum(i.quantity for i in items)

        if total_qty > 0:
            for item in items:
                share = item.quantity / total_qty
                item.delivery_cost = round(amount * share, 2)
                db_session.flush()

        db_session.add(Transaction(
            order_id=order.id,
            transaction_type=TransactionType.EXPENSE_DELIVERY,
            amount=amount,
            currency=currency,
            amount_usd=_convert_to_usd(amount, currency),
            description=f"Доставка заказа {order.order_number} (общая)",
            transaction_date=date.today(),
        ))

        db_session.commit()
        return await _finalize_order(order, db_session, ctx)

    else:
        # По каждой позиции
        delivery_items = ctx.get_temp("delivery_items", [])
        delivery_index = ctx.get_temp("delivery_index", 0)

        if delivery_index < len(delivery_items):
            item_id = delivery_items[delivery_index]
            item = db_session.query(OrderItem).get(item_id)
            if item:
                item.delivery_cost = amount
                db_session.flush()

            delivery_index += 1
            ctx.set_temp("delivery_index", delivery_index)

            if delivery_index < len(delivery_items):
                next_item = db_session.query(OrderItem).get(
                    delivery_items[delivery_index])
                return f"✅ Записал. Доставка для «{next_item.name}» ({next_item.quantity} {next_item.unit}):"

        # Все позиции введены
        total_delivery = sum(
            (db_session.query(OrderItem).get(iid).delivery_cost or 0)
            for iid in delivery_items
        )
        order.delivery_cost = total_delivery
        order.delivery_currency = currency

        db_session.add(Transaction(
            order_id=order.id,
            transaction_type=TransactionType.EXPENSE_DELIVERY,
            amount=total_delivery,
            currency=currency,
            amount_usd=_convert_to_usd(total_delivery, currency),
            description=f"Доставка заказа {order.order_number} (по позициям)",
            transaction_date=date.today(),
        ))

        db_session.commit()
        return await _finalize_order(order, db_session, ctx)


# ═══════════════════════════════════════════════════════════════════════════════
# ФИНАЛИЗАЦИЯ ЗАКАЗА
# ═══════════════════════════════════════════════════════════════════════════════

async def _finalize_order(
    order: Order,
    db_session: Session,
    ctx: ConversationContext,
) -> str:
    """
    Закрытие заказа.
    По ТЗ: ДОХОД - ТОВАР = ОСТАТОК - ДОСТАВКА = ЧИСТАЯ ПРИБЫЛЬ
    Чистая прибыль → расходы + отложения (%)
    Все позиции → архивный файл
    Временный файл → удаляется
    """
    # Расчёт
    income_usd = _convert_to_usd(
        order.income or 0, order.income_currency or "USD")
    expense_goods_usd = _convert_to_usd(
        order.expense_goods or 0, order.expense_goods_currency or "USD"
    )
    delivery_usd = _convert_to_usd(
        order.delivery_cost or 0, order.delivery_currency or "USD"
    )

    remainder = income_usd - expense_goods_usd
    net_profit = remainder - delivery_usd

    # Распределение прибыли
    exp_pct = config.finance.expense_percent
    sav_pct = config.finance.savings_percent

    profit_expenses = round(net_profit * exp_pct / 100,
                            2) if net_profit > 0 else 0
    profit_savings = round(net_profit * sav_pct / 100,
                           2) if net_profit > 0 else 0

    # Сохраняем в заказ
    order.net_profit = net_profit
    order.profit_to_expenses = profit_expenses
    order.profit_to_savings = profit_savings
    order.expense_percent = exp_pct
    order.savings_percent = sav_pct
    order.completed_date = date.today()
    order.status = OrderStatus.COMPLETED

    # Транзакции распределения
    if profit_expenses > 0:
        db_session.add(Transaction(
            order_id=order.id,
            transaction_type=TransactionType.PROFIT_EXPENSES,
            amount=profit_expenses,
            currency="USD",
            amount_usd=profit_expenses,
            description=f"На расходы ({exp_pct}%) из {order.order_number}",
            transaction_date=date.today(),
        ))
    if profit_savings > 0:
        db_session.add(Transaction(
            order_id=order.id,
            transaction_type=TransactionType.PROFIT_SAVINGS,
            amount=profit_savings,
            currency="USD",
            amount_usd=profit_savings,
            description=f"Отложения ({sav_pct}%) из {order.order_number}",
            transaction_date=date.today(),
        ))

    # ─── Архивация позиций (ВСЕ → единый архив) ─────────────────────
    items = db_session.query(OrderItem).filter_by(order_id=order.id).all()
    for item in items:
        archived = ArchivedOrderItem(
            original_order_id=order.id,
            order_number=order.order_number,
            item_name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=item.unit_price,
            price_currency=item.price_currency,
            weight=item.weight,
            tracking_number=item.tracking_number,
            arrival_date=item.arrival_date,
            delivery_cost=item.delivery_cost,
            total_cost=item.total_cost,
            supplier_name=order.supplier.name if order.supplier else None,
            client_name=order.client.name if order.client else None,
            order_income=order.income,
            order_expense_goods=order.expense_goods,
            order_delivery_cost=order.delivery_cost,
            order_net_profit=order.net_profit,
            order_date=order.order_date,
            completed_date=order.completed_date,
            archived_date=date.today(),
        )
        db_session.add(archived)

    order.status = OrderStatus.ARCHIVED
    order.archived_date = date.today()

    # Удаляем временный файл если есть
    if order.temp_file_path and os.path.exists(order.temp_file_path):
        try:
            os.remove(order.temp_file_path)
        except OSError:
            pass

    db_session.commit()
    ctx.clear_temp()

    # Формируем отчёт
    result = (
        f"🏁 Заказ {order.order_number} — ЗАКРЫТ!\n\n"
        f"📊 Финансовый итог:\n"
        f"  Доход: ${income_usd:.2f}\n"
        f"  Товар: -${expense_goods_usd:.2f}\n"
        f"  Остаток: ${remainder:.2f}\n"
        f"  Доставка: -${delivery_usd:.2f}\n"
        f"  ━━━━━━━━━━━━━━━\n"
        f"  Чистая прибыль: ${net_profit:.2f}\n\n"
        f"📈 Распределение:\n"
        f"  На расходы ({exp_pct:.0f}%): ${profit_expenses:.2f}\n"
        f"  Отложения ({sav_pct:.0f}%): ${profit_savings:.2f}\n\n"
        f"📁 Все позиции сохранены в архив."
    )

    if net_profit < 0:
        result += "\n\n⚠️ Внимание: заказ убыточный!"

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# РЕАЛИЗАЦИЯ: Статус, финансы, заметки, безопасность, брифинг
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_order_status(
    ctx: ConversationContext,
    entities: dict,
    db_session: Session,
) -> str:
    """Статус заказов."""
    order_number = entities.get("order_number")

    if order_number:
        order = db_session.query(Order).filter_by(
            order_number=order_number).first()
        if not order:
            return f"Заказ {order_number} не найден."
        return _format_order_detail(order, db_session)

    # Все активные заказы
    active = db_session.query(Order).filter(
        Order.status.notin_([OrderStatus.ARCHIVED, OrderStatus.COMPLETED])
    ).all()

    if not active:
        return "Нет активных заказов."

    lines = ["📋 Активные заказы:\n"]
    for o in active:
        item_count = db_session.query(
            OrderItem).filter_by(order_id=o.id).count()
        pending = db_session.query(OrderItem).filter_by(
            order_id=o.id, status=ItemStatus.PENDING
        ).count()
        lines.append(
            f"• {o.order_number} | {o.status.value} | "
            f"Позиций: {item_count} (ждём: {pending})"
        )

    return "\n".join(lines)


async def _finance_query(
    ctx: ConversationContext,
    text: str,
    db_session: Session,
) -> str:
    """Финансовый запрос — LLM строит ответ из данных БД."""
    # Собираем сводку
    from sqlalchemy import func

    total_income = db_session.query(
        func.sum(Transaction.amount_usd)
    ).filter_by(transaction_type=TransactionType.INCOME).scalar() or 0

    total_goods = db_session.query(
        func.sum(Transaction.amount_usd)
    ).filter_by(transaction_type=TransactionType.EXPENSE_GOODS).scalar() or 0

    total_delivery = db_session.query(
        func.sum(Transaction.amount_usd)
    ).filter_by(transaction_type=TransactionType.EXPENSE_DELIVERY).scalar() or 0

    total_savings = db_session.query(
        func.sum(Transaction.amount_usd)
    ).filter_by(transaction_type=TransactionType.PROFIT_SAVINGS).scalar() or 0

    total_profit_exp = db_session.query(
        func.sum(Transaction.amount_usd)
    ).filter_by(transaction_type=TransactionType.PROFIT_EXPENSES).scalar() or 0

    completed_orders = db_session.query(Order).filter(
        Order.status.in_([OrderStatus.COMPLETED, OrderStatus.ARCHIVED])
    ).count()

    net = total_income - total_goods - total_delivery

    finance_context = (
        f"Финансовая сводка (всё в USD):\n"
        f"Общий доход: ${total_income:.2f}\n"
        f"Расходы на товар: ${total_goods:.2f}\n"
        f"Расходы на доставку: ${total_delivery:.2f}\n"
        f"Чистая прибыль: ${net:.2f}\n"
        f"На расходы: ${total_profit_exp:.2f}\n"
        f"Отложено: ${total_savings:.2f}\n"
        f"Закрытых заказов: {completed_orders}\n"
    )

    response = await llm_engine.chat(
        message=f"Вопрос пользователя: {text}\n\nДанные:\n{finance_context}",
        history=ctx.get_history_for_llm(),
        task_type="financial_calc",
    )

    return response


async def _start_set_income(ctx, entities, db_session):
    """Начать ввод дохода для заказа."""
    order = _find_latest_active_order(db_session)
    if not order:
        return "Нет активного заказа для ввода дохода."
    ctx.set_state(ConversationState.AWAITING_INCOME, order_id=order.id)
    return f"💰 Введи сумму дохода за заказ {order.order_number}:"


async def _start_set_expense(ctx, entities, db_session):
    """Начать ввод расхода для заказа."""
    order = _find_latest_active_order(db_session)
    if not order:
        return "Нет активного заказа для ввода расхода."
    ctx.set_state(ConversationState.AWAITING_EXPENSE, order_id=order.id)
    return f"💸 Введи сумму расхода на товар за заказ {order.order_number}:"


async def _start_delivery(ctx, entities, db_session):
    """Начать ввод доставки."""
    order = _find_latest_active_order(db_session)
    if not order:
        return "Нет активного заказа."
    ctx.set_state(ConversationState.AWAITING_DELIVERY_TYPE, order_id=order.id)
    return (
        f"📦 Доставка для {order.order_number}.\n"
        f"Вводим «общей суммой» или «по каждой позиции»?"
    )


async def _add_items_to_order(ctx, text, entities, db_session):
    """Добавить позиции в существующий заказ."""
    order = _find_latest_active_order(db_session)
    if not order:
        return "Нет активного заказа. Скажи «новый заказ» чтобы создать."

    from pds_ultimate.utils.parsers import parser
    result = await parser.parse_text_smart(text)

    if not result.items:
        return "Не смог распознать позиции. Попробуй в другом формате."

    for item_data in result.items:
        first_check = date.today() + timedelta(days=config.logistics.first_status_check_days)
        item = OrderItem(
            order_id=order.id,
            name=item_data.name,
            quantity=item_data.quantity,
            unit=item_data.unit,
            unit_price=item_data.unit_price,
            price_currency=item_data.currency,
            weight=item_data.weight,
            status=ItemStatus.PENDING,
            next_check_date=first_check,
        )
        db_session.add(item)

    db_session.commit()
    total = db_session.query(OrderItem).filter_by(order_id=order.id).count()

    return (
        f"✅ Добавлено {len(result.items)} позиций в {order.order_number}.\n"
        f"Всего позиций: {total}."
    )


async def _handle_contact_note(ctx, text, entities, db_session):
    """Создание заметки о контрагенте (умные карточки)."""
    response = await llm_engine.chat(
        message=(
            f"Из следующего текста извлеки: 1) имя контакта, 2) заметку о нём.\n"
            f"Текст: «{text}»\n"
            f"Верни JSON: {{\"name\": \"...\", \"note\": \"...\", \"is_warning\": true/false}}"
        ),
        task_type="parse_order",
        temperature=0.1,
        json_mode=True,
    )

    try:
        data = json.loads(response)
    except Exception:
        return await _general_response(ctx, text)

    name = data.get("name", "").strip()
    note = data.get("note", "").strip()
    is_warning = data.get("is_warning", False)

    if not name or not note:
        return await _general_response(ctx, text)

    # Ищем или создаём контакт
    contact = db_session.query(Contact).filter(
        Contact.name.ilike(f"%{name}%")
    ).first()

    if not contact:
        contact = Contact(name=name, contact_type=ContactType.OTHER)
        db_session.add(contact)
        db_session.flush()

    if is_warning:
        existing = contact.warnings or ""
        contact.warnings = f"{existing}\n[{date.today()}] {note}".strip()
    else:
        existing = contact.notes or ""
        contact.notes = f"{existing}\n[{date.today()}] {note}".strip()

    db_session.commit()

    emoji = "⚠️" if is_warning else "📝"
    return f"{emoji} Записал о «{contact.name}»: {note}"


async def _morning_brief(db_session: Session) -> str:
    """Утренний брифинг."""
    from sqlalchemy import func

    # Активные заказы
    active_orders = db_session.query(Order).filter(
        Order.status.notin_([OrderStatus.ARCHIVED, OrderStatus.COMPLETED])
    ).count()

    # Позиции ожидающие
    pending_items = db_session.query(OrderItem).filter_by(
        status=ItemStatus.PENDING
    ).count()

    # Финансы
    total_income = db_session.query(
        func.sum(Transaction.amount_usd)
    ).filter_by(transaction_type=TransactionType.INCOME).scalar() or 0

    total_expenses = db_session.query(
        func.sum(Transaction.amount_usd)
    ).filter(Transaction.transaction_type.in_([
        TransactionType.EXPENSE_GOODS,
        TransactionType.EXPENSE_DELIVERY,
    ])).scalar() or 0

    total_savings = db_session.query(
        func.sum(Transaction.amount_usd)
    ).filter_by(transaction_type=TransactionType.PROFIT_SAVINGS).scalar() or 0

    balance = total_income - total_expenses

    today = date.today().strftime("%d.%m.%Y")

    return (
        f"☀️ БРИФИНГ НА {today}\n\n"
        f"📦 Активных заказов: {active_orders}\n"
        f"📋 Ожидаем позиций: {pending_items}\n"
        f"💰 Баланс: ${balance:.2f}\n"
        f"🏦 Отложено: ${total_savings:.2f}\n\n"
        f"Что делаем сегодня, босс?"
    )


async def _security_emergency(db_session: Session) -> str:
    """Экстренное удаление финансовых данных."""
    from pds_ultimate.config import ALL_ORDERS_ARCHIVE_PATH, MASTER_FINANCE_PATH

    # Удаляем файлы
    for fp in [MASTER_FINANCE_PATH, ALL_ORDERS_ARCHIVE_PATH]:
        if fp.exists():
            try:
                os.remove(fp)
            except OSError:
                pass

    # Очищаем финансовые таблицы
    db_session.query(Transaction).delete()
    db_session.commit()

    logger.critical("🚨 SECURITY MODE ACTIVATED — финансовые данные удалены")
    return "🔒 Режим безопасности активирован. Финансовые данные удалены."


# ═══════════════════════════════════════════════════════════════════════════════
# СВОБОДНЫЙ ОТВЕТ — DeepSeek делает ВСЁ
# ═══════════════════════════════════════════════════════════════════════════════

async def _general_response(
    ctx: ConversationContext,
    text: str,
) -> str:
    """
    Свободный режим — DeepSeek отвечает на ЛЮБОЙ запрос.
    Используется полная история разговора для контекста.
    """
    response = await llm_engine.chat(
        message=text,
        history=ctx.get_history_for_llm(),
        task_type="general",
    )
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_amount(text: str) -> tuple[float | None, str]:
    """
    Извлечь сумму и валюту из текста.
    '5000$' → (5000.0, 'USD')
    '35000 манат' → (35000.0, 'TMT')
    '2000 юань' → (2000.0, 'CNY')
    """
    import re

    text = text.strip().lower()

    # Маппинг
    curr_map = {
        "$": "USD", "usd": "USD", "долл": "USD", "бакс": "USD",
        "¥": "CNY", "cny": "CNY", "юан": "CNY", "юань": "CNY",
        "ман": "TMT", "tmt": "TMT", "манат": "TMT",
        "€": "EUR", "eur": "EUR", "евро": "EUR",
        "руб": "RUB", "rub": "RUB", "₽": "RUB",
    }

    # Ищем число
    num_match = re.search(r"[\d\s]+[.,]?\d*", text)
    if not num_match:
        return None, "USD"

    num_str = num_match.group(0).replace(" ", "").replace(",", ".")
    try:
        amount = float(num_str)
    except ValueError:
        return None, "USD"

    # Ищем валюту
    currency = "USD"  # дефолт
    for key, code in curr_map.items():
        if key in text:
            currency = code
            break

    return amount, currency


def _convert_to_usd(amount: float, currency: str) -> float:
    """Конвертировать в USD по фиксированным курсам."""
    if currency == "USD":
        return amount
    rates = config.currency.fixed_rates
    if currency in rates:
        return round(amount / rates[currency], 2)
    # Для других валют — TODO: динамический курс
    return amount


def _format_items_list(items) -> str:
    """Форматировать список ParsedItem."""
    lines = []
    for i, item in enumerate(items, 1):
        price = f" по {item.unit_price} {item.currency}" if item.unit_price else ""
        lines.append(f"{i}. {item.name} — {item.quantity} {item.unit}{price}")
    return "\n".join(lines)


def _format_items_list_from_dicts(items: list[dict]) -> str:
    """Форматировать список позиций из словарей."""
    lines = []
    for i, item in enumerate(items, 1):
        price = ""
        if item.get("unit_price"):
            price = f" по {item['unit_price']} {item.get('currency', 'USD')}"
        lines.append(
            f"{i}. {item['name']} — {item['quantity']} {item.get('unit', 'шт')}{price}"
        )
    return "\n".join(lines)


def _format_order_detail(order: Order, db_session: Session) -> str:
    """Детальная информация о заказе."""
    items = db_session.query(OrderItem).filter_by(order_id=order.id).all()

    lines = [
        f"📦 Заказ {order.order_number}",
        f"Статус: {order.status.value}",
        f"Дата: {order.order_date}",
        "",
        "Позиции:",
    ]

    for i, item in enumerate(items, 1):
        status_emoji = "✅" if item.status == ItemStatus.ARRIVED else "⏳"
        track = f" | Трек: {item.tracking_number}" if item.tracking_number else ""
        lines.append(
            f"  {i}. {status_emoji} {item.name} — {item.quantity} {item.unit}{track}")

    if order.income:
        lines.append(f"\n💰 Доход: {order.income} {order.income_currency}")
    if order.expense_goods:
        lines.append(
            f"💸 Товар: {order.expense_goods} {order.expense_goods_currency}")
    if order.net_profit is not None:
        lines.append(f"📊 Чистая прибыль: ${order.net_profit:.2f}")

    return "\n".join(lines)


def _find_latest_active_order(db_session: Session) -> Order | None:
    """Найти последний активный заказ."""
    return db_session.query(Order).filter(
        Order.status.notin_([OrderStatus.ARCHIVED, OrderStatus.COMPLETED])
    ).order_by(Order.id.desc()).first()


async def _check_next_pending_item(
    order_id: int,
    db_session: Session,
    ctx: ConversationContext,
) -> str:
    """Проверить следующую ожидающую позицию."""
    next_item = db_session.query(OrderItem).filter_by(
        order_id=order_id,
        status=ItemStatus.PENDING,
    ).first()

    if next_item:
        ctx.set_state(ConversationState.AWAITING_STATUS,
                      current_item_id=next_item.id)
        return f"⏳ «{next_item.name}» ({next_item.quantity} {next_item.unit}) — пришло?"

    # Все проверены — есть ли ещё ожидающие?
    pending = db_session.query(OrderItem).filter_by(
        order_id=order_id,
        status=ItemStatus.PENDING,
    ).count()

    if pending == 0:
        order = db_session.query(Order).get(order_id)
        if order:
            return await _all_items_arrived(order, db_session, ctx)

    ctx.clear_temp()
    return "На сегодня всё. Спрошу снова во вторник."


def _next_weekday(weekday: int) -> date:
    """Найти ближайший день недели (0=Пн, 1=Вт, ..., 6=Вс)."""
    today = date.today()
    days_ahead = weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def _extract_answer_from_json(text: str) -> str:
    """
    v3: 4-уровневая защита от утечки JSON.
    Использует _clean_json_from_response из agent.py.
    НИКОГДА не показывает сырой JSON пользователю.
    """
    from pds_ultimate.core.agent import _clean_json_from_response
    return _clean_json_from_response(text)


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Разбить длинное сообщение на части для Telegram."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Ищем ближайший перенос строки до лимита
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos == -1:
            split_pos = max_len

        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")

    return chunks


def _looks_like_api_key(text: str) -> bool:
    """
    Эвристика: текст похож на API-ключ?
    Проверяем по паттернам из user_manager.
    """
    import re
    text = text.strip()

    # Короткий текст или слишком длинный — не ключ
    if len(text) < 10 or len(text) > 500:
        return False

    # Содержит пробелы и не JSON — скорее обычный текст
    if " " in text and not text.strip().startswith("{"):
        # Но может быть "sk-xxx мой ключ" — проверяем префиксы
        first_word = text.split()[0]
        key_prefixes = ("sk-", "pk-", "Bearer ", "ghp_", "gho_")
        if not any(first_word.startswith(p) for p in key_prefixes):
            return False

    # Проверяем по паттернам
    from pds_ultimate.core.user_manager import API_KEY_PATTERNS
    for pattern, api_type, field_name in API_KEY_PATTERNS:
        if re.search(pattern, text):
            return True

    # JSON с credentials
    if text.strip().startswith("{"):
        return True

    # URL, похожий на API endpoint
    if text.startswith("http") and "api" in text.lower():
        return True

    return False


def _save_to_db(
    db_session: Session,
    chat_id: int,
    role: str,
    content: str,
) -> None:
    """Сохранить сообщение в историю БД."""
    try:
        entry = ConversationHistory(
            chat_id=chat_id,
            role=role,
            content=content,
            content_type="text",
        )
        db_session.add(entry)
    except Exception as e:
        logger.warning(f"Не удалось сохранить в историю: {e}")
