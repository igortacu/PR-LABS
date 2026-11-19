# Lab 2: Coffee shop over TCP

The server and shop logic are written in Java 17. The interactive client and
provider are written in Python 3.10 or newer. Both sides use the language's
plain socket API and a shared text protocol, with no network framework or
third-party dependency.

## Build and run on two computers

On computer A, from the repository root:

```sh
mkdir -p lab2/out
javac --release 17 -d lab2/out $(find lab2/src -name '*.java')
java -cp lab2/out prlabs.coffee.Server 5000
```

On computer B, replace `192.168.1.10` with computer A's LAN IP address:

```sh
python3 lab2/python/coffee_peer.py client 192.168.1.10 5000
python3 lab2/python/coffee_peer.py provider 192.168.1.10 5000
```

Both computers need a copy of the repository and must be able to connect over
TCP port `5000`. The server listens on all local interfaces. `localhost` works
only when the client and server run on the same computer. The Python program
prints `[TRACE]` connection and application-message events to standard error.
Use `--no-trace` to hide all trace events.

## Commands and wire protocol

The client accepts `menu`, `order coffee=1 tea=2`, and `quit`. The provider
accepts `menu`, `deliver coffee=20 croissant=10`, and `quit`. The program
uppercases only the command word; the server validates all input.

Each wire message is a strict UTF-8 line ending with the byte `\n`, with at
most 4096 bytes before it. TCP can split one message across several receives
or combine several messages in one receive, so both implementations buffer
bytes until a complete line is available.

The first message is `ROLE CLIENT\n` or `ROLE PROVIDER\n`. The server replies
`OK CLIENT` or `OK PROVIDER`. There can be only one provider connection at a
time. Later messages are:

| Request | Response |
| --- | --- |
| `MENU` | `MENU coffee=12 tea=20 croissant=8` |
| `ORDER coffee=1 tea=2` | `ACCEPTED 7 10` immediately, then `READY 7` later |
| Order exceeding stock | `REFUSED coffee=0 tea=20 croissant=8` |
| `DELIVER coffee=20 croissant=10` from provider | `DELIVERED coffee=20 croissant=10` |
| Invalid input | `ERROR` followed by the reason |
| `QUIT` | `BYE` |

The server sends `ALERT coffee=4` to the provider when stock falls below five,
or when a provider connects while stock is already low. Client and provider
programs receive server messages while keyboard input remains available.

## Server behavior

`InMemoryShop` starts with a random quantity from 10 through 50 of each
product. Coffee takes four seconds, tea three, and croissants two. The time
for an order is the sum of its item times. The server starts one preparation
worker per logical processor. Client connection threads atomically check and
reserve stock, then add accepted orders to a thread-safe FIFO queue. Each
worker prepares one whole order. New orders can be accepted while workers
are busy.

At startup, the server logs its worker count. When all worker slots are already
occupied, an accepted order also gets an `Order queued` log line with its
position at acceptance. For example, with eight workers, the ninth concurrent
order is logged at queue position 1. A refusal means insufficient stock, not a
full worker pool.

`stateLock` protects stock, reserved quantities, order states, client-to-order
records, and the next order ID. The blocking queue protects its own
operations. No stock lock is held during preparation. On client disconnect,
queued and preparing orders are canceled and refunded once; a per-order
latch wakes a preparing worker. A replacement order waits its full time.
Provider deliveries are atomic. The server logs connections, accepted,
refused and ready orders, deliveries, and errors with the remote endpoint.
Closed and reset connections are detected when the socket read fails or returns
end-of-stream. Both sides enable TCP keepalive; a silent network loss may take
longer to detect.

`LineChannel` handles split and combined TCP messages, malformed UTF-8,
oversized messages, and serialized writes to a socket. The server sends
`ACCEPTED` before `READY`, even if a worker finishes quickly.

## Tests

```sh
javac --release 17 -d lab2/out $(find lab2/src lab2/test -name '*.java')
java -cp lab2/out prlabs.coffee.InMemoryShopTest
java -cp lab2/out prlabs.coffee.NetworkSmokeTest
java -cp lab2/out prlabs.coffee.RealServerIntegrationTest
python3 -m unittest discover -s lab2/test_python -v
java -cp lab2/out prlabs.coffee.PythonInteropSmokeTest
```

The Java shop tests use a shorter clock and fixed stock. The production
constructor uses real seconds and random stock.
