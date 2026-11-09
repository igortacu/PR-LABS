# Lab 2: Coffee shop over TCP

This is the networking half of the Java implementation. The shop logic belongs
in a class that implements `prlabs.coffee.ShopService`; see that interface for
the exact contract. No external libraries or network frameworks are used.

## Build

Use Java 17 or newer, from the repository root:

```sh
mkdir -p lab2/out
javac --release 17 -d lab2/out $(find lab2/src -name '*.java')
```

To check the socket layer with a fake shop implementation:

```sh
javac --release 17 -d lab2/out $(find lab2/src lab2/test -name '*.java')
java -cp lab2/out prlabs.coffee.NetworkSmokeTest
```

After adding your `ShopService` implementation, start the server on computer A:

```sh
java -cp lab2/out prlabs.coffee.Server 5000 prlabs.coffee.YourShopService
```

Start the programs on computer B, replacing `192.168.1.10` with computer A's
local IP address:

```sh
java -cp lab2/out prlabs.coffee.ConsolePeer client 192.168.1.10 5000
java -cp lab2/out prlabs.coffee.ConsolePeer provider 192.168.1.10 5000
```

Both computers need Java and a copy of the same repository. They must be on a
network that permits TCP connections to the chosen port. The server binds to
all local interfaces. `localhost` connects only to the same computer.

## Console commands and wire protocol

Enter `menu`, `order coffee=1 tea=2`, or `quit` in the client. Enter `menu`,
`deliver coffee=20 croissant=10`, or `quit` in the provider. The console
normalizes only the command word to uppercase; the server validates all input.

Each wire message is one strict UTF-8 line ending with LF, with a maximum of
4096 bytes before LF. The first message is `ROLE CLIENT` or `ROLE PROVIDER`.
The server sends `OK CLIENT` or `OK PROVIDER`. There can be one provider at a
time. Later commands are `MENU`, `ORDER product=quantity ...`,
`DELIVER product=quantity ...`, and `QUIT`. Product names are lowercase.

Responses include `MENU coffee=... tea=... croissant=...`,
`ACCEPTED <order-id> <preparation-seconds>`, `REFUSED` followed by available
stock, `READY <order-id>`, `DELIVERED` followed by delivered items,
`ALERT product=quantity`, `ERROR <reason>`, and `BYE`. The connection also
exchanges `PING` and `PONG` to detect silent network failures. These messages
are hidden by the console program.

The TCP reader preserves partial lines across socket timeouts, handles several
lines in one receive, rejects malformed UTF-8, and discards oversized lines.
Sends from a worker and a connection thread are serialized per socket.

## Shop logic contract

Your implementation should initialize each product with a random stock from
10 to 50 and start one worker per `Runtime.getRuntime().availableProcessors()`.
It should use a FIFO queue. `placeOrder` must check and reserve the entire
order atomically, returning `Accepted` or `Refused` with a stock snapshot.
Workers prepare an entire order, then call `whenReady.accept(orderId)` once.
`cancelClient` must stop any running preparation, remove queued orders, and
refund each canceled order exactly once. `deliver` adds all quantities
atomically. Call the stock-change listener after each stock mutation, outside
your stock lock. `stockSnapshot` and `Refused.available` must be stable copies.

The server guarantees an `ACCEPTED` response is sent before a worker's `READY`
notification for that order. It calls `cancelClient` when a client disconnects,
including after a heartbeat timeout. The shop implementation must make its
own methods thread-safe because several connection threads call them.

## Working on two computers

Use the same Git repository. One person owns the shop implementation; the
other owns the protocol and socket programs. Agree on changes to
`ShopService` before changing it. Each person works on a separate branch,
pushes small changes, and reviews the other's pull request. After merging,
both pull and run the same commit. At the defense, explain both sides of the
contract, not only the files you wrote.
