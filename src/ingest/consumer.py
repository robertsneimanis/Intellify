"""AMQP consumer for one tenant vhost.

Each tenant has a durable queue bound to `amq.topic` with key `#`, so MQTT
messages pile up while the service is down. A message is acknowledged only
after its database transaction commits; on a broker or database error the
connection is dropped, unacknowledged messages return to the queue, and the
consumer reconnects with exponential backoff.
"""

import logging
import threading
from collections.abc import Mapping

import pika
import pika.exceptions
import psycopg

from ingest.config import Config
from ingest.pipeline import Pipeline

log = logging.getLogger(__name__)

MAX_BACKOFF = 60


class VhostConsumer(threading.Thread):
    def __init__(
        self, vhost: str, config: Config, metric_ids: Mapping[str, int], stop: threading.Event
    ) -> None:
        super().__init__(name=f"consumer-{vhost}", daemon=True)
        self.vhost = vhost
        self.config = config
        self.metric_ids = metric_ids
        self.stop = stop
        self.backoff = 1

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                self._consume()
            except (pika.exceptions.AMQPError, psycopg.OperationalError) as exc:
                log.warning("vhost %s: %r; reconnecting in %ss", self.vhost, exc, self.backoff)
                self.stop.wait(self.backoff)
                self.backoff = min(self.backoff * 2, MAX_BACKOFF)

    def _consume(self) -> None:
        cfg = self.config
        params = pika.ConnectionParameters(
            host=cfg.amqp_host,
            port=cfg.amqp_port,
            virtual_host=self.vhost,
            credentials=pika.PlainCredentials(cfg.amqp_user, cfg.amqp_password),
            heartbeat=30,
            client_properties={"connection_name": f"ingest-{self.vhost}"},
        )
        with psycopg.connect(cfg.database_url, autocommit=True) as db:
            pipeline = Pipeline(db, self.metric_ids)
            connection = pika.BlockingConnection(params)
            try:
                channel = connection.channel()
                channel.queue_declare(cfg.queue, durable=True)
                channel.queue_bind(cfg.queue, "amq.topic", routing_key="#")
                channel.basic_qos(prefetch_count=cfg.prefetch)
                log.info("vhost %s: consuming queue %r", self.vhost, cfg.queue)
                self.backoff = 1

                for method, _, body in channel.consume(cfg.queue, inactivity_timeout=1):
                    if self.stop.is_set():
                        break
                    if method is None:  # inactivity timeout: re-check stop
                        continue
                    outcome = pipeline.handle(self.vhost, method.routing_key, body)
                    channel.basic_ack(method.delivery_tag)
                    log.log(
                        logging.WARNING if outcome.status == "rejected" else logging.INFO,
                        "vhost %s: %s raw=%s %s stored=%d suspect=%d%s",
                        self.vhost,
                        method.routing_key,
                        outcome.raw_id,
                        outcome.status,
                        outcome.stored,
                        outcome.suspect,
                        f" notes={outcome.errors}" if outcome.errors else "",
                    )
                channel.cancel()
            finally:
                if connection.is_open:
                    connection.close()
