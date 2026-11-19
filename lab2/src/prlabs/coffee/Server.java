package prlabs.coffee;

import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.EnumSet;
import java.util.Map;
import java.util.UUID;

/** TCP front end. Shop stock and worker behavior live in ShopService. */
public final class Server {
    private final ShopService shop;
    private final Object providerLock = new Object();
    private volatile Session provider;

    public Server(ShopService shop) {
        this.shop = shop;
        shop.setStockChangeListener(this::alertProvider);
    }

    public void serve(int port) throws IOException {
        try (ServerSocket listener = new ServerSocket(port)) {
            log("Listening on port " + port);
            if (shop instanceof InMemoryShop inMemoryShop) {
                log("Preparation workers: " + inMemoryShop.workerCount());
            }
            while (true) {
                Socket socket = listener.accept();
                Thread thread = new Thread(() -> serveSession(socket), "connection-" + socket.getPort());
                thread.start();
            }
        }
    }

    private void serveSession(Socket socket) {
        Session session = null;
        String endpoint = String.valueOf(socket.getRemoteSocketAddress());
        log("Connection " + endpoint);
        try (socket) {
            socket.setKeepAlive(true);
            session = new Session(socket, new LineChannel(socket));
            session.run();
        } catch (IOException e) {
            log("Error " + endpoint + ": " + e.getMessage());
        } finally {
            if (session != null) session.disconnect();
            log("Disconnected " + endpoint);
        }
    }

    private void alertProvider() {
        Session current = provider;
        if (current == null) return;
        current.alertLowStock();
    }

    private static void log(String message) {
        System.out.println("[" + java.time.Instant.now() + "] " + message);
    }

    private final class Session {
        private final Socket socket;
        private final LineChannel channel;
        private final UUID id = UUID.randomUUID();
        private final String endpoint;
        private volatile boolean closed;
        private final Object orderReplyLock = new Object();
        private final EnumSet<Product> alertedProducts = EnumSet.noneOf(Product.class);
        private boolean client;
        private boolean isProvider;

        Session(Socket socket, LineChannel channel) {
            this.socket = socket;
            this.channel = channel;
            this.endpoint = String.valueOf(socket.getRemoteSocketAddress());
        }

        void run() throws IOException {
            while (!closed) {
                try {
                    String line = channel.readLine();
                    if (line == null) return;
                    handle(line);
                } catch (LineChannel.InvalidFrameException e) {
                    error(e.getMessage());
                } catch (IllegalArgumentException e) {
                    error(e.getMessage());
                }
            }
        }

        private void handle(String line) throws IOException {
            if (closed) return;
            if (line.chars().anyMatch(Character::isISOControl)) {
                throw new IllegalArgumentException("Control character in message");
            }
            if (!client && !isProvider) {
                if (line.equals("ROLE CLIENT")) {
                    client = true;
                    channel.send("OK CLIENT");
                } else if (line.equals("ROLE PROVIDER")) {
                    synchronized (providerLock) {
                        if (provider != null) throw new IllegalArgumentException("Provider already connected");
                        channel.send("OK PROVIDER");
                        provider = this;
                        isProvider = true;
                    }
                    alertProvider();
                } else {
                    throw new IllegalArgumentException("Identify with ROLE CLIENT or ROLE PROVIDER");
                }
                return;
            }
            if (line.equals("MENU")) {
                channel.send("MENU" + Protocol.formatStock(shop.stockSnapshot()));
            } else if (line.startsWith("ORDER ")) {
                if (!client) throw new IllegalArgumentException("Only clients can order");
                Map<Product, Integer> items = Protocol.parseItems(line.substring(6));
                synchronized (orderReplyLock) {
                    if (closed) return;
                    ShopService.OrderResult result = shop.placeOrder(id, items, orderId -> {
                        synchronized (orderReplyLock) {
                            log("Order ready #" + orderId + " " + endpoint);
                            sendOrDisconnect("READY " + orderId);
                        }
                    });
                    if (result instanceof ShopService.Accepted accepted) {
                        log("Order accepted #" + accepted.orderId() + " " + endpoint);
                        if (accepted.queuePosition() > 0) {
                            log("Order queued #" + accepted.orderId() + " position="
                                    + accepted.queuePosition() + " " + endpoint);
                        }
                        channel.send("ACCEPTED " + accepted.orderId() + " " + accepted.preparationSeconds());
                    } else if (result instanceof ShopService.Refused refused) {
                        log("Order refused " + endpoint);
                        channel.send("REFUSED" + Protocol.formatStock(refused.available()));
                    }
                }
            } else if (line.startsWith("DELIVER ")) {
                if (!isProvider) throw new IllegalArgumentException("Only the provider can deliver");
                Map<Product, Integer> items = Protocol.parseItems(line.substring(8));
                shop.deliver(items);
                log("Delivery " + endpoint + Protocol.formatItems(items));
                channel.send("DELIVERED" + Protocol.formatItems(items));
            } else if (line.equals("QUIT")) {
                channel.send("BYE");
                closed = true;
            } else {
                throw new IllegalArgumentException("Unknown or malformed command");
            }
        }

        private void error(String message) {
            String safe = message == null ? "Invalid request" : message.replaceAll("[\\p{Cntrl}]", "?");
            if (safe.length() > 200) safe = safe.substring(0, 200);
            log("Error " + endpoint + ": " + safe);
            sendOrDisconnect("ERROR " + safe);
        }

        private synchronized void alertLowStock() {
            Map<Product, Integer> stock = shop.stockSnapshot();
            for (Product product : Product.values()) {
                int quantity = stock.getOrDefault(product, 0);
                if (quantity >= 5) {
                    alertedProducts.remove(product);
                } else if (alertedProducts.add(product)) {
                    sendOrDisconnect("ALERT " + product.wireName() + "=" + quantity);
                }
            }
        }

        private void sendOrDisconnect(String line) {
            if (closed) return;
            try {
                channel.send(line);
            } catch (IOException e) {
                log("Error " + endpoint + ": " + e.getMessage());
                disconnect();
                try { socket.close(); } catch (IOException ignored) {}
            }
        }

        private void disconnect() {
            synchronized (orderReplyLock) {
                if (closed && !client && !isProvider) return;
                closed = true;
                if (isProvider) {
                    synchronized (providerLock) {
                        if (provider == this) provider = null;
                    }
                    isProvider = false;
                }
                if (client) {
                    client = false;
                    shop.cancelClient(id);
                }
            }
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 1 || args.length > 2) {
            System.err.println("Usage: Server <port> [ShopService implementation class]");
            System.exit(2);
        }
        int port = Integer.parseInt(args[0]);
        ShopService shop = args.length == 1 ? new InMemoryShop()
                : (ShopService) Class.forName(args[1]).getDeclaredConstructor().newInstance();
        new Server(shop).serve(port);
    }
}
