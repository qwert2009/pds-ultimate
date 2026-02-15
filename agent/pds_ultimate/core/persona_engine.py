"""
PDS-Ultimate Persona Engine — Самообучение личности
========================================================
Агент учится стилю владельца и отдельно каждому пользователю.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pds_ultimate.config import config, logger

PERSONA_DIR = Path("/home/slavik/lessons.py.itea.2026/101/agent/data/persona")


@dataclass
class UserPersonaProfile:
    chat_id: int
    display_name: str = ""
    avg_message_length: float = 0.0
    uses_emoji: bool = True
    emoji_frequency: float = 0.0
    formality_level: float = 0.5
    humor_level: float = 0.3
    languages: list[str] = field(default_factory=lambda: ["ru"])
    preferred_language: str = "ru"
    favorite_words: list[tuple[str, int]] = field(default_factory=list)
    favorite_phrases: list[str] = field(default_factory=list)
    favorite_jokes: list[str] = field(default_factory=list)
    greeting_style: str = "привет"
    farewell_style: str = "пока"
    interests: dict[str, float] = field(default_factory=dict)
    topics_discussed: int = 0
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5
    messages_analyzed: int = 0
    last_updated: float = 0.0

    def to_style_guide(self, shared_context: dict[str, Any] | None = None) -> str:
        if self.messages_analyzed < 6:
            return ""

        name_part = f" ({self.display_name})" if self.display_name else ""
        parts = [f"СТИЛЬ ПОЛЬЗОВАТЕЛЯ{name_part}:"]

        if self.avg_message_length < 30:
            parts.append("- Пишет ОЧЕНЬ кратко. Максимум 1-2 предложения.")
        elif self.avg_message_length < 80:
            parts.append("- Пишет кратко, по делу.")
        else:
            parts.append("- Пишет развёрнуто, любит детали.")

        if self.emoji_frequency > 0.3:
            parts.append("- Часто использует эмодзи.")
        elif self.emoji_frequency < 0.05:
            parts.append("- Редко использует эмодзи.")

        if self.formality_level < 0.3:
            parts.append("- Общается неформально, как с другом.")
        elif self.formality_level > 0.7:
            parts.append("- Предпочитает формальный стиль.")

        if self.humor_level > 0.6:
            parts.append("- Любит юмор и шутки, допускается лёгкий сленг.")

        if self.favorite_words:
            top = [w for w, _ in self.favorite_words[:5]]
            parts.append(f"- Часто использует: {', '.join(top)}")

        if self.favorite_phrases:
            top_phrases = self.favorite_phrases[:4]
            parts.append(f"- Типичные фразы: {', '.join(top_phrases)}")

        if self.favorite_jokes:
            top_jokes = self.favorite_jokes[:3]
            parts.append(f"- Любимые шутки/мемы: {', '.join(top_jokes)}")

        if self.interests:
            top_interests = sorted(
                self.interests.items(), key=lambda x: x[1], reverse=True
            )[:5]
            topics = [t for t, _ in top_interests]
            parts.append(f"- Интересуется: {', '.join(topics)}")

        if len(self.languages) > 1:
            parts.append(f"- Говорит на: {', '.join(self.languages)}")

        if shared_context:
            shared_phrases = shared_context.get("shared_phrases", [])
            shared_jokes = shared_context.get("shared_jokes", [])
            if shared_phrases:
                parts.append(
                    f"- Общие фразы для группы: {', '.join(shared_phrases[:4])}"
                )
            if shared_jokes:
                parts.append(
                    f"- Общие шутки группы: {', '.join(shared_jokes[:3])}"
                )

        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "display_name": self.display_name,
            "avg_message_length": self.avg_message_length,
            "uses_emoji": self.uses_emoji,
            "emoji_frequency": round(self.emoji_frequency, 3),
            "formality_level": round(self.formality_level, 2),
            "humor_level": round(self.humor_level, 2),
            "languages": self.languages,
            "preferred_language": self.preferred_language,
            "favorite_words": self.favorite_words[:30],
            "favorite_phrases": self.favorite_phrases[:20],
            "favorite_jokes": self.favorite_jokes[:20],
            "greeting_style": self.greeting_style,
            "farewell_style": self.farewell_style,
            "interests": dict(
                sorted(self.interests.items(),
                       key=lambda x: x[1], reverse=True)[:20]
            ),
            "messages_analyzed": self.messages_analyzed,
            "openness": round(self.openness, 2),
            "conscientiousness": round(self.conscientiousness, 2),
            "extraversion": round(self.extraversion, 2),
            "agreeableness": round(self.agreeableness, 2),
            "neuroticism": round(self.neuroticism, 2),
            "last_updated": self.last_updated,
        }


class PersonaEngine:
    TOPIC_KEYWORDS: dict[str, list[str]] = {
        "бизнес": ["заказ", "доставк", "товар", "прибыл", "клиент", "сделк", "контракт"],
        "финансы": ["деньг", "курс", "доллар", "плат", "баланс", "долг", "кредит"],
        "технологии": ["код", "программ", "софт", "сервер", "api", "бот", "python"],
        "путешествия": ["отпуск", "рейс", "билет", "виза", "отель", "поездк"],
        "еда": ["ресторан", "кухн", "рецепт", "готов", "еда", "вкусн", "заказ еды"],
        "здоровье": ["врач", "больниц", "здоров", "спорт", "тренировк", "болит"],
        "семья": ["жена", "муж", "ребён", "мам", "пап", "сын", "дочь", "брат", "сестр"],
        "авто": ["машин", "авто", "бензин", "ремонт авто", "шин", "двигатель"],
        "учёба": ["учи", "курс", "книг", "образован", "универ", "лекци"],
        "развлечения": ["фильм", "сериал", "игр", "музык", "концерт", "netflix"],
    }

    INFORMAL_MARKERS = [
        "ок", "норм", "ахах", "лол", "хах", "ваще", "чё",
        "щас", "оч", "мб", "кста", "нзч", "имхо", "пж",
    ]
    FORMAL_MARKERS = [
        "пожалуйста", "будьте добры", "уважаемый", "прошу",
        "благодарю", "извините", "позвольте",
    ]
    HUMOR_MARKERS = [
        "ахах", "лол", "хаха", "ржу", ":)", ":-)", "😂", "🤣", "xD", "))", ")))",
    ]

    def __init__(self):
        PERSONA_DIR.mkdir(parents=True, exist_ok=True)
        self._profiles: dict[int, UserPersonaProfile] = {}
        self._word_counters: dict[int, Counter] = defaultdict(Counter)
        self._phrase_counters: dict[int, Counter] = defaultdict(Counter)
        self._joke_counters: dict[int, Counter] = defaultdict(Counter)
        self._session_factory = None
        self._shared_groups: list[dict[str, Any]] = []
        self._last_retrain_at: float = 0.0
        self._load()

    def set_session_factory(self, session_factory) -> None:
        self._session_factory = session_factory

    def _get_profile(self, chat_id: int, display_name: str = "") -> UserPersonaProfile:
        if chat_id not in self._profiles:
            self._profiles[chat_id] = UserPersonaProfile(chat_id=chat_id)
        profile = self._profiles[chat_id]
        if display_name and display_name != profile.display_name:
            profile.display_name = display_name
        return profile

    def _extract_tokens(self, text: str) -> list[str]:
        return re.findall(r"[а-яёa-z]+", text.lower())

    def _extract_phrases(self, tokens: list[str]) -> list[str]:
        phrases: list[str] = []
        if len(tokens) < 4:
            return phrases
        for size in (2, 3, 4, 5):
            for i in range(len(tokens) - size + 1):
                chunk = tokens[i:i + size]
                if all(len(w) > 1 for w in chunk):
                    phrases.append(" ".join(chunk))
        return phrases

    def learn_from_message(
        self,
        chat_id: int,
        text: str,
        is_owner: bool = False,
        display_name: str = "",
    ) -> None:
        if not text:
            return

        text = text.strip()
        if len(text) < 2:
            return

        profile = self._get_profile(chat_id, display_name)
        profile.messages_analyzed += 1
        profile.last_updated = time.time()

        profile.avg_message_length = (
            (profile.avg_message_length * (profile.messages_analyzed - 1))
            + len(text)
        ) / max(profile.messages_analyzed, 1)

        emoji_pattern = re.compile(
            r"[\U0001F300-\U0001F9FF\U00002702-\U000027B0"
            r"\U000024C2-\U0001F251\U0001FA00-\U0001FA6F"
            r"\U0001FA70-\U0001FAFF]+",
            flags=re.UNICODE,
        )
        has_emoji = bool(emoji_pattern.search(text))
        if has_emoji:
            profile.emoji_frequency = (
                (profile.emoji_frequency * (profile.messages_analyzed - 1)) + 1
            ) / max(profile.messages_analyzed, 1)
        else:
            profile.emoji_frequency = (
                profile.emoji_frequency * (profile.messages_analyzed - 1)
            ) / max(profile.messages_analyzed, 1)
        profile.uses_emoji = profile.emoji_frequency > 0.1

        lower = text.lower()
        informal_hits = sum(1 for m in self.INFORMAL_MARKERS if m in lower)
        formal_hits = sum(1 for m in self.FORMAL_MARKERS if m in lower)
        if informal_hits > formal_hits:
            profile.formality_level = max(0, profile.formality_level - 0.02)
        elif formal_hits > informal_hits:
            profile.formality_level = min(1, profile.formality_level + 0.02)

        humor_hits = sum(1 for m in self.HUMOR_MARKERS if m in lower)
        if humor_hits:
            profile.humor_level = min(1, profile.humor_level + 0.03)
        else:
            profile.humor_level = max(0, profile.humor_level - 0.005)

        tokens = self._extract_tokens(text)
        stopwords = {
            "и", "в", "на", "с", "по", "не", "что", "это", "как",
            "а", "но", "да", "же", "ты", "я", "мы", "он", "она",
            "они", "мне", "его", "её", "от", "до", "за", "из",
            "бы", "ли", "так", "то", "вот", "для", "уже", "ещё",
            "все", "всё", "тут", "там", "тоже", "или", "если",
            "the", "is", "a", "an", "to", "of", "in", "and", "it",
        }
        meaningful = [w for w in tokens if len(w) > 2 and w not in stopwords]
        self._word_counters[chat_id].update(meaningful)
        profile.favorite_words = self._word_counters[chat_id].most_common(30)

        phrases = self._extract_phrases(tokens)
        if phrases:
            self._phrase_counters[chat_id].update(phrases)
            profile.favorite_phrases = [
                p for p, _ in self._phrase_counters[chat_id].most_common(20)]

        if humor_hits and len(text) <= 140:
            self._joke_counters[chat_id].update([text])
            profile.favorite_jokes = [
                j for j, _ in self._joke_counters[chat_id].most_common(20)
            ]

        for topic, keywords in self.TOPIC_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in lower)
            if hits > 0:
                current = profile.interests.get(topic, 0)
                profile.interests[topic] = current + hits * 0.1

        cyrillic = len(re.findall(r"[а-яё]", lower))
        latin = len(re.findall(r"[a-z]", lower))
        if latin > cyrillic * 2 and "en" not in profile.languages:
            profile.languages.append("en")
        if cyrillic > latin * 2:
            profile.preferred_language = "ru"
        elif latin > cyrillic * 2:
            profile.preferred_language = "en"

        greetings = ["привет", "салам", "здравствуй", "hello", "hi", "йо"]
        for g in greetings:
            if lower.startswith(g):
                profile.greeting_style = g
                break

        if "!" in text:
            profile.extraversion = min(1, profile.extraversion + 0.005)
        if "?" in text:
            profile.openness = min(1, profile.openness + 0.005)
        if "спасибо" in lower or "пожалуйста" in lower:
            profile.agreeableness = min(1, profile.agreeableness + 0.01)

        if is_owner:
            self._profiles[chat_id] = profile

    def would_user_care(self, chat_id: int, text: str) -> float:
        if not text:
            return 0.0
        profile = self._get_profile(chat_id)
        lower = text.lower()
        score = 0.0

        for topic, weight in profile.interests.items():
            keywords = self.TOPIC_KEYWORDS.get(topic, [])
            for kw in keywords:
                if kw in lower:
                    score += weight * 0.3

        owner_words = {w for w, _ in profile.favorite_words[:20]}
        words_in_msg = set(re.findall(r"[а-яёa-z]+", lower))
        overlap = words_in_msg & owner_words
        score += len(overlap) * 0.1

        if "?" in text:
            score += 0.2
        if re.search(r"\d{3,}", text):
            score += 0.15

        return min(score, 1.0)

    def _similarity(self, a: UserPersonaProfile, b: UserPersonaProfile) -> float:
        words_a = {w for w, _ in a.favorite_words[:20]}
        words_b = {w for w, _ in b.favorite_words[:20]}
        phrases_a = set(a.favorite_phrases[:15])
        phrases_b = set(b.favorite_phrases[:15])
        topics_a = set(
            sorted(a.interests, key=a.interests.get, reverse=True)[:6])
        topics_b = set(
            sorted(b.interests, key=b.interests.get, reverse=True)[:6])

        def jaccard(x: set, y: set) -> float:
            if not x and not y:
                return 0.0
            return len(x & y) / max(len(x | y), 1)

        word_sim = jaccard(words_a, words_b)
        phrase_sim = jaccard(phrases_a, phrases_b)
        topic_sim = jaccard(topics_a, topics_b)
        return 0.4 * word_sim + 0.35 * phrase_sim + 0.25 * topic_sim

    def rebuild_shared_groups(self) -> None:
        profiles = list(self._profiles.values())
        if len(profiles) < 2:
            self._shared_groups = []
            return

        parent = {p.chat_id: p.chat_id for p in profiles}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        for i in range(len(profiles)):
            for j in range(i + 1, len(profiles)):
                sim = self._similarity(profiles[i], profiles[j])
                if sim >= 0.35:
                    union(profiles[i].chat_id, profiles[j].chat_id)

        groups: dict[int, list[UserPersonaProfile]] = defaultdict(list)
        for p in profiles:
            groups[find(p.chat_id)].append(p)

        shared_groups: list[dict[str, Any]] = []
        for members in groups.values():
            if len(members) < 2:
                continue
            shared_phrases = set(members[0].favorite_phrases[:20])
            shared_jokes = set(members[0].favorite_jokes[:15])
            shared_topics = set(members[0].interests.keys())
            for m in members[1:]:
                shared_phrases &= set(m.favorite_phrases[:20])
                shared_jokes &= set(m.favorite_jokes[:15])
                shared_topics &= set(m.interests.keys())
            shared_groups.append({
                "members": [m.chat_id for m in members],
                "shared_phrases": list(shared_phrases)[:10],
                "shared_jokes": list(shared_jokes)[:10],
                "shared_topics": list(shared_topics)[:10],
            })

        self._shared_groups = shared_groups

    def get_shared_context(self, chat_id: int) -> dict[str, Any] | None:
        for group in self._shared_groups:
            if chat_id in group.get("members", []):
                return group
        return None

    def get_style_guide(self, chat_id: int) -> str:
        profile = self._get_profile(chat_id)
        shared = self.get_shared_context(chat_id)
        return profile.to_style_guide(shared_context=shared)

    def run_periodic_retrain(self, days: int = 3, max_messages: int = 1500) -> dict[str, Any]:
        now = time.time()
        if not self._session_factory:
            return {"retrained": False, "reason": "no_session_factory"}

        if now - self._last_retrain_at < days * 86400:
            return {"retrained": False, "reason": "interval_not_reached"}

        since_ts = self._last_retrain_at or (now - days * 86400)
        since_dt = datetime.fromtimestamp(since_ts)
        processed = 0

        try:
            from pds_ultimate.core.database import ConversationHistory

            with self._session_factory() as session:
                rows = (
                    session.query(ConversationHistory)
                    .filter(ConversationHistory.role == "user")
                    .filter(ConversationHistory.created_at >= since_dt)
                    .order_by(ConversationHistory.created_at.asc())
                    .limit(max_messages)
                    .all()
                )

                for row in rows:
                    is_owner = row.chat_id == config.telegram.owner_id
                    self.learn_from_message(
                        chat_id=row.chat_id,
                        text=row.content,
                        is_owner=is_owner,
                    )
                    processed += 1

            self.rebuild_shared_groups()
            self._last_retrain_at = now
            self._save()
            return {"retrained": True, "processed": processed}
        except Exception as e:
            logger.debug(f"Persona retrain error: {e}")
            return {"retrained": False, "reason": str(e)}

    def _save(self) -> None:
        try:
            data = {
                "users": {str(cid): p.to_dict() for cid, p in self._profiles.items()},
                "word_counters": {
                    str(cid): dict(cnt.most_common(200)) for cid, cnt in self._word_counters.items()
                },
                "phrase_counters": {
                    str(cid): dict(cnt.most_common(120)) for cid, cnt in self._phrase_counters.items()
                },
                "joke_counters": {
                    str(cid): dict(cnt.most_common(80)) for cid, cnt in self._joke_counters.items()
                },
                "shared_groups": self._shared_groups,
                "last_retrain_at": self._last_retrain_at,
            }
            path = PERSONA_DIR / "persona.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.debug(f"Persona save error: {e}")

    def _load(self) -> None:
        try:
            path = PERSONA_DIR / "persona.json"
            if not path.exists():
                return

            data = json.loads(path.read_text(encoding="utf-8"))
            users = data.get("users", {})
            for cid_str, pdata in users.items():
                cid = int(cid_str)
                profile = UserPersonaProfile(chat_id=cid)
                profile.display_name = pdata.get("display_name", "")
                profile.avg_message_length = pdata.get("avg_message_length", 0)
                profile.uses_emoji = pdata.get("uses_emoji", True)
                profile.emoji_frequency = pdata.get("emoji_frequency", 0)
                profile.formality_level = pdata.get("formality_level", 0.5)
                profile.humor_level = pdata.get("humor_level", 0.3)
                profile.languages = pdata.get("languages", ["ru"])
                profile.preferred_language = pdata.get(
                    "preferred_language", "ru")
                profile.favorite_words = [
                    tuple(x) for x in pdata.get("favorite_words", [])]
                profile.favorite_phrases = pdata.get("favorite_phrases", [])
                profile.favorite_jokes = pdata.get("favorite_jokes", [])
                profile.greeting_style = pdata.get("greeting_style", "привет")
                profile.farewell_style = pdata.get("farewell_style", "пока")
                profile.interests = pdata.get("interests", {})
                profile.messages_analyzed = pdata.get("messages_analyzed", 0)
                profile.openness = pdata.get("openness", 0.5)
                profile.conscientiousness = pdata.get("conscientiousness", 0.5)
                profile.extraversion = pdata.get("extraversion", 0.5)
                profile.agreeableness = pdata.get("agreeableness", 0.5)
                profile.neuroticism = pdata.get("neuroticism", 0.5)
                profile.last_updated = pdata.get("last_updated", 0)
                self._profiles[cid] = profile

            for cid_str, cnt in data.get("word_counters", {}).items():
                self._word_counters[int(cid_str)] = Counter(cnt)
            for cid_str, cnt in data.get("phrase_counters", {}).items():
                self._phrase_counters[int(cid_str)] = Counter(cnt)
            for cid_str, cnt in data.get("joke_counters", {}).items():
                self._joke_counters[int(cid_str)] = Counter(cnt)

            self._shared_groups = data.get("shared_groups", [])
            self._last_retrain_at = data.get("last_retrain_at", 0)

            logger.info(
                f"PersonaEngine: loaded profiles ({len(self._profiles)} users)"
            )
        except Exception as e:
            logger.debug(f"Persona load error: {e}")

    def save(self) -> None:
        self._save()

    def get_stats(self) -> dict[str, Any]:
        return {
            "users": len(self._profiles),
            "shared_groups": len(self._shared_groups),
            "last_retrain_at": self._last_retrain_at,
        }


persona_engine = PersonaEngine()
