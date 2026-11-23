"""End-to-end checks against both transports on loopback sockets."""

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent import futures
from http.server import ThreadingHTTPServer
from pathlib import Path

import grpc

import broker_pb2
import broker_pb2_grpc
from broker_core import Broker
from broker_grpc import Service
from broker_http import Handler


class Lab4Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "messages.json"
        self.tokens = Path(self.temp.name) / "tokens.json"
        self.tokens.write_text(json.dumps({"secret": {"name": "teacher", "topics": ["grades"]}}))
        self.broker = Broker(self.data, self.tokens)

    def test_http_delivery_auth_and_restart(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.broker = self.broker
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        streams = [urllib.request.urlopen(base + "/topics/grades/stream") for _ in range(2)]
        for stream in streams:
            self.addCleanup(stream.close)

        def publish(token, topic="grades"):
            request = urllib.request.Request(base + f"/topics/{topic}/messages",
                data=b'{"sender":"teacher","body":"hello"}',
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                method="POST")
            return urllib.request.urlopen(request)

        for token, topic, expected in [("", "grades", 401), ("wrong", "grades", 401),
                                       ("secret", "news", 403)]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                publish(token, topic)
            self.assertEqual(caught.exception.code, expected)
            caught.exception.close()
        with publish("secret") as response:
            self.assertEqual(response.status, 202)
            self.assertEqual(json.load(response)["id"], 1)
        with futures.ThreadPoolExecutor(max_workers=8) as pool:
            def publish_id(_):
                with publish("secret") as response:
                    return json.load(response)["id"]
            ids = list(pool.map(publish_id, range(10)))
        self.assertEqual(sorted(ids), list(range(2, 12)))
        for stream in streams:
            self.assertEqual([json.loads(stream.readline())["id"] for _ in range(11)], list(range(1, 12)))
        with urllib.request.urlopen(base + "/topics") as response:
            self.assertEqual(json.load(response)["topics"], [{"topic": "grades", "size": 11}])
        restarted = Broker(self.data, self.tokens)
        self.assertEqual(restarted.publish("grades", "teacher", "again", "secret")["id"], 12)

    def test_grpc_concurrent_publishers_and_streams(self):
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
        broker_pb2_grpc.add_BrokerServicer_to_server(Service(self.broker), server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        self.addCleanup(lambda: server.stop(0).wait())
        channel = grpc.insecure_channel(f"127.0.0.1:{port}")
        self.addCleanup(channel.close)
        stub = broker_pb2_grpc.BrokerStub(channel)
        streams = [stub.Subscribe(broker_pb2.SubscribeRequest(topic="grades")) for _ in range(2)]
        for stream in streams:
            self.addCleanup(stream.cancel)
        time.sleep(0.1)

        def publish(index):
            return stub.Publish(broker_pb2.PublishRequest(
                topic="grades", sender="teacher", body=f"message {index}"),
                metadata=(("authorization", "Bearer secret"),)).message.id

        with futures.ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(publish, range(20)))
        self.assertEqual(sorted(ids), list(range(1, 21)))
        for stream in streams:
            self.assertEqual([next(stream).id for _ in range(20)], list(range(1, 21)))
        self.assertEqual(stub.ListTopics(broker_pb2.ListTopicsRequest()).topics[0].size, 20)
        with self.assertRaises(grpc.RpcError) as caught:
            stub.Publish(broker_pb2.PublishRequest(topic="grades", sender="teacher", body="x"))
        self.assertEqual(caught.exception.code(), grpc.StatusCode.UNAUTHENTICATED)
        self.assertEqual(Broker(self.data, self.tokens).publish("grades", "teacher", "next", "secret")["id"], 21)


if __name__ == "__main__":
    unittest.main()
