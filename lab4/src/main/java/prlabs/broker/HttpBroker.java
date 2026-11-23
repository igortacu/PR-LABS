package prlabs.broker;

import com.google.gson.Gson;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/** Part 1: plain JDK HttpServer, no web framework. */
public class HttpBroker {
    private record Input(String sender, String body) {}
    private final Broker broker;
    private final Gson gson = new Gson();

    private HttpBroker(Broker broker) { this.broker = broker; }

    private void answer(HttpExchange exchange, int status, Object value) throws IOException {
        byte[] bytes = gson.toJson(value).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (var output = exchange.getResponseBody()) { output.write(bytes); }
    }

    private void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String client = exchange.getRemoteAddress().toString();
        String[] parts = path.split("/");
        String topic = parts.length > 2 ? parts[2] : "-";
        long id = 0;
        int status = 500;
        try {
            if (path.equals("/topics") && exchange.getRequestMethod().equals("GET")) {
                status = 200;
                answer(exchange, status, java.util.Map.of("topics", broker.listTopics()));
            } else if (parts.length == 4 && parts[1].equals("topics") &&
                       parts[3].equals("messages") && exchange.getRequestMethod().equals("POST")) {
                byte[] bytes = exchange.getRequestBody().readNBytes(70001);
                if (bytes.length > 70000) throw new Broker.BrokerException("invalid", "Request too large");
                Input input;
                try { input = gson.fromJson(new String(bytes, StandardCharsets.UTF_8), Input.class); }
                catch (RuntimeException error) { throw new Broker.BrokerException("invalid", "Invalid JSON"); }
                if (input == null) throw new Broker.BrokerException("invalid", "Missing JSON body");
                String authorization = exchange.getRequestHeaders().getFirst("Authorization");
                String token = authorization != null && authorization.startsWith("Bearer ")
                        ? authorization.substring(7) : "";
                Broker.Message message = broker.publish(topic, input.sender(), input.body(), token);
                id = message.id();
                status = 202;
                answer(exchange, status, message);
            } else if (parts.length == 4 && parts[1].equals("topics") &&
                       parts[3].equals("stream") && exchange.getRequestMethod().equals("GET")) {
                var mailbox = broker.subscribe(topic);
                status = 200;
                exchange.getResponseHeaders().set("Content-Type", "application/x-ndjson; charset=utf-8");
                exchange.sendResponseHeaders(200, 0); // chunked response stays open
                Broker.log(client, topic, 0, "HTTP 200 subscribed");
                try (var output = exchange.getResponseBody()) {
                    while (true) {
                        Broker.Message message = mailbox.poll(10, TimeUnit.SECONDS);
                        String line = message == null ? "\n" : gson.toJson(message) + "\n";
                        output.write(line.getBytes(StandardCharsets.UTF_8));
                        output.flush();
                        if (message != null) Broker.log(client, topic, message.id(), "HTTP delivered");
                    }
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                } catch (IOException ignored) {
                    // The subscriber disconnected.
                } finally {
                    broker.unsubscribe(topic, mailbox);
                    Broker.log(client, topic, 0, "HTTP disconnected");
                }
                return;
            } else {
                status = 404;
                answer(exchange, status, java.util.Map.of("error", "Unknown route"));
            }
        } catch (Broker.BrokerException error) {
            status = switch (error.kind) {
                case "invalid" -> 400;
                case "unauthenticated" -> 401;
                case "forbidden" -> 403;
                default -> 500;
            };
            if (status == 401) exchange.getResponseHeaders().set("WWW-Authenticate", "Bearer");
            answer(exchange, status, java.util.Map.of("error", error.getMessage()));
        } finally {
            Broker.log(client, topic, id, "HTTP " + status);
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            System.out.println("Usage: HttpBroker <port> <data-file> <tokens-file>");
            return;
        }
        Broker broker = new Broker(Path.of(args[1]), Path.of(args[2]));
        HttpBroker app = new HttpBroker(broker);
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", Integer.parseInt(args[0])), 0);
        server.createContext("/", app::handle);
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();
        System.out.println("HTTP broker listening on port " + args[0]);
    }
}
