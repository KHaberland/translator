import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.models.schemas import DocumentBlock, LanguageCode
from app.services.translation_cache import normalize_translation_cache_text


@dataclass(frozen=True)
class GlossaryTerm:
    source: str
    target: str


class SQLiteTranslationMemory:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._ensure_schema()

    def lookup_exact(
        self,
        source_text: str,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        domain: str | None = None,
    ) -> str | None:
        normalized_source_text = normalize_translation_cache_text(source_text)
        if not normalized_source_text:
            return None

        domain_key = _domain_key(domain)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT translated_text
                FROM translation_memory
                WHERE normalized_source_text = ?
                  AND source_lang = ?
                  AND target_lang = ?
                  AND domain = ?
                ORDER BY frequency DESC, updated_at DESC
                LIMIT 1
                """,
                (
                    normalized_source_text,
                    source_lang.value,
                    target_lang.value,
                    domain_key,
                ),
            ).fetchone()

        return row["translated_text"] if row is not None else None

    def save_translation(
        self,
        source_text: str,
        translated_text: str,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        domain: str | None = None,
    ) -> None:
        normalized_source_text = normalize_translation_cache_text(source_text)
        if not normalized_source_text or not translated_text.strip():
            return

        domain_key = _domain_key(domain)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO translation_memory (
                    source_text,
                    normalized_source_text,
                    translated_text,
                    source_lang,
                    target_lang,
                    domain,
                    frequency
                )
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(normalized_source_text, source_lang, target_lang, domain)
                DO UPDATE SET
                    source_text = excluded.source_text,
                    translated_text = excluded.translated_text,
                    frequency = translation_memory.frequency + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    source_text,
                    normalized_source_text,
                    translated_text,
                    source_lang.value,
                    target_lang.value,
                    domain_key,
                ),
            )

    def increment_frequency(
        self,
        source_text: str,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        domain: str | None = None,
    ) -> None:
        normalized_source_text = normalize_translation_cache_text(source_text)
        if not normalized_source_text:
            return

        domain_key = _domain_key(domain)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE translation_memory
                SET frequency = frequency + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE normalized_source_text = ?
                  AND source_lang = ?
                  AND target_lang = ?
                  AND domain = ?
                """,
                (
                    normalized_source_text,
                    source_lang.value,
                    target_lang.value,
                    domain_key,
                ),
            )

    def add_glossary_term(
        self,
        source: str,
        target: str,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        domain: str | None = None,
    ) -> None:
        normalized_source = normalize_translation_cache_text(source).casefold()
        if not normalized_source or not target.strip():
            return

        domain_key = _domain_key(domain)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO translation_glossary (
                    source,
                    normalized_source,
                    target,
                    source_lang,
                    target_lang,
                    domain
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_source, source_lang, target_lang, domain)
                DO UPDATE SET
                    source = excluded.source,
                    target = excluded.target,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    source,
                    normalized_source,
                    target,
                    source_lang.value,
                    target_lang.value,
                    domain_key,
                ),
            )

    def glossary_terms_for_blocks(
        self,
        blocks: Sequence[DocumentBlock],
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        domain: str | None = None,
    ) -> list[GlossaryTerm]:
        if not blocks:
            return []

        text = "\n".join(block.text for block in blocks).casefold()
        domain_key = _domain_key(domain)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source, target, normalized_source
                FROM translation_glossary
                WHERE source_lang = ?
                  AND target_lang = ?
                  AND domain = ?
                ORDER BY length(normalized_source) DESC, source ASC
                """,
                (
                    source_lang.value,
                    target_lang.value,
                    domain_key,
                ),
            ).fetchall()

        return [
            GlossaryTerm(source=row["source"], target=row["target"])
            for row in rows
            if row["normalized_source"] in text
        ]

    def frequency_for(
        self,
        source_text: str,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        domain: str | None = None,
    ) -> int:
        normalized_source_text = normalize_translation_cache_text(source_text)
        if not normalized_source_text:
            return 0

        domain_key = _domain_key(domain)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT frequency
                FROM translation_memory
                WHERE normalized_source_text = ?
                  AND source_lang = ?
                  AND target_lang = ?
                  AND domain = ?
                """,
                (
                    normalized_source_text,
                    source_lang.value,
                    target_lang.value,
                    domain_key,
                ),
            ).fetchone()

        return int(row["frequency"]) if row is not None else 0

    def _ensure_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL,
                    normalized_source_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    source_lang TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    frequency INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_translation_memory_exact
                ON translation_memory (
                    normalized_source_text,
                    source_lang,
                    target_lang,
                    domain
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_glossary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    normalized_source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    source_lang TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_translation_glossary_source
                ON translation_glossary (
                    normalized_source,
                    source_lang,
                    target_lang,
                    domain
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection


def get_translation_memory(db_path: Path) -> SQLiteTranslationMemory:
    return SQLiteTranslationMemory(db_path)


def _domain_key(domain: str | None) -> str:
    return normalize_translation_cache_text(domain or "").casefold()
