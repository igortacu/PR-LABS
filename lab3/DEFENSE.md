# Defense Guide

The best preparation is to trace one general message and one private message through `app.py`, then explain why the program owns two sockets. The answers below match this implementation rather than describing a hypothetical chat.

## Task 1 - The general channel

### 1. Why bind to `0.0.0.0`, not one IP or `127.0.0.1`?

`0.0.0.0` means all local IPv4 interfaces. A datagram arriving through Wi-Fi, Ethernet, or loopback can reach the socket. Binding to one interface address excludes traffic arriving on another. `127.0.0.1` is loopback-only and can communicate only with processes on the same computer, so a second computer could not join.

### 2. How can several peers bind the same port, and who receives general messages?

Before `bind`, the shared socket enables `SO_REUSEADDR` and, when the operating system supports it, `SO_REUSEPORT`. That permits several UDP sockets to bind `0.0.0.0:<chat-port>`. An incoming broadcast is copied to every matching shared socket, so every local peer receives the general message. Unicast behaves differently and normally selects one matching socket, which is why private traffic uses unique ports.

### 3. How is the peer's returned message recognized?

Every process has a random `sender_id` UUID and every general message has a `message_id`. The sender records the ID and displays the message once after a successful `sendto`. When the broadcast returns, its own `sender_id` is recognized and ignored. The message-ID cache also suppresses a duplicate datagram.

### 4. Why 500 characters, and what about 100,000?

The limit bounds memory, parsing time, UI abuse, and wire size. This implementation additionally rejects encoded datagrams over 1400 bytes. A 100,000-character message cannot fit in one UDP datagram: the maximum IPv4 UDP payload is about 65,507 bytes. Even a smaller large datagram would be fragmented at the IP layer; losing one fragment loses the whole message. The program rejects it instead of fragmenting it itself.

## Task 2 - Who is online

### 1. How does a new peer learn who is online, and how long does it take?

It starts both receive threads, broadcasts one `join`, and waits up to one second. Every existing peer immediately unicasts a targeted `presence` reply to the new peer's advertised private endpoint. The joiner records the reply's username, UUID, source IP, and private port. It usually learns the list in milliseconds and, by requirement, within the one-second startup window.

### 2. How is a killed peer noticed, and why not immediately like TCP?

Every peer broadcasts a heartbeat every 5 seconds. The directory stores a monotonic `last_seen` time and removes a peer after 15 seconds without a valid message. `/quit` is immediate because it broadcasts `leave`; a killed process cannot do that. UDP has no connection state or close handshake, so silence is indistinguishable from delay or packet loss until a timeout. TCP endpoints maintain connection state and detect FIN/RST or eventually a failed connection.

### 3. What if two peers start with the same name simultaneously?

Both see the other's join while in the startup state. They compare their random UUIDs lexicographically. The smaller UUID wins and sends a targeted conflict; the larger UUID loses and aborts startup. The rule is deterministic, so packet ordering does not allow both to stay.

## Task 3 - Private messages

### 1. How does a private message reach the correct peer when local peers share a port?

Only broadcast/discovery uses the shared chat port. Every process also binds a second UDP socket to `0.0.0.0:0`; the operating system gives it a unique ephemeral port. The peer advertises that port, and the directory pairs it with the source IP. `/msg` sends one unicast datagram to that unique endpoint, so the kernel selects the intended socket.

### 2. Why not broadcast private text with a receiver name inside?

Broadcast would deliver the supposedly private content to every peer and every network sniffer, waste bandwidth and CPU, and rely on applications to discard data they never needed. Unicast provides correct network-level delivery scope. Encryption then protects content from outsiders.

### 3. What if the recipient left one second ago?

If its leave datagram was received, the name has already been removed and the sender reports that it is offline. If the leave was lost or the process was killed, the directory can remain stale for up to 15 seconds. UDP `sendto` may still report success because it only queued the datagram locally; the datagram is then lost, or an ICMP error may be generated. There is no delivery confirmation in the current protocol.

### 4. How could a sender know a UDP private message arrived?

Add an `ack` datagram carrying the original `message_id`. The sender keeps an unacknowledged table and starts a timer. If no ACK arrives, it retransmits a limited number of times and then reports failure. The receiver must cache IDs and display each message only once because an ACK can be lost and cause a duplicate retransmission.

## Task 4 - Secure private messages

### 1. Why derive a key instead of using passphrase bytes directly?

Human passphrases have variable length and usually low entropy; ChaCha20-Poly1305 requires a uniform 32-byte key. Scrypt converts any UTF-8 passphrase into the required key and deliberately consumes memory and CPU, making offline dictionary guesses more expensive. Its salt is deterministic and bound to the protocol/chat port so equal inputs interoperate while different chat ports derive different keys.

### 2. Which algorithm is used, why must the nonce be unique, and where does it come from?

