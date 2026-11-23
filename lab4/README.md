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

## Part 1: HTTP

Run each command in a separate terminal from the repository root. Replace
`BROKER_IP` with the broker computer's LAN IP address for other computers.
Use `127.0.0.1` when all programs are on your computer.

```sh
mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.HttpBroker -Dexec.args='8000 lab4/data/http.json lab4/tokens.txt'
mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.HttpSubscriber -Dexec.args='http://BROKER_IP:8000 grades'
mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.HttpPublisher -Dexec.args='http://BROKER_IP:8000 grades teacher teacher-secret'
```

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

## Part 2: gRPC

Stop the HTTP broker before starting this example, or use the separate data
file shown below. gRPC has its own port and only the calls in `broker.proto`.

```sh
mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.GrpcBroker -Dexec.args='50051 lab4/data/grpc.json lab4/tokens.txt'
mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.GrpcSubscriber -Dexec.args='BROKER_IP:50051 grades'
mvn -q -f lab4/pom.xml exec:java -Dexec.mainClass=prlabs.broker.GrpcPublisher -Dexec.args='BROKER_IP:50051 grades teacher teacher-secret'
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
