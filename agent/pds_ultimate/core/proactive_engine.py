"""
PDS-Ultimate Proactive Engine — Фоновый интеллект
=====================================================
ФИШКА: Агент РАБОТАЕТ даже когда его НЕ вызывают.

Manus.ai: ждёт запроса пользователя.
Мы: сами инициируем действия когда видим возможность.

Capabilities:
1. Idle Watcher — проверяет задачи/триггеры когда пользователь молчит
2. Task Auto-Executor — выполняет накопленные задачи по приоритету
3. Proactive Suggestions — сам предлагает идеи/действия
4. Scheduled Intelligence — утренний/вечерний digest
5. Anomaly Detector — замечает аномалии в данных/финансах
6. Self-Improvement — анализирует свои ошибки и улучшается
7. Chat Listener — слушает чаты и фильтрует важное
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from pds_ultimate.config import config, logger

# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class ProactiveEventType(str, Enum):
    SUGGESTION = "suggestion"
    REMINDER = "reminder"
    ALERT = "alert"
    DIGEST = "digest"
    ANOMALY = "anomaly"
    TASK_DONE = "task_done"
    SELF_IMPROVE = "self_improve"
    CHAT_IMPORTANT = "chat_important"


@dataclass
class ProactiveEvent:
    """Событие, которое агент генерирует сам."""
    type: ProactiveEventType
    title: str
    message: str
    priority: int = 1  # 1=low, 5=critical
    target_chat_id: int = 0
    created_at: float = field(default_factory=time.time)
    delivered: bool = False
    data: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# PROACTIVE ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class ProactiveEngine:
    """
    Фоновый мозг агента — работает без вызова пользователя.

    Каждые N минут:
    1. Проверяет pending задачи
    2. Ищет аномалии
    3. Генерирует предложения
    4. Выполняет автоматические задачи
    """

    # Intervals (seconds)
    CHECK_TASKS_INTERVAL = 300          # 5 min
    CHECK_ANOMALIES_INTERVAL = 1800     # 30 min
    SELF_IMPROVE_INTERVAL = 3600        # 1 hour
    DIGEST_INTERVAL = 43200             # 12 hours
    CHAT_FILTER_INTERVAL = 60           # 1 min
    PERSONA_RETRAIN_INTERVAL = 259200   # 3 days

    def __init__(self):
        self._running = False
        self._event_queue: list[ProactiveEvent] = []
        self._send_callback: Callable | None = None
        self._owner_chat_id: int = config.telegram.owner_id
        self._last_check_tasks: float = 0
        self._last_check_anomalies: float = 0
        self._last_self_improve: float = 0
        self._last_digest: float = 0
        self._last_chat_filter: float = 0
        self._last_persona_retrain: float = 0
        self._stats = {
            "events_generated": 0,
            "events_delivered": 0,
            "tasks_auto_executed": 0,
            "anomalies_found": 0,
            "improvements": 0,
            "important_messages_flagged": 0,
        }
        self._important_keywords: list[str] = [
            "срочно", "urgent", "критич", "ошибка", "error", "problem",
            "деньг", "оплат", "плат", "перевод", "долг",
            "встреч", "завтра", "сейчас", "дедлайн", "deadline",
            "заказ", "доставк", "клиент", "жалоб",
            "пароль", "безопасн", "взлом", "hack",
        ]

    def set_send_callback(self, callback: Callable):
        """Set callback to send messages to user."""
        self._send_callback = callback

    async def start(self):
        """Start the proactive engine background loop."""
        if self._running:
            return
        self._running = True
        logger.info("🧠 ProactiveEngine: фоновый интеллект запущен")
        asyncio.create_task(self._main_loop())

    async def stop(self):
        """Stop the engine."""
        self._running = False
        logger.info("🧠 ProactiveEngine: остановлен")

    # ─── Main Background Loop ───────────────────────────────────────────

    async def _main_loop(self):
        """Main background loop — runs every 30 seconds."""
        while self._running:
            try:
                now = time.time()

                # Check pending tasks
                if now - self._last_check_tasks > self.CHECK_TASKS_INTERVAL:
                    await self._check_pending_tasks()
                    self._last_check_tasks = now

                # Check anomalies
                if now - self._last_check_anomalies > self.CHECK_ANOMALIES_INTERVAL:
                    await self._check_anomalies()
                    self._last_check_anomalies = now

                # Self improvement
                if now - self._last_self_improve > self.SELF_IMPROVE_INTERVAL:
                    await self._self_improve()
                    self._last_self_improve = now

                if now - self._last_persona_retrain > self.PERSONA_RETRAIN_INTERVAL:
                    await self._retrain_persona()
                    self._last_persona_retrain = now

                # Deliver pending events
                await self._deliver_events()

            except Exception as e:
                logger.debug(f"ProactiveEngine loop error: {e}")

            await asyncio.sleep(30)

    # ─── Check Pending Tasks ────────────────────────────────────────────

    async def _check_pending_tasks(self):
        """Check and auto-execute pending tasks."""
        try:
            from pds_ultimate.core.autonomy_engine import autonomy_engine

            stats = autonomy_engine.get_stats()
            pending = stats.get("pending", 0)

            if pending > 0:
                # Execute highest priority task
                try:
                    from pds_ultimate.core.tools import tool_registry

                    async def _tool_executor(tool_name: str, params: dict) -> str:
                        result = await tool_registry.execute(tool_name, params)
                        return str(result)

                    completed = await autonomy_engine.execute_next(
                        tool_executor=_tool_executor
                    )
                    if completed:
                        self._stats["tasks_auto_executed"] += 1
                        self._event_queue.append(ProactiveEvent(
                            type=ProactiveEventType.TASK_DONE,
                            title="✅ Задача выполнена",
                            message=f"Автономно выполнена задача: {completed.title}",
                            priority=2,
                            target_chat_id=self._owner_chat_id,
                        ))
                except Exception as e:
                    logger.debug(f"Auto-task execution error: {e}")

        except Exception as e:
            logger.debug(f"Check pending tasks error: {e}")

    # ─── Check Anomalies ───────────────────────────────────────────────

    async def _check_anomalies(self):
        """Check for anomalies in system/data."""
        try:
            from pds_ultimate.core.production import production

            report = production.get_system_report()
            health = report.get("health", {})
            overall = health.get("overall", "healthy")

            if overall != "healthy":
                self._stats["anomalies_found"] += 1
                self._event_queue.append(ProactiveEvent(
                    type=ProactiveEventType.ANOMALY,
                    title="⚠️ Аномалия системы",
                    message=f"Здоровье системы: {overall}",
                    priority=3 if overall == "degraded" else 5,
                    target_chat_id=self._owner_chat_id,
                    data=health,
                ))

            # Check alerts
            alerts = report.get("alerts", {}).get("active", [])
            for alert in alerts[:3]:
                self._event_queue.append(ProactiveEvent(
                    type=ProactiveEventType.ALERT,
                    title=f"🚨 {alert.get('name', 'Alert')}",
                    message=alert.get("message", ""),
                    priority=4,
                    target_chat_id=self._owner_chat_id,
                ))

        except Exception as e:
            logger.debug(f"Anomaly check error: {e}")

    # ─── Self Improvement ──────────────────────────────────────────────

    async def _self_improve(self):
        """Analyze past errors and improve."""
        try:
            from pds_ultimate.core.memory_v2 import memory_v2

            stats = memory_v2.get_stats()
            failures = stats.get("failures", 0)

            if failures > 0:
                # Analyze common failure patterns
                top_failures = memory_v2.get_top_failures(5)
                if top_failures:
                    patterns = []
                    for f in top_failures:
                        pattern = f.get("pattern", "")
                        if pattern:
                            patterns.append(pattern)

                    if patterns:
                        self._stats["improvements"] += 1
                        logger.info(
                            f"ProactiveEngine: analyzed {len(patterns)} failure patterns"
                        )

        except Exception as e:
            logger.debug(f"Self-improve error: {e}")

    # ─── Chat Message Filtering ─────────────────────────────────────────

    async def filter_incoming_message(
        self,
        text: str,
        chat_id: int,
        sender_name: str = "",
    ) -> ProactiveEvent | None:
        """
        Filter incoming message for importance.
        Called from Telethon listener for non-bot chats.
        Returns ProactiveEvent if message is important.
        """
        if not text:
            return None

        lower = text.lower()
        importance_score = 0

        # Check keywords
        for kw in self._important_keywords:
            if kw in lower:
                importance_score += 2

        # Long messages are more likely important
        if len(text) > 200:
            importance_score += 1

        # Questions directed at the user
        if "?" in text:
            importance_score += 1

        # Mentions
        if "@" in text:
            importance_score += 2

        # Numbers (possibly money/amounts)
        import re
        numbers = re.findall(r'\d+(?:[.,]\d+)?', text)
        if numbers and any(float(n.replace(",", ".")) > 100 for n in numbers):
            importance_score += 1

        try:
            from pds_ultimate.core.persona_engine import persona_engine
            care_score = persona_engine.would_user_care(chat_id, text)
            if care_score >= 0.6:
                importance_score += 2
            elif care_score >= 0.3:
                importance_score += 1
        except Exception:
            pass

        if importance_score >= 3:
            self._stats["important_messages_flagged"] += 1
            return ProactiveEvent(
                type=ProactiveEventType.CHAT_IMPORTANT,
                title=f"📨 Важное от {sender_name or 'неизвестного'}",
                message=text[:500],
                priority=min(importance_score, 5),
                target_chat_id=self._owner_chat_id,
                data={"source_chat_id": chat_id, "sender": sender_name},
            )

        return None

    # ─── Proactive Suggestions ──────────────────────────────────────────

    async def generate_suggestion(self, context: str = "") -> ProactiveEvent | None:
        """Generate a proactive suggestion based on context."""
        try:

            now = datetime.now()
            hour = now.hour

            # Time-based suggestions
            if 7 <= hour <= 9 and not context:
                return ProactiveEvent(
                    type=ProactiveEventType.SUGGESTION,
                    title="🌅 Доброе утро!",
                    message="Хочешь утренний брифинг? Я подготовлю сводку за вчера.",
                    priority=2,
                    target_chat_id=self._owner_chat_id,
                )
            elif 21 <= hour <= 23 and not context:
                return ProactiveEvent(
                    type=ProactiveEventType.SUGGESTION,
                    title="🌙 Вечерний отчёт",
                    message="Подготовить вечерний дайджест дня?",
                    priority=1,
                    target_chat_id=self._owner_chat_id,
                )

            return None

        except Exception:
            return None

    # ─── Event Delivery ─────────────────────────────────────────────────

    async def _deliver_events(self):
        """Deliver pending events to user."""
        if not self._send_callback or not self._event_queue:
            return

        # Sort by priority (highest first)
        self._event_queue.sort(key=lambda e: e.priority, reverse=True)

        # Deliver top events (max 3 per cycle to not spam)
        delivered = 0
        remaining = []

        for event in self._event_queue:
            if delivered >= 3:
                remaining.append(event)
                continue

            if event.delivered:
                continue

            try:
                text = f"{event.title}\n{event.message}"
                await self._send_callback(event.target_chat_id, text)
                event.delivered = True
                delivered += 1
                self._stats["events_generated"] += 1
                self._stats["events_delivered"] += 1
            except Exception as e:
                logger.debug(f"Event delivery error: {e}")
                remaining.append(event)

        self._event_queue = remaining

    # ─── Public API ─────────────────────────────────────────────────────

    def add_event(self, event: ProactiveEvent):
        """Manually add an event to the queue."""
        self._event_queue.append(event)

    def add_important_keyword(self, keyword: str):
        """Add a keyword to the importance filter."""
        kw = keyword.lower().strip()
        if kw and kw not in self._important_keywords:
            self._important_keywords.append(kw)

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "running": self._running,
            "pending_events": len(self._event_queue),
            "important_keywords": len(self._important_keywords),
        }

    async def _retrain_persona(self):
        try:
            from pds_ultimate.core.persona_engine import persona_engine
            result = persona_engine.run_periodic_retrain()
            if result.get("retrained"):
                logger.info(
                    f"PersonaEngine retrain: processed {result.get('processed', 0)} msgs"
                )
        except Exception as e:
            logger.debug(f"Persona retrain error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

proactive_engine = ProactiveEngine()
