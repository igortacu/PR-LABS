package prlabs.coffee;

import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.EnumMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.LongConsumer;

/** Checks the transport with a fake shop; the real shop logic is tested separately. */
public final class NetworkSmokeTest {
    private NetworkSmokeTest() {}

    public static void main(String[] args) throws Exception {
        int port;
        try (ServerSocket unused = new ServerSocket(0)) {
            port = unused.getLocalPort();
        }
        FakeShop shop = new FakeShop();
        Thread server = new Thread(() -> {
            try { new Server(shop).serve(port); }
            catch (IOException e) { throw new RuntimeException(e); }
        }, "smoke-server");
        server.setDaemon(true);
        server.start();

        try (Socket client = connect(port)) {
            client.setSoTimeout(3000);
            LineChannel clientChannel = new LineChannel(client);
            client.getOutputStream().write("ROLE CL".getBytes(StandardCharsets.UTF_8));
            Thread.sleep(50); // The first message arrives in two TCP writes.
            client.getOutputStream().write("IENT\nMENU\nORDER coffee=1\n".getBytes(StandardCharsets.UTF_8));
            expect(clientChannel.readLine(), "OK CLIENT");
            expect(clientChannel.readLine(), "MENU coffee=4 tea=10 croissant=10");
            expect(clientChannel.readLine(), "ACCEPTED 1 4");
            expect(clientChannel.readLine(), "READY 1");

            clientChannel.send("DELIVER tea=1");
            expect(clientChannel.readLine(), "ERROR Only the provider can deliver");
            clientChannel.send("ORDER coffee=0");
            expect(clientChannel.readLine(), "ERROR Quantity must be a positive number");
            client.getOutputStream().write(new byte[] {(byte) 0xff, '\n'});
            expect(clientChannel.readLine(), "ERROR Invalid UTF-8");
            client.getOutputStream().write("x".repeat(4097).getBytes(StandardCharsets.UTF_8));
            expect(clientChannel.readLine(), "ERROR Message too long");
            client.getOutputStream().write("\nMENU\n".getBytes(StandardCharsets.UTF_8));
            expect(clientChannel.readLine(), "MENU coffee=4 tea=10 croissant=10");
            clientChannel.send("QUIT");
            expect(clientChannel.readLine(), "BYE");
        }
        if (!shop.canceled.await(3, TimeUnit.SECONDS)) throw new AssertionError("Client was not canceled");
        if (shop.cancelCalls.get() != 1) throw new AssertionError("Cancellation ran more than once");

        try (Socket provider = connect(port)) {
            provider.setSoTimeout(3000);
            LineChannel channel = new LineChannel(provider);
            channel.send("ROLE PROVIDER");
            expect(channel.readLine(), "OK PROVIDER");
            expect(channel.readLine(), "ALERT coffee=4");
            channel.send("DELIVER coffee=2");
            expect(channel.readLine(), "DELIVERED coffee=2");
            channel.send("QUIT");
            expect(channel.readLine(), "BYE");
        }
        System.out.println("Network smoke test passed");
    }

    private static Socket connect(int port) throws Exception {
        for (int attempt = 0; attempt < 20; attempt++) {
            try { return new Socket("127.0.0.1", port); }
            catch (IOException e) { Thread.sleep(50); }
        }
        throw new AssertionError("Server did not start");
    }

    private static void expect(String actual, String expected) {
        if (!expected.equals(actual)) throw new AssertionError("Expected '" + expected + "', got '" + actual + "'");
    }

    private static final class FakeShop implements ShopService {
        private final AtomicInteger cancelCalls = new AtomicInteger();
        private final CountDownLatch canceled = new CountDownLatch(1);
        private Runnable listener = () -> {};

        public Map<Product, Integer> stockSnapshot() {
            Map<Product, Integer> result = new EnumMap<>(Product.class);
            result.put(Product.COFFEE, 4);
            result.put(Product.TEA, 10);
            result.put(Product.CROISSANT, 10);
            return result;
        }

        public OrderResult placeOrder(UUID clientId, Map<Product, Integer> items, LongConsumer whenReady) {
            Thread worker = new Thread(() -> whenReady.accept(1));
            worker.start();
            return new Accepted(1, 4);
        }

        public void deliver(Map<Product, Integer> items) { listener.run(); }

        public void cancelClient(UUID clientId) {
            cancelCalls.incrementAndGet();
            canceled.countDown();
        }

        public void setStockChangeListener(Runnable listener) { this.listener = listener; }
    }
}
