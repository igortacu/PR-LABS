"""Interactive gRPC stream subscriber."""

import argparse

import grpc

import broker_pb2
import broker_pb2_grpc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("broker", help="host:port")
    parser.add_argument("topic")
    args = parser.parse_args()
    try:
        with grpc.insecure_channel(args.broker) as channel:
            for item in broker_pb2_grpc.BrokerStub(channel).Subscribe(
                broker_pb2.SubscribeRequest(topic=args.topic)):
                print(f"[{item.topic}] {item.sender}: {item.body}", flush=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
