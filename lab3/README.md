# Laboratory Work 3 - A Local Network Chat

A serverless console chat for a local network, implemented directly with Python UDP sockets. Every running copy is an equal peer: it broadcasts general messages and discovery traffic, while private messages are encrypted and sent only to the intended peer's unique UDP endpoint.

The implementation completes Tasks 1-4 from the assignment and is intended for the grade-10 defense. Read [PROTOCOL.md](PROTOCOL.md) for the datagram format and [DEFENSE.md](DEFENSE.md) for the questions and answers.

## Requirements

- Python 3.10 or newer
- Computers connected to the same LAN, Wi-Fi, or phone hotspot
- Permission for Python to receive UDP traffic through the operating-system firewall

The program uses Python's low-level `socket` module directly. The only external package is `cryptography`, used for Scrypt and ChaCha20-Poly1305.

## Installation

Run these commands from the repository's `lab3` directory.

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run on two computers

Choose one UDP chat port and one passphrase. Use exactly the same values on every computer, but a different username.

Computer 1:

```bash
python run_chat.py Ana 5000 "laboratory shared secret"
```

Computer 2:

```bash
python run_chat.py Ion 5000 "laboratory shared secret"
```

For the required three-peer demonstration, start another terminal on either computer:

```bash
python run_chat.py Maria 5000 "laboratory shared secret"
```

The positional command-line parameters are `NAME PORT PASSPHRASE`. Usernames are unique, contain no whitespace, and have at most 32 characters. All peers in one chat use the same port. A peer waits at most one second for discovery and name-conflict replies before accepting input.

Do not use a valuable password as the passphrase: command-line arguments may be visible to other users of the computer. Use a strong, lab-specific phrase.

## Chat commands

```text
hello everyone          send one general broadcast datagram
/msg Ion see you at five
/users                  list the online names
/quit                   announce departure and exit
```

Example output:

```text
* Ion joined the chat
[general] Ion: hello everyone
[private] Ion: see you at five
* Ion left the chat
```

Messages have at most 500 characters. A message whose UTF-8 JSON representation would exceed the 1400-byte safety budget is rejected even when it has 500 characters. This avoids IP fragmentation on ordinary Ethernet/Wi-Fi networks.

## Broadcast selection and troubleshooting

The default destination is the limited broadcast address `255.255.255.255`. If the network does not forward it, pass the subnet's directed broadcast address on every peer. For example, an address `192.168.1.42` with mask `255.255.255.0` normally uses:

```bash
python run_chat.py Ana 5000 "laboratory shared secret" --broadcast 192.168.1.255
```

If peers do not discover one another:

1. Confirm they are on the same network and use the same chat port.
2. Confirm the broadcast address is correct; `255.255.255.255` or the subnet broadcast must be used by all peers.
3. Allow Python through Windows Defender Firewall, macOS Firewall, or the Linux firewall. The application needs the shared chat port and dynamically selected private UDP ports; allowing the Python application is simpler than opening one port.
4. Disable VPNs temporarily because they may change broadcast routing.
5. Turn off Wi-Fi client/AP isolation, or use a phone hotspot as the assignment suggests.
6. Check `logs/` to see whether datagrams are sent, received, or dropped.

Only one peer receiving a private datagram is correct. A private socket has a unique operating-system-assigned port even though all peers share the general-channel port.

## Architecture

Each peer uses exactly two IPv4 UDP sockets:

1. **Shared broadcast socket** - bound to `0.0.0.0:<chat-port>` with address/port reuse. It receives general messages, joins, heartbeats, and leaves on every local peer.
2. **Unique private socket** - bound to `0.0.0.0:0`. The operating system assigns a different port to each process. Its port is advertised in discovery messages and receives presence replies, conflicts, and encrypted private messages.

Two receiver threads call `recvfrom` so messages appear immediately while the main thread is blocked in `input`. A maintenance thread sends a heartbeat every 5 seconds and removes a peer after 15 seconds without traffic. Shared state and output are protected by locks.

Every received datagram is decoded only after its 1400-byte limit, UTF-8, JSON, exact fields, protocol version, types, UUIDs, ports, and message-specific values are validated. Invalid input is logged and ignored; the receiver continues.

## Security model

Private text is protected by ChaCha20-Poly1305. A 256-bit key is derived from the shared passphrase with Scrypt and a deterministic salt bound to the chat port. Every private message uses a fresh 96-bit random nonce. Visible routing metadata is authenticated as associated data, so changing it causes decryption to fail.

This protects against outsiders who do not know the passphrase. It is not end-to-end secrecy between two members: every legitimate member who knows the shared passphrase can derive the same key. UDP metadata (addresses, sizes, timing, usernames, and general messages) remains visible.

## Logs

The default log name is `logs/<name>-<peer-id>.log`. Each line is an independent JSON object with:

- local timestamp with timezone;
- action: `sent`, `received`, or `dropped`;
- remote/destination IP and port;
- protocol message kind;
- datagram size;
- drop reason, when applicable.

Use `--log PATH` to choose another file. Logs do not contain decrypted private text or the passphrase.

## Automated verification

From the repository root, after installing the `lab3` virtual environment:

```bash
lab3/.venv/bin/python -m unittest discover -s lab3/tests -v
lab3/.venv/bin/python -m compileall -q lab3/lan_chat lab3/run_chat.py
lab3/.venv/bin/python lab3/run_chat.py --help
```

On Windows, replace `lab3/.venv/bin/python` with `lab3\.venv\Scripts\python.exe`.

The integration suite binds real UDP sockets and starts multiple peers. It verifies discovery, separate private ports, a single self-display for general messages, encrypted private unicast, invalid-input survival, duplicate-name rejection, graceful departure, and timeout departure.

## Project layout

```text
lab3/
  lan_chat/
    app.py          sockets, threads, discovery, messaging, lifecycle
    cli.py          argument parsing and interactive commands
    constants.py    assignment limits and intervals
    crypto.py       Scrypt and ChaCha20-Poly1305
    event_log.py    JSON Lines datagram audit log
    peers.py        thread-safe online directory
    protocol.py     strict JSON validation and encoding
  tests/            unit and real-socket integration tests
  DEFENSE.md        assignment and control-question answers
  PROTOCOL.md       interoperable wire-format specification
  requirements.txt
  run_chat.py
```

## Demonstration checklist

1. Connect two computers to the same LAN/hotspot.
2. Start Ana and Ion on different computers, then Maria in a second terminal.
3. Show all three names with `/users`.
4. Send one general message and show it once on all three peers.
5. Send `/msg Ion secret` and show that only Ion receives it.
6. Try a duplicate username and show that it refuses to join.
7. Quit one peer normally and show the immediate leave notice.
8. Terminate one peer without `/quit` and show its timeout after 15 seconds.
9. Open two log files and identify sent, received, and dropped records.
10. Explain both sockets and the protocol using `PROTOCOL.md` and `DEFENSE.md`.
