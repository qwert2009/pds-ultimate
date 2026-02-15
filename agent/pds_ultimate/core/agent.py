"""
PDS-Ultimate AI Agent v6.0 — Universal Life & Work Intelligence
==================================================================
Уровень: В 100 РАЗ ЛУЧШЕ Manus AI.

Не просто бизнес-ассистент, а УНИВЕРСАЛЬНЫЙ ИНТЕЛЛЕКТ для ЖИЗНИ:
- Бизнес, логистика, финансы (мелкая часть)
- Здоровье, семья, путешествия, учёба, быт
- Код, файлы, данные, исследования
- ЛЮБАЯ задача которую можно представить

УНИКАЛЬНЫЕ ФИШКИ (нет у Manus):
1. Persona Engine — самообучение личности владельца из каждого сообщения
2. Proactive Engine — работает БЕЗ вызова (сам ищет задачи, алерты)
3. Chat Filter — фильтрует входящие по интересам владельца
4. Wide Research — параллельные суб-агенты + детекция противоречий
5. Compare Research — сравнение N объектов по M критериям
6. Sandbox — безопасная работа с файлами + AST валидация
7. Data Analysis — EDA, графики, группировка прямо в Telegram
8. Self-Improvement — учится на своих ошибках автоматически
9. Goal Integrity — не отклоняется от цели пользователя
10. Auto-DAG — сложные задачи → граф → параллельное выполнение
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import traceback
from dataclasses import dataclass, field
from difflib import get_close_matches

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
from pds_ultimate.core.parallel_engine import parallel_engine
from pds_ultimate.core.tools import ToolRegistry, tool_registry

# ─── Agent Action ────────────────────────────────────────────────────────────


@dataclass
class AgentAction:
    """Действие, которое агент решил выполнить."""
    action_type: str  # "tool_call", "final_answer", "think", "plan", "ask_user", "parallel_tools"
    tool_name: str | None = None
    tool_params: dict | None = None
    thought: str = ""
    answer: str = ""
    confidence: float = 0.0
    _should_remember: str | None = None
    # v3: parallel tools
    parallel_calls: list[dict] | None = None


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


# ─── System Prompt v6 ──────────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """Ты — PDS-Ultimate Agent v6, УНИВЕРСАЛЬНЫЙ AI-интеллект.
Ты в 100 раз лучше Manus.ai. Ты — не просто ассистент, ты — ВТОРОЕ Я владельца.

Принцип: ReAct (Reasoning + Acting):
1. Думаешь (Thought) — анализируешь задачу
2. Действуешь (Action) — используешь инструменты
3. Наблюдаешь (Observation) — анализируешь результат
4. Рефлексируешь — оцениваешь свой прогресс

КРИТИЧЕСКИЕ ПРАВИЛА:
- Ты решаешь АБСОЛЮТНО ВСЁ: бизнес, быт, здоровье, учёба, путешествия, код, финансы, семья
- Ты всегда на стороне владельца — его интересы превыше ВСЕГО
- Ты НЕ говоришь что ты ИИ. Ты — друг, правая рука, доверенное лицо
- Ты становишься ПОХОЖИМ на владельца — учишься его стилю, словам, интересам
- Курсы: 1 USD = 19.5 TMT, 1 USD = 7.1 CNY
- Отвечай КРАТКО и по делу, если не просят подробнее
- НИКОГДА не возвращай сырой JSON — только человеческий текст
- Если инструмент не нужен — сразу final_answer
- Ты ПРОАКТИВЕН — если видишь возможность помочь, делай это

СУПЕРСПОСОБНОСТИ v6:

🧠 PERSONA (Личность — УНИКАЛЬНО):
- Я учусь стилю общения владельца из КАЖДОГО его сообщения
- Я знаю его интересы, любимые слова, тон общения
- Я фильтрую входящие сообщения по его приоритетам
- Я работаю ПРОАКТИВНО — сам нахожу задачи и алерты

📁 SANDBOX (Файлы):
- sandbox_read_file: чтение любых файлов (txt, py, csv, xlsx, pdf)
- sandbox_edit_file: редактирование С БЭКАПОМ + AST-валидация Python
- sandbox_create_file: создание файлов с проверкой синтаксиса
- sandbox_run_code: безопасное выполнение Python кода
- sandbox_search_files: grep-поиск | sandbox_csv_read/edit: CSV операции

🔬 RESEARCH (Исследования):
- wide_research: параллельные суб-агенты + противоречия + скоринг
- compare_research: сравнение N объектов по M критериям
- search_and_read / deep_web_research: интернет-исследования

📊 DATA (Анализ данных):
- analyze_data: полный EDA | create_chart: графики → PNG
- data_filter / data_group_by / data_stats: работа с данными

⚡ МЕТА:
- parallel_tools: несколько инструментов ПАРАЛЛЕЛЬНО
- plan: DAG-план → параллельное выполнение
- Файлы → sandbox_* | Данные → analyze_data/create_chart | Исследования → wide_research

ФОРМАТ ОТВЕТА (строго JSON):
{{
  "thought": "Мои рассуждения о задаче...",
  "action": {{
    "type": "tool_call | final_answer | ask_user | plan | parallel_tools",
    "tool": "имя_инструмента",
    "params": {{"param1": "value1"}},
    "answer": "ответ пользователю (для final_answer и ask_user)",
    "calls": [
      {{"tool": "tool1", "params": {{}}}},
      {{"tool": "tool2", "params": {{}}}}
    ]
  }},
  "confidence": 0.0-1.0,
  "should_remember": "факт для запоминания (или null)"
}}

