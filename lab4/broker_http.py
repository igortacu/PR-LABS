"""HTTP/1.1 broker using only Python's standard library."""

import argparse
import json
import queue
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from broker_core import Broker, BrokerError, log


ROUTE = re.compile(r"/topics/([^/]+)/(messages|stream)\Z")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, status, value, headers=None):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error, topic="-"):
        status = {"invalid": 400, "unauthenticated": 401, "forbidden": 403,
                  "storage": 500}.get(error.code, 500)
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        self._json(status, {"error": str(error)}, headers)
        log(self.client_address, topic, "-", f"HTTP {status}: {error}")

    def do_POST(self):
        match = ROUTE.fullmatch(urlsplit(self.path).path)
        if not match or match.group(2) != "messages":
            self._json(404, {"error": "unknown route"})
            log(self.client_address, "-", "-", "HTTP 404 unknown route")
            return
        topic = unquote(match.group(1))
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > 70000:
                raise BrokerError("invalid", "invalid Content-Length")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or not isinstance(request.get("sender"), str):
                raise BrokerError("invalid", "JSON object with sender and body required")
            authorization = self.headers.get("Authorization", "")
            token = authorization[7:] if authorization.startswith("Bearer ") else ""
            message = self.server.broker.publish(topic, request["sender"], request.get("body"), token)
            self._json(202, message)
            log(self.client_address, topic, message["id"], "HTTP 202 published")
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            self._error(BrokerError("invalid", "invalid JSON or Content-Length"), topic)
        except BrokerError as error:
            self._error(error, topic)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/topics":
            self._json(200, {"topics": self.server.broker.list_topics()})
            log(self.client_address, "-", "-", "HTTP 200 topics")
            return
        match = ROUTE.fullmatch(path)
        if not match or match.group(2) != "stream":
            self._json(404, {"error": "unknown route"})
            log(self.client_address, "-", "-", "HTTP 404 unknown route")
            return
        topic = unquote(match.group(1))
        try:
            mailbox = self.server.broker.subscribe(topic)
        except BrokerError as error:
            self._error(error, topic)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        log(self.client_address, topic, "-", "HTTP 200 subscribed")
        try:
            while True:
                try:
                    message = mailbox.get(timeout=10)
                    content = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
                except queue.Empty:
                    content = b"\n"  # heartbeat detects disconnected idle clients
                self.wfile.write(f"{len(content):X}\r\n".encode() + content + b"\r\n")
                self.wfile.flush()
                if content != b"\n":
                    log(self.client_address, topic, message["id"], "HTTP delivered")
        except (BrokenPipeError, ConnectionResetError, OSError):
            log(self.client_address, topic, "-", "HTTP disconnected")
        finally:
            self.server.broker.unsubscribe(topic, mailbox)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", default="lab4/data/messages.json")
    parser.add_argument("--tokens", default="lab4/tokens.json")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.broker = Broker(args.data, args.tokens)
    print(f"HTTP broker on {args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
