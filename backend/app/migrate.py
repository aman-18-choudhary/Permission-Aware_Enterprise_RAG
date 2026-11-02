"""Run database migrations at startup (and from the CLI: python -m app.migrate)."""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from .config import get_settings

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def run_migrations(url: str | None = None) -> None:
    """Bring the schema to the latest revision.

    A database created by the old `create_all` (tables exist, no alembic_version)
    is adopted by stamping it at the first revision instead of re-creating tables."""
    url = url or get_settings().database_url
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    cfg = _config(url)
    if "alembic_version" not in tables and "users" in tables:
        log.info("adopting existing schema at revision 0001")
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migrations()
