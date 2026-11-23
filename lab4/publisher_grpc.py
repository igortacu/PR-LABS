"""Interactive gRPC publisher."""

import argparse

import grpc

import broker_pb2
import broker_pb2_grpc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("broker", help="host:port, e.g. 127.0.0.1:50051")
    parser.add_argument("topic")
    parser.add_argument("name")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    try:
        with grpc.insecure_channel(args.broker) as channel:
            stub = broker_pb2_grpc.BrokerStub(channel)
            while True:
                line = input()
                try:
                    reply = stub.Publish(broker_pb2.PublishRequest(
                        topic=args.topic, sender=args.name, body=line),
                        metadata=(("authorization", "Bearer " + args.token),))
                    print(f"accepted id={reply.message.id}")
                except grpc.RpcError as error:
                    print(f"error {error.code().name}: {error.details()}")
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
