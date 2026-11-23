package prlabs.broker;

import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import prlabs.broker.proto.BrokerGrpc;
import prlabs.broker.proto.SubscribeRequest;

public class GrpcSubscriber {
    public static void main(String[] args) {
        if (args.length != 2) {
            System.out.println("Usage: GrpcSubscriber <host:port> <topic>");
            return;
        }
        ManagedChannel channel = ManagedChannelBuilder.forTarget(args[0]).usePlaintext().build();
        try {
            var stream = BrokerGrpc.newBlockingStub(channel).subscribe(
                    SubscribeRequest.newBuilder().setTopic(args[1]).build());
            while (stream.hasNext()) {
                var message = stream.next();
                System.out.printf("[%s] %s: %s%n", message.getTopic(), message.getSender(), message.getBody());
            }
        } finally {
            channel.shutdownNow();
        }
    }
}
