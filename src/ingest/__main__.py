"""Service entry point: `python -m ingest`.

Starts one consumer thread per tenant vhost listed in the `tenants` table and
checks for new tenants periodically, so adding a tenant needs no restart.
Stops cleanly on SIGTERM / SIGINT (PM2, systemd, Ctrl+C).
"""

import logging
import os
import signal
import threading

import psycopg

from ingest import devices, storage
from ingest.config import Config
from ingest.consumer import MAX_BACKOFF, VhostConsumer

log = logging.getLogger("ingest")


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)
    config = Config.from_env()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    metric_ids = _with_retry(stop, _sync_metrics, config)
    consumers: dict[str, VhostConsumer] = {}
    while not stop.is_set():
        try:
            with psycopg.connect(config.database_url) as conn:
                vhosts = storage.tenant_vhosts(conn)
        except psycopg.OperationalError as exc:
            log.warning("cannot load tenants: %r", exc)
            vhosts = list(consumers)
        if not vhosts:
            log.warning("no tenants configured; add one with `python -m ingest.admin add-tenant`")
        for vhost in vhosts:
            if vhost not in consumers or not consumers[vhost].is_alive():
                consumers[vhost] = VhostConsumer(vhost, config, metric_ids, stop)
                consumers[vhost].start()
        stop.wait(config.tenant_refresh_seconds)

    log.info("stopping")
    for consumer in consumers.values():
        consumer.join(timeout=10)


def _sync_metrics(config: Config) -> dict[str, int]:
    with psycopg.connect(config.database_url) as conn:
        ids = storage.sync_metrics(conn, devices.catalog().values())
    log.info(
        "metric catalog synced: %d metrics from %d device models", len(ids), len(devices.MODELS)
    )
    return ids


def _with_retry(stop, fn, *args):
    delay = 1
    while True:
        try:
            return fn(*args)
        except psycopg.OperationalError as exc:
            if stop.is_set():
                raise SystemExit(1) from exc
            log.warning("database unavailable: %r; retrying in %ss", exc, delay)
            stop.wait(delay)
            delay = min(delay * 2, MAX_BACKOFF)


if __name__ == "__main__":
    main()
