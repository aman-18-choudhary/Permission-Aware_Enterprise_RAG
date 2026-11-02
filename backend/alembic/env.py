from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.config import get_settings
from app.db import Base

config = context.config
url = config.get_main_option("sqlalchemy.url") or get_settings().database_url

with create_engine(url, poolclass=pool.NullPool).connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
