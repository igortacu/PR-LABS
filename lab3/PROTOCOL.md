# LAN Chat Wire Protocol v1

This document is sufficient for an independent implementation to interoperate with this Python chat.

## Transport

- IPv4 UDP only.
- UTF-8 JSON, one JSON object per datagram.
- Compact JSON is used, but field order is irrelevant.
- Maximum datagram: 1400 bytes.
- Maximum user text: 500 Unicode characters, subject to the 1400-byte wire limit.
- Broadcast destination: configured broadcast address and shared chat port.
- Unicast destination: source IP learned from UDP plus `private_port` advertised by that peer.

## Common fields

Every object contains exactly these common fields plus the fields specified for its type:

| Field | Type | Meaning |
|---|---|---|
| `protocol` | string | Always `lan-chat` |
| `version` | integer | Always `1` |
| `type` | string | One of the types below |
| `sender` | string | Unique name, 1-32 characters, no whitespace |
| `sender_id` | string | Canonical random UUID identifying one process |
| `private_port` | integer | Sender's unique unicast UDP port, 1-65535 |

Unknown, missing, or extra fields make a datagram invalid.

## Message types

### Broadcast control

- `join`: common fields only. Sent once when starting.
- `heartbeat`: common fields only. Sent every 5 seconds after joining.
- `leave`: common fields only. Sent by `/quit` before sockets close.

### Unicast discovery

- `presence`: common fields plus `target_id` (UUID of the joining peer). Existing peers send it immediately to a joiner's private endpoint.
- `conflict`: common fields plus `target_id` and `name`. It tells that target that its requested name is already used.

### General channel

`general` is broadcast and has:

```json
{
  "protocol": "lan-chat",
  "version": 1,
  "type": "general",
  "sender": "Ana",
  "sender_id": "d64ed6a7-f9ec-4625-84c8-61bd08f44e5c",
  "private_port": 49152,
  "message_id": "3c58de63-8b0d-4d34-8385-a721b70a5bce",
  "text": "hello everyone"
}
```

The sender records `message_id` before broadcasting and displays the text locally after `sendto`. Its returned broadcast is recognized by `sender_id`/`message_id` and is not displayed twice. Receivers keep a bounded message-ID cache to suppress duplicates.

### Private channel

`private` is sent to exactly one advertised private endpoint and adds:

| Field | Meaning |
|---|---|
| `message_id` | Random canonical UUID |
| `recipient` | Destination username |
| `nonce` | Base64 encoding of a fresh 12-byte random nonce |
| `ciphertext` | Base64 ChaCha20-Poly1305 ciphertext including its 16-byte tag |

The key is derived with Scrypt:

```text
passphrase bytes = UTF-8(passphrase)
salt = first 16 bytes of SHA-256("lan-chat-v1|port=<decimal chat port>")
Scrypt parameters: N=16384, r=8, p=1, output length=32
```

ChaCha20-Poly1305 associated data is the UTF-8 encoding of these values joined by `|` in this exact order:

```text
chat_port|sender|sender_id|private_port|recipient|message_id
```

The receiver validates the outer schema, checks that `recipient` is its own name, reconstructs associated data, verifies/decrypts, decodes UTF-8, and applies the 500-character text validation. Authentication failure drops the datagram.

## Discovery and liveness

1. Bind the shared socket to `0.0.0.0:<chat-port>` with address reuse, port reuse when available, and broadcast enabled.
2. Bind the private socket to `0.0.0.0:0` and record the assigned port.
3. Start both receive loops, broadcast `join`, and wait up to one second for replies.
4. Each existing peer adds the joiner's `(source IP, private_port)`, displays its join, and unicasts `presence` immediately.
5. The joiner adds every valid targeted presence reply.
6. Broadcast `heartbeat` every 5 seconds. Remove a peer after 15 seconds without a valid message.

If an already joined peer sees its own name in another join, it unicasts `conflict`. If two same-name peers are both starting, the lexicographically smaller `sender_id` wins; this deterministic rule prevents both from believing they won.

UDP provides no delivery guarantee. The protocol intentionally has no acknowledgement/retry for chat messages; the defense notes explain how it could be added.