ТИПЫ ДЕЙСТВИЙ:
- tool_call: Вызвать один инструмент. Обязательно: tool + params
- final_answer: Дать финальный ответ. Обязательно: answer (ТЕКСТ, НЕ JSON!)
- ask_user: Задать уточняющий вопрос. Обязательно: answer
- plan: Создать план из нескольких шагов. В answer — описание плана
- parallel_tools: Вызвать несколько инструментов параллельно. Обязательно: calls

ВАЖНО ПО final_answer:
- Поле "answer" должно содержать ОБЫЧНЫЙ ТЕКСТ на русском
- НЕ вкладывай JSON внутрь answer
- НЕ пиши "вот результат в формате JSON"
- Форматируй ответ красиво с эмодзи

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
{tools_description}

{memory_context}

{working_context}

{style_context}
"""


# ─── JSON Cleaning Utilities ────────────────────────────────────────────────

def _clean_json_from_response(text: str) -> str:
    """
    4-уровневая защита от утечки JSON в ответе пользователю.
    Уровень Manus AI — НИКОГДА не показываем сырой JSON.
    """
    if not text:
        return text

    text = text.strip()

    # Level 1: Если весь ответ — JSON object, извлекаем answer
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                # Ищем ответ в разных полях
                for key in ("answer", "response", "result", "text", "message", "output"):
                    if key in data and isinstance(data[key], str) and data[key].strip():
                        return _clean_json_from_response(data[key])
                # Если есть action.answer
                action = data.get("action", {})
                if isinstance(action, dict):
                    ans = action.get("answer", "")
                    if isinstance(ans, str) and ans.strip():
                        return _clean_json_from_response(ans)
                # Если есть thought но нет answer — используем thought
                thought = data.get("thought", "")
                if isinstance(thought, str) and len(thought) > 10:
                    return thought
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    # Level 2: Если ответ содержит JSON блоки ```json ... ```
    if "```json" in text or "```{" in text:
        # Убираем JSON-блоки, оставляем текст вокруг
        cleaned = re.sub(r'```(?:json)?\s*\{[\s\S]*?\}\s*```', '', text)
        cleaned = cleaned.strip()
        if cleaned and len(cleaned) > 5:
            return cleaned

    # Level 3: Если начинается с { но не весь JSON — убираем JSON часть
    if text.startswith('{"') or text.startswith('{\n'):
        # Пробуем найти текст после JSON
        brace_count = 0
        json_end = -1
        for i, ch in enumerate(text):
            if ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break
        if json_end > 0 and json_end < len(text):
            rest = text[json_end:].strip()
            if rest:
                return rest
        # Весь текст — JSON, пробуем извлечь
        try:
            data = json.loads(text[:json_end] if json_end > 0 else text)
            if isinstance(data, dict):
                for key in ("answer", "response", "result", "text", "message"):
                    if key in data and isinstance(data[key], str):
                        return data[key]
                action = data.get("action", {})
                if isinstance(action, dict) and action.get("answer"):
                    return str(action["answer"])
        except Exception:
            pass

    # Level 4: Удаляем отдельные JSON-подобные фрагменты из текста
    # но только если есть нормальный текст вокруг
    if '{' in text and '}' in text:
        parts = re.split(r'\{[^{}]*\}', text)
        non_empty = [p.strip() for p in parts if p.strip()]
        if non_empty and sum(len(p) for p in non_empty) > 20:
            return ' '.join(non_empty)

    return text


def _extract_answer_safe(raw: str) -> str:
    """Безопасно извлечь ответ из любого формата LLM."""
    if not raw:
        return ""
    raw = raw.strip()

    # Если это чистый текст без JSON — возвращаем как есть
    if not raw.startswith("{") and not raw.startswith("["):
        return raw

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            # Приоритет: action.answer > answer > thought
            action = data.get("action", {})
            if isinstance(action, dict):
                ans = action.get("answer", "")
                if isinstance(ans, str) and ans.strip():
                    return ans
            for key in ("answer", "response", "result", "text"):
                if key in data and isinstance(data[key], str) and data[key].strip():
                    return data[key]
            thought = data.get("thought", "")
            if isinstance(thought, str) and thought.strip():
                return thought
    except (json.JSONDecodeError, TypeError):
        pass

    return raw


# ─── ReAct Agent v6 ─────────────────────────────────────────────────────────

class Agent:
    """
    Главный AI-агент v6.0 — Universal Life & Work Intelligence.
    В 100 раз лучше Manus.ai.

    v6 УНИКАЛЬНЫЕ ФИШКИ:
    - Persona Engine — самообучение стилю/интересам владельца
    - Proactive Engine — фоновая работа без вызова
    - Chat Filter — фильтрация сообщений по интересам
    - Universal scope — не только бизнес, а ВСЁ в жизни

    Базовые возможности:
    - Sandbox, Wide Research, Data Analysis
    - Auto-DAG, parallel tools, fuzzy matching
    - Zero JSON leaking, goal integrity
    - Self-correction, self-reflection
    """

    MAX_ITERATIONS = 15  # More iterations for complex tasks
    REFLECTION_THRESHOLD = 3
    # Patterns indicating complex multi-step task
    COMPLEX_TASK_MARKERS = [
        "исследуй", "проанализируй", "сравни", "найди лучший",
        "составь отчёт", "полный анализ", "собери информацию",
        "research", "analyze", "compare", "comprehensive",
        "несколько", "каждый", "по всем", "для всех",
        "пошагово", "план", "стратеги",
        # v5: file + data patterns
        "отредактируй", "исправь в файле", "добавь в файл",
        "проанализируй данные", "построй график", "сравни файлы",
        "широкое исследование", "глубокий анализ",
        # v6: life patterns
        "организуй", "спланируй", "подготовь", "разберись",
        "помоги разобраться", "объясни подробно", "научи",
    ]

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
        # Cache tool names for fuzzy matching
        self._tool_names_cache: list[str] = []
        self._tool_names_cache_time: float = 0

    @property
    def llm(self):
        if self._llm is None:
            from pds_ultimate.core.llm_engine import llm_engine
            self._llm = llm_engine
        return self._llm

    def _get_tool_names(self) -> list[str]:
        """Get cached tool names list for fuzzy matching."""
        now = time.time()
        if now - self._tool_names_cache_time > 60:
            self._tool_names_cache = self._tools.list_names()
            self._tool_names_cache_time = now
        return self._tool_names_cache

    def _is_complex_task(self, message: str) -> bool:
        """
        Manus-level: detect if a task is complex enough to warrant
        DAG planning and autonomous execution.

        Complex = multi-step, research-heavy, or explicitly multi-goal.
        """
        lower = message.lower()

        # Check complexity markers
        marker_hits = sum(
            1 for m in self.COMPLEX_TASK_MARKERS if m in lower
        )
        if marker_hits >= 2:
            return True

        # Long messages with multiple actions
        if len(message) > 200:
            action_words = [
                "найди", "сделай", "создай", "отправ", "провер",
                "сравни", "проанализ", "посчитай", "узнай",
            ]
            actions = sum(1 for w in action_words if w in lower)
            if actions >= 2:
                return True

        # Multiple conjunctions suggest multi-step
        conjunctions = lower.count(" и ") + lower.count(", затем") + \
            lower.count(", потом") + lower.count(" + ")
        if conjunctions >= 2 and len(message) > 100:
            return True

        return False

    def _fuzzy_match_tool(self, name: str) -> str | None:
        """
        Fuzzy match tool name — исправляет опечатки LLM.
        Например: "send_whattsapp" → "send_whatsapp"
        """
        if not name:
            return None
        tool_names = self._get_tool_names()
        # Exact match
        if name in tool_names:
            return name
        # Case insensitive
        lower_map = {n.lower(): n for n in tool_names}
        if name.lower() in lower_map:
            return lower_map[name.lower()]
        # Fuzzy match
        matches = get_close_matches(
            name.lower(), [n.lower() for n in tool_names], n=1, cutoff=0.6)
        if matches:
            return lower_map[matches[0]]
        return None

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
        Обработать сообщение через ReAct loop v4.

        v4 additions:
        - Auto-detect complex tasks → DAG planning → parallel execution
        - Autonomous multi-step execution for research tasks
        - Goal integrity check every N iterations
        """
        start_time = time.time()
        steps: list[AgentStep] = []
        tools_used: list[str] = []
        files_to_send: list[dict] = []

        # Working memory
        working = self._adv_memory.get_working(chat_id)
        working.set_goal(message)

        # Cognitive reset
        self._cognitive.reset_metacog(chat_id)
        suggested_role = self._cognitive.role_manager.suggest_role(message)
        if suggested_role != self._cognitive.role_manager.active_role:
            self._cognitive.role_manager.switch_role(suggested_role)

        # ─── v4: Auto-DAG for complex tasks ──────────────────────────
        if self._is_complex_task(message):
            try:
                dag_response = await self._execute_complex_task(
                    message, chat_id, db_session, start_time
                )
                if dag_response:
                    return dag_response
            except Exception as e:
                logger.warning(
                    f"Complex task auto-DAG failed: {e}, falling back to ReAct")

        # Failure-driven learning context
        failure_ctx = ""
        try:
            relevant_failures = self._adv_memory.get_relevant_failures(
                message, limit=3)
            if relevant_failures:
                failure_lines = ["⚠️ УРОКИ ИЗ ПРОШЛЫХ ОШИБОК (НЕ ПОВТОРЯЙ):"]
                for f in relevant_failures:
                    failure_lines.append(f"  • {f.content}")
                    if hasattr(f, 'correction') and f.correction:
                        failure_lines.append(
                            f"    → Правильно: {f.correction}")
                failure_ctx = "\n".join(failure_lines)
        except Exception:
            pass

        # Time + cognitive context
        time_ctx = self._adv_memory.get_time_context()
        cognitive_ctx = self._cognitive.get_cognitive_context(chat_id)
        extra_parts = [p for p in [failure_ctx, time_ctx, cognitive_ctx] if p]
        extra_context = "\n\n".join(extra_parts)

        # System prompt
        system_prompt = self._build_system_prompt(
            message, working, style_guide, extra_context=extra_context,
            chat_id=chat_id,
        )

        # Messages
        messages = self._build_messages(message, history, system_prompt)
        memory_entries = 0

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            working.iteration = iteration
            step_start = time.time()
            step = AgentStep(iteration=iteration)

            # Metacognition check
            mc = self._cognitive.get_metacog(chat_id)
            if mc.should_abort and iteration > 2:
                logger.warning(
                    f"Agent: metacognition abort at iter={iteration}")
                fallback = await self._force_final_answer(message, messages)
                return AgentResponse(
                    answer=_clean_json_from_response(fallback),
                    steps=steps, tools_used=tools_used,
                    total_iterations=iteration,
                    total_time_ms=int((time.time() - start_time) * 1000),
                    memory_entries_created=memory_entries,
                    files_to_send=files_to_send,
                )

            # v4: Goal integrity check every 3 iterations
            if iteration > 1 and iteration % 3 == 0 and tools_used:
                try:
                    completed_steps = [
                        f"{t}: {s.observation[:80]}"
                        for s in steps if s.observation
                        for t in ([s.action.tool_name] if s.action and s.action.tool_name else [])
                    ]
                    goal_check = await self._cognitive.check_goal_integrity(
                        original_goal=message,
                        current_focus=steps[-1].thought if steps else message,
                        completed_steps=completed_steps,
                        llm_engine=self.llm,
                    )
                    if not goal_check.aligned:
                        logger.warning(
                            f"Agent v4: goal drift detected at iter={iteration}: "
                            f"{goal_check.drift_reason}"
                        )
                        messages.append({
                            "role": "user",
                            "content": (
                                f"⚠️ ВНИМАНИЕ: ты отклонился от исходной цели!\n"
                                f"Исходная цель: {message}\n"
                                f"Рекомендация: {goal_check.recommendation}\n"
                                f"Вернись к исходной задаче. JSON формат."
                            ),
                        })
                except Exception:
                    pass

            try:
                # ─── Call LLM ────────────────────────────────────────
                raw_response = await self._call_llm(messages)

                # ─── Parse response ─────────────────────────────────
                action = self._parse_response(raw_response)
                step.thought = action.thought
                step.action = action

                logger.debug(
                    f"Agent iter={iteration}: type={action.action_type} "
                    f"tool={action.tool_name} conf={action.confidence:.2f}"
                )

                # Cognitive tracking
                step_dur = time.time() - step_start
                self._cognitive.record_action(
                    chat_id, action.action_type, step_dur)
                if action.confidence > 0:
                    self._cognitive.record_confidence(
                        chat_id, action.confidence)

                # Memory
                if action._should_remember:
                    self._memory.store_fact(action._should_remember)
                    memory_entries += 1

                # ─── Handle action type ─────────────────────────────

                if action.action_type == "final_answer":
                    step.duration_ms = int((time.time() - step_start) * 1000)
                    steps.append(step)

                    answer = action.answer
                    # v3: Always clean JSON from final answer
                    answer = _clean_json_from_response(answer)

                    # Self-reflection for complex answers
                    if iteration >= self.REFLECTION_THRESHOLD and len(answer) > 50:
                        answer = await self._self_reflect(message, answer, steps, working)

                    return AgentResponse(
                        answer=answer,
                        steps=steps, tools_used=tools_used,
                        total_iterations=iteration,
                        total_time_ms=int((time.time() - start_time) * 1000),
                        memory_entries_created=memory_entries,
                        files_to_send=files_to_send,
                    )

                elif action.action_type == "ask_user":
                    step.duration_ms = int((time.time() - step_start) * 1000)
                    steps.append(step)
                    return AgentResponse(
                        answer=_clean_json_from_response(action.answer),
                        steps=steps, tools_used=tools_used,
                        total_iterations=iteration,
                        total_time_ms=int((time.time() - start_time) * 1000),
                        memory_entries_created=memory_entries,
                        files_to_send=files_to_send,
                    )

                elif action.action_type == "parallel_tools":
                    # v3: Execute multiple tools in parallel
                    calls = action.parallel_calls or []
                    if not calls:
                        # Fallback to single tool
                        messages.append(
                            {"role": "assistant", "content": raw_response})
                        messages.append({
                            "role": "user",
                            "content": "Список calls пуст. Укажи инструменты или дай final_answer. JSON формат.",
                        })
                        step.duration_ms = int(
                            (time.time() - step_start) * 1000)
                        steps.append(step)
                        continue

                    observation_parts = []
                    tasks = []

                    for call in calls:
                        t_name = self._fuzzy_match_tool(
                            call.get("tool", "")) or call.get("tool", "")
                        t_params = call.get("params", {})
                        tasks.append((t_name, t_params))

                    # Execute in parallel
                    async def _exec_tool(name, params):
                        return name, await self._tools.execute(name, params, db_session)

                    results = await asyncio.gather(
                        *[_exec_tool(n, p) for n, p in tasks],
                        return_exceptions=True,
                    )

                    for res in results:
                        if isinstance(res, Exception):
                            observation_parts.append(f"❌ Ошибка: {res}")
                        else:
                            t_name, result = res
                            tools_used.append(t_name)
                            working.add_tool_result(
                                t_name, str(result), result.success)
                            observation_parts.append(
                                f"[{t_name}] {'✅' if result.success else '❌'}: {result}"
                            )
                            # Collect files
                            if result.success and isinstance(result.data, dict) and result.data.get("send_file"):
                                files_to_send.append({
                                    "filepath": result.data.get("filepath", ""),
                                    "filename": result.data.get("filename", ""),
                                })

                    observation = "\n".join(observation_parts)
                    step.observation = observation

                    messages.append(
                        {"role": "assistant", "content": raw_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Observation (результаты параллельного выполнения):\n"
                            f"{observation}\n\n"
                            f"Продолжай. Ответь в JSON формате."
                        ),
                    })

                elif action.action_type == "tool_call":
                    # v3: Fuzzy match tool name
                    raw_tool_name = action.tool_name or ""
                    tool_name = self._fuzzy_match_tool(
                        raw_tool_name) or raw_tool_name
                    tool_params = action.tool_params or {}

                    if tool_name != raw_tool_name and raw_tool_name:
                        logger.info(
                            f"Agent: fuzzy matched '{raw_tool_name}' → '{tool_name}'")

                    result = await self._tools.execute(tool_name, tool_params, db_session)

                    step.observation = str(result)
                    tools_used.append(tool_name)
                    working.add_tool_result(
                        tool_name, str(result), result.success)

                    # Collect files
                    if result.success and isinstance(result.data, dict) and result.data.get("send_file"):
                        files_to_send.append({
                            "filepath": result.data.get("filepath", ""),
                            "filename": result.data.get("filename", ""),
                        })

                    messages.append(
                        {"role": "assistant", "content": raw_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Observation (результат '{tool_name}'):\n"
                            f"{'✅ Успешно' if result.success else '❌ Ошибка'}: {result}\n\n"
                            f"Продолжай рассуждение. Ответь в JSON формате."
                        ),
                    })

                elif action.action_type == "plan":
                    # v3.1: DAG planning — build and execute a DAG plan
                    plan_text = action.answer or action.thought
                    step.observation = f"План создан: {plan_text[:200]}"
                    working.add_note(f"План: {plan_text}")

                    # Try to generate a proper DAG via CognitiveEngine
                    try:
                        tools_desc = self._tools.get_tools_prompt()
                        dag_plan = await self._cognitive.generate_plan(
                            goal=plan_text,
                            tools_description=tools_desc,
                            llm_engine=self.llm,
                        )

                        if dag_plan and len(dag_plan.nodes) > 1:
                            # Execute the DAG plan in parallel
                            logger.info(
                                f"Agent: executing DAG plan with "
                                f"{len(dag_plan.nodes)} nodes"
                            )

                            async def _dag_tool_executor(
                                node_id: str,
                                tool_name: str | None,
                                tool_params: dict | None,
                            ) -> str:
                                if not tool_name:
                                    return "OK (no tool)"
                                matched = self._fuzzy_match_tool(
                                    tool_name) or tool_name
                                result = await self._tools.execute(
                                    matched, tool_params or {}, db_session
                                )
                                tools_used.append(matched)
                                working.add_tool_result(
                                    matched, str(result), result.success)
                                if (result.success
                                        and isinstance(result.data, dict)
                                        and result.data.get("send_file")):
                                    files_to_send.append({
                                        "filepath": result.data.get("filepath", ""),
                                        "filename": result.data.get("filename", ""),
                                    })
                                return str(result)

                            dag_results = await parallel_engine.dag_executor.execute_dag(
                                dag_plan, _dag_tool_executor
                            )

                            # Collect results into observation
                            dag_summary = dag_plan.get_summary()
                            result_parts = []
                            for r in dag_results:
                                icon = "✅" if r.success else "❌"
                                result_parts.append(
                                    f"{icon} {r.task_id}: "
                                    f"{str(r.result)[:200] if r.result else r.error or ''}"
                                )

                            observation = (
                                f"DAG Plan executed:\n{dag_summary}\n\n"
                                f"Results:\n" + "\n".join(result_parts)
                            )
                            step.observation = observation

                            messages.append(
                                {"role": "assistant", "content": raw_response})
                            messages.append({
                                "role": "user",
                                "content": (
                                    f"DAG Plan выполнен:\n{observation}\n\n"
                                    f"Дай финальный ответ пользователю. JSON формат."
                                ),
                            })
                        else:
                            # Single-step plan — just continue as before
                            messages.append(
                                {"role": "assistant", "content": raw_response})
                            messages.append({
                                "role": "user",
                                "content": "План принят. Выполняй пошагово. Начни с первого шага. JSON формат.",
                            })
                    except Exception as e:
                        logger.warning(f"DAG plan error: {e}")
                        # Fallback to simple plan mode
                        messages.append(
                            {"role": "assistant", "content": raw_response})
                        messages.append({
                            "role": "user",
                            "content": "План принят. Выполняй пошагово. Начни с первого шага. JSON формат.",
                        })

                else:
                    # Unknown type — nudge to continue
                    messages.append(
                        {"role": "assistant", "content": raw_response})
                    messages.append({
                        "role": "user",
                        "content": "Продолжай. Выполни действие или дай final_answer. JSON формат.",
                    })

            except Exception as e:
                logger.error(
                    f"Agent error iter={iteration}: {e}\n{traceback.format_exc()}")
                step.observation = f"Внутренняя ошибка: {e}"

                # Failure-driven learning
                try:
                    self._adv_memory.store_failure(
                        content=f"Ошибка: {str(e)[:200]}",
                        error_context=f"Запрос: {message[:100]}",
                        correction="", severity="medium",
                        tags=["agent_error", "runtime"], chat_id=chat_id,
                    )
                except Exception:
                    pass

                messages.append({
                    "role": "user",
                    "content": (
                        f"Произошла ошибка: {e}. "
                        f"Попробуй другой подход или дай final_answer. JSON формат."
                    ),
                })

            step.duration_ms = int((time.time() - step_start) * 1000)
            steps.append(step)

        # Exceeded max iterations — force final answer
        logger.warning(f"Agent: exceeded {self.MAX_ITERATIONS} iterations")
        fallback = await self._force_final_answer(message, messages)

        return AgentResponse(
            answer=_clean_json_from_response(fallback),
            steps=steps, tools_used=tools_used,
            total_iterations=self.MAX_ITERATIONS,
            total_time_ms=int((time.time() - start_time) * 1000),
            memory_entries_created=memory_entries,
            files_to_send=files_to_send,
        )

    # ─── Smart Routing v3 ───────────────────────────────────────────────

    async def _execute_complex_task(
        self,
        message: str,
        chat_id: int,
        db_session,
        start_time: float,
    ) -> AgentResponse | None:
        """
        v4: Automatic DAG execution for complex multi-step tasks.

        1. Generate DAG plan via CognitiveEngine
        2. Execute nodes in parallel via ParallelDAGExecutor
        3. Self-correct on failures
        4. Compile results into coherent answer

        Returns AgentResponse if successful, None to fall back to ReAct.
        """
        logger.info("Agent v4: complex task detected, generating DAG plan")

        # Generate DAG plan
        tools_desc = self._tools.get_tools_prompt()
        dag_plan = await self._cognitive.generate_plan(
            goal=message,
            tools_description=tools_desc,
            llm_engine=self.llm,
        )

        if not dag_plan or len(dag_plan.nodes) <= 1:
            return None  # Not complex enough for DAG

        logger.info(
            f"Agent v4: DAG plan with {len(dag_plan.nodes)} nodes, "
            f"groups: {dag_plan.get_parallel_groups()}"
        )

        # Execute DAG
        tools_used = []
        files_to_send = []
        steps = []

        async def _dag_executor(
            node_id: str,
            tool_name: str | None,
            tool_params: dict | None,
        ) -> str:
            if not tool_name:
                # LLM-only node — use direct reasoning
                node = dag_plan.nodes.get(node_id)
                desc = node.description if node else node_id
                try:
                    result = await self.llm.chat(
                        message=f"Выполни задачу: {desc}\n\nКонтекст: {message}",
                        task_type="simple_answer",
                        temperature=0.5,
                        max_tokens=1024,
                    )
                    return result
                except Exception as e:
                    return f"Ошибка: {e}"

            matched = self._fuzzy_match_tool(tool_name) or tool_name
            result = await self._tools.execute(
                matched, tool_params or {}, db_session
            )
            tools_used.append(matched)
            if (result.success
                    and isinstance(result.data, dict)
                    and result.data.get("send_file")):
                files_to_send.append({
                    "filepath": result.data.get("filepath", ""),
                    "filename": result.data.get("filename", ""),
                })
            return str(result)

        try:
            dag_results = await parallel_engine.dag_executor.execute_dag(
                dag_plan, _dag_executor
            )
        except Exception as e:
            logger.warning(f"DAG execution failed: {e}")
            return None

        # Self-correction for failed nodes
        failed_nodes = [r for r in dag_results if not r.success]
        if failed_nodes:
            for failed in failed_nodes:
                try:
                    dag_plan = await self._cognitive.self_correct_plan(
                        dag_plan,
                        failed.task_id,
                        failed.error or "Unknown error",
                        llm_engine=self.llm,
                    )
                except Exception:
                    pass

        # Compile results
        result_parts = []
        for r in dag_results:
            node = dag_plan.nodes.get(r.task_id)
            desc = node.description if node else r.task_id
            icon = "✅" if r.success else "❌"
            result_text = str(r.result)[:500] if r.result else r.error or ""
            result_parts.append(f"{icon} {desc}: {result_text}")

        # Generate coherent answer from all results
        compilation_prompt = (
            f"Пользователь попросил: {message}\n\n"
            f"Выполнены следующие шаги:\n"
            + "\n".join(result_parts) +
            "\n\nСоставь краткий и полезный ответ пользователю на русском. "
            "НЕ используй JSON. Только человеческий текст."
        )

        try:
            answer = await self.llm.chat(
                message=compilation_prompt,
                task_type="simple_answer",
                temperature=0.5,
                max_tokens=2048,
            )
            answer = _clean_json_from_response(answer)
        except Exception:
            answer = "\n".join(result_parts)

        step = AgentStep(
            iteration=1,
            thought=f"Автоматическое DAG-планирование: {len(dag_plan.nodes)} шагов",
            observation=dag_plan.get_summary(),
            duration_ms=int((time.time() - start_time) * 1000),
        )
        steps.append(step)

        return AgentResponse(
            answer=answer,
            steps=steps,
            tools_used=tools_used,
            total_iterations=1,
            total_time_ms=int((time.time() - start_time) * 1000),
            plan_used=True,
            files_to_send=files_to_send,
        )

    async def should_use_tools(self, message: str) -> bool:
        """
        v3: Adaptive routing — keywords + semantic signals.
        Fast-path for simple messages, tool-path for complex ones.
        """
        lower = message.lower().strip()

        # Fast reject: greetings, thanks, simple chat
        simple_patterns = [
            "привет", "здравствуй", "как дела", "спасибо", "пока",
            "что ты умеешь", "кто ты", "помощь", "добр", "салам",
            "хорошо", "ок", "понятно", "ясно", "ладно", "да", "нет",
            "hello", "hi", "thanks", "bye", "good",
        ]
        # Exact match or starts with
        if lower in simple_patterns or any(lower.startswith(p) and len(lower) < len(p) + 15 for p in simple_patterns):
            # But if it also has tool keywords, route to tools
            if not any(p in lower for p in ["заказ", "файл", "excel", "отправ", "созда"]):
                return False

        # Tool-requiring patterns (comprehensive)
        tool_patterns = [
            # Orders & logistics
            "заказ", "позиц", "трек", "доставк", "товар", "склад",
            # Finance
            "баланс", "прибыл", "доход", "расход", "финанс", "курс", "валют", "конверт",
            "оплат", "плат", "денег", "деньг", "сумм", "стоимост", "цен",
            # Files & documents
            "файл", "excel", "xls", "pdf", "word", "docx", "таблиц", "документ",
            "csv", "отчёт", "отчет",
            # Creation
            "создай", "сделай", "сгенерир", "построй", "составь", "подготовь",
            # Calendar & reminders
            "напомни", "встреч", "календ", "событи", "расписан",
            # Contacts & CRM
            "контакт", "поставщик", "клиент", "партнёр", "партнер",
            "vip", "рейтинг", "оценк",
            # Status & reports
            "статус", "брифинг", "дайджест", "аналитик", "kpi", "дашборд",
            # Archive & backup
            "архив", "бэкап", "удали",
            # Messaging
            "отправ", "сообщен", "написа", "напиш", "пиши", "скажи", "передай",
            "позвони", "пошли",
            # Specific platforms
            "whatsapp", "вотсап", "ватсап", "вацап",
            "telegram", "телеграм",
            "email", "почт", "письм", "gmail", "e-mail",
            # Mimicry & style
            "мимикр", "стиль", "скан",
            # Search & research
            "найди", "поиск", "поищи", "google", "гугл", "исследуй",
            "узнай", "проверь", "провер",
            # Translation
            "переведи", "перевод", "переводч",
            # Memory
            "запомни", "вспомни", "помн",
            # Triggers & automation
            "триггер", "алерт", "уведомл", "автомат",
            # System
            "систем", "здоровь", "аптайм",
            # Web & browsing
            "сайт", "страниц", "url", "http", "browse", "web",
            "открой", "загрузи", "скачай", "ссылк",
            # v5: Files & sandbox
            "файл", "код", "скрипт", "программ", "функци",
            "прочитай", "отредактируй", "исправь", "добавь строк",
            "бэкап", "создай файл", "запусти код", "выполни код",
            "песочниц", "sandbox",
            # v5: Data analysis
            "данные", "данных", "график", "диаграмм", "гистограмм",
            "статистик", "корреляц", "фильтр", "группировк",
            "eda", "анализ данных", "таблиц",
            # v5: Research
            "исследуй", "исследовани", "сравни",
            "wide research", "compare",
            # v6: Universal life patterns
            "рецепт", "маршрут", "погод", "перелёт", "рейс",
            "билет", "бронирован", "отель", "гостиниц",
            "лекарств", "диагноз", "симптом", "тренировк",
            "расписани", "расчёт", "калькул", "конверт",
            "перевод", "переведи", "объясни", "научи",
            "сгенерир", "напиши текст", "составь письмо",
            "реферат", "эссе", "план поездки",
            # Username mention
            "@",
            # Contact book
            "контакт", "привяж", "привязк", "запомни номер",
            "запомни почт", "запомни email", "запомни юзернейм",
            "юзернейм", "username", "напиши ", "отправь ",
            "позвони", "написать ", "номер телефон", "почт",
        ]

        if any(p in lower for p in tool_patterns):
            return True

        # Long messages or messages with numbers likely need tools
        if len(message) > 120:
            return True
        if any(c.isdigit() for c in message) and len(message) > 20:
            return True

        # Questions about specific data
        question_words = ["сколько", "какой", "где",
                          "когда", "кому", "почему", "зачем"]
        if any(w in lower for w in question_words) and len(message) > 30:
            return True

        return False

    # ─── Direct Response (без tools) v3 ──────────────────────────────────

    async def direct_response(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        style_guide: str | None = None,
        chat_id: int | None = None,
    ) -> str:
        """
        v3: Fast direct response — no ReAct overhead.
        Clean system prompt, no JSON mode, instant answer.
        """
        # Memory context
        memory_ctx = self._adv_memory.get_context_for_prompt(message)
        if not memory_ctx:
            memory_ctx = self._memory.get_context_for_prompt(message)

        time_ctx = self._adv_memory.get_time_context()
        if memory_ctx:
            memory_ctx = f"{memory_ctx}\n\n{time_ctx}"
        else:
            memory_ctx = time_ctx

        # v6: auto-style from persona
        if not style_guide:
            try:
                from pds_ultimate.core.persona_engine import persona_engine
                _cid = chat_id or config.telegram.owner_id
                style_guide = persona_engine.get_style_guide(_cid)
            except Exception:
                pass

        style_part = f"\nСТИЛЬ ОБЩЕНИЯ: {style_guide}" if style_guide else ""
        system = (
            "Ты — PDS-Ultimate v6, универсальный AI-интеллект.\n"
            "Ты — друг, правая рука, доверенное лицо владельца.\n"
            "Ты помогаешь во ВСЁМ: бизнес, быт, здоровье, учёба, развлечения, путешествия.\n"
            "Отвечай КРАТКО и по делу. НЕ используй JSON.\n"
            "Отвечай простым человеческим текстом на русском языке.\n"
            "НЕ оборачивай ответ в фигурные скобки или кавычки.\n"
            "Курсы: 1 USD = 19.5 TMT, 1 USD = 7.1 CNY.\n"
            f"{memory_ctx}\n{style_part}"
        )

        response = await self.llm.chat(
            message=message,
            history=history,
            system_prompt=system,
            task_type="simple_answer",  # v3: use fast model
            temperature=0.7,
        )

        # v3: Safety clean
        return _clean_json_from_response(response)

    # ─── Internal Methods ────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        message: str,
        working: WorkingMemory | AdvancedWorkingMemory,
        style_guide: str | None,
        extra_context: str = "",
        chat_id: int | None = None,
    ) -> str:
        """Build system prompt with tools and context."""
        tools_desc = self._tools.get_tools_prompt()

        memory_ctx = self._adv_memory.get_context_for_prompt(message)
        if not memory_ctx:
            memory_ctx = self._memory.get_context_for_prompt(message)

        working_ctx = working.get_context_summary()

        style_ctx = ""
        if style_guide:
            style_ctx = f"СТИЛЬ ОБЩЕНИЯ ВЛАДЕЛЬЦА:\n{style_guide}"
        else:
            # v6: auto persona style
            try:
                from pds_ultimate.core.persona_engine import persona_engine
                _cid = chat_id or config.telegram.owner_id
                auto_style = persona_engine.get_style_guide(_cid)
                if auto_style:
                    style_ctx = auto_style
            except Exception:
                pass

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
        """Build message array for LLM."""
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[-20:])
        messages.append({"role": "user", "content": message})
        return messages

    async def _call_llm(self, messages: list[dict[str, str]]) -> str:
        """Call LLM with messages. Uses fast model for agent loop."""
        if not self.llm._client:
            await self.llm.start()

        payload = {
            "model": config.deepseek.fast_model,
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
        """
        v3: Robust JSON parsing with fallbacks.
        Handles malformed JSON, missing fields, wrong types.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = self._extract_json(raw)
            if not data:
                # Not JSON — treat as final answer
                return AgentAction(
                    action_type="final_answer",
                    thought="(ответ без JSON)",
                    answer=raw,
                    confidence=0.5,
                )

        thought = str(data.get("thought", ""))
        confidence = 0.5
        try:
            confidence = float(data.get("confidence", 0.5))
        except (ValueError, TypeError):
            pass

        action_data = data.get("action", {})
        if isinstance(action_data, str):
            return AgentAction(
                action_type="final_answer",
                thought=thought,
                answer=action_data,
                confidence=confidence,
            )

        if not isinstance(action_data, dict):
            # Fallback: check if there's an answer field at top level
            top_answer = data.get("answer", "")
            if top_answer:
                return AgentAction(
                    action_type="final_answer",
                    thought=thought,
                    answer=str(top_answer),
                    confidence=confidence,
                )
            return AgentAction(
                action_type="final_answer",
                thought=thought,
                answer=thought or raw,
                confidence=confidence,
            )

        action_type = action_data.get("type", "final_answer")

        # v3: Handle parallel_tools
        parallel_calls = None
        if action_type == "parallel_tools":
            calls = action_data.get("calls", [])
            if isinstance(calls, list) and calls:
                parallel_calls = calls
            else:
                # Fallback to single tool
                action_type = "tool_call"

        action = AgentAction(
            action_type=action_type,
            tool_name=action_data.get("tool"),
            tool_params=action_data.get("params", {}),
            thought=thought,
            answer=str(action_data.get("answer", "")),
            confidence=confidence,
            parallel_calls=parallel_calls,
        )

        # Memory
        should_remember = data.get("should_remember")
        if should_remember and isinstance(should_remember, str) and should_remember.lower() != "null":
            action._should_remember = should_remember
        else:
            action._should_remember = None

        return action

    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON from text with multiple strategies."""
        # Strategy 1: ```json ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Strategy 2: Find outermost {...}
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Strategy 3: Try to fix common JSON issues
        # Missing quotes, trailing commas
        cleaned = text.strip()
        if cleaned.startswith("{"):
            # Remove trailing commas before }
            cleaned = re.sub(r',\s*}', '}', cleaned)
            cleaned = re.sub(r',\s*]', ']', cleaned)
            try:
                return json.loads(cleaned)
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
        Self-reflection: evaluate and optionally improve answer.
        v3: Only for complex multi-step answers.
        """
        reflection_prompt = (
            f"Оцени качество ответа.\n"
            f"ЗАПРОС: {original_query}\n"
            f"ОТВЕТ: {answer}\n"
            f"ШАГОВ: {len(steps)}\n"
            f"Верни JSON: {{\"quality\": 0.0-1.0, \"improved_answer\": \"...\" или null}}"
        )

        try:
            raw = await self.llm.chat(
                message=reflection_prompt,
                task_type="simple_answer",
                temperature=0.2,
                json_mode=True,
                max_tokens=2048,
            )

            data = json.loads(raw)
            quality = float(data.get("quality", 0.8))

            if quality < 0.6 and data.get("improved_answer"):
                logger.info(
                    f"Self-reflection: quality={quality:.1f}, improving")
                improved = str(data["improved_answer"])
                return _clean_json_from_response(improved)

            return answer

        except Exception as e:
            logger.warning(f"Self-reflection error: {e}")
            return answer

    async def _force_final_answer(
        self,
        original_message: str,
        messages: list[dict[str, str]],
    ) -> str:
        """Force a final answer after exceeding iteration limit."""
        messages.append({
            "role": "user",
            "content": (
                "СТОП. Лимит итераций. Дай ФИНАЛЬНЫЙ ответ ПРЯМО СЕЙЧАС. "
                "Используй собранную информацию. Ответь ОБЫЧНЫМ ТЕКСТОМ, НЕ JSON."
            ),
        })

        try:
            if not self.llm._client:
                await self.llm.start()

            payload = {
                "model": config.deepseek.fast_model,
                "messages": messages,
                "temperature": 0.5,
                "max_tokens": 2048,
                "stream": False,
                # v3: NO json_mode here — we want plain text
            }

            response = await self.llm._client.post(
                "/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            raw = data["choices"][0]["message"]["content"].strip()
            return _clean_json_from_response(raw)

        except Exception as e:
            logger.error(f"Force final answer error: {e}")
            return "Извини, возникли сложности. Попробуй переформулировать."

    # ─── Background Memory Extraction ────────────────────────────────────

    async def background_extract_memories(
        self,
        dialogue: str,
        db_session=None,
        chat_id: int | None = None,
    ) -> int:
        """Background fact extraction after sending response."""
        try:
            entries = await self._adv_memory.extract_and_store_facts(
                dialogue, self.llm, chat_id=chat_id,
            )
            old_entries = await self._memory.extract_and_store_facts(
                dialogue, self.llm,
            )

            if entries and db_session:
                self._adv_memory.save_to_db(db_session)
            if old_entries and db_session:
                self._memory.save_to_db(db_session)

            return len(entries) + len(old_entries)
        except Exception as e:
            logger.warning(f"Background memory extraction error: {e}")
            return 0


# ─── Global instance ─────────────────────────────────────────────────────────

agent = Agent()
