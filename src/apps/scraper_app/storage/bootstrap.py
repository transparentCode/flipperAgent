"""Operator step: apply the ``scraper`` schema, create the role, grant minimums.

Run as ``python -m apps.scraper_app.storage.bootstrap`` with ``POSTGRES_URI``
(an administrative connection), ``SCRAPER_DB_PASSWORD`` and
``SCRAPER_PURGE_DB_PASSWORD`` set. Idempotent;
exits non-zero on any error. The runtime role gets ``SELECT`` and ``INSERT``
only: it cannot update, delete or truncate evidence. Deletion belongs to the
separate ``scraper_purge`` role (SELECT and DELETE only).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import asyncpg

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

SCHEMA_NAME = "scraper"
ROLE_NAME = "scraper_app"
PURGE_ROLE_NAME = "scraper_purge"
TABLES = (
    "scraper.reads",
    "scraper.bar_observations",
    "scraper.payload_observations",
)
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def grant_statements(sequence_name: str) -> list[str]:
    """Statements that leave ``scraper_app`` with exactly the intended rights."""
    tables = ", ".join(TABLES)
    return [
        f"GRANT USAGE ON SCHEMA {SCHEMA_NAME} TO {ROLE_NAME}",
        f"REVOKE ALL ON {tables} FROM {ROLE_NAME}",
        f"GRANT SELECT, INSERT ON {tables} TO {ROLE_NAME}",
        f"REVOKE ALL ON SEQUENCE {sequence_name} FROM {ROLE_NAME}",
        f"GRANT USAGE ON SEQUENCE {sequence_name} TO {ROLE_NAME}",
    ]


def purge_grant_statements() -> list[str]:
    """``scraper_purge`` reads and deletes; it can never insert or update."""
    tables = ", ".join(TABLES)
    return [
        f"GRANT USAGE ON SCHEMA {SCHEMA_NAME} TO {PURGE_ROLE_NAME}",
        f"REVOKE ALL ON {tables} FROM {PURGE_ROLE_NAME}",
        f"GRANT SELECT, DELETE ON {tables} TO {PURGE_ROLE_NAME}",
    ]


async def _ensure_login_role(
    connection: asyncpg.Connection, role: str, password: str
) -> None:
    # CREATE/ALTER ROLE cannot take bind parameters; quote the literal server-side.
    literal = await connection.fetchval("SELECT quote_literal($1::text)", password)
    exists = await connection.fetchval(
        "SELECT 1 FROM pg_roles WHERE rolname = $1", role
    )
    verb = "ALTER" if exists else "CREATE"
    await connection.execute(f"{verb} ROLE {role} WITH LOGIN PASSWORD {literal}")


async def apply_scraper_schema(
    connection: asyncpg.Connection,
    password: str,
    purge_password: str | None = None,
) -> None:
    """Apply schema, roles and grants in one transaction.

    The purge role is created only when ``purge_password`` is given.
    """
    if not password:
        raise ValueError("SCRAPER_DB_PASSWORD must not be empty")
    if purge_password is not None and not purge_password:
        raise ValueError("SCRAPER_PURGE_DB_PASSWORD must not be empty")
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    async with connection.transaction():
        await connection.execute(schema_sql)
        await _ensure_login_role(connection, ROLE_NAME, password)
        sequence = await connection.fetchval(
            "SELECT pg_get_serial_sequence('scraper.reads', 'read_id')"
        )
        for statement in grant_statements(sequence):
            await connection.execute(statement)
        if purge_password is not None:
            await _ensure_login_role(connection, PURGE_ROLE_NAME, purge_password)
            for statement in purge_grant_statements():
                await connection.execute(statement)


async def _run() -> None:
    uri = os.environ.get("POSTGRES_URI", "").strip()
    password = os.environ.get("SCRAPER_DB_PASSWORD", "")
    if not uri:
        raise RuntimeError("POSTGRES_URI is not set")
    if not password:
        raise RuntimeError("SCRAPER_DB_PASSWORD is not set")
    purge_password = os.environ.get("SCRAPER_PURGE_DB_PASSWORD", "")
    if not purge_password:
        raise RuntimeError("SCRAPER_PURGE_DB_PASSWORD is not set")
    connection = await asyncpg.connect(uri)
    try:
        await apply_scraper_schema(connection, password, purge_password)
    finally:
        await connection.close()
    logger.info(
        "scraper schema applied; role %s granted SELECT, INSERT; role %s SELECT, DELETE",
        ROLE_NAME,
        PURGE_ROLE_NAME,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(_run())
    except Exception:
        logger.exception("scraper bootstrap failed")
        sys.exit(1)


if __name__ == "__main__":
    main()


__all__ = [
    "PURGE_ROLE_NAME",
    "apply_scraper_schema",
    "grant_statements",
    "main",
    "purge_grant_statements",
]
