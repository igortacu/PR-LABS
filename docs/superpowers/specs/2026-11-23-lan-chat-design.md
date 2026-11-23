# LAN Chat Design

## Intent

Build the complete Python laboratory work described by "Laboratory Work 3: A Local Network Chat". The result must be understandable at a defense, work between at least two computers on one LAN, and support several peers on one computer without a server.

## Scope

- One interactive console peer implemented with Python's low-level `socket` module.
- UDP broadcast for the general channel and discovery.
- UDP unicast to a per-peer endpoint for private traffic.
- Join, presence response, heartbeat, graceful leave, and timeout-based leave detection.
- Unique usernames, including deterministic resolution of simultaneous startup conflicts.
- Commands: ordinary general text, `/msg name text`, `/users`, and `/quit`.
- Maximum message length of 500 characters and maximum wire datagram size of 1400 bytes.
- One structured log line for every sent, received, and dropped datagram.
- Strict, versioned JSON datagrams; malformed, oversized, unknown, and inconsistent datagrams are dropped without crashing.
- Passphrase-derived shared key using Scrypt; private text encrypted and authenticated using ChaCha20-Poly1305 with a fresh random nonce.
- Automated unit and loopback integration tests plus clear two-computer instructions.
- Defense notes answering every task and control question.

## Architecture

Each peer owns two sockets. The shared socket binds `0.0.0.0:<chat-port>` with address/port reuse and receives broadcast general and discovery traffic. The private socket binds `0.0.0.0:0`, giving that process a unique unicast port; peers advertise this endpoint during discovery, so private messages reach the intended process even when many peers share one computer.

Incoming datagrams are handled by receiver threads and periodic presence work by a maintenance thread. The main thread owns the prompt. A lock keeps console output and mutable peer state coherent. A short startup discovery interval gives existing peers time to answer before the user can chat.

Every message has protocol/version, type, sender name, sender UUID, and the sender's private port. Broadcast messages also have a message UUID for self/deduplication. Private datagrams carry a random nonce and authenticated ciphertext. The stable chat port is included as associated authenticated data so ciphertext cannot be transplanted between differently configured chats unnoticed.

## User-visible defaults and constraints

- Run as `python -m lan_chat NAME PORT PASSPHRASE`.
- Python 3.10 or newer.
- One external runtime dependency: `cryptography`.
- Heartbeat every 5 seconds; absent after 15 seconds; startup discovery lasts up to 1 second.
- Broadcast target defaults to `255.255.255.255` and can be overridden for difficult networks.
- Logs are written to `logs/<safe-name>-<peer-id>.log` unless overridden.
- The program provides actionable errors for a used name, unavailable user, long text, oversized datagram, socket failure, and bad command.

## Non-goals

- TCP-style guaranteed delivery, ordering, retries, or acknowledgements.
- End-to-end privacy from other members who know the shared passphrase.
- Internet/NAT traversal, accounts, history synchronization, GUI, or server infrastructure.

## Quality bar

The repository must include executable code, automated tests, installation and run instructions for two computers, troubleshooting guidance, protocol documentation, demonstration steps, and complete defense answers. Tests must cover invalid network input and actual UDP socket exchanges, not only pure helper functions.
