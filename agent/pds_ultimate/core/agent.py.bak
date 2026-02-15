"""
PDS-Ultimate AI Agent (ReAct Architecture)
=============================================
Ядро агентной системы — полный цикл рассуждения и действия.

Архитектура вдохновлена:
- ReAct (Reason + Act): Think → Action → Observation → Reflect
- Manus AI: автономный многошаговый агент
- MemGPT: долгосрочная память + self-reflection
- Maestro: оркестрация подзадач
- Phidata: tool use + knowledge + memory

Ключевые возможности:
1. ReAct Loop — думает, действует, наблюдает результат, рефлексирует
2. Planning — разбивает сложные задачи на подзадачи
3. Tool Use — формальный вызов инструментов через structured output
4. Self-Reflection — оценивает качество своих ответов
5. Memory Integration — подгружает релевантные воспоминания
6. Multi-step Execution — цепочки инструментов для сложных задач
7. Error Recovery — автоматическое исправление ошибок

Формат общения с LLM (DeepSeek):
- System Prompt описывает все tools + правила
- LLM отвечает в structured format (JSON)
- Агент парсит ответ и выполняет actions
- Результаты actions возвращаются в LLM для следующей итерации
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field

from pds_ultimate.config import config, logger
from pds_ultimate.core.advanced_memory import AdvancedWorkingMemory
from pds_ultimate.core.advanced_memory_manager import (
    AdvancedMemoryManager,
    advanced_memory_manager,
)
from pds_ultimate.core.cognitive_engine import (
    CognitiveEngine,
    cognitive_engine,
)
from pds_ultimate.core.memory import MemoryManager, WorkingMemory, memory_manager
from pds_ultimate.core.tools import ToolRegistry, tool_registry

# ─── Agent Action ────────────────────────────────────────────────────────────


@dataclass
class AgentAction:
    """Действие, которое агент решил выполнить."""
    action_type: str  # "tool_call", "final_answer", "think", "plan", "ask_user"
    tool_name: str | None = None
    tool_params: dict | None = None
    thought: str = ""
    answer: str = ""
    confidence: float = 0.0
    _should_remember: str | None = None


@dataclass
class AgentStep:
    """Один шаг ReAct loop."""
    iteration: int
    thought: str = ""
    action: AgentAction | None = None
    observation: str = ""
    reflection: str = ""
    duration_ms: int = 0


@dataclass
class AgentResponse:
    """Финальный ответ агента."""
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    total_iterations: int = 0
    total_time_ms: int = 0
    memory_entries_created: int = 0
    plan_used: bool = False
    files_to_send: list[dict] = field(default_factory=list)


# ─── System Prompt ──────────────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """Ты — PDS-Ultimate Agent, продвинутый AI-ассистент высшего класса.
Ты работаешь по принципу ReAct (Reasoning + Acting):
1. Думаешь (Thought) — анализируешь задачу
2. Действуешь (Action) — используешь инструменты
3. Наблюдаешь (Observation) — анализируешь результат
4. Рефлексируешь — оцениваешь свой прогресс

КРИТИЧЕСКИЕ ПРАВИЛА:
- Ты выполняешь АБСОЛЮТНО ЛЮБЫЕ задачи: бизнес, логистика, финансы, быт, тексты, код
- Ты всегда на стороне владельца — его интересы превыше всего
- Ты НЕ говоришь что ты ИИ. Ты — помощник, секретарь, правая рука
- Финансовая формула: ДОХОД - ТОВАР = ОСТАТОК - ДОСТАВКА = ЧИСТАЯ ПРИБЫЛЬ
- Курсы: 1 USD = 19.5 TMT, 1 USD = 7.1 CNY
- Отвечай КРАТКО и по делу, если не просят подробнее

ФОРМАТ ОТВЕТА (строго JSON):
{{
  "thought": "Мои рассуждения о задаче...",
  "action": {{
    "type": "tool_call | final_answer | ask_user | plan",
    "tool": "имя_инструмента",
    "params": {{"param1": "value1"}},
    "answer": "ответ пользователю (для final_answer и ask_user)"
  }},
  "confidence": 0.0-1.0,
  "should_remember": "факт для запоминания (или null)"
}}

