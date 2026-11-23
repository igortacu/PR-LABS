"""Shared, durable publish/subscribe state for the HTTP and gRPC front ends."""

import json
import os
import queue
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


TOPIC = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class BrokerError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def log(client, topic, message_id, result):
    print(f"{datetime.now(timezone.utc).isoformat()} client={client} "
          f"topic={topic} id={message_id} result={result}", flush=True)


class Broker:
    def __init__(self, data_path, tokens_path):
        self.path = Path(data_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(tokens_path, encoding="utf-8") as file:
            raw_tokens = json.load(file)
        self.tokens = {}
        for token, item in raw_tokens.items():
            if not token or not isinstance(item.get("name"), str) or not item["name"]:
                raise ValueError("each token needs a publisher name")
            topics = item.get("topics")
            if not isinstance(topics, list) or not all(isinstance(t, str) and TOPIC.fullmatch(t) for t in topics):
                raise ValueError("each token needs a list of valid topics")
            self.tokens[token] = (item["name"], frozenset(topics))
        self.messages = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        if not isinstance(self.messages, dict):
            raise ValueError("invalid broker data")
        for topic, items in self.messages.items():
            if not TOPIC.fullmatch(topic) or not isinstance(items, list) or any(
                item.get("id") != index for index, item in enumerate(items, 1)
            ):
                raise ValueError(f"invalid saved topic: {topic}")
        self.lock = threading.RLock()
        self.subscribers = {}
        self.pending = {}

    @staticmethod
    def valid_topic(topic):
        if not TOPIC.fullmatch(topic):
            raise BrokerError("invalid", "topic must be 1-64 letters, digits, _, . or -")

    def authorize(self, token, topic, sender):
        identity = self.tokens.get(token)
        if identity is None:
            raise BrokerError("unauthenticated", "missing or unknown bearer token")
        name, topics = identity
        if topic not in topics or sender != name:
            raise BrokerError("forbidden", "token cannot publish for this sender and topic")

    def publish(self, topic, sender, body, token):
        self.valid_topic(topic)
        self.authorize(token, topic, sender)
        if not isinstance(body, str) or not body or len(body.encode("utf-8")) > 65536:
            raise BrokerError("invalid", "body must be nonempty and at most 65536 UTF-8 bytes")
        with self.lock:
            items = self.messages.setdefault(topic, [])
            message = {"id": len(items) + 1, "topic": topic, "sender": sender,
                       "body": body, "time": datetime.now(timezone.utc).isoformat()}
            items.append(message)
            try:
                self._save()
            except OSError:
                items.pop()
                if not items:
                    del self.messages[topic]
                raise BrokerError("storage", "could not save message")
            self._worker(topic)
            self.pending[topic].put(message)
            return message

    def _save(self):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".broker-", delete=False) as file:
                temporary = file.name
                json.dump(self.messages, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def _worker(self, topic):
        if topic in self.pending:
            return
        pending = queue.Queue()
        self.pending[topic] = pending
        thread = threading.Thread(target=self._deliver, args=(topic, pending), daemon=True)
        thread.start()

    def _deliver(self, topic, pending):
        while True:
            message = pending.get()
            with self.lock:
                subscribers = list(self.subscribers.get(topic, ()))
            for subscriber in subscribers:
                subscriber.put(message)

    def subscribe(self, topic):
        self.valid_topic(topic)
        mailbox = queue.Queue()
        with self.lock:
            self.subscribers.setdefault(topic, set()).add(mailbox)
        return mailbox

    def unsubscribe(self, topic, mailbox):
        with self.lock:
            self.subscribers.get(topic, set()).discard(mailbox)

    def list_topics(self):
        with self.lock:
            return [{"topic": topic, "size": len(items)} for topic, items in sorted(self.messages.items())]
