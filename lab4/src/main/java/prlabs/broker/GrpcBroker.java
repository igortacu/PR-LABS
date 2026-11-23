package prlabs.broker;

import com.google.protobuf.Timestamp;
import io.grpc.Context;
import io.grpc.Contexts;
import io.grpc.Grpc;
import io.grpc.Metadata;
import io.grpc.Server;
import io.grpc.ServerBuilder;
import io.grpc.ServerInterceptors;
import io.grpc.ServerInterceptor;
import io.grpc.ServerCall;
import io.grpc.ServerCallHandler;
import io.grpc.Status;
import io.grpc.stub.StreamObserver;
import java.nio.file.Path;
import java.time.Instant;
import java.util.concurrent.TimeUnit;
import prlabs.broker.proto.BrokerGrpc;
import prlabs.broker.proto.ListTopicsReply;
import prlabs.broker.proto.ListTopicsRequest;
import prlabs.broker.proto.PublishReply;
import prlabs.broker.proto.PublishRequest;
import prlabs.broker.proto.SubscribeRequest;
import prlabs.broker.proto.TopicInfo;

/** Part 2: the same broker state, exposed through gRPC only. */
public class GrpcBroker extends BrokerGrpc.BrokerImplBase {
    private static final Context.Key<String> TOKEN = Context.key("token");
    private static final Context.Key<String> CLIENT = Context.key("client");
    private final Broker broker;

    private GrpcBroker(Broker broker) { this.broker = broker; }

    private static prlabs.broker.proto.Message wire(Broker.Message message) {
        Instant time = Instant.parse(message.time());
        return prlabs.broker.proto.Message.newBuilder()
                .setId(message.id()).setTopic(message.topic()).setSender(message.sender())
                .setBody(message.body()).setTime(Timestamp.newBuilder()
                        .setSeconds(time.getEpochSecond()).setNanos(time.getNano())).build();
    }

    private static Status status(Broker.BrokerException error) {
        return switch (error.kind) {
            case "invalid" -> Status.INVALID_ARGUMENT;
            case "unauthenticated" -> Status.UNAUTHENTICATED;
            case "forbidden" -> Status.PERMISSION_DENIED;
            default -> Status.INTERNAL;
        };
    }

    @Override public void publish(PublishRequest request, StreamObserver<PublishReply> reply) {
        String authorization = TOKEN.get();
        String token = authorization != null && authorization.startsWith("Bearer ")
                ? authorization.substring(7) : "";
        try {
            Broker.Message message = broker.publish(request.getTopic(), request.getSender(), request.getBody(), token);
            reply.onNext(PublishReply.newBuilder().setMessage(wire(message)).build());
            reply.onCompleted();
            Broker.log(CLIENT.get(), request.getTopic(), message.id(), "gRPC published");
        } catch (Broker.BrokerException error) {
            reply.onError(status(error).withDescription(error.getMessage()).asRuntimeException());
            Broker.log(CLIENT.get(), request.getTopic(), 0, "gRPC " + error.kind);
        }
    }

    @Override public void subscribe(SubscribeRequest request,
                                    StreamObserver<prlabs.broker.proto.Message> reply) {
        java.util.concurrent.BlockingQueue<Broker.Message> mailbox;
        try {
            mailbox = broker.subscribe(request.getTopic());
        } catch (Broker.BrokerException error) {
            reply.onError(status(error).withDescription(error.getMessage()).asRuntimeException());
            Broker.log(CLIENT.get(), request.getTopic(), 0, "gRPC " + error.kind);
            return;
        }
        Broker.log(CLIENT.get(), request.getTopic(), 0, "gRPC subscribed");
        try {
            while (!Context.current().isCancelled()) {
                Broker.Message message = mailbox.poll(1, TimeUnit.SECONDS);
                if (message != null) {
                    reply.onNext(wire(message));
                    Broker.log(CLIENT.get(), request.getTopic(), message.id(), "gRPC delivered");
                }
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
        } catch (RuntimeException ignored) {
            // The subscriber disconnected.
        } finally {
            broker.unsubscribe(request.getTopic(), mailbox);
            Broker.log(CLIENT.get(), request.getTopic(), 0, "gRPC disconnected");
        }
    }

    @Override public void listTopics(ListTopicsRequest request, StreamObserver<ListTopicsReply> reply) {
        ListTopicsReply.Builder result = ListTopicsReply.newBuilder();
        for (Broker.TopicInfo topic : broker.listTopics()) {
            result.addTopics(TopicInfo.newBuilder().setTopic(topic.topic()).setSize(topic.size()));
        }
        reply.onNext(result.build());
        reply.onCompleted();
        Broker.log(CLIENT.get(), "-", 0, "gRPC listed topics");
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            System.out.println("Usage: GrpcBroker <port> <data-file> <tokens-file>");
            return;
        }
        Broker broker = new Broker(Path.of(args[1]), Path.of(args[2]));
        Metadata.Key<String> header = Metadata.Key.of("authorization", Metadata.ASCII_STRING_MARSHALLER);
        ServerInterceptor auth = new ServerInterceptor() {
            @Override public <ReqT, RespT> ServerCall.Listener<ReqT> interceptCall(
                    ServerCall<ReqT, RespT> call, Metadata headers, ServerCallHandler<ReqT, RespT> next) {
                String client = String.valueOf(call.getAttributes().get(Grpc.TRANSPORT_ATTR_REMOTE_ADDR));
                return Contexts.interceptCall(Context.current()
                        .withValue(TOKEN, headers.get(header)).withValue(CLIENT, client), call, headers, next);
            }
        };
        Server server = ServerBuilder.forPort(Integer.parseInt(args[0]))
                .addService(ServerInterceptors.intercept(new GrpcBroker(broker), auth))
                .build().start();
        System.out.println("gRPC broker listening on port " + args[0]);
        server.awaitTermination();
    }
}
