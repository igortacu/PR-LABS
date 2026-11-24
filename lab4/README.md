# Lab 4: A message broker in Java

This project has two versions of the same broker: Part 1 uses Java's built-in
`HttpServer`; Part 2 uses gRPC. There is no existing message broker or web
framework. Both versions use `Broker.java`, which keeps messages, assigns IDs,
saves them to disk, and delivers them through one queue per topic.

## Build

Install Java 17 or newer and Maven. From the repository root:

```sh
mvn -f lab4/pom.xml package
cp lab4/tokens.example.txt lab4/tokens.txt
```

Edit `lab4/tokens.txt` if you want different tokens. Each line is
`token|publisher-name|topic1,topic2`. The tokens file is ignored by Git.
The `.proto` Java classes are generated during the Maven build.

## TLS certificate

Both brokers use TLS, so tokens and messages are encrypted on the network.
On the broker computer, choose a keystore password and create the certificate
for the broker's LAN IP address (add more IPs if it has several):

```sh
export KEYSTORE_PASSWORD='choose-a-password'
sh lab4/make-cert.sh BROKER_IP
```

This creates `lab4/certs/broker.p12` (the private key; it stays on the broker
computer) and `lab4/certs/broker.crt` (public; copy it to the same path on every
client computer). Both are ignored by Git. Clients must connect with
`127.0.0.1`, `localhost` or an IP given to the script, because the certificate
is valid only for those names. The broker needs `KEYSTORE_PASSWORD` in the
terminal where it runs. Publishers read their token from `BROKER_TOKEN`, not
from the command line, so it does not show up in the process list.

## Part 1: HTTP

Run each command in a separate terminal from the repository root. Replace
`BROKER_IP` with the broker computer's LAN IP address for other computers.
Use `127.0.0.1` when all programs are on your computer.

```sh
KEYSTORE_PASSWORD='choose-a-password' mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.HttpBroker -Dexec.args='8000 lab4/data/http.json lab4/tokens.txt lab4/certs/broker.p12'
mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.HttpSubscriber -Dexec.args='https://BROKER_IP:8000 grades lab4/certs/broker.crt'
BROKER_TOKEN=teacher-secret mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.HttpPublisher -Dexec.args='https://BROKER_IP:8000 grades teacher lab4/certs/broker.crt'
```

To try it with curl, pass the certificate: `curl --cacert lab4/certs/broker.crt https://BROKER_IP:8000/topics`.

Type a line in the publisher terminal and press Enter. Start a second publisher
and subscriber in two more terminals to demonstrate concurrency. The HTTP API is:

| Request | Result |
| --- | --- |
| `POST /topics/{topic}/messages` | JSON `sender` and `body`; returns 202 and the full message |
| `GET /topics/{topic}/stream` | open newline-delimited JSON stream |
| `GET /topics` | topic names and stored message counts |

Publishing requires the header `Authorization: Bearer token`. A missing or
unknown token gets HTTP 401; a valid token for the wrong sender or topic gets
HTTP 403. The stream sends a blank line every 10 seconds to notice disconnects.
The log removes control characters such as newlines from every field, so a
client cannot add fake lines to it. A storage failure gives the client only a
short error; the details go to the broker's error output.

## Part 2: gRPC

Stop the HTTP broker before starting this example, or use the separate data
file shown below. gRPC has its own port and only the calls in `broker.proto`.

```sh
KEYSTORE_PASSWORD='choose-a-password' mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.GrpcBroker -Dexec.args='50051 lab4/data/grpc.json lab4/tokens.txt lab4/certs/broker.p12'
mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.GrpcSubscriber -Dexec.args='BROKER_IP:50051 grades lab4/certs/broker.crt'
BROKER_TOKEN=teacher-secret mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.GrpcPublisher -Dexec.args='BROKER_IP:50051 grades teacher lab4/certs/broker.crt'
```

Missing and unknown tokens get `UNAUTHENTICATED`; tokens for another sender or
topic get `PERMISSION_DENIED`. The gRPC subscriber receives a server stream.

## Restart and testing

Stop and restart a broker with the same data file. Its messages and next IDs
remain. Each publish writes a temporary file and atomically replaces the old
one. Subscribers receive new messages while connected; saved messages are not
replayed when they reconnect.

```sh
mvn -f lab4/pom.xml test
```

You do not need a colleague's laptop to build or test the lab. The handout asks
for a defense demo with two publishers and two subscribers on **two computers**.
For that demo you need a second computer, which can be a colleague's laptop.
Both computers need the project and a network connection to the broker port.