ТИПЫ ДЕЙСТВИЙ:
- tool_call: Вызвать инструмент. Обязательно: tool + params
- final_answer: Дать финальный ответ. Обязательно: answer
- ask_user: Задать уточняющий вопрос. Обязательно: answer
- plan: Создать план из нескольких шагов. В answer — описание плана

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
{tools_description}

{memory_context}

{working_context}

{style_context}
"""


# ─── ReAct Agent ─────────────────────────────────────────────────────────────

class Agent:
    """
    Главный AI-агент системы.

    ReAct Loop:
    1. Получает сообщение пользователя
    2. Подгружает контекст (память, историю, инструменты)
    3. Формирует system prompt с tools
    4. LLM думает → выбирает action
    5. Если action = tool_call → выполняет tool → добавляет observation
    6. Если action = final_answer → возвращает ответ
    7. Self-reflection: оценивает качество (опционально)
    8. Memory extraction: извлекает факты для запоминания
    """

    MAX_ITERATIONS = 10  # Защита от бесконечных циклов
    REFLECTION_THRESHOLD = 3  # После скольких итераций включать рефлексию

    def __init__(
        self,
        tool_reg: ToolRegistry | None = None,
        mem_mgr: MemoryManager | None = None,
        adv_mem: AdvancedMemoryManager | None = None,
        cog_engine: CognitiveEngine | None = None,
    ):
        self._tools = tool_reg or tool_registry
        self._memory = mem_mgr or memory_manager
        self._adv_memory = adv_mem or advanced_memory_manager
        self._cognitive = cog_engine or cognitive_engine
        self._llm = None  # Lazy init

    @property
    def llm(self):
        if self._llm is None:
            from pds_ultimate.core.llm_engine import llm_engine
            self._llm = llm_engine
        return self._llm

    # ─── Main Entry Point ────────────────────────────────────────────────

    async def process(
        self,
        message: str,
        chat_id: int,
        history: list[dict[str, str]] | None = None,
        db_session=None,
        style_guide: str | None = None,
    ) -> AgentResponse:
        """
        Обработать сообщение пользователя через ReAct loop.

        Args:
            message: Текст сообщения
            chat_id: ID чата (для рабочей памяти)
            history: История разговора
            db_session: SQLAlchemy session
            style_guide: Стиль общения (для мимикрии)

        Returns:
            AgentResponse с ответом и метаданными
        """
        start_time = time.time()
        steps: list[AgentStep] = []
        tools_used: list[str] = []
        files_to_send: list[dict] = []

        # Используем advanced working memory (с goal integrity, hypotheses)
        working = self._adv_memory.get_working(chat_id)
        working.set_goal(message)

        # Cognitive engine: сбрасываем метакогницию для нового запроса
        self._cognitive.reset_metacog(chat_id)

        # Cognitive engine: определяем роль по типу задачи
        suggested_role = self._cognitive.role_manager.suggest_role(message)
        if suggested_role != self._cognitive.role_manager.active_role:
            self._cognitive.role_manager.switch_role(suggested_role)

        # Получаем контекст ошибок (failure-driven learning)
        failure_ctx = ""
        relevant_failures = self._adv_memory.get_relevant_failures(
            message, limit=3)
        if relevant_failures:
            failure_lines = ["⚠️ УРОКИ ИЗ ПРОШЛЫХ ОШИБОК (НЕ ПОВТОРЯЙ):"]
            for f in relevant_failures:
                failure_lines.append(f"  • {f.content}")
                if hasattr(f, 'correction') and f.correction:
                    failure_lines.append(f"    → Правильно: {f.correction}")
            failure_ctx = "\n".join(failure_lines)

        # Time awareness
        time_ctx = self._adv_memory.get_time_context()

        # Cognitive context (план, задачи, метакогниция)
        cognitive_ctx = self._cognitive.get_cognitive_context(chat_id)

        # Формируем extra_context
        extra_parts = [p for p in [failure_ctx, time_ctx, cognitive_ctx] if p]
        extra_context = "\n\n".join(extra_parts)

        # Формируем system prompt
        system_prompt = self._build_system_prompt(
            message, working, style_guide,
            extra_context=extra_context,
        )

        # Начальные сообщения для LLM
        messages = self._build_messages(message, history, system_prompt)

        memory_entries = 0

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            working.iteration = iteration
            step_start = time.time()

            step = AgentStep(iteration=iteration)

            # Metacognition: проверяем, не пора ли остановиться
            mc = self._cognitive.get_metacog(chat_id)
            if mc.should_abort and iteration > 2:
                logger.warning(
                    f"Agent: metacognition abort at iter={iteration} "
                    f"(stuck={mc.is_stuck}, time={mc.thinking_time_seconds:.1f}s)"
                )
                fallback = await self._force_final_answer(message, messages)
                return AgentResponse(
                    answer=fallback,
                    steps=steps,
                    tools_used=tools_used,
                    total_iterations=iteration,
                    total_time_ms=int((time.time() - start_time) * 1000),
                    memory_entries_created=memory_entries,
                )

            try:
                # ─── Вызов LLM ───────────────────────────────────────
                raw_response = await self._call_llm(messages)

                # ─── Парсинг ответа ──────────────────────────────────
                action = self._parse_response(raw_response)
                step.thought = action.thought
                step.action = action

                logger.debug(
                    f"Agent iter={iteration}: thought={action.thought[:100]}... "
                    f"action={action.action_type}"
                )

                # Cognitive engine: записываем действие и уверенность
                step_dur = time.time() - step_start
                self._cognitive.record_action(
                    chat_id, action.action_type, step_dur)
                if action.confidence > 0:
                    self._cognitive.record_confidence(
                        chat_id, action.confidence)

                # ─── Запоминание ─────────────────────────────────────
                if action._should_remember:
                    self._memory.store_fact(action._should_remember)
                    memory_entries += 1

                # ─── Обработка действия ──────────────────────────────

                if action.action_type == "final_answer":
                    step.duration_ms = int((time.time() - step_start) * 1000)
                    steps.append(step)

                    # Self-reflection для сложных ответов
                    answer = action.answer
                    if iteration >= self.REFLECTION_THRESHOLD:
                        answer = await self._self_reflect(
                            message, answer, steps, working
                        )

                    return AgentResponse(
                        answer=answer,
                        steps=steps,
                        tools_used=tools_used,
                        total_iterations=iteration,
                        total_time_ms=int((time.time() - start_time) * 1000),
                        memory_entries_created=memory_entries,
                        files_to_send=files_to_send,
                    )

                elif action.action_type == "ask_user":
                    step.duration_ms = int((time.time() - step_start) * 1000)
                    steps.append(step)

                    return AgentResponse(
                        answer=action.answer,
                        steps=steps,
                        tools_used=tools_used,
                        total_iterations=iteration,
                        total_time_ms=int((time.time() - start_time) * 1000),
                        memory_entries_created=memory_entries,
                        files_to_send=files_to_send,
                    )

                elif action.action_type == "tool_call":
                    # Выполняем инструмент
                    tool_name = action.tool_name or ""
                    tool_params = action.tool_params or {}

                    result = await self._tools.execute(
                        tool_name, tool_params, db_session
                    )

                    step.observation = str(result)
                    tools_used.append(tool_name)

                    working.add_tool_result(
                        tool_name, str(result), result.success
                    )

                    # Собираем файлы для отправки пользователю
                    if result.success and isinstance(result.data, dict) and result.data.get("send_file"):
                        files_to_send.append({
                            "filepath": result.data.get("filepath", ""),
                            "filename": result.data.get("filename", ""),
                        })

                    # Добавляем observation в messages для следующей итерации
                    messages.append({
                        "role": "assistant",
                        "content": raw_response,
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Observation (результат инструмента '{tool_name}'):\n"
                            f"{'Успешно' if result.success else 'Ошибка'}: {result}\n\n"
                            f"Продолжай рассуждение. Ответь в том же JSON формате."
                        ),
                    })

                elif action.action_type == "plan":
                    # Агент хочет разбить задачу на шаги
                    step.observation = "План создан"
                    working.add_note(f"План: {action.answer}")

                    messages.append({
                        "role": "assistant",
                        "content": raw_response,
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            "План принят. Теперь выполняй его пошагово. "
                            "Начни с первого шага. Ответь в JSON формате."
                        ),
                    })

                else:
                    # Неизвестный тип — think / другое
                    messages.append({
                        "role": "assistant",
                        "content": raw_response,
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            "Продолжай. Выполни действие или дай финальный ответ. "
                            "Ответь в JSON формате."
                        ),
                    })

            except Exception as e:
                logger.error(
                    f"Agent error iter={iteration}: {e}\n"
                    f"{traceback.format_exc()}"
                )
                step.observation = f"Внутренняя ошибка: {e}"

                # Failure-driven learning: записываем ошибку
                try:
                    self._adv_memory.store_failure(
                        content=f"Ошибка при обработке: {str(e)[:200]}",
                        error_context=f"Запрос: {message[:100]}",
                        correction="",
                        severity="medium",
                        tags=["agent_error", "runtime"],
                        chat_id=chat_id,
                    )
                except Exception:
                    pass  # Не блокируем основной поток

                # Пытаемся восстановиться
                messages.append({
                    "role": "user",
                    "content": (
                        f"Произошла ошибка: {e}. "
                        f"Попробуй другой подход или дай финальный ответ. "
                        f"Ответь в JSON формате."
                    ),
                })

            step.duration_ms = int((time.time() - step_start) * 1000)
            steps.append(step)

        # Превышен лимит итераций — даём fallback ответ
        logger.warning(
            f"Agent: превышен лимит итераций ({self.MAX_ITERATIONS})")

        # Просим LLM дать финальный ответ
        fallback = await self._force_final_answer(message, messages)

        return AgentResponse(
            answer=fallback,
            steps=steps,
            tools_used=tools_used,
            total_iterations=self.MAX_ITERATIONS,
            total_time_ms=int((time.time() - start_time) * 1000),
            memory_entries_created=memory_entries,
            files_to_send=files_to_send,
        )

    # ─── Smart Routing ──────────────────────────────────────────────────

    async def should_use_tools(self, message: str) -> bool:
        """
        Быстрая проверка: нужны ли инструменты для этого сообщения?

        Простые вопросы (привет, как дела, переведи) → прямой ответ LLM.
        Сложные задачи (заказы, финансы, файлы) → ReAct loop.
        """
        # Паттерны, не требующие инструментов
        simple_patterns = [
            "привет", "здравствуй", "как дела", "спасибо", "пока",
            "что ты умеешь", "кто ты", "помощь",
        ]
        lower = message.lower().strip()
        if any(p in lower for p in simple_patterns):
            return False

        # Паттерны, требующие инструментов
        tool_patterns = [
            "заказ", "позиц", "трек", "доставк", "товар",
            "баланс", "прибыл", "доход", "расход", "финанс",
            "файл", "excel", "pdf", "word", "таблиц", "документ", "создай",
            "напомни", "встреч", "календ",
            "контакт", "поставщик", "клиент",
            "vip", "статус", "отчёт", "брифинг",
            "архив", "бэкап", "удали",
            "переведи", "перевод",  # Может потребоваться tool
            "отправ", "сообщен", "написа", "позвони",  # Messaging
            "напиши", "пиши", "скажи", "передай",  # More messaging
            "whatsapp", "вотсап", "ватсап", "вацап",  # WhatsApp
            "telegram", "телеграм",  # Telegram
            "email", "почт", "письм", "gmail",  # Email
            "мимикр", "стиль", "скан",  # Style mimicry
            "найди", "поиск", "поищи", "google", "гугл",  # Search
            "курс", "валют", "конверт",  # Currency
            "@",  # Telegram username mention
        ]
        if any(p in lower for p in tool_patterns):
            return True

        # По умолчанию: если сообщение длинное или содержит числа — tools
        if len(message) > 100:
            return True
        if any(c.isdigit() for c in message):
            return True

        return False

    # ─── Direct Response (без tools) ─────────────────────────────────────

    async def direct_response(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        style_guide: str | None = None,
    ) -> str:
        """
        Прямой ответ LLM без ReAct loop.
        Для простых вопросов и разговоров.
        """
        # Подгружаем релевантную память (advanced first, then fallback)
        memory_ctx = self._adv_memory.get_context_for_prompt(message)
        if not memory_ctx:
            memory_ctx = self._memory.get_context_for_prompt(message)

        # Time awareness
        time_ctx = self._adv_memory.get_time_context()
        if memory_ctx:
            memory_ctx = f"{memory_ctx}\n\n{time_ctx}"
        else:
            memory_ctx = time_ctx

        # Для прямого ответа — простой промпт БЕЗ JSON-формата
        style_part = f"\nСТИЛЬ ОБЩЕНИЯ: {style_guide}" if style_guide else ""
        system = (
            "Ты — PDS-Ultimate, продвинутый AI-ассистент высшего класса.\n"
            "Ты — помощник, секретарь, правая рука владельца бизнеса.\n"
            "Отвечай КРАТКО и по делу. НЕ используй JSON.\n"
            "Отвечай простым человеческим текстом на русском языке.\n"
            "Курсы: 1 USD = 19.5 TMT, 1 USD = 7.1 CNY.\n"
            f"{memory_ctx}\n{style_part}"
        )

        # Для прямого ответа не нужен JSON mode
        response = await self.llm.chat(
            message=message,
            history=history,
            system_prompt=system,
            task_type="general",
            temperature=0.7,
        )

        return response

    # ─── Internal Methods ────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        message: str,
        working: WorkingMemory | AdvancedWorkingMemory,
        style_guide: str | None,
        extra_context: str = "",
    ) -> str:
        """Построить system prompt с инструментами и контекстом."""
        tools_desc = self._tools.get_tools_prompt()

        # Используем advanced memory для контекста (если доступна)
        memory_ctx = self._adv_memory.get_context_for_prompt(message)
        if not memory_ctx:
            memory_ctx = self._memory.get_context_for_prompt(message)

        working_ctx = working.get_context_summary()

        style_ctx = ""
        if style_guide:
            style_ctx = f"СТИЛЬ ОБЩЕНИЯ ВЛАДЕЛЬЦА:\n{style_guide}"

        # Добавляем extra_context (failures, time awareness)
        if extra_context:
            memory_ctx = f"{memory_ctx}\n\n{extra_context}" if memory_ctx else extra_context

        return AGENT_SYSTEM_PROMPT.format(
            tools_description=tools_desc or "[Нет зарегистрированных инструментов]",
            memory_context=memory_ctx,
            working_context=working_ctx,
            style_context=style_ctx,
        )

    def _build_messages(
        self,
        message: str,
        history: list[dict[str, str]] | None,
        system_prompt: str,
    ) -> list[dict[str, str]]:
        """Построить массив сообщений для LLM."""
        messages = [{"role": "system", "content": system_prompt}]

        if history:
            # Ограничиваем историю для контекстного окна
            messages.extend(history[-20:])

        messages.append({"role": "user", "content": message})
        return messages

    async def _call_llm(self, messages: list[dict[str, str]]) -> str:
        """Вызвать LLM с messages."""
        if not self.llm._client:
            await self.llm.start()

        payload = {
            "model": config.deepseek.fast_model,  # Используем быструю модель для агента
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2048,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

        try:
            response = await self.llm._client.post(
                "/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip()
        except Exception as e:
            logger.error(f"Agent LLM call error: {e}")
            raise

    def _parse_response(self, raw: str) -> AgentAction:
        """Распарсить JSON ответ LLM в AgentAction."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Пытаемся извлечь JSON
            data = self._extract_json(raw)
            if not data:
                # Если не JSON — считаем это финальным ответом
                return AgentAction(
                    action_type="final_answer",
                    thought="(ответ без JSON)",
                    answer=raw,
                    confidence=0.5,
                )

        thought = data.get("thought", "")
        confidence = float(data.get("confidence", 0.5))

        action_data = data.get("action", {})
        if isinstance(action_data, str):
            # LLM вернул action как строку
            return AgentAction(
                action_type="final_answer",
                thought=thought,
                answer=action_data,
                confidence=confidence,
            )

        action_type = action_data.get("type", "final_answer")

        action = AgentAction(
            action_type=action_type,
            tool_name=action_data.get("tool"),
            tool_params=action_data.get("params", {}),
            thought=thought,
            answer=action_data.get("answer", ""),
            confidence=confidence,
        )

        # Запоминание
        should_remember = data.get("should_remember")
        if should_remember and isinstance(should_remember, str):
            action._should_remember = should_remember
        else:
            action._should_remember = None

        return action

    def _extract_json(self, text: str) -> dict | None:
        """Извлечь JSON из текста."""
        import re

        # ```json ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # {...}
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    async def _self_reflect(
        self,
        original_query: str,
        answer: str,
        steps: list[AgentStep],
        working: WorkingMemory,
    ) -> str:
        """
        Self-reflection: оценить качество ответа.

        Если ответ плохой — пытается улучшить.
        Вдохновлено: PraisonAI self-reflection, Reflexion.
        """
        reflection_prompt = (
            f"Оцени качество следующего ответа на запрос пользователя.\n\n"
            f"ЗАПРОС: {original_query}\n\n"
            f"ОТВЕТ: {answer}\n\n"
            f"КОЛИЧЕСТВО ШАГОВ: {len(steps)}\n\n"
            f"Ответ полный? Точный? Есть ли ошибки?\n"
            f"Верни JSON: {{'quality': 0.0-1.0, 'issues': '...', "
            f"'improved_answer': '...' или null}}"
        )

        try:
            raw = await self.llm.chat(
                message=reflection_prompt,
                task_type="general",
                temperature=0.2,
                json_mode=True,
                max_tokens=2048,
            )

            data = json.loads(raw)
            quality = float(data.get("quality", 0.8))

            if quality < 0.6 and data.get("improved_answer"):
                logger.info(
                    f"Self-reflection: quality={quality:.1f}, "
                    f"улучшаю ответ"
                )
                return data["improved_answer"]

            return answer

        except Exception as e:
            logger.warning(f"Self-reflection error: {e}")
            return answer

    async def _force_final_answer(
        self,
        original_message: str,
        messages: list[dict[str, str]],
    ) -> str:
        """Принудительно получить финальный ответ после превышения лимита."""
        messages.append({
            "role": "user",
            "content": (
                "СТОП. Ты превысил лимит итераций. "
                "Дай ФИНАЛЬНЫЙ ответ на исходный запрос ПРЯМО СЕЙЧАС. "
                "Используй всю собранную информацию. "
                "Ответь обычным текстом, не JSON."
            ),
        })

        try:
            # Без JSON mode
            if not self.llm._client:
                await self.llm.start()

            payload = {
                "model": config.deepseek.fast_model,
                "messages": messages,
                "temperature": 0.5,
                "max_tokens": 2048,
                "stream": False,
            }

            response = await self.llm._client.post(
                "/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logger.error(f"Force final answer error: {e}")
            return "Извини, возникли сложности с обработкой запроса. Попробуй переформулировать."

    # ─── Background Memory Extraction ────────────────────────────────────

    async def background_extract_memories(
        self,
        dialogue: str,
        db_session=None,
        chat_id: int | None = None,
    ) -> int:
        """
        Фоновое извлечение фактов из диалога и сохранение в память.

        Вызывается ПОСЛЕ отправки ответа пользователю (не блокирует).
        Использует advanced memory manager для типизированных фактов.
        """
        try:
            # Advanced memory — типизированное извлечение фактов
            entries = await self._adv_memory.extract_and_store_facts(
                dialogue, self.llm, chat_id=chat_id,
            )

            # Также обновляем старую память для backward compat
            old_entries = await self._memory.extract_and_store_facts(
                dialogue, self.llm
            )

            if entries and db_session:
                self._adv_memory.save_to_db(db_session)

            if old_entries and db_session:
                self._memory.save_to_db(db_session)

            return len(entries) + len(old_entries)
        except Exception as e:
            logger.warning(f"Background memory extraction error: {e}")
            return 0


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

agent = Agent()
