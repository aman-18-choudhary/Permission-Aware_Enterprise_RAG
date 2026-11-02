from sqlalchemy import create_engine, inspect, text

from app.db import Base
from app.migrate import run_migrations

TABLES = {"users", "sources", "documents", "audit_log"}


def test_fresh_database_gets_the_schema(tmp_path):
    url = f"sqlite:///{tmp_path}/fresh.db"
    run_migrations(url)
    insp = inspect(create_engine(url))
    assert TABLES <= set(insp.get_table_names()) and "alembic_version" in insp.get_table_names()


def test_database_from_old_create_all_is_adopted_not_recreated(tmp_path):
    url = f"sqlite:///{tmp_path}/legacy.db"
    eng = create_engine(url)
    Base.metadata.create_all(eng)  # what earlier versions did
    with eng.begin() as c:
        c.execute(text("INSERT INTO users (id,email,name,groups,is_admin,created_at) VALUES ('1','a@b.c','','[]',0,'2026-01-01')"))
    run_migrations(url)  # must not fail with "table already exists"
    with create_engine(url).connect() as c:
        assert c.execute(text("SELECT email FROM users")).scalar() == "a@b.c"  # data kept
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0001"
    run_migrations(url)  # idempotent
