#!/usr/bin/env python3
"""Interactive Python client/provider for the Java coffee-shop server."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
from typing import TextIO


MAX_LINE_BYTES = 4096


class InvalidFrameError(Exception):
    """A complete incoming protocol message was not valid."""


class LineChannel:
    """Bounded UTF-8, LF-framed messages over a plain TCP socket."""

    def __init__(self, connection: socket.socket):
        self._connection = connection
        self._buffer = bytearray()
        self._discarding_long_frame = False
        self._send_lock = threading.Lock()

    def read_line(self) -> str | None:
        """Read one message, or return None after a clean peer shutdown."""
        while True:
            if self._discarding_long_frame:
                newline = self._buffer.find(b"\n")
                if newline >= 0:
                    del self._buffer[: newline + 1]
                    self._discarding_long_frame = False
                else:
                    self._buffer.clear()
                    data = self._connection.recv(4096)
                    if not data:
                        raise ConnectionError("Connection ended in the middle of a message")
                    self._buffer.extend(data)
                continue

            newline = self._buffer.find(b"\n")
            if newline >= 0:
                frame = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                if len(frame) > MAX_LINE_BYTES:
                    raise InvalidFrameError("Message too long")
                if frame.endswith(b"\r"):
                    frame = frame[:-1]
                try:
                    return frame.decode("utf-8", errors="strict")
                except UnicodeDecodeError as error:
                    raise InvalidFrameError("Invalid UTF-8") from error

            if len(self._buffer) > MAX_LINE_BYTES:
                self._buffer.clear()
                self._discarding_long_frame = True
                raise InvalidFrameError("Message too long")

            data = self._connection.recv(4096)
            if not data:
                if self._buffer:
                    raise ConnectionError("Connection ended in the middle of a message")
                return None
            self._buffer.extend(data)

    def send(self, line: str) -> None:
        """Send exactly one message without interleaving concurrent writers."""
        if "\n" in line or "\r" in line:
            raise ValueError("Protocol message contains a newline")
        encoded = line.encode("utf-8")
        if len(encoded) > MAX_LINE_BYTES:
            raise ValueError("Message too long")
        with self._send_lock:
            self._connection.sendall(encoded + b"\n")


def normalize_command(line: str) -> str:
    """Trim input and uppercase only its command word."""
    trimmed = line.strip()
    if not trimmed:
        return ""
    command, separator, arguments = trimmed.partition(" ")
    return command.upper() + (separator + arguments if separator else "")


def run_peer(
    role: str,
    host: str,
    port: int,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
    trace: bool = True,
) -> int:
    """Connect and run the interactive receive/keyboard loops."""
    normalized_role = role.lower()
    if normalized_role not in {"client", "provider"}:
        print("Role must be client or provider", file=error_stream, flush=True)
        return 2

    endpoint = f"{host}:{port}"

    def write_trace(event: str) -> None:
        if trace:
            print(f"[TRACE] {event}", file=error_stream, flush=True)

    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    connection.settimeout(5)
    try:
        connection.connect((host, port))
    except OSError as error:
        print(f"Could not connect to {endpoint}: {error}", file=error_stream, flush=True)
        connection.close()
        return 1
    connection.settimeout(None)

    write_trace(f"CONNECT {endpoint}")
    channel = LineChannel(connection)
    stop = threading.Event()

    def send(message: str) -> None:
        channel.send(message)
        write_trace(f"SEND {message}")

    def read_keyboard() -> None:
        try:
            for line in input_stream:
                if stop.is_set():
                    return
                message = normalize_command(line)
                if not message:
                    continue
                try:
                    send(message)
                except ValueError as error:
                    print(f"Invalid input: {error}", file=error_stream, flush=True)
                    continue
                if message == "QUIT":
                    return
            if not stop.is_set():
                send("QUIT")
        except OSError as error:
            if not stop.is_set():
                print(f"Input/send error: {error}", file=error_stream, flush=True)

    exit_code = 0
    try:
        send(f"ROLE {normalized_role.upper()}")
        example = "order coffee=1 tea=2" if normalized_role == "client" else "deliver coffee=20 tea=10"
        print(f"Connected. Commands: menu, {example}, quit", file=output_stream, flush=True)

        keyboard = threading.Thread(target=read_keyboard, name="keyboard", daemon=True)
        keyboard.start()

        while True:
            try:
                message = channel.read_line()
            except InvalidFrameError as error:
                print(f"Invalid server message: {error}", file=error_stream, flush=True)
                continue
            if message is None:
                print("Server disconnected.", file=output_stream, flush=True)
                break

            write_trace(f"RECV {message}")
            print(message, file=output_stream, flush=True)
            if message == "BYE":
                break
    except (ConnectionError, OSError) as error:
        print(f"Connection lost: {error}", file=error_stream, flush=True)
        exit_code = 1
    finally:
        stop.set()
        connection.close()
        write_trace(f"CLOSE {endpoint}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coffee-shop TCP client/provider")
    parser.add_argument("role", choices=("client", "provider"))
    parser.add_argument("server_address")
    parser.add_argument("port", type=int)
    parser.add_argument("--no-trace", action="store_true", help="hide TCP send/receive traces")
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.port <= 65535:
        parser.error("port must be between 1 and 65535")
    return run_peer(
        arguments.role,
        arguments.server_address,
        arguments.port,
        trace=not arguments.no_trace,
    )


if __name__ == "__main__":
    raise SystemExit(main())
