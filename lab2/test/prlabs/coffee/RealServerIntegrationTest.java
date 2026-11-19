package prlabs.coffee;

import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.Map;

/** Exercises the real shop through the same text protocol a Python client uses. */
public final class RealServerIntegrationTest {
    private RealServerIntegrationTest() {}

    public static void main(String[] args) throws Exception {
        int port;
        try (ServerSocket unused = new ServerSocket(0)) {
            port = unused.getLocalPort();
        }
        InMemoryShop shop = new InMemoryShop(Map.of(
                Product.COFFEE, 5, Product.TEA, 10, Product.CROISSANT, 10), 1, 100);
        Thread server = new Thread(() -> {
            try { new Server(shop).serve(port); }
            catch (IOException e) { throw new RuntimeException(e); }
        }, "integration-server");
        server.setDaemon(true);
        server.start();

        try (Socket provider = connect(port); Socket client = connect(port)) {
            provider.setSoTimeout(3000);
            client.setSoTimeout(3000);
            LineChannel providerChannel = new LineChannel(provider);
            LineChannel clientChannel = new LineChannel(client);
            providerChannel.send("ROLE PROVIDER");
            expect(providerChannel.readLine(), "OK PROVIDER");
            clientChannel.send("ROLE CLIENT");
            expect(clientChannel.readLine(), "OK CLIENT");

            clientChannel.send("ORDER coffee=1");
            expect(clientChannel.readLine(), "ACCEPTED 1 4");
            expect(providerChannel.readLine(), "ALERT coffee=4");
            clientChannel.send("MENU");
            expect(clientChannel.readLine(), "MENU coffee=4 tea=10 croissant=10");
            expect(clientChannel.readLine(), "READY 1");

            providerChannel.send("DELIVER coffee=2");
            expect(providerChannel.readLine(), "DELIVERED coffee=2");
            clientChannel.send("MENU");
            expect(clientChannel.readLine(), "MENU coffee=6 tea=10 croissant=10");
            clientChannel.send("QUIT");
            expect(clientChannel.readLine(), "BYE");
            providerChannel.send("QUIT");
            expect(providerChannel.readLine(), "BYE");
        }
        try (Socket departingClient = connect(port)) {
            departingClient.setSoTimeout(3000);
            LineChannel channel = new LineChannel(departingClient);
            channel.send("ROLE CLIENT");
            expect(channel.readLine(), "OK CLIENT");
            channel.send("ORDER tea=1");
            expect(channel.readLine(), "ACCEPTED 2 3");
            // Closing during preparation must restore the reserved tea.
        }
        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(3);
        while (shop.stockSnapshot().get(Product.TEA) != 10 && System.nanoTime() < deadline) {
            Thread.sleep(10);
        }
        if (shop.stockSnapshot().get(Product.TEA) != 10) {
            throw new AssertionError("Disconnected client's order was not refunded");
        }
        System.out.println("Real server integration test passed");
    }

    private static Socket connect(int port) throws Exception {
        for (int attempt = 0; attempt < 20; attempt++) {
            try { return new Socket("127.0.0.1", port); }
            catch (IOException e) { Thread.sleep(50); }
        }
        throw new AssertionError("Server did not start");
    }

    private static void expect(String actual, String expected) {
        if (!expected.equals(actual)) {
            throw new AssertionError("Expected '" + expected + "', got '" + actual + "'");
        }
    }
}
