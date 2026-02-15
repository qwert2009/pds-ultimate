"""
PDS-Ultimate Voice Handler
==============================
Обработка голосовых сообщений:
1. Скачивание .ogg файла
2. Конвертация в WAV (через ffmpeg)
3. Распознавание Vosk (offline, локально) + Whisper fallback
4. Передача текста в Universal Handler
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.orm import Session

from pds_ultimate.bot.conversation import conversation_manager
from pds_ultimate.bot.handlers.universal import _save_to_db, handle_text
from pds_ultimate.config import logger

router = Router(name="voice")


@router.message(F.voice)
async def handle_voice(message: Message, db_session: Session) -> None:
    """
    Голосовое сообщение → текст → обработка как текст.
    Использует Vosk (offline) для распознавания речи.
    """
    chat_id = message.chat.id
    ctx = conversation_manager.get(chat_id)

    await message.bot.send_chat_action(chat_id, "typing")

    tmp_dir = tempfile.mkdtemp(prefix="pds_voice_")
    ogg_path = Path(tmp_dir) / "voice.ogg"

    try:
        # ─── 1. Скачиваем файл голосового ────────────────────────────
        file = await message.bot.get_file(message.voice.file_id)
        await message.bot.download_file(file.file_path, destination=str(ogg_path))

        logger.info(
            f"Голосовое: {file.file_path}, "
            f"размер: {ogg_path.stat().st_size} байт, "
            f"длительность: {message.voice.duration}с"
        )

        # ─── 2. Распознавание через SpeechEngine (Vosk) ─────────────
        #     SpeechEngine сам конвертирует OGG → WAV через ffmpeg
        from pds_ultimate.core.speech_engine import speech_engine

        text = speech_engine.transcribe(str(ogg_path))

        if not text or text.strip() == "":
            await message.answer("🔇 Не удалось распознать речь. Попробуй ещё раз, говори чётче.")
            return

        logger.info(
            f"Vosk распознал ({message.voice.duration}с): «{text[:100]}...»")

        # Уведомляем пользователя о том что распознано
        preview = text[:200]
        if len(text) > 200:
            preview += "..."

        await message.answer(f"🎤 Распознал: «{preview}»")

        # Сохраняем в историю
        _save_to_db(
            db_session, chat_id, "user",
            f"[голосовое {message.voice.duration}с]: {text}",
        )

        # ─── 3. Обрабатываем как текстовое сообщение ─────────────────
        # aiogram Message — frozen Pydantic model, нельзя менять .text
        # Создаём копию с текстом из голосового
        text_message = message.model_copy(update={"text": text})
        await handle_text(text_message, db_session)

    except FileNotFoundError:
        logger.error("ffmpeg не найден. Установите: apt install ffmpeg")
        await message.answer(
            "❌ Сервер не настроен для голосовых (нужен ffmpeg). "
            "Напиши текстом, я пойму."
        )

    except Exception as e:
        logger.error(f"Ошибка обработки голосового: {e}", exc_info=True)
        await message.answer("❌ Ошибка при обработке голосового. Попробуй текстом.")

    finally:
        # ─── Очистка временных файлов ────────────────────────────────
        for p in [ogg_path]:
            try:
                if p.exists():
                    os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


@router.message(F.video_note)
async def handle_video_note(message: Message, db_session: Session) -> None:
    """
    Видео-кружок → извлечение аудио → распознавание через Vosk.
    """
    chat_id = message.chat.id

    await message.bot.send_chat_action(chat_id, "typing")

    tmp_dir = tempfile.mkdtemp(prefix="pds_videonote_")
    video_path = Path(tmp_dir) / "video.mp4"

    try:
        file = await message.bot.get_file(message.video_note.file_id)
        await message.bot.download_file(file.file_path, destination=str(video_path))

        # SpeechEngine сам конвертирует MP4 → WAV через ffmpeg
        from pds_ultimate.core.speech_engine import speech_engine

        text = speech_engine.transcribe(str(video_path))

        if not text or text.strip() == "":
            await message.answer("🔇 Не удалось распознать речь из видео-кружка.")
            return

        await message.answer(f"🎤 Распознал из кружка: «{text[:200]}»")

        _save_to_db(
            db_session, chat_id, "user",
            f"[видео-кружок {message.video_note.length}]: {text}",
        )

        text_message = message.model_copy(update={"text": text})
        await handle_text(text_message, db_session)

    except Exception as e:
        logger.error(f"Ошибка обработки видео-кружка: {e}", exc_info=True)
        await message.answer("❌ Ошибка при обработке видео-кружка. Напиши текстом.")

    finally:
        for p in [video_path]:
            try:
                if p.exists():
                    os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass
