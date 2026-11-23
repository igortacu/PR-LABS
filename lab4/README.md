# Lab 4: A message broker

This implements both defenses: Part 1 with Python's standard-library HTTP server,
and Part 2 with gRPC. Each transport has a broker, publisher, and subscriber
console program. Both brokers use `broker_core.py` for durable topics, ordered
background delivery, and token checks. Run **one broker at a time** against a
given data file; two broker processes do not coordinate writes to that file.

## Setup

Use Python 3.10 or newer. From the repository root:

```sh
python3 -m venv lab4/.venv
lab4/.venv/bin/python -m pip install -r lab4/requirements.txt
lab4/.venv/bin/python -m grpc_tools.protoc -I lab4 --python_out=lab4 --grpc_python_out=lab4 lab4/broker.proto
cp lab4/tokens.example.json lab4/tokens.json
```

Edit `lab4/tokens.json` to choose private tokens, publisher names, and their
allowed topics. Do not commit that file. Generated `broker_pb2.py` and
`broker_pb2_grpc.py` are included, so generation is needed only if you change
the contract. HTTP programs need only the Python standard library.

## Part 1: HTTP

On the broker computer:

```sh
python3 lab4/broker_http.py --host 0.0.0.0 --port 8000
```

On one or more computers, replace `BROKER_IP` with the broker computer's LAN
address. Run two subscribers and two publishers in separate terminals:

```sh
python3 lab4/subscriber_http.py http://BROKER_IP:8000 grades
python3 lab4/publisher_http.py http://BROKER_IP:8000 grades teacher --token teacher-secret
```

Type a line and press Enter to publish it. The API returns JSON:

- `POST /topics/{topic}/messages` with `{"sender":"teacher","body":"Hello"}`
  and `Authorization: Bearer teacher-secret` returns 202 and the saved message.
- `GET /topics/{topic}/stream` returns an open chunked NDJSON stream. Blank
  heartbeat lines are sent every 10 seconds.
- `GET /topics` returns `{"topics":[{"topic":"grades","size":1}]}`.

## Part 2: gRPC

Use a separate data file from HTTP if both are running:

```sh
lab4/.venv/bin/python lab4/broker_grpc.py --host 0.0.0.0 --port 50051 --data lab4/data/grpc.json
lab4/.venv/bin/python lab4/subscriber_grpc.py BROKER_IP:50051 grades
lab4/.venv/bin/python lab4/publisher_grpc.py BROKER_IP:50051 grades teacher --token teacher-secret
```

`broker.proto` defines `Publish`, streaming `Subscribe`, and `ListTopics`.
gRPC metadata uses `authorization: Bearer token`. A missing or unknown token
returns `UNAUTHENTICATED`; a valid token for the wrong sender or topic returns
`PERMISSION_DENIED`. HTTP returns 401 with `WWW-Authenticate: Bearer` or 403.

The broker keeps all messages in a JSON file. Every publish rewrites a temporary
file, syncs it, and atomically replaces the old file before returning. IDs
continue after a restart. Subscriptions receive new messages while connected;
past messages remain on disk and count in `ListTopics` but are not replayed.

## Verify

```sh
lab4/.venv/bin/python -m unittest discover -s lab4 -p 'test_*.py' -v
```

The tests use loopback sockets, so **you do not need your colleagues' laptop to
build or test the lab**. The handout explicitly asks you to demonstrate two
publishers and two subscribers on **two computers** at the defense. For that
demonstration, you do need a second computer (a colleague's laptop is one
option), both computers on a network that can reach the broker's port, and a
copy of the relevant client files and dependencies on that computer.
