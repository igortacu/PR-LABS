package prlabs.coffee;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.EnumMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.function.LongConsumer;

/** Proves that the Python peer speaks the Java server's wire protocol. */
public final class PythonInteropSmokeTest {
    private PythonInteropSmokeTest() {}

    public static void main(String[] args) throws Exception {
        Path pythonClient = Path.of("lab2", "python", "coffee_peer.py");
        if (!Files.isRegularFile(pythonClient)) {
            throw new AssertionError("Run this test from the repository root");
        }

        int port;
        try (ServerSocket unused = new ServerSocket(0)) {
            port = unused.getLocalPort();
        }

        Thread server = new Thread(() -> {
            try {
                new Server(new FakeShop()).serve(port);
            } catch (IOException error) {
                throw new RuntimeException(error);
            }
        }, "python-interop-server");
        server.setDaemon(true);
        server.start();
        awaitServer(port);

        String python = System.getenv().getOrDefault("PYTHON", "python3");
        Process process = new ProcessBuilder(
                python, pythonClient.toString(), "client", "127.0.0.1", Integer.toString(port))
                .redirectErrorStream(true)
                .start();
        StringBuffer capturedOutput = new StringBuffer();
        CountDownLatch readySeen = new CountDownLatch(1);
        Thread outputReader = new Thread(() -> {
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    capturedOutput.append(line).append('\n');
                    if (line.equals("READY 1")) readySeen.countDown();
                }
            } catch (IOException e) {
                capturedOutput.append("Output read failed: ").append(e).append('\n');
            }
        }, "python-output-reader");
        outputReader.start();
        process.getOutputStream().write("menu\norder coffee=1\n".getBytes(StandardCharsets.UTF_8));
        process.getOutputStream().flush();
        if (!readySeen.await(5, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            outputReader.join();
            throw new AssertionError("Python client did not receive READY:\n" + capturedOutput);
        }
        process.getOutputStream().write("quit\n".getBytes(StandardCharsets.UTF_8));
        process.getOutputStream().close();

        if (!process.waitFor(5, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            throw new AssertionError("Python client did not exit");
        }
        outputReader.join();
        String output = capturedOutput.toString();
        if (process.exitValue() != 0) {
            throw new AssertionError("Python client failed:\n" + output);
        }
        expectContains(output, "[TRACE] SEND ROLE CLIENT");
        expectContains(output, "OK CLIENT");
        expectContains(output, "MENU coffee=10 tea=11 croissant=12");
        expectContains(output, "ACCEPTED 1 4");
        expectContains(output, "READY 1");
        expectContains(output, "BYE");
        System.out.println("Java server/Python client interop test passed");
    }

    private static void awaitServer(int port) throws Exception {
        for (int attempt = 0; attempt < 20; attempt++) {
            try (Socket ignored = new Socket("127.0.0.1", port)) {
                return;
            } catch (IOException error) {
                Thread.sleep(50);
            }
        }
        throw new AssertionError("Java server did not start");
    }

    private static void expectContains(String output, String expected) {
        if (!output.contains(expected)) {
            throw new AssertionError("Missing '" + expected + "' in:\n" + output);
        }
    }

    private static final class FakeShop implements ShopService {
        public Map<Product, Integer> stockSnapshot() {
            Map<Product, Integer> stock = new EnumMap<>(Product.class);
            stock.put(Product.COFFEE, 10);
            stock.put(Product.TEA, 11);
            stock.put(Product.CROISSANT, 12);
            return stock;
        }

        public OrderResult placeOrder(UUID clientId, Map<Product, Integer> items, LongConsumer whenReady) {
            Thread worker = new Thread(() -> whenReady.accept(1), "fake-shop-worker");
            worker.start();
            return new Accepted(1, 4);
        }

        public void deliver(Map<Product, Integer> items) {}

        public void cancelClient(UUID clientId) {}

        public void setStockChangeListener(Runnable listener) {}
    }
}
