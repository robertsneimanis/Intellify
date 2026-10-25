"""Integration tests against a real PostgreSQL (docker compose up -d).

A fresh `telemetry_test` database is created from db/migrations once per
session; tests are skipped when PostgreSQL is not reachable.
"""

import os
from pathlib import Path

import psycopg
import pytest

from ingest import devices, storage

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://ingest:ingest@localhost:5432/postgres"
)
TEST_DB = "telemetry_test"
MIGRATIONS = Path(__file__).parents[2] / "db" / "migrations"


@pytest.fixture(scope="session")
def database_url():
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable; run `docker compose up -d`")
    with admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    url = psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=TEST_DB)
    with psycopg.connect(url, autocommit=True) as conn:
        for sql in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(sql.read_text())
    return url


@pytest.fixture(scope="session")
def metric_ids(database_url):
    with psycopg.connect(database_url) as conn:
        return storage.sync_metrics(conn, devices.catalog().values())


@pytest.fixture
def conn(database_url, metric_ids):
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "TRUNCATE measurements, raw_messages, devices, buildings, tenants RESTART IDENTITY"
        )
        tenant = conn.execute(
            "INSERT INTO tenants (vhost, name) VALUES ('demo', 'Demo') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO buildings (tenant_id, slug, name, timezone)"
            " VALUES (%s, 'ostas-skati', 'Ostas Skati', 'Europe/Riga')",
            (tenant,),
        )
        conn.commit()
        yield conn
