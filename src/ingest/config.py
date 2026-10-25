"""Settings from environment variables; defaults match docker-compose.yml."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    database_url: str
    amqp_host: str
    amqp_port: int
    amqp_user: str
    amqp_password: str
    queue: str
    prefetch: int
    tenant_refresh_seconds: float

    @classmethod
    def from_env(cls) -> "Config":
        env = os.environ.get
        return cls(
            database_url=env("DATABASE_URL", "postgresql://ingest:ingest@localhost:5432/telemetry"),
            amqp_host=env("AMQP_HOST", "localhost"),
            amqp_port=int(env("AMQP_PORT", "5672")),
            amqp_user=env("AMQP_USER", "ingest"),
            amqp_password=env("AMQP_PASSWORD", "ingest"),
            queue=env("INGEST_QUEUE", "ingest"),
            prefetch=int(env("INGEST_PREFETCH", "50")),
            tenant_refresh_seconds=float(env("TENANT_REFRESH_SECONDS", "60")),
        )
