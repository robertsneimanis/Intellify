"""Publish the sample fixtures over MQTT, as a building's gateway would.

    python scripts/publish_samples.py --username demo:demo-ostas-skati --password ... \
        --building ostas-skati

Each fixture goes to <building>/<format>/<device_id> with QoS 1. Exits
non-zero if the broker refuses the connection or a publish.
"""

import argparse
import json
import sys
from pathlib import Path

import paho.mqtt.client as mqtt

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def device_id(source_format: str, payload: dict) -> str:
    match source_format:
        case "milesight":
            return payload["devEUI"]
        case "viltrus":
            return str(payload["SN"])
        case _:
            return payload["name"]  # WAGO serials may contain '+', an MQTT wildcard


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, help="default: 8883 with --tls, else 1883")
    parser.add_argument("--tls", action="store_true", help="connect with TLS")
    parser.add_argument("--cafile", default="broker/certs/ca.pem", help="CA to verify the broker")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--building", required=True)
    parser.add_argument("--topic", help="publish every fixture to this topic instead")
    parser.add_argument(
        "files", nargs="*", help="fixtures relative to tests/fixtures (default: all)"
    )
    args = parser.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    client.username_pw_set(args.username, args.password)
    acks: dict[int, int] = {}  # message id -> PUBACK reason code (>= 128 is a refusal)
    client.on_publish = lambda _c, _u, mid, reason, _p: acks.__setitem__(mid, reason.value)
    try:
        if args.tls:
            client.tls_set(ca_certs=args.cafile)
        client.connect(args.host, args.port or (8883 if args.tls else 1883))
    except OSError as exc:
        print(f"cannot connect: {exc}", file=sys.stderr)
        return 1
    client.loop_start()

    failed = False
    paths = [FIXTURES / f for f in args.files] or sorted(FIXTURES.rglob("*.json"))
    for path in paths:
        source_format = path.parent.name
        payload = json.loads(path.read_text(encoding="utf-8"))
        topic = args.topic or f"{args.building}/{source_format}/{device_id(source_format, payload)}"
        info = client.publish(topic, json.dumps(payload), qos=1)
        try:
            info.wait_for_publish(timeout=5)
            ok = info.is_published() and acks.get(info.mid, 255) < 128
        except RuntimeError:  # connection refused or dropped
            ok = False
        print(f"{'ok    ' if ok else 'FAILED'} {topic}")
        failed |= not ok
    client.loop_stop()
    client.disconnect()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
