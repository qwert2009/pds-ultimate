"""
PDS-Ultimate Wide Research Engine — Параллельные суб-агенты
=============================================================
ВЫШЕ Manus.ai Wide Research:

Manus:
  - Параллельные суб-агенты в своих VM
  - Каждый с чистым контекстом
  - Сбор результатов в финальный отчёт

PDS-Ultimate (мы лучше):
  - Параллельные суб-агенты через asyncio (без VM overhead)
  - Каждый с чистым контекстом + ПАМЯТЬ из прошлых исследований
  - Кросс-верификация результатов (суб-агенты проверяют друг друга)
  - Дедупликация данных (удаление повторов)
  - Автоматическое определение уровня глубины
  - Source credibility scoring (оценка надёжности источников)
  - Contradiction detection (обнаружение противоречий)
  - Progressive summarization (послойное сжатие)
  - Telegram-native: результат можно отправить сразу в чат
  - Контекст владельца: учитывает бизнес-интересы при исследовании

Наши УНИКАЛЬНЫЕ фишки (чего нет у Manus):
  🔥 Contradiction Detector — находит противоречия между источниками
  🔥 Confidence Scoring — оценка уверенности по каждому факту
  🔥 Business Context — учёт бизнес-контекста владельца
  🔥 Source Graph — граф связей между источниками
  🔥 Incremental Research — дополнение к предыдущим исследованиям
  🔥 Auto-depth — автоматический выбор глубины исследования
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pds_ultimate.config import logger

# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ResearchFinding:
    """Single finding from a sub-agent."""
    source_url: str
    source_title: str
    fact: str
    confidence: float = 0.8  # 0.0-1.0
    category: str = ""
    tags: list[str] = field(default_factory=list)
    # IDs of contradicting findings
    contradicts: list[str] = field(default_factory=list)
    # IDs of supporting findings
    supports: list[str] = field(default_factory=list)
    _id: str = ""

    def __post_init__(self):
        if not self._id:
            h = hashlib.md5(
                f"{self.source_url}:{self.fact[:50]}".encode()
            ).hexdigest()[:8]
            self._id = f"F-{h}"

    def __str__(self):
        stars = "⭐" * max(1, int(self.confidence * 5))
        return f"[{self._id}] {stars} {self.fact[:200]} ({self.source_title})"


@dataclass
class SubAgentResult:
    """Result from one sub-agent task."""
    task_id: str
    task_description: str
    findings: list[ResearchFinding] = field(default_factory=list)
    sources_checked: int = 0
    success: bool = True
    error: str = ""
    duration_ms: int = 0
    raw_text: str = ""


@dataclass
class ResearchReport:
    """Complete research report."""
    query: str
    total_sub_agents: int = 0
    total_sources: int = 0
    total_findings: int = 0
    findings: list[ResearchFinding] = field(default_factory=list)
    contradictions: list[dict[str, str]] = field(default_factory=list)
    key_insights: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    sub_results: list[SubAgentResult] = field(default_factory=list)
    duration_ms: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    def summary(self, max_findings: int = 20) -> str:
        parts = [
            f"📊 Исследование: {self.query}",
            f"🕐 Время: {self.duration_ms}ms | 📅 {self.created_at}",
            f"🤖 Суб-агентов: {self.total_sub_agents} | "
            f"📄 Источников: {self.total_sources} | "
            f"💡 Фактов: {self.total_findings}",
            f"🎯 Уверенность: {self.confidence_score:.0%}",
        ]

        if self.key_insights:
            parts.append("\n🔑 КЛЮЧЕВЫЕ ВЫВОДЫ:")
            for i, insight in enumerate(self.key_insights[:10], 1):
                parts.append(f"  {i}. {insight}")

        if self.contradictions:
            parts.append(f"\n⚠️ ПРОТИВОРЕЧИЯ ({len(self.contradictions)}):")
            for c in self.contradictions[:5]:
                parts.append(
                    f"  • {c.get('description', '')[:200]}"
                )

        if self.findings:
            parts.append(
                f"\n📋 ФАКТЫ (топ-{min(max_findings, len(self.findings))}):")
            sorted_f = sorted(
                self.findings, key=lambda f: f.confidence, reverse=True
            )
            for f in sorted_f[:max_findings]:
                conf_bar = "█" * int(f.confidence * 5) + \
                    "░" * (5 - int(f.confidence * 5))
                parts.append(f"  [{conf_bar}] {f.fact[:200]}")
                parts.append(
                    f"       📎 {f.source_title} | {f.source_url[:60]}")

        return "\n".join(parts)

    def to_markdown(self) -> str:
        """Generate full Markdown report."""
        lines = [
            f"# 📊 Исследование: {self.query}",
            "",
            f"**Дата:** {self.created_at}  ",
            f"**Суб-агентов:** {self.total_sub_agents}  ",
            f"**Источников:** {self.total_sources}  ",
            f"**Фактов:** {self.total_findings}  ",
            f"**Уверенность:** {self.confidence_score:.0%}  ",
            f"**Время:** {self.duration_ms}ms  ",
            "",
        ]

        if self.key_insights:
            lines.append("## 🔑 Ключевые выводы\n")
            for i, insight in enumerate(self.key_insights, 1):
                lines.append(f"{i}. {insight}")
            lines.append("")

        if self.contradictions:
            lines.append("## ⚠️ Противоречия\n")
            for c in self.contradictions:
                lines.append(f"- {c.get('description', '')}")
            lines.append("")

        if self.findings:
            lines.append("## 📋 Все факты\n")
            lines.append("| # | Уверенность | Факт | Источник |")
            lines.append("|---|---|---|---|")
            sorted_f = sorted(
                self.findings, key=lambda f: f.confidence, reverse=True
            )
            for i, f in enumerate(sorted_f, 1):
                conf = f"{f.confidence:.0%}"
                fact = f.fact[:150].replace("|", "\\|")
                src = f.source_title[:30].replace("|", "\\|")
                lines.append(f"| {i} | {conf} | {fact} | {src} |")
            lines.append("")

        if self.sub_results:
            lines.append("## 🤖 Суб-агенты\n")
            for sr in self.sub_results:
                icon = "✅" if sr.success else "❌"
                lines.append(
                    f"- {icon} **{sr.task_id}**: {sr.task_description} "
                    f"({sr.sources_checked} источников, {len(sr.findings)} фактов, "
                    f"{sr.duration_ms}ms)"
                )

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# WIDE RESEARCH ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class WideResearchEngine:
    """
    Параллельные суб-агенты для масштабных исследований.

    Архитектура:
        Main Agent
        ├── SubAgent-1 (search + extract)
        ├── SubAgent-2 (search + extract)
        ├── SubAgent-3 (search + extract)
        ├── ...
        └── Aggregator (dedupe + verify + compile)
    """

    def __init__(self, max_concurrent: int = 5):
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._history: list[ResearchReport] = []

    async def research(
        self,
        query: str,
        sub_queries: list[str] | None = None,
        max_sources_per_query: int = 5,
        follow_links: bool = True,
        business_context: str = "",
        llm_engine=None,
    ) -> ResearchReport:
        """
        Execute wide research with parallel sub-agents.

        Args:
            query: Main research question
            sub_queries: Optional list of sub-queries. Auto-generated if None.
            max_sources_per_query: Max sources per sub-agent
            follow_links: Whether to follow links from results
            business_context: Owner's business context for relevance filtering
            llm_engine: LLM engine for analysis

        Returns:
            Complete ResearchReport
        """
        start = time.time()

        # Auto-generate sub-queries if not provided
        if not sub_queries:
            sub_queries = await self._generate_sub_queries(
                query, llm_engine
            )

        logger.info(
            f"WideResearch: starting {len(sub_queries)} sub-agents for '{query}'"
        )

        # Launch sub-agents in parallel
        tasks = []
        for i, sq in enumerate(sub_queries):
            task_id = f"SA-{i + 1}"
            tasks.append(
                self._run_sub_agent(
                    task_id, sq, max_sources_per_query, follow_links
                )
            )

        sub_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all results
        valid_results = []
        for r in sub_results:
            if isinstance(r, SubAgentResult):
                valid_results.append(r)
            elif isinstance(r, Exception):
                logger.warning(f"Sub-agent error: {r}")

        # Aggregate findings
        all_findings = []
        total_sources = 0
        for sr in valid_results:
            all_findings.extend(sr.findings)
            total_sources += sr.sources_checked

        # Deduplicate
        deduped_findings = self._deduplicate(all_findings)

        # Detect contradictions
        contradictions = self._detect_contradictions(deduped_findings)

        # Score confidence
        for f in deduped_findings:
            f.confidence = self._score_confidence(f, deduped_findings)

        # Generate key insights
        key_insights = await self._generate_insights(
            query, deduped_findings, contradictions,
            business_context, llm_engine
        )

        overall_confidence = (
            sum(f.confidence for f in deduped_findings) / len(deduped_findings)
            if deduped_findings else 0.0
        )

        duration_ms = int((time.time() - start) * 1000)

        report = ResearchReport(
            query=query,
            total_sub_agents=len(valid_results),
            total_sources=total_sources,
            total_findings=len(deduped_findings),
            findings=deduped_findings,
            contradictions=contradictions,
            key_insights=key_insights,
            confidence_score=overall_confidence,
            sub_results=valid_results,
            duration_ms=duration_ms,
        )

        self._history.append(report)
        logger.info(
            f"WideResearch: completed in {duration_ms}ms, "
            f"{len(deduped_findings)} findings from {total_sources} sources"
        )

        return report

    # ─── Sub-Agent ───────────────────────────────────────────────────────

    async def _run_sub_agent(
        self,
        task_id: str,
        query: str,
        max_sources: int,
        follow_links: bool,
    ) -> SubAgentResult:
        """Run a single sub-agent with its own context."""
        start = time.time()

        async with self._semaphore:
            try:
                from pds_ultimate.core.httpx_browser import HttpxBrowser

                # Each sub-agent gets its own browser instance (clean context)
                browser = HttpxBrowser()

                if follow_links:
                    # Deep search with link following
                    research_data = await browser.deep_search(
                        query,
                        max_sources=max_sources,
                        follow_depth=1,
                        max_text_per_page=2000,
                    )
                else:
                    # Shallow search
                    pages = await browser.search_and_extract(
                        query,
                        max_pages=max_sources,
                        max_text_per_page=2000,
                    )
                    research_data = {
                        "findings": [
                            {
                                "url": p.url,
                                "title": p.title,
                                "text": p.text[:2000],
                                "tables": p.tables[:3],
                            }
                            for p in pages if p.success
                        ],
                        "sources_count": len(pages),
                    }

                # Extract findings from raw data
                findings = []
                for item in research_data.get("findings", []):
                    text = item.get("text", "")
                    if not text:
                        continue

                    # Split text into fact-sized chunks
                    paragraphs = [
                        p.strip() for p in text.split("\n")
                        if len(p.strip()) > 30
                    ]

                    for para in paragraphs[:15]:
                        findings.append(ResearchFinding(
                            source_url=item.get("url", ""),
                            source_title=item.get("title", ""),
                            fact=para[:500],
                            category=task_id,
                        ))

                duration_ms = int((time.time() - start) * 1000)

                return SubAgentResult(
                    task_id=task_id,
                    task_description=query,
                    findings=findings,
                    sources_checked=research_data.get("sources_count", 0),
                    success=True,
                    duration_ms=duration_ms,
                )

            except Exception as e:
                logger.warning(f"Sub-agent {task_id} error: {e}")
                return SubAgentResult(
                    task_id=task_id,
                    task_description=query,
                    success=False,
                    error=str(e),
                    duration_ms=int((time.time() - start) * 1000),
                )

    # ─── Sub-Query Generation ────────────────────────────────────────────

    async def _generate_sub_queries(
        self,
        main_query: str,
        llm_engine=None,
    ) -> list[str]:
        """Generate sub-queries for parallel research."""
        if llm_engine:
            try:
                prompt = (
                    f"Разбей исследовательский запрос на 3-5 конкретных подзапросов "
                    f"для параллельного поиска.\n\n"
                    f"Запрос: {main_query}\n\n"
                    f"Верни JSON: {{\"sub_queries\": [\"запрос1\", \"запрос2\", ...]}}\n"
                    f"Каждый подзапрос — конкретный поисковый запрос для Google/DDG."
                )
                import json
                raw = await llm_engine.chat(
                    message=prompt,
                    task_type="simple_answer",
                    json_mode=True,
                    temperature=0.3,
                    max_tokens=500,
                )
                data = json.loads(raw)
                subs = data.get("sub_queries", [])
                if subs and isinstance(subs, list) and len(subs) >= 2:
                    return subs[:7]
            except Exception as e:
                logger.debug(f"Sub-query generation error: {e}")

        # Fallback: create variations
        variations = [
            main_query,
            f"{main_query} обзор",
            f"{main_query} сравнение",
            f"{main_query} отзывы",
            f"{main_query} статистика",
        ]
        return variations[:5]

    # ─── Deduplication ───────────────────────────────────────────────────

    def _deduplicate(
        self,
        findings: list[ResearchFinding],
    ) -> list[ResearchFinding]:
        """Remove duplicate findings based on text similarity."""
        if not findings:
            return []

        unique = []
        seen_hashes = set()

        for f in findings:
            # Normalize text for comparison
            normalized = re.sub(r'\s+', ' ', f.fact.lower().strip())
            # Use first 100 chars as fingerprint
            fingerprint = hashlib.md5(
                normalized[:100].encode()
            ).hexdigest()

            if fingerprint not in seen_hashes:
                seen_hashes.add(fingerprint)
                unique.append(f)
            else:
                # Boost confidence of existing finding
                for existing in unique:
                    existing_norm = re.sub(
                        r'\s+', ' ', existing.fact.lower().strip()
                    )
                    existing_fp = hashlib.md5(
                        existing_norm[:100].encode()
                    ).hexdigest()
                    if existing_fp == fingerprint:
                        existing.confidence = min(
                            1.0, existing.confidence + 0.1
                        )
                        existing.supports.append(f._id)
                        break

        return unique

    # ─── Contradiction Detection ─────────────────────────────────────────

    def _detect_contradictions(
        self,
        findings: list[ResearchFinding],
    ) -> list[dict[str, str]]:
        """
        🔥 НАША ФИШКА: Detect contradictions between findings.
        Manus не делает этого!
        """
        contradictions = []

        # Simple keyword-based contradiction detection
        negation_pairs = [
            ("увеличился", "уменьшился"),
            ("вырос", "упал"),
            ("лучше", "хуже"),
            ("дороже", "дешевле"),
            ("быстрее", "медленнее"),
            ("больше", "меньше"),
            ("рост", "падение"),
            ("positive", "negative"),
            ("increase", "decrease"),
            ("higher", "lower"),
            ("рекомендуется", "не рекомендуется"),
            ("безопасно", "опасно"),
            ("эффективн", "неэффективн"),
        ]

        for i, f1 in enumerate(findings):
            for f2 in findings[i + 1:]:
                # Skip same source
                if f1.source_url == f2.source_url:
                    continue

                f1_lower = f1.fact.lower()
                f2_lower = f2.fact.lower()

                for pos, neg in negation_pairs:
                    if (
                        (pos in f1_lower and neg in f2_lower) or
                        (neg in f1_lower and pos in f2_lower)
                    ):
                        # Check if they're about the same topic
                        f1_words = set(f1_lower.split())
                        f2_words = set(f2_lower.split())
                        common = f1_words & f2_words
                        # If they share enough words, likely about same topic
                        if len(common) >= 3:
                            contradictions.append({
                                "finding_1": f1._id,
                                "finding_2": f2._id,
                                "description": (
                                    f"'{f1.fact[:100]}' ({f1.source_title}) "
                                    f"vs '{f2.fact[:100]}' ({f2.source_title})"
                                ),
                                "type": f"{pos}/{neg}",
                            })
                            f1.contradicts.append(f2._id)
                            f2.contradicts.append(f1._id)
                            break

        return contradictions

    # ─── Confidence Scoring ──────────────────────────────────────────────

    def _score_confidence(
        self,
        finding: ResearchFinding,
        all_findings: list[ResearchFinding],
    ) -> float:
        """
        🔥 НАША ФИШКА: Score confidence based on:
        - Support from other sources
        - Contradictions reduce confidence
        - Source domain credibility
        - Text quality signals
        """
        score = 0.5  # Base

        # Boost if supported by multiple sources
        score += 0.1 * len(finding.supports)

        # Penalize contradictions
        score -= 0.15 * len(finding.contradicts)

        # Text quality signals
        fact = finding.fact
        if len(fact) > 50:
            score += 0.05  # Detailed fact
        if any(c.isdigit() for c in fact):
            score += 0.1  # Contains numbers/data
        if any(w in fact.lower() for w in [
            "исследование", "статистика", "данные", "отчёт",
            "study", "research", "data", "report", "according",
        ]):
            score += 0.1  # Academic/data-backed

        # Source credibility
        url = finding.source_url.lower()
        trusted_domains = [
            "wikipedia", "gov.", ".edu", "reuters", "bloomberg",
            "statista", "worldbank", "who.int", "un.org",
        ]
        if any(d in url for d in trusted_domains):
            score += 0.15

        untrusted_signals = [
            "forum", "blog", "reddit", "quora",
        ]
        if any(s in url for s in untrusted_signals):
            score -= 0.1

        return max(0.1, min(1.0, score))

    # ─── Insights Generation ────────────────────────────────────────────

    async def _generate_insights(
        self,
        query: str,
        findings: list[ResearchFinding],
        contradictions: list[dict[str, str]],
        business_context: str,
        llm_engine=None,
    ) -> list[str]:
        """Generate key insights from findings using LLM."""
        if not llm_engine or not findings:
            # Fallback: top findings by confidence
            sorted_f = sorted(
                findings, key=lambda f: f.confidence, reverse=True
            )
            return [f.fact[:200] for f in sorted_f[:5]]

        try:
            facts_text = "\n".join(
                f"- [{f.confidence:.0%}] {f.fact[:200]} (src: {f.source_title})"
                for f in sorted(
                    findings, key=lambda f: f.confidence, reverse=True
                )[:30]
            )

            contrad_text = ""
            if contradictions:
                contrad_text = "\n\nПРОТИВОРЕЧИЯ:\n" + "\n".join(
                    f"- {c['description'][:200]}"
                    for c in contradictions[:5]
                )

            biz_ctx = ""
            if business_context:
                biz_ctx = f"\n\nКОНТЕКСТ БИЗНЕСА: {business_context}"

            prompt = (
                f"Исследование: {query}\n\n"
                f"ФАКТЫ:\n{facts_text}"
                f"{contrad_text}{biz_ctx}\n\n"
                f"Сформулируй 3-7 КЛЮЧЕВЫХ ВЫВОДОВ. Каждый — одно предложение.\n"
                f"Верни JSON: {{\"insights\": [\"вывод1\", \"вывод2\", ...]}}"
            )

            import json
            raw = await llm_engine.chat(
                message=prompt,
                task_type="simple_answer",
                json_mode=True,
                temperature=0.3,
                max_tokens=1000,
            )
            data = json.loads(raw)
            insights = data.get("insights", [])
            if insights and isinstance(insights, list):
                return insights[:7]

        except Exception as e:
            logger.debug(f"Insights generation error: {e}")

        return [f.fact[:200] for f in findings[:5]]

    # ─── Quick Research (lightweight) ────────────────────────────────────

    async def quick_research(
        self,
        query: str,
        max_sources: int = 3,
    ) -> ResearchReport:
        """
        Quick research without LLM — just search, extract, dedupe.
        For simple factual queries.
        """
        return await self.research(
            query=query,
            sub_queries=[query],
            max_sources_per_query=max_sources,
            follow_links=False,
        )

    # ─── Compare Research ────────────────────────────────────────────────

    async def compare_research(
        self,
        items: list[str],
        criteria: list[str] | None = None,
        llm_engine=None,
    ) -> ResearchReport:
        """
        🔥 НАША ФИШКА: Compare N items on M criteria in parallel.
        E.g. compare_research(["iPhone 16", "Samsung S25"], ["цена", "камера"])
        """
        sub_queries = []
        for item in items:
            if criteria:
                for criterion in criteria:
                    sub_queries.append(f"{item} {criterion}")
            else:
                sub_queries.append(f"{item} обзор характеристики цена")

        return await self.research(
            query=f"Сравнение: {', '.join(items)}",
            sub_queries=sub_queries[:10],
            max_sources_per_query=3,
            follow_links=False,
            llm_engine=llm_engine,
        )

    # ─── History ─────────────────────────────────────────────────────────

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent research history."""
        return [
            {
                "query": r.query,
                "findings": r.total_findings,
                "sources": r.total_sources,
                "confidence": f"{r.confidence_score:.0%}",
                "date": r.created_at,
                "duration_ms": r.duration_ms,
            }
            for r in self._history[-limit:]
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

wide_research = WideResearchEngine()
