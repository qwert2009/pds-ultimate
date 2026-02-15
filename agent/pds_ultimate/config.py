"""
PDS-Ultimate Configuration
===========================
Центральный конфигурационный модуль системы.
Все настройки, токены, пути и константы — здесь.

Конфигурация загружается из .env файла (секреты) и этого модуля (логика).
Поддерживает валидацию, значения по умолчанию и переопределение через env.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

# ─── Загрузка .env ───────────────────────────────────────────────────────────
# .env лежит рядом с config.py (внутри pds_ultimate/)
_THIS_DIR = Path(__file__).resolve().parent
load_dotenv(_THIS_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    """Получить переменную окружения с дефолтом."""
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    """Получить числовую переменную окружения."""
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(key: str, default: float = 0.0) -> float:
    """Получить float переменную окружения."""
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    """Получить bool переменную окружения."""
    val = os.getenv(key, "").lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


# ─── Пути ────────────────────────────────────────────────────────────────────

# Корень проекта (pds_ultimate/)
BASE_DIR = Path(__file__).resolve().parent

# Папка с данными
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Подпапки данных
ACTIVE_ORDERS_DIR = DATA_DIR / "active_orders"
ACTIVE_ORDERS_DIR.mkdir(parents=True, exist_ok=True)

DOCUMENTS_DIR = DATA_DIR / "documents"
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

BACKUPS_DIR = DATA_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

USER_FILES_DIR = DATA_DIR / "user_files"
USER_FILES_DIR.mkdir(parents=True, exist_ok=True)

# Credentials (OAuth tokens, service accounts)
CREDENTIALS_DIR = BASE_DIR / "credentials"
CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

# Ключевые файлы
DATABASE_PATH = DATA_DIR / "pds_ultimate.db"
MASTER_FINANCE_PATH = DATA_DIR / "Master_Finance.xlsx"
ALL_ORDERS_ARCHIVE_PATH = DATA_DIR / "All_Orders_Archive.xlsx"

# Логи
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "pds_ultimate.log"


# ─── Уровни логирования ─────────────────────────────────────────────────────

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


LOG_LEVEL = LogLevel(_env("LOG_LEVEL", "INFO"))


# ─── Telegram Bot ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TelegramBotConfig:
    """Конфигурация Telegram бота (Aiogram)."""
    token: str = _env("TG_BOT_TOKEN")
    owner_id: int = _env_int("TG_OWNER_ID")
    parse_mode: str = "HTML"
    # HTTP-прокси для обхода блокировок (например http://127.0.0.1:10809)
    proxy: str = _env("TG_PROXY", "")

    def validate(self) -> None:
        if not self.token:
            raise ValueError("TG_BOT_TOKEN не задан в .env")
        if not self.owner_id:
            raise ValueError("TG_OWNER_ID не задан в .env")


# ─── Telegram Userbot (Telethon) ─────────────────────────────────────────────

@dataclass(frozen=True)
class TelethonConfig:
    """Конфигурация Telegram Userbot для анализа чатов и мимикрии."""
    api_id: int = _env_int("TG_API_ID")
    api_hash: str = _env("TG_API_HASH")
    phone: str = _env("TG_PHONE", "")
    session_name: str = _env("TG_SESSION_NAME", "pds_userbot")
    # Количество чатов для анализа стиля (по ТЗ: 7 чатов TG)
    style_analysis_chat_count: int = _env_int("TG_STYLE_CHATS", 7)
    # Количество сообщений из каждого чата для анализа
    messages_per_chat: int = _env_int("TG_MESSAGES_PER_CHAT", 100)
    # Список чатов для анализа (username, phone или id через запятую)
    style_chats: list[str] = field(default_factory=lambda: [
        c.strip() for c in _env("TG_STYLE_CHAT_LIST", "").split(",")
        if c.strip()
    ])

    def validate(self) -> None:
        if not self.api_id:
            raise ValueError("TG_API_ID не задан в .env")
        if not self.api_hash:
            raise ValueError("TG_API_HASH не задан в .env")


# ─── WhatsApp (Green-API) ─────────────────────────────────────────────────

@dataclass(frozen=True)
class WhatsAppConfig:
    """Конфигурация WhatsApp через Green-API."""
    enabled: bool = _env_bool("WA_ENABLED", False)
    # Количество чатов для анализа стиля (по ТЗ: 3 чата WA)
    style_analysis_chat_count: int = _env_int("WA_STYLE_CHATS", 3)
    messages_per_chat: int = _env_int("WA_MESSAGES_PER_CHAT", 100)
    # Green-API credentials
    green_api_instance: str = _env("WA_GREEN_API_INSTANCE", "")
    green_api_token: str = _env("WA_GREEN_API_TOKEN", "")


# ─── DeepSeek API (LLM) ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeepSeekConfig:
    """Конфигурация DeepSeek API — мозг системы."""
    api_key: str = _env("DEEPSEEK_API_KEY")
    base_url: str = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model: str = _env("DEEPSEEK_MODEL", "deepseek-reasoner")
    # Модель для быстрых/лёгких задач (дешевле и быстрее)
    fast_model: str = _env("DEEPSEEK_FAST_MODEL", "deepseek-chat")
    max_tokens: int = _env_int("DEEPSEEK_MAX_TOKENS", 4096)
    temperature: float = _env_float("DEEPSEEK_TEMPERATURE", 0.7)
    # Таймаут запроса в секундах
    timeout: int = _env_int("DEEPSEEK_TIMEOUT", 120)
    # Максимум повторов при ошибке
    max_retries: int = _env_int("DEEPSEEK_MAX_RETRIES", 3)
    # HTTP-прокси (наследуется от TG_PROXY если не задано явно)
    proxy: str = _env("DEEPSEEK_PROXY", _env("TG_PROXY", ""))

    def validate(self) -> None:
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY не задан в .env")


# ─── Faster-Whisper (Локальное распознавание голоса) ─────────────────────────

@dataclass(frozen=True)
class WhisperConfig:
    """Конфигурация Faster-Whisper — локальная обработка голоса."""
    model_size: str = _env("WHISPER_MODEL", "medium")
    device: str = _env("WHISPER_DEVICE", "auto")  # auto, cpu, cuda
    compute_type: str = _env("WHISPER_COMPUTE_TYPE", "int8")
    language: str = _env("WHISPER_LANGUAGE", "ru")
    # Директория для скачанных моделей
    model_dir: Path = Path(
        _env("WHISPER_MODEL_DIR", str(DATA_DIR / "whisper_models"))
    )


# ─── Gmail API ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GmailConfig:
    """Конфигурация Gmail API."""
    enabled: bool = _env_bool("GMAIL_ENABLED", False)
    credentials_file: Path = Path(
        _env("GMAIL_CREDENTIALS", str(BASE_DIR / "credentials" / "gmail.json"))
    )
    token_file: Path = Path(
        _env("GMAIL_TOKEN", str(DATA_DIR / "gmail_token.json"))
    )
    # Почта владельца (для отчётов каждые 3 дня)
    owner_email: str = _env("GMAIL_OWNER_EMAIL")
    scopes: list[str] = field(default_factory=lambda: [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
    ])


# ─── SMTP Fallback ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SmtpConfig:
    """SMTP fallback для отправки email без OAuth."""
    enabled: bool = _env_bool("SMTP_ENABLED", False)
    host: str = _env("SMTP_HOST", "smtp.gmail.com")
    port: int = int(_env("SMTP_PORT", "587"))
    user: str = _env("SMTP_USER", "")  # email
    password: str = _env("SMTP_PASSWORD", "")  # app password
    use_tls: bool = _env_bool("SMTP_TLS", True)
    from_name: str = _env("SMTP_FROM_NAME", "PDS-Ultimate")


# ─── Валюты ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CurrencyConfig:
    """
    Конфигурация валют.
    Фиксированные курсы по ТЗ:
      1 USD = 19.5 TMT (Туркменский манат)
      1 USD = 7.1 CNY (Китайский юань)
    Остальные курсы — динамически из API.
    """
    # Фиксированные курсы (key: валюта, value: сколько единиц за 1 USD)
    fixed_rates: dict[str, float] = field(default_factory=lambda: {
        "TMT": 19.5,   # Туркменский манат
        "CNY": 7.1,    # Китайский юань
    })
    # API для динамических курсов
    exchange_api_url: str = _env(
        "EXCHANGE_API_URL",
        "https://api.exchangerate-api.com/v4/latest/USD"
    )
    # Базовая валюта учёта
    base_currency: str = _env("BASE_CURRENCY", "USD")
    # Кэш курсов (время жизни в секундах, 6 часов)
    cache_ttl: int = _env_int("CURRENCY_CACHE_TTL", 21600)


# ─── Финансы ─────────────────────────────────────────────────────────────────

@dataclass
class FinanceConfig:
    """
    Конфигурация финансового модуля.
    Формула прибыли по ТЗ:
      ДОХОД (сколько заплатили МНЕ)
      - РАСХОД_ТОВАР (сколько Я заплатил поставщику)
      = ОСТАТОК
      - РАСХОД_ДОСТАВКА
      = ЧИСТАЯ_ПРИБЫЛЬ
      → На расходы (expense_percent %)
      → Отложения на будущее (savings_percent %)
    БЕЗ налогов и комиссий.
    """
    # Процент от чистой прибыли на текущие расходы
    expense_percent: float = _env_float("FINANCE_EXPENSE_PERCENT", 50.0)
    # Процент от чистой прибыли на отложения/будущее
    savings_percent: float = _env_float("FINANCE_SAVINGS_PERCENT", 50.0)

    def validate(self) -> None:
        total = self.expense_percent + self.savings_percent
        if abs(total - 100.0) > 0.01:
            raise ValueError(
                f"Сумма процентов должна быть 100%, "
                f"сейчас: {self.expense_percent}% + {self.savings_percent}% = {total}%"
            )


# ─── Логистика ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LogisticsConfig:
    """
    Конфигурация логистического модуля.
    По ТЗ:
      - T+4 дня: первый запрос статуса
      - Повтор каждый вторник
      - Антизабывание: напоминание через 2 часа, потом вечером
    """
    # Через сколько дней после создания заказа — первый запрос статуса
    first_status_check_days: int = _env_int("LOGISTICS_FIRST_CHECK_DAYS", 4)
    # День недели для повторных проверок (0=пн, 1=вт, ..., 6=вс)
    recurring_check_weekday: int = _env_int(
        "LOGISTICS_CHECK_WEEKDAY", 1)  # Вторник
    # Антизабывание: повтор через N часов если нет ответа
    reminder_hours: int = _env_int("LOGISTICS_REMINDER_HOURS", 2)
    # Вечернее напоминание (час)
    evening_reminder_hour: int = _env_int("LOGISTICS_EVENING_HOUR", 20)


# ─── Планировщик ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SchedulerConfig:
    """Конфигурация APScheduler."""
    # Хранилище задач (для выживания при перезагрузке)
    jobstore_url: str = f"sqlite:///{DATABASE_PATH}"
    # Максимальное количество параллельных задач
    max_workers: int = _env_int("SCHEDULER_MAX_WORKERS", 10)
    # Время утреннего брифинга
    morning_brief_hour: int = _env_int("MORNING_BRIEF_HOUR", 8)
    morning_brief_minute: int = _env_int("MORNING_BRIEF_MINUTE", 30)
    # Отчёт каждые N дней
    report_interval_days: int = _env_int("REPORT_INTERVAL_DAYS", 3)
    report_hour: int = _env_int("REPORT_HOUR", 9)
    report_minute: int = _env_int("REPORT_MINUTE", 0)
    # Бэкап каждый день
    backup_hour: int = _env_int("BACKUP_HOUR", 3)
    backup_minute: int = _env_int("BACKUP_MINUTE", 0)


# ─── Мимикрия (стиль общения) ───────────────────────────────────────────────

@dataclass(frozen=True)
class StyleConfig:
    """Конфигурация модуля анализа стиля общения."""
    # Периодичность пересканирования стиля (в днях)
    rescan_interval_days: int = _env_int("STYLE_RESCAN_DAYS", 7)
    # Минимальное количество сообщений для качественного профиля
    min_messages_for_profile: int = _env_int("STYLE_MIN_MESSAGES", 50)


# ─── Безопасность ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SecurityConfig:
    """Конфигурация безопасности."""
    # Кодовое слово для экстренного удаления финансовых данных
    emergency_code: str = _env("SECURITY_EMERGENCY_CODE", "")
    # Ежесуточный бэкап
    auto_backup: bool = _env_bool("SECURITY_AUTO_BACKUP", True)
    # Куда бэкапить (email = отправка на вторую почту)
    backup_target: str = _env("SECURITY_BACKUP_TARGET",
                              "local")  # local | email
    backup_email: str = _env("SECURITY_BACKUP_EMAIL", "")


# ─── OCR ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OCRConfig:
    """Конфигурация OCR для распознавания фото чеков, накладных, трек-номеров."""
    engine: str = _env("OCR_ENGINE", "easyocr")  # easyocr | tesseract
    languages: list[str] = field(
        default_factory=lambda: ["ru", "en", "ch_sim"])
    # Уверенность распознавания (0.0 - 1.0)
    confidence_threshold: float = _env_float("OCR_CONFIDENCE", 0.5)


# ─── Browser Engine ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BrowserConfig:
    """
    Конфигурация Browser Engine (Playwright).

    Anti-detection, stealth, human-like поведение.
    Используется для:
    - Поиск в интернете
    - Скрапинг данных с сайтов
    - Работа с WhatsApp Web
    - Автоматизация веб-форм
    """
    # Headless mode (True для сервера, False для отладки)
    headless: bool = _env_bool("BROWSER_HEADLESS", True)
    # Тип браузера: chromium, firefox, webkit
    browser_type: str = _env("BROWSER_TYPE", "chromium")
    # User-Agent (пустой = рандомный из пула)
    user_agent: str = _env("BROWSER_USER_AGENT", "")
    # Viewport размеры
    viewport_width: int = _env_int("BROWSER_VIEWPORT_W", 1920)
    viewport_height: int = _env_int("BROWSER_VIEWPORT_H", 1080)
    # Таймауты (мс)
    default_timeout: int = _env_int("BROWSER_TIMEOUT", 30000)
    navigation_timeout: int = _env_int("BROWSER_NAV_TIMEOUT", 60000)
    # Прокси (опционально)
    proxy_server: str = _env("BROWSER_PROXY", "")
    # Директория для скриншотов
    screenshots_dir: Path = Path(
        _env("BROWSER_SCREENSHOTS_DIR", str(DATA_DIR / "screenshots"))
    )
    # Директория для downloads
    downloads_dir: Path = Path(
        _env("BROWSER_DOWNLOADS_DIR", str(DATA_DIR / "downloads"))
    )
    # Максимум страниц одновременно
    max_pages: int = _env_int("BROWSER_MAX_PAGES", 5)
    # Human-like задержки (мс)
    min_type_delay: int = _env_int("BROWSER_MIN_TYPE_DELAY", 50)
    max_type_delay: int = _env_int("BROWSER_MAX_TYPE_DELAY", 150)
    min_click_delay: int = _env_int("BROWSER_MIN_CLICK_DELAY", 100)
    max_click_delay: int = _env_int("BROWSER_MAX_CLICK_DELAY", 500)
    # Stealth mode
    stealth_enabled: bool = _env_bool("BROWSER_STEALTH", True)
    # Locale
    locale: str = _env("BROWSER_LOCALE", "en-US")
    timezone: str = _env("BROWSER_TIMEZONE", "Asia/Ashgabat")


# ─── Сводная конфигурация ────────────────────────────────────────────────────

@dataclass
class AppConfig:
    """
    Главная конфигурация приложения.
    Объединяет все модульные конфиги в единую точку доступа.

    Использование:
        config = AppConfig.load()
        config.validate()
        print(config.deepseek.api_key)
    """
    telegram: TelegramBotConfig = field(default_factory=TelegramBotConfig)
    telethon: TelethonConfig = field(default_factory=TelethonConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    deepseek: DeepSeekConfig = field(default_factory=DeepSeekConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    currency: CurrencyConfig = field(default_factory=CurrencyConfig)
    finance: FinanceConfig = field(default_factory=FinanceConfig)
    logistics: LogisticsConfig = field(default_factory=LogisticsConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    style: StyleConfig = field(default_factory=StyleConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)

    @classmethod
    def load(cls) -> "AppConfig":
        """Загрузить конфигурацию из .env и дефолтов."""
        return cls()

    def validate(self) -> list[str]:
        """
        Валидация конфигурации.
        Возвращает список предупреждений (некритичные проблемы).
        Бросает ValueError при критичных ошибках.
        """
        warnings: list[str] = []

        # Критичные — без них система не запустится
        self.telegram.validate()
        self.deepseek.validate()
        self.finance.validate()

        # Предупреждения — система работает, но с ограничениями
        try:
            self.telethon.validate()
        except ValueError as e:
            warnings.append(f"Telethon (мимикрия стиля): {e}")

        if not self.gmail.enabled:
            warnings.append(
                "Gmail отключён — отчёты каждые 3 дня не будут отправляться")

        if not self.whatsapp.enabled:
            warnings.append(
                "WhatsApp отключён — анализ стиля WA и авто-перевод не будут работать")

        if not self.security.emergency_code:
            warnings.append(
                "Кодовое слово безопасности не задано (SECURITY_EMERGENCY_CODE)")

        return warnings


# ─── Логирование ─────────────────────────────────────────────────────────────

def setup_logging(level: LogLevel = LOG_LEVEL) -> logging.Logger:
    """
    Настройка логирования для всей системы.
    Логи пишутся и в файл, и в консоль.
    """
    logger = logging.getLogger("pds_ultimate")
    logger.setLevel(getattr(logging, level.value))

    # Формат логов
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # Файл
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

config = AppConfig.load()
logger = setup_logging()
