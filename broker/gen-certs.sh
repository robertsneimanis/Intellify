#!/bin/sh
# Create a development CA and a server certificate for the MQTT TLS listener.
# Runs in the `certs` compose service on first start; skips if certificates exist.
# Devices verify the broker with ca.pem. For production, use certificates from
# your own CA instead and mount them at the same paths.
#
# Extra names for the certificate (e.g. the Mac's LAN address) can be given as
# EXTRA_SANS="IP:192.168.1.10,DNS:broker.local".
set -eu

DIR=${1:-/certs}
if [ -f "$DIR/server.pem" ]; then
    echo "certificates already exist in $DIR"
    exit 0
fi
cd "$DIR"

SANS="DNS:localhost,DNS:rabbitmq,IP:127.0.0.1${EXTRA_SANS:+,$EXTRA_SANS}"
openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=Intellify dev CA" \
    -keyout ca.key -out ca.pem
openssl req -newkey rsa:2048 -nodes -subj "/CN=localhost" -keyout server.key -out server.csr
printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\n' "$SANS" > server.ext
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 825 \
    -extfile server.ext -out server.pem
rm server.csr server.ext ca.srl
chmod 644 server.key  # must be readable by the rabbitmq user in its container (dev only)
echo "created CA and server certificate for $SANS in $DIR"
