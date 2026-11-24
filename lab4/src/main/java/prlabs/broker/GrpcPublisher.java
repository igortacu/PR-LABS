package prlabs.broker;

import io.grpc.ManagedChannel;
import io.grpc.Grpc;
import io.grpc.TlsChannelCredentials;
import io.grpc.Metadata;
import io.grpc.StatusRuntimeException;
import io.grpc.stub.MetadataUtils;
import java.util.Scanner;
import prlabs.broker.proto.BrokerGrpc;
import prlabs.broker.proto.PublishRequest;

public class GrpcPublisher {
    public static void main(String[] args) throws Exception {
        if (args.length != 4) {
            System.out.println("Usage: BROKER_TOKEN=... GrpcPublisher <host:port> <topic> <name> <broker.crt>");
            return;
        }
        String token = Tls.token();
        var credentials = TlsChannelCredentials.newBuilder().trustManager(new java.io.File(args[3])).build();
        ManagedChannel channel = Grpc.newChannelBuilder(args[0], credentials).build();
        Metadata headers = new Metadata();
        headers.put(Metadata.Key.of("authorization", Metadata.ASCII_STRING_MARSHALLER), "Bearer " + token);
        var stub = BrokerGrpc.newBlockingStub(channel).withInterceptors(MetadataUtils.newAttachHeadersInterceptor(headers));
        try (Scanner keyboard = new Scanner(System.in)) {
            while (keyboard.hasNextLine()) {
                String body = keyboard.nextLine();
                try {
                    var reply = stub.publish(PublishRequest.newBuilder()
                            .setTopic(args[1]).setSender(args[2]).setBody(body).build());
                    System.out.println("accepted id=" + reply.getMessage().getId());
                } catch (StatusRuntimeException error) {
                    System.out.println("error " + error.getStatus());
                }
            }
        } finally {
            channel.shutdownNow();
        }
    }
}
