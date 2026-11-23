"""gRPC-only front end for the shared broker state."""

import argparse
import queue
from concurrent import futures
from datetime import datetime

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

import broker_pb2
import broker_pb2_grpc
from broker_core import Broker, BrokerError, log


def proto_message(item):
    stamp = Timestamp()
    stamp.FromDatetime(datetime.fromisoformat(item["time"]))
    return broker_pb2.Message(id=item["id"], topic=item["topic"], sender=item["sender"],
                              body=item["body"], time=stamp)


def fail(context, error, topic):
    code = {"invalid": grpc.StatusCode.INVALID_ARGUMENT,
            "unauthenticated": grpc.StatusCode.UNAUTHENTICATED,
            "forbidden": grpc.StatusCode.PERMISSION_DENIED,
            "storage": grpc.StatusCode.INTERNAL}[error.code]
    log(context.peer(), topic, "-", f"gRPC {code.name}: {error}")
    context.abort(code, str(error))


class Service(broker_pb2_grpc.BrokerServicer):
    def __init__(self, broker):
        self.broker = broker

    def Publish(self, request, context):
        authorization = dict(context.invocation_metadata()).get("authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else ""
        try:
            item = self.broker.publish(request.topic, request.sender, request.body, token)
        except BrokerError as error:
            fail(context, error, request.topic)
        log(context.peer(), request.topic, item["id"], "gRPC published")
        return broker_pb2.PublishReply(message=proto_message(item))

    def Subscribe(self, request, context):
        try:
            mailbox = self.broker.subscribe(request.topic)
        except BrokerError as error:
            fail(context, error, request.topic)
        log(context.peer(), request.topic, "-", "gRPC subscribed")
        try:
            while context.is_active():
                try:
                    item = mailbox.get(timeout=1)
                except queue.Empty:
                    continue
                yield proto_message(item)
                log(context.peer(), request.topic, item["id"], "gRPC delivered")
        finally:
            self.broker.unsubscribe(request.topic, mailbox)
            log(context.peer(), request.topic, "-", "gRPC disconnected")

    def ListTopics(self, request, context):
        topics = self.broker.list_topics()
        log(context.peer(), "-", "-", "gRPC listed topics")
        return broker_pb2.ListTopicsReply(topics=[broker_pb2.TopicInfo(**item) for item in topics])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--data", default="lab4/data/messages.json")
    parser.add_argument("--tokens", default="lab4/tokens.json")
    args = parser.parse_args()
    broker = Broker(args.data, args.tokens)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=64))
    broker_pb2_grpc.add_BrokerServicer_to_server(Service(broker), server)
    server.add_insecure_port(f"{args.host}:{args.port}")
    server.start()
    print(f"gRPC broker on {args.host}:{args.port}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
