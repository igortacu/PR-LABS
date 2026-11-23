"""Command-line interface for the LAN chat."""

from __future__ import annotations

import argparse
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .app import ChatError, LanChatPeer, NameInUseError
from .constants import DEFAULT_BROADCAST_ADDRESS


class CommandError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    action: str
    target: str | None = None
    text: str | None = None


def parse_command(line: str) -> ParsedCommand:
    if not isinstance(line, str) or not line:
        raise CommandError("enter a message or command")
    if not line.startswith("/"):
        return ParsedCommand("general", text=line)
    if line == "/users":
        return ParsedCommand("users")
    if line == "/quit":
        return ParsedCommand("quit")
    if line.startswith("/msg "):
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return ParsedCommand("private", target=parts[1], text=parts[2])
        raise CommandError("usage: /msg NAME TEXT")
    raise CommandError("unknown command; use /msg, /users, or /quit")


class Console:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def write(self, text: str) -> None:
        with self._lock:
            print(f"\r{text}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lan_chat",
        description="Serverless UDP chat for computers on the same LAN.",
    )
    parser.add_argument("name", help="unique username (no spaces, at most 32 characters)")
    parser.add_argument("port", type=int, help="shared chat UDP port (same on every peer)")
    parser.add_argument("passphrase", help="shared passphrase used for private-message encryption")
    parser.add_argument(
        "--broadcast",
        default=DEFAULT_BROADCAST_ADDRESS,
        help="broadcast address (default: %(default)s; a subnet broadcast may work better)",
    )
    parser.add_argument("--log", type=Path, help="custom datagram log path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    try:
        peer = LanChatPeer(
            args.name,
            args.port,
            args.passphrase,
            broadcast_address=args.broadcast,
            log_path=args.log,
            on_event=console.write,
        )
        peer.start()
    except NameInUseError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError, ChatError) as error:
        print(f"Error: could not start chat: {error}", file=sys.stderr)
        return 2

    print(f"Joined as {peer.name}; chat port {peer.port}; private UDP port {peer.private_port}.")
    print("Commands: /msg NAME TEXT, /users, /quit")
    try:
        while True:
            try:
                command = parse_command(input("> "))
                if command.action == "general":
                    peer.send_general(command.text or "")
                elif command.action == "private":
                    peer.send_private(command.target or "", command.text or "")
                elif command.action == "users":
                    print("Online: " + ", ".join(peer.online_users()))
                elif command.action == "quit":
                    break
            except CommandError as error:
                print(f"Error: {error}")
            except (ValueError, ChatError, OSError) as error:
                print(f"Error: {error}")
    except (EOFError, KeyboardInterrupt):
        print()
    finally:
        peer.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
