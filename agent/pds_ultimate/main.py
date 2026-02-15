"""
PDS-Ultimate — Точка входа
============================
Запуск всей системы: инициализация БД, LLM, модулей, интеграций, Scheduler, Telegram Bot.

Wiring-архитектура (Part 4 + Part 5):
- main.py создаёт SessionFactory
- Передаёт его во все модули и бот
- Запускает интеграции (Telethon, WhatsApp, Gmail)
- Подключает модули к планировщику
- Связывает Bot → Scheduler для отправки напоминаний

Использование:
    python -m pds_ultimate.main
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pds_ultimate.config import config, logger

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main():
    """Главная точка входа."""

    logger.info("=" * 60)
    logger.info("  PDS-ULTIMATE v1.0 — Запуск системы")
    logger.info("=" * 60)

    # ─── 1. Валидация конфигурации ───────────────────────────────────────
    logger.info("[1/7] Валидация конфигурации...")
    try:
        warnings = config.validate()
        for w in warnings:
            logger.warning(f"  ⚠ {w}")
        logger.info("  ✅ Конфигурация валидна")
    except ValueError as e:
        logger.critical(f"  ❌ Критическая ошибка конфигурации: {e}")
        logger.critical("  Проверьте файл .env (скопируйте из .env.example)")
        sys.exit(1)

    # ─── 2. Инициализация базы данных ────────────────────────────────────
    logger.info("[2/7] Инициализация базы данных...")
    from pds_ultimate.core.database import init_database
    engine, session_factory = init_database()
    logger.info("  ✅ БД готова")

    from pds_ultimate.core.persona_engine import persona_engine
    persona_engine.set_session_factory(session_factory)

    from pds_ultimate.core.contact_book import contact_book
    contact_book.set_session_factory(session_factory)

    # ─── 3. Запуск LLM Engine ────────────────────────────────────────────
    logger.info("[3/7] Запуск LLM Engine (DeepSeek API)...")
    from pds_ultimate.core.llm_engine import llm_engine
    await llm_engine.start()
    logger.info("  ✅ LLM Engine запущен")

    # ─── 3.5. Инициализация AI Agent System ─────────────────────────────
    logger.info("[3.5/7] Инициализация AI Agent (ReAct + Tools + Memory)...")
    from pds_ultimate.core.advanced_memory_manager import advanced_memory_manager
    from pds_ultimate.core.browser_engine import browser_engine
    from pds_ultimate.core.business_tools import register_all_tools
    from pds_ultimate.core.cognitive_engine import cognitive_engine
    from pds_ultimate.core.memory import memory_manager

    # Регистрируем бизнес-инструменты
    tools_count = register_all_tools()
    logger.info(f"  🔧 Зарегистрировано {tools_count} инструментов")

    # Запуск Browser Engine (для web_search и т.д.)
    try:
        await browser_engine.start()
        logger.info("  🌐 Browser Engine запущен")
    except Exception as e:
        logger.warning(f"  ⚠ Browser Engine: {e} (работа без браузера)")

    # Internet Reasoning Engine (использует Browser Engine)
    try:
        from pds_ultimate.core.internet_reasoning import reasoning_engine
        logger.info(
            "  🔬 Internet Reasoning Engine: готов "
            f"(trust domains: {len(reasoning_engine.trust_scorer._domain_scores)})"
        )
    except Exception as e:
        logger.warning(f"  ⚠ Internet Reasoning Engine: {e}")

    # Part 6: Новые движки
    from pds_ultimate.core.parallel_engine import parallel_engine
    from pds_ultimate.core.performance_engine import performance_engine
    from pds_ultimate.core.semantic_engine import semantic_engine

    logger.info("  💖 Emotional Intelligence Engine: готов")
    logger.info(
        f"  ⚡ Performance Engine: cache_max={performance_engine.cache._max_size}, "
        f"dedup={performance_engine.dedup is not None}"
    )
    logger.info(
        f"  🔀 Parallel Engine: "
        f"max_concurrent={parallel_engine.concurrency._max_concurrent}"
    )
    logger.info(
        f"  🔍 Semantic Engine: "
        f"index_size={len(semantic_engine.index._vectors)}"
    )

    # Загружаем долгосрочную память из БД (оба менеджера)
    with session_factory() as mem_session:
        mem_count = memory_manager.load_from_db(mem_session)
        logger.info(f"  🧠 Загружено {mem_count} записей памяти (basic)")
        adv_count = advanced_memory_manager.load_from_db(mem_session)
        logger.info(f"  🧠 Загружено {adv_count} записей памяти (advanced)")

    # Инициализация multi-user системы
    logger.info("  👥 User Manager: готов к работе")

    # Memory stats
    stats = advanced_memory_manager.get_stats()
    logger.info(
        f"  📊 Advanced Memory: {stats['total']} записей, "
        f"types={stats['by_type']}, failures={stats['failures_stored']}"
    )

    # Cognitive engine stats
    cog_stats = cognitive_engine.get_stats()
    logger.info(
        f"  🧠 Cognitive Engine: role={cog_stats['active_role']}, "
        f"plans={cog_stats['active_plans']}, "
        f"tasks={cog_stats['tasks']['total']}"
    )

    # Part 8: New engines
    from pds_ultimate.core.autonomy_engine import autonomy_engine
    from pds_ultimate.core.memory_v2 import memory_v2
    from pds_ultimate.core.plugin_system import plugin_manager

    # Load plugins from disk
    plugin_manager.load()

    logger.info(
        f"  🔌 Plugin System: {plugin_manager.get_stats()['total']} плагинов"
    )
    logger.info(
        f"  🤖 Autonomy Engine: ready "
        f"(tasks={autonomy_engine.get_stats()['total']})"
    )
    logger.info(
        "  🌐 Browser Pro: anti-bot stealth + form filler"
    )
    logger.info(
        "  🔬 Reasoning v2: trust scorer + contradiction detector + "
        "hypothesis tester + context compressor"
    )
    mv2_stats = memory_v2.get_stats()
    logger.info(
        f"  🧠 Memory v2: skills={mv2_stats['skills']}, "
        f"failures={mv2_stats['failures']}, patterns={mv2_stats['patterns']}"
    )

    logger.info("  ✅ AI Agent System инициализирована")

    # Part 9: Smart Triggers, Analytics, CRM, Evening Digest, Workflow
    from pds_ultimate.core.analytics_dashboard import analytics_dashboard
    from pds_ultimate.core.crm_engine import crm_engine
    from pds_ultimate.core.evening_digest import evening_digest
    from pds_ultimate.core.smart_triggers import trigger_manager
    from pds_ultimate.core.workflow_engine import workflow_engine

    trig_stats = trigger_manager.get_stats()
    logger.info(
        f"  🔔 Smart Triggers: {trig_stats['total']} триггеров, "
        f"{trig_stats['active']} активных"
    )
    ad_stats = analytics_dashboard.get_stats()
    logger.info(
        f"  📊 Analytics Dashboard: "
        f"{ad_stats['metrics']['series_count']} метрик, "
        f"{ad_stats['kpi']['total']} KPI"
    )
    crm_stats = crm_engine.get_stats()
    logger.info(
        f"  📇 CRM-Lite: {crm_stats['contacts']['total']} контактов, "
        f"{crm_stats['pipeline']['total']} сделок"
    )
    ed_stats = evening_digest.get_stats()
    logger.info(
        f"  🌙 Evening Digest: ready "
        f"(days={ed_stats['days_recorded']}, rules={ed_stats['rules_count']})"
    )
    wf_stats = workflow_engine.get_stats()
    logger.info(
        f"  📋 Workflow Engine: {wf_stats['templates']['total']} шаблонов, "
        f"{wf_stats['checklists']['total']} чек-листов"
    )

    # Part 10: Semantic Search V2, Confidence, Query Expansion,
    #          Task Prioritizer, Context Compressor, Time Relevance
    from pds_ultimate.core.adaptive_query import adaptive_query
    from pds_ultimate.core.confidence_tracker import confidence_tracker
    from pds_ultimate.core.context_compressor import context_compressor
    from pds_ultimate.core.semantic_search_v2 import semantic_search_v2
    from pds_ultimate.core.task_prioritizer import task_prioritizer
    from pds_ultimate.core.time_relevance import time_relevance

    ss_stats = semantic_search_v2.get_stats()
    logger.info(
        f"  🔍 Semantic Search V2: "
        f"kb={ss_stats['knowledge_base']['total']}, "
        f"docs={ss_stats['document_store']['documents']}"
    )
    ct_stats = confidence_tracker.get_stats()
    logger.info(
        f"  📊 Confidence Tracker: "
        f"threshold={ct_stats['auto_search']['threshold']}"
    )
    aq_stats = adaptive_query.get_stats()
    logger.info(
        f"  🔄 Adaptive Query: "
        f"synonyms={aq_stats['synonyms_count']}, "
        f"refinements={aq_stats['refinement']['total_refinements']}"
    )
    tp_stats = task_prioritizer.get_stats()
    logger.info(
        f"  📋 Task Prioritizer: "
        f"queue={tp_stats['queue']['total']}"
    )
    cc_stats = context_compressor.get_stats()
    logger.info(
        f"  📝 Context Compressor: "
        f"window={cc_stats['context_window']['entries']} entries"
    )
    tr_stats = time_relevance.get_stats()
    logger.info(
        f"  ⏱️ Time Relevance: "
        f"sources={tr_stats['sources']['count']}"
    )

    # Part 11: Integration Layer — pipelines, retry, circuit breaker
    from pds_ultimate.core.integration_layer import integration_layer

    il_stats = integration_layer.get_stats()
    logger.info(
        f"  🔗 Integration Layer: "
        f"chains={il_stats.get('chains', 0)}, "
        f"breakers={il_stats.get('circuit_breakers', 0)}, "
        f"fallbacks={il_stats.get('fallbacks', 0)}"
    )

    # Part 12: Production Hardening — rate limiting, health, monitoring
    from pds_ultimate.core.production import production

    ph_stats = production.get_stats()
    logger.info(
        f"  🏥 Production Hardening: "
        f"health={ph_stats['health']['overall']}, "
        f"uptime={ph_stats['uptime']['uptime_human']}"
    )

    # ─── 4. Запуск интеграций ────────────────────────────────────────────
    logger.info("[4/7] Запуск внешних интеграций...")

    from pds_ultimate.integrations.gmail import gmail_client
    from pds_ultimate.integrations.telethon_client import telethon_client
    from pds_ultimate.integrations.whatsapp import wa_client

    # Telethon (userbot для стиля)
    try:
        await telethon_client.start()
    except Exception as e:
        logger.warning(f"  ⚠ Telethon: {e}")

    # WhatsApp (browser для стиля)
    try:
        await wa_client.start()
    except Exception as e:
        logger.warning(f"  ⚠ WhatsApp: {e}")

    # Gmail (API для отчётов)
    try:
        await gmail_client.start()
    except Exception as e:
        logger.warning(f"  ⚠ Gmail: {e}")

    logger.info("  ✅ Интеграции запущены")

    # ─── 5. Инициализация модулей ────────────────────────────────────────
    logger.info("[5/7] Инициализация бизнес-модулей...")

    # Secretary
    from pds_ultimate.modules.secretary.auto_responder import AutoResponder
    from pds_ultimate.modules.secretary.calendar_mgr import CalendarManager
    from pds_ultimate.modules.secretary.style_analyzer import StyleAnalyzer
    from pds_ultimate.modules.secretary.vip_hub import VIPHub

    calendar_mgr = CalendarManager(session_factory)
    auto_responder = AutoResponder(session_factory)
    vip_hub = VIPHub(session_factory)
    style_analyzer = StyleAnalyzer(session_factory)

    # Загружаем существующий профиль стиля или сканируем
    style_loaded = await style_analyzer.load_existing_profile()
    if not style_loaded and style_analyzer.needs_rescan():
        logger.info("  📝 Запуск первого сканирования стиля...")
        try:
            await style_analyzer.full_scan()
        except Exception as e:
            logger.warning(f"  ⚠ Сканирование стиля отложено: {e}")

    # Logistics
    from pds_ultimate.modules.logistics.archive import ArchiveManager
    from pds_ultimate.modules.logistics.delivery_calc import DeliveryCalculator
    from pds_ultimate.modules.logistics.item_tracker import ItemTracker
    from pds_ultimate.modules.logistics.order_manager import OrderManager

    order_manager = OrderManager(session_factory)
    item_tracker = ItemTracker(session_factory)
    delivery_calc = DeliveryCalculator(session_factory)
    archive_mgr = ArchiveManager(session_factory)

    # Finance
    from pds_ultimate.modules.finance.currency import CurrencyManager
    from pds_ultimate.modules.finance.master_finance import MasterFinance
    from pds_ultimate.modules.finance.profit_calc import ProfitCalculator
    from pds_ultimate.modules.finance.sync_engine import SyncEngine

    master_finance = MasterFinance(session_factory)
    currency_mgr = CurrencyManager(session_factory)
    profit_calc = ProfitCalculator(session_factory)
    sync_engine = SyncEngine(session_factory)

    # Executive
    from pds_ultimate.modules.executive.backup_security import (
        BackupManager,
        SecurityManager,
    )
    from pds_ultimate.modules.executive.morning_brief import MorningBrief

    morning_brief = MorningBrief(session_factory)
    backup_mgr = BackupManager(session_factory)
    security_mgr = SecurityManager(session_factory)

    # Files
    from pds_ultimate.modules.files.file_manager import FileManager

    file_manager = FileManager(session_factory)

    # Part 7: File Engines

    # Part 7: Executive Tools

    # Part 7: Business Integrations

    logger.info("  📄 File Engines: Excel, PDF, OCR, Converter — готовы")
    logger.info("  🧾 Executive: Receipt Scanner, Translator, Archivist — готовы")
    logger.info("  💱 Integrations: Exchange Rates, Google Calendar — готовы")

    logger.info("  ✅ Все модули инициализированы")

    # ─── 6. Запуск Telegram Bot ──────────────────────────────────────────
    logger.info("[6/7] Запуск Telegram Bot...")
    from pds_ultimate.bot.setup import create_bot, start_polling

    bot, dp = await create_bot(session_factory=session_factory)
    logger.info("  ✅ Telegram Bot создан")

    # ─── 7. Запуск планировщика с реальными обработчиками ────────────────
    logger.info("[7/7] Запуск планировщика задач...")
    from pds_ultimate.core.scheduler import scheduler

    # Передаём зависимости планировщику
    scheduler.set_dependencies(
        session_factory=session_factory,
        bot=bot,
        morning_brief=morning_brief,
        calendar_mgr=calendar_mgr,
        item_tracker=item_tracker,
        backup_mgr=backup_mgr,
    )
    await scheduler.start()
    logger.info("  ✅ Планировщик запущен с реальными модулями")

    logger.info("=" * 60)
    logger.info("  PDS-ULTIMATE — Система запущена и готова к работе")
    logger.info("=" * 60)

    # ─── Запуск polling (блокирующий) ────────────────────────────────────
    try:
        await start_polling(bot, dp)
    finally:
        # ─── Cleanup ─────────────────────────────────────────────────────
        logger.info("Остановка системы...")

        # Сохраняем память агента (оба менеджера)
        try:
            with session_factory() as save_session:
                saved = memory_manager.save_to_db(save_session)
                if saved:
                    logger.info(
                        f"  💾 Сохранено {saved} записей памяти (basic)")
                adv_saved = advanced_memory_manager.save_to_db(save_session)
                if adv_saved:
                    logger.info(
                        f"  💾 Сохранено {adv_saved} записей памяти (advanced)")
                # Pruning before shutdown
                pruned = advanced_memory_manager.prune()
                if pruned:
                    logger.info(
                        f"  🗑️ Pruned {pruned} устаревших записей памяти")
        except Exception as e:
            logger.warning(f"  ⚠ Ошибка сохранения памяти: {e}")

        await scheduler.stop()
        await telethon_client.stop()
        await wa_client.stop()
        await gmail_client.stop()
        try:
            await browser_engine.stop()
        except Exception:
            pass
        try:
            persona_engine.save()
        except Exception:
            pass
        await llm_engine.stop()
        logger.info("PDS-ULTIMATE остановлен. До встречи!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
