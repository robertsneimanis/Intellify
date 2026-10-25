"""Provision tenants and buildings in RabbitMQ and PostgreSQL.

    python -m ingest.admin init
    python -m ingest.admin add-tenant demo "Demo Ltd"
    python -m ingest.admin add-building demo ostas-skati "Ostas Skati" [--timezone Europe/Riga]

Isolation model:
- one RabbitMQ vhost per tenant; a tenant's users have no rights elsewhere;
- one MQTT user per building, `<vhost>-<building>`, that devices log in as
  `<vhost>:<vhost>-<building>`. It may only publish, and topic permissions
  restrict it to topics under its own building: `<building>/#`;
- the ingest service user may only use the `ingest` queue in each vhost.

Uses the RabbitMQ management HTTP API, so it works against a remote broker.
All commands are idempotent.
"""

import argparse
import base64
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

import psycopg

from ingest.config import Config

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # no "." or "/": they are topic separators


class Broker:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def call(self, method: str, path: str, body: dict | None = None) -> None:
        parts = [urllib.parse.quote(p, safe="") for p in path]
        request = urllib.request.Request(
            f"{self.url}/{'/'.join(parts)}",
            data=json.dumps(body or {}).encode(),
            headers=self.headers,
            method=method,
        )
        try:
            urllib.request.urlopen(request, timeout=10).close()
        except urllib.error.HTTPError as exc:
            raise SystemExit(
                f"{method} {'/'.join(path)}: {exc.code} {exc.read().decode()}"
            ) from exc

    def user(self, name: str, password: str) -> None:
        self.call("PUT", ["users", name], {"password": password, "tags": ""})

    def permissions(self, vhost: str, user: str, configure: str, write: str, read: str) -> None:
        body = {"configure": configure, "write": write, "read": read}
        self.call("PUT", ["permissions", vhost, user], body)

    def topic_permissions(self, vhost: str, user: str, write: str, read: str) -> None:
        body = {"exchange": "amq.topic", "write": write, "read": read}
        self.call("PUT", ["topic-permissions", vhost, user], body)


def broker_from_env() -> Broker:
    return Broker(
        os.environ.get("RABBITMQ_API_URL", "http://localhost:15672/api"),
        os.environ.get("RABBITMQ_ADMIN_USER", "admin"),
        os.environ.get("RABBITMQ_ADMIN_PASS", "admin"),
    )


def init(config: Config, broker: Broker) -> None:
    broker.user(config.amqp_user, config.amqp_password)
    print(f"ingest service user {config.amqp_user!r} ready")


def add_tenant(config: Config, broker: Broker, vhost: str, name: str) -> None:
    _check_slug(vhost)
    broker.call("PUT", ["vhosts", vhost], {"description": name})
    queue = re.escape(config.queue)
    broker.permissions(
        vhost, config.amqp_user, f"^{queue}$", f"^{queue}$", rf"^({queue}|amq\.topic)$"
    )
    # Declared here, not only by the service, so messages are kept from the first publish.
    broker.call("PUT", ["queues", vhost, config.queue], {"durable": True})
    broker.call(
        "POST", ["bindings", vhost, "e", "amq.topic", "q", config.queue], {"routing_key": "#"}
    )
    with psycopg.connect(config.database_url) as conn:
        conn.execute(
            "INSERT INTO tenants (vhost, name) VALUES (%s, %s)"
            " ON CONFLICT (vhost) DO UPDATE SET name = EXCLUDED.name",
            (vhost, name),
        )
    print(f"tenant {vhost!r} ready: vhost, queue {config.queue!r} bound to amq.topic '#'")


def add_building(
    config: Config,
    broker: Broker,
    vhost: str,
    slug: str,
    name: str,
    timezone: str,
    password: str | None,
) -> None:
    _check_slug(slug)
    with psycopg.connect(config.database_url) as conn:
        row = conn.execute(
            """
            INSERT INTO buildings (tenant_id, slug, name, timezone)
            SELECT id, %s, %s, %s FROM tenants WHERE vhost = %s
            ON CONFLICT (tenant_id, slug) DO UPDATE
                SET name = EXCLUDED.name, timezone = EXCLUDED.timezone
            RETURNING id
            """,
            (slug, name, timezone, vhost),
        ).fetchone()
        if row is None:
            raise SystemExit(f"unknown tenant {vhost!r}; run add-tenant first")

    user = f"{vhost}-{slug}"
    password = password or secrets.token_urlsafe(18)
    broker.user(user, password)
    # Publish only: no queues of its own, no reading, and only its building's topics.
    broker.permissions(vhost, user, configure="^$", write=r"^amq\.topic$", read="^$")
    broker.topic_permissions(vhost, user, write=rf"^{re.escape(slug)}\.", read="^$")
    print(f"building {slug!r} ready in tenant {vhost!r}")
    print(f"  MQTT username: {vhost}:{user}")
    print(f"  MQTT password: {password}")
    print(f"  publish to:    {slug}/<format>/<device_id>  (format: milesight | viltrus | wago)")


def _check_slug(value: str) -> None:
    if not SLUG.match(value):
        raise SystemExit(f"{value!r} must be lowercase letters, digits and '-'")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m ingest.admin", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the ingest service's broker user")
    tenant = sub.add_parser("add-tenant", help="create a tenant vhost, its queue and DB row")
    tenant.add_argument("vhost")
    tenant.add_argument("name")
    building = sub.add_parser("add-building", help="create a building and its MQTT user")
    building.add_argument("vhost")
    building.add_argument("slug")
    building.add_argument("name")
    building.add_argument("--timezone", default="Europe/Riga")
    building.add_argument("--password", help="MQTT password (generated if omitted)")
    args = parser.parse_args(argv)

    config, broker = Config.from_env(), broker_from_env()
    match args.command:
        case "init":
            init(config, broker)
        case "add-tenant":
            add_tenant(config, broker, args.vhost, args.name)
        case "add-building":
            add_building(
                config, broker, args.vhost, args.slug, args.name, args.timezone, args.password
            )


if __name__ == "__main__":
    main(sys.argv[1:])
