"""Tenant isolation on the running broker (docker compose up -d).

Provisions two throwaway tenants with the admin CLI, then checks over real
MQTT connections that each building can publish only to its own topics and
that messages land only in its own tenant's queue. Skipped when RabbitMQ is
not reachable.
"""

import dataclasses
import socket
import time

import paho.mqtt.client as mqtt
import pika
import pytest

from ingest import admin
from ingest.config import Config

A, B = "isotest-a", "isotest-b"
PASSWORD = "isotest-secret"


@pytest.fixture(scope="module")
def tenants(database_url):
    try:
        socket.create_connection(("localhost", 1883), timeout=2).close()
    except OSError:
        pytest.skip("RabbitMQ not reachable; run `docker compose up -d`")
    config = dataclasses.replace(Config.from_env(), database_url=database_url)
    broker = admin.broker_from_env()
    admin.init(config, broker)
    for vhost, building in ((A, "north"), (B, "south")):
        admin.add_tenant(config, broker, vhost, vhost)
        admin.add_building(config, broker, vhost, building, building, "Europe/Riga", PASSWORD)
    yield config
    for vhost, building in ((A, "north"), (B, "south")):
        broker.delete(["users", f"{vhost}-{building}"])
        broker.delete(["vhosts", vhost])


def publish(username: str, topic: str, password: str = PASSWORD) -> str:
    """Publish one QoS 1 message; return 'ok' or why it failed."""
    result: dict[str, str] = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    client.username_pw_set(username, password)
    client.on_connect = lambda _c, _u, _f, reason, _p: result.setdefault("connect", str(reason))
    client.on_publish = lambda _c, _u, _m, reason, _p: result.setdefault("puback", str(reason))
    client.on_disconnect = lambda _c, _u, _f, reason, _p: result.setdefault(
        "disconnect", str(reason)
    )
    client.connect("localhost", 1883)
    client.loop_start()
    deadline = time.monotonic() + 5
    while "connect" not in result and time.monotonic() < deadline:
        time.sleep(0.05)
    if result.get("connect") == "Success":
        client.publish(topic, b"{}", qos=1)
        while not ({"puback", "disconnect"} & result.keys()) and time.monotonic() < deadline:
            time.sleep(0.05)
    client.loop_stop()
    client.disconnect()
    if result.get("connect") != "Success":
        return f"connect refused: {result.get('connect')}"
    if result.get("puback") == "Success":
        return "ok"
    return f"publish refused: {result.get('puback') or result.get('disconnect')}"


def drain(config: Config, vhost: str) -> list[str]:
    """Routing keys waiting in a tenant's ingest queue, read as the ingest service user."""
    params = pika.ConnectionParameters(
        "localhost",
        virtual_host=vhost,
        credentials=pika.PlainCredentials(config.amqp_user, config.amqp_password),
    )
    with pika.BlockingConnection(params) as connection:
        channel = connection.channel()
        keys = []
        while (message := channel.basic_get(config.queue, auto_ack=True))[0] is not None:
            keys.append(message[0].routing_key)
        return keys


def test_building_publishes_only_into_its_own_tenant_queue(tenants):
    drain(tenants, A), drain(tenants, B)

    assert publish(f"{A}:{A}-north", "north/milesight/dev1") == "ok"

    assert drain(tenants, A) == ["north.milesight.dev1"]
    assert drain(tenants, B) == []


@pytest.mark.parametrize(
    ("username", "topic", "password"),
    [
        (f"{A}:{A}-north", "south/milesight/dev1", PASSWORD),  # other building's topic
        (f"{A}:{A}-north", "other/milesight/dev1", PASSWORD),  # unprovisioned building
    ],
)
def test_publish_outside_own_building_is_refused(tenants, username, topic, password):
    assert publish(username, topic, password).startswith("publish refused")
    assert drain(tenants, A) == []


@pytest.mark.parametrize(
    ("username", "password"),
    [
        (f"{B}:{A}-north", PASSWORD),  # valid user, another tenant's vhost
        (f"{A}-north", PASSWORD),  # no vhost prefix: default vhost, no access
        (f"{A}:{A}-north", "wrong"),
        ("", ""),  # anonymous
    ],
)
def test_login_outside_own_tenant_is_refused(tenants, username, password):
    assert publish(username, "north/milesight/dev1", password).startswith("connect refused")


def test_building_cannot_subscribe(tenants):
    granted: list[str] = []
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    client.username_pw_set(f"{A}:{A}-north", PASSWORD)
    client.on_subscribe = lambda _c, _u, _m, codes, _p: granted.extend(str(c) for c in codes)
    client.connect("localhost", 1883)
    client.loop_start()
    client.subscribe("#", qos=1)
    deadline = time.monotonic() + 5
    while not granted and time.monotonic() < deadline:
        time.sleep(0.05)
    client.loop_stop()
    client.disconnect()

    assert granted == ["Not authorized"]
