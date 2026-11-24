#!/bin/sh
# Creates the broker's TLS keystore (private, stays on the broker computer)
# and broker.crt (public, copied to every client computer).
# Usage: KEYSTORE_PASSWORD=... sh lab4/make-cert.sh BROKER_IP [MORE_IPS...]
set -e
if [ -z "$KEYSTORE_PASSWORD" ] || [ $# -lt 1 ]; then
  echo "Usage: KEYSTORE_PASSWORD=... sh lab4/make-cert.sh BROKER_IP [MORE_IPS...]" >&2
  exit 1
fi
dir="$(dirname "$0")/certs"
mkdir -p "$dir"
rm -f "$dir/broker.p12" "$dir/broker.crt"

# The certificate is valid only for these names, so clients must use one of them.
san="dns:localhost,ip:127.0.0.1"
for ip in "$@"; do san="$san,ip:$ip"; done

keytool -genkeypair -alias broker -keyalg RSA -keysize 2048 -validity 365 \
  -dname "CN=lab4-broker" -ext "SAN=$san" \
  -keystore "$dir/broker.p12" -storetype PKCS12 -storepass:env KEYSTORE_PASSWORD
keytool -exportcert -rfc -alias broker \
  -keystore "$dir/broker.p12" -storepass:env KEYSTORE_PASSWORD -file "$dir/broker.crt"
echo "Created $dir/broker.p12 (keep private) and $dir/broker.crt (give to clients) for $san"
