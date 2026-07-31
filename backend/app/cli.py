"""Operational commands — `python -m app.cli <command>`.

Phase 2 ships `init-db` and `healthcheck`. `ingest` and `reindex` arrive in
Phase 3 and are listed here as explicit "not yet" entries rather than being
absent, so `--help` describes the finished tool.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

from app.config import ConfigError, get_settings
from app.database import dispose_engine, init_engine, probe_database
from app.llm import registry
from app.utils.logging import configure_logging

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
INIT_SQL = SQL_DIR / "init.sql"


async def _init_db() -> int:
    """Apply sql/init.sql. Idempotent — safe against an existing database."""
    settings = get_settings()

    if not INIT_SQL.is_file():
        print(f"error: {INIT_SQL} not found", file=sys.stderr)
        return 1

    engine = init_engine(settings)
    try:
        ddl = INIT_SQL.read_text(encoding="utf-8")

        # Executed on the raw asyncpg connection rather than through
        # SQLAlchemy. Both of SQLAlchemy's routes fail on this file:
        # `text()` reads the `:=` in the plpgsql trigger body as a bound
        # parameter, and `exec_driver_sql()` goes through asyncpg's prepared
        # statement path, which rejects multi-command scripts outright
        # ("cannot insert multiple commands into a prepared statement").
        # asyncpg's own `execute()` uses the simple query protocol, which is
        # the only one that accepts a script — and the DO blocks have to stay
        # in one script to remain atomic.
        async with engine.begin() as conn:
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(ddl)

        async with engine.connect() as conn:
            tables = (
                await conn.scalars(
                    text(
                        """
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public' ORDER BY tablename
                        """
                    )
                )
            ).all()
            indexes = await conn.scalar(
                text(
                    "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'"
                )
            )
            vector_version = await conn.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )

        print(f"schema applied to {settings.redacted_dsn()}")
        print(f"  pgvector : {vector_version}")
        print(f"  tables   : {', '.join(tables)}")
        print(f"  indexes  : {indexes}")
        return 0
    finally:
        await dispose_engine()


async def _healthcheck() -> int:
    """Report the same picture as GET /api/health, without starting a server."""
    settings = get_settings()
    engine = init_engine(settings)
    try:
        registry.reset_probe_cache()
        probe = await probe_database(engine)
        statuses = await registry.get_all_statuses(settings)

        print(f"database  : {settings.redacted_dsn()}")
        print(f"  connected: {probe.connected}")
        print(f"  pgvector : {probe.pgvector}")
        if probe.chunks:
            print(
                f"  chunks   : total={probe.chunks.get('total', 0)} "
                f"local={probe.chunks.get('local', 0)} "
                f"voyage={probe.chunks.get('voyage', 0)}"
            )
        if probe.error:
            print(f"  error    : {probe.error}")

        for name, status in statuses.items():
            mark = "available" if status.available else "unavailable"
            print(f"{name:<10}: {mark} ({status.model})")
            if status.reason:
                print(f"  reason   : {status.reason}")

        healthy = probe.connected and probe.pgvector
        return 0 if healthy else 1
    finally:
        await dispose_engine()


async def _ingest(args: argparse.Namespace) -> int:
    """Fetch, chunk, embed, and upsert the transcript corpus."""
    from app.ingestion.fetch import FetchError, ensure_corpus, local_corpus
    from app.ingestion.pipeline import run_ingest

    settings = get_settings()

    try:
        if args.corpus_dir:
            episodes = local_corpus(Path(args.corpus_dir))
        else:
            episodes = ensure_corpus(refresh=not args.skip_fetch)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.embed_space:
        # Override the configured space for this run only, so a corpus can be
        # ingested into the second space without editing .env.
        settings = settings.model_copy(update={"embed_space": args.embed_space})

    engine = init_engine(settings)
    try:
        print(f"ingesting from {episodes}")
        print(f"  embed space: {settings.embed_space}")
        stats = await run_ingest(
            engine, settings, episodes, limit_episodes=args.limit_episodes
        )
        print(f"done: {stats.as_line()}")
        return 0 if not stats.errors else 1
    finally:
        await dispose_engine()


def _not_implemented(command: str) -> int:
    print(f"'{command}' is not implemented.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="The Lenny Growth Assistant — operational commands.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create enums, tables, indexes and triggers.")
    sub.add_parser("healthcheck", help="Report database and provider status.")

    ingest = sub.add_parser(
        "ingest", help="Fetch, chunk, embed and store the transcript corpus."
    )
    ingest.add_argument(
        "--source", choices=["github"], default="github", help="Corpus source."
    )
    ingest.add_argument(
        "--corpus-dir", help="Use an existing local corpus instead of cloning."
    )
    ingest.add_argument(
        "--embed-space",
        choices=["local", "voyage"],
        help="Override EMBED_SPACE for this run.",
    )
    ingest.add_argument(
        "--skip-fetch", action="store_true", help="Do not refresh the cached corpus."
    )
    ingest.add_argument(
        "--limit-episodes", type=int, help="Bound the run while developing."
    )

    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level if args.command == "ingest" else "WARNING")

    try:
        if args.command == "init-db":
            return asyncio.run(_init_db())
        if args.command == "healthcheck":
            return asyncio.run(_healthcheck())
        if args.command == "ingest":
            return asyncio.run(_ingest(args))
        return _not_implemented(args.command)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
