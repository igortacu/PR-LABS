package prlabs.broker;

import io.grpc.ManagedChannel;
import io.grpc.Grpc;
import io.grpc.TlsChannelCredentials;
import prlabs.broker.proto.BrokerGrpc;
import prlabs.broker.proto.SubscribeRequest;

public class GrpcSubscriber {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            System.out.println("Usage: GrpcSubscriber <host:port> <topic> <broker.crt>");
            return;
        }
        var credentials = TlsChannelCredentials.newBuilder().trustManager(new java.io.File(args[2])).build();
        ManagedChannel channel = Grpc.newChannelBuilder(args[0], credentials).build();
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