The program uses ChaCha20-Poly1305, an authenticated-encryption algorithm. Reusing a nonce with the same key reuses the stream cipher keystream, exposing relationships between plaintexts and undermining authentication. Every encryption obtains a fresh 12-byte nonce from the operating system's cryptographically secure `os.urandom`; it is sent in Base64 next to the ciphertext.

### 3. Who can read Ana and Ion's private message, and how could only they read it?

Every chat member knows the passphrase and derives the same symmetric key, so any member who captures the unicast can decrypt it. To restrict it to Ana and Ion, each peer needs a long-term or ephemeral public/private key pair, authenticated public-key discovery, and a pairwise shared secret (for example X25519 plus a KDF), ideally with a ratcheting session protocol.

### 4. Can an outsider change encrypted content unnoticed?

Not feasibly. Poly1305 supplies a 128-bit authentication tag. ChaCha20-Poly1305 verifies it before returning plaintext. The visible sender, recipient, UUIDs, ports, message ID, and chat port are included as associated authenticated data; changing ciphertext, nonce, or this metadata causes authentication failure and the datagram is dropped.

## Control questions

### 1. Which TCP promises does UDP omit, and which were rebuilt?

UDP does not promise delivery, ordering, duplicate suppression, a byte stream, flow/congestion control, connection establishment, or connection-close notification. The chat rebuilds peer discovery, application identity, duplicate suppression for general messages, liveness through heartbeats/timeouts, and clean departure through `leave`. It deliberately does not implement reliable delivery, ordering, retransmission, acknowledgements, congestion control, or sessions.

### 2. Why does one `sendto` correspond to one `recvfrom`, unlike TCP `send`/`receive`?

UDP is message-oriented: the datagram boundary is part of the transport abstraction. One successful `sendto` creates one datagram; one `recvfrom` returns that datagram (or truncates it if the receive buffer is too small). TCP is a byte stream: several sends can be combined into one receive, and one send can be split across receives. Therefore this UDP JSON protocol needs neither a delimiter nor a length prefix; the datagram boundary already frames one message.

### 3. How large can UDP be, and why stay below about 1400 bytes?

The UDP length field is 16 bits. For IPv4, subtracting the minimum 20-byte IP header and 8-byte UDP header leaves 65,507 payload bytes. Real Ethernet commonly has a 1500-byte MTU; IP/UDP headers and possible extra headers reduce the safe application budget. Staying at 1400 avoids IP fragmentation on typical networks. Fragmentation increases loss probability because every fragment is required and is often filtered.

### 4. Broadcast versus multicast; which is used?

Broadcast targets every IPv4 host on a local subnet or the limited local broadcast address. Receivers do not join a group, but routers normally do not forward it. Multicast targets a group address; interested sockets explicitly join the group and network equipment can limit delivery to members. This chat uses broadcast. A multicast version would choose an administratively scoped group, set multicast TTL/interface options, call `IP_ADD_MEMBERSHIP` on each shared socket, and send general/discovery traffic to the group instead of the broadcast address.

### 5. How many sockets are used and where are they bound?

Exactly two. The shared socket is bound to `0.0.0.0:<chat-port>` so it can receive broadcasts on every interface; reuse options allow every local peer to bind it. The private socket is bound to `0.0.0.0:0`, so the kernel assigns a unique port while still accepting traffic through any interface. The first is for broadcast control/general traffic; the second is for targeted discovery responses, conflicts, and private messages.

### 6. What does the UDP checksum protect, and why is it insufficient against an attacker?

The checksum covers the UDP header, payload, and an IP pseudo-header, detecting accidental bit errors and some misdelivery. It is not keyed. An attacker who changes a datagram can recompute the checksum, so it provides no authenticity. ChaCha20-Poly1305's secret-key authentication tag protects private messages against intentional modification.

## Code tour for a live defense

- `protocol.py`: explain exact-field validation, the 500-character check, compact JSON, and the 1400-byte check.
- `app.py::_open_sockets`: show both `socket`, `setsockopt`, and `bind` calls.
- `app.py::_receive_loop`: show `recvfrom`, invalid-datagram logging, and why the loop survives exceptions.
- `app.py::_handle_message`: trace join/presence/heartbeat/leave/general/private branches.
- `app.py::send_general`: one broadcast `sendto`, local display, and duplicate/self recognition.
- `app.py::send_private`: directory lookup, AEAD, and one unicast `sendto`.
- `crypto.py`: point to Scrypt parameters, random 12-byte nonce, and ChaCha20-Poly1305.
- `peers.py`: explain locking, immutable records, last-seen updates, expiry, and conflict arbitration.
- `event_log.py`: show one JSON line for each send/receive/drop.

Useful small defense changes to practise: add `/help`, change the heartbeat constant, add a timestamp to displayed chat text, or add a new harmless control message type together with its schema and test.
