package prlabs.coffee;

import java.util.ArrayList;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.LongConsumer;

/** Thread-safe stock, FIFO order queue, and a fixed pool of preparation workers. */
public final class InMemoryShop implements ShopService {
    private final ReentrantLock stateLock = new ReentrantLock();
    private final EnumMap<Product, Integer> stock = new EnumMap<>(Product.class);
    private final EnumMap<Product, Integer> reserved = new EnumMap<>(Product.class);
    private final BlockingQueue<Order> waitingOrders = new LinkedBlockingQueue<>();
    private final Map<UUID, Set<Order>> ordersByClient = new HashMap<>();
    private final int workerCount;
    private final long millisecondsPerSecond;
    private long nextOrderId = 1; // Guarded by stateLock.
    private long unfinishedOrders; // Guarded by stateLock; includes preparing and waiting orders.
    private volatile Runnable stockChangeListener = () -> {};

    public InMemoryShop() {
        this(randomStock(), Runtime.getRuntime().availableProcessors(), 1000);
    }

    // Package-private so tests can use a fixed stock, one worker, and a faster clock.
    InMemoryShop(Map<Product, Integer> initialStock, int workerCount, long millisecondsPerSecond) {
        if (workerCount < 1 || millisecondsPerSecond < 1) {
            throw new IllegalArgumentException("Worker count and time scale must be positive");
        }
        for (Product product : Product.values()) {
            Integer quantity = initialStock.get(product);
            if (quantity == null || quantity < 0) {
                throw new IllegalArgumentException("Invalid initial stock for " + product.wireName());
            }
            stock.put(product, quantity);
            reserved.put(product, 0);
        }
        this.workerCount = workerCount;
        this.millisecondsPerSecond = millisecondsPerSecond;
        for (int i = 0; i < workerCount; i++) {
            Thread worker = new Thread(this::work, "preparation-worker-" + (i + 1));
            worker.setDaemon(true);
            worker.start();
        }
    }

    private static Map<Product, Integer> randomStock() {
        EnumMap<Product, Integer> amounts = new EnumMap<>(Product.class);
        for (Product product : Product.values()) {
            amounts.put(product, ThreadLocalRandom.current().nextInt(10, 51));
        }
        return amounts;
    }

    public int workerCount() {
        return workerCount;
    }

    @Override
    public Map<Product, Integer> stockSnapshot() {
        stateLock.lock();
        try {
            return Map.copyOf(stock);
        } finally {
            stateLock.unlock();
        }
    }

    @Override
    public OrderResult placeOrder(UUID clientId, Map<Product, Integer> requested, LongConsumer whenReady) {
        if (clientId == null || whenReady == null) throw new IllegalArgumentException("Missing client or callback");
        EnumMap<Product, Integer> items = checkedItems(requested);
        OrderResult result;
        stateLock.lock();
        try {
            for (Map.Entry<Product, Integer> item : items.entrySet()) {
                if (stock.get(item.getKey()) < item.getValue()) {
                    return new Refused(Map.copyOf(stock));
                }
            }
            long seconds = 0;
            for (Map.Entry<Product, Integer> item : items.entrySet()) {
                seconds = Math.addExact(seconds,
                        Math.multiplyExact((long) item.getValue(), item.getKey().preparationSeconds()));
            }
            long delayMillis = Math.multiplyExact(seconds, millisecondsPerSecond);
            long orderId = nextOrderId;
            nextOrderId = Math.addExact(nextOrderId, 1);
            long queuePosition = Math.max(0, unfinishedOrders - workerCount + 1);
            Order order = new Order(orderId, clientId, items, delayMillis, whenReady);
            for (Map.Entry<Product, Integer> item : items.entrySet()) {
                stock.put(item.getKey(), stock.get(item.getKey()) - item.getValue());
                reserved.put(item.getKey(), reserved.get(item.getKey()) + item.getValue());
            }
            ordersByClient.computeIfAbsent(clientId, ignored -> new HashSet<>()).add(order);
            waitingOrders.add(order);
            unfinishedOrders++;
            result = new Accepted(orderId, seconds, queuePosition);
        } finally {
            stateLock.unlock();
        }
        stockChangeListener.run();
        return result;
    }

    @Override
    public void deliver(Map<Product, Integer> delivered) {
        EnumMap<Product, Integer> items = checkedItems(delivered);
        stateLock.lock();
        try {
            // Check every resulting quantity before changing any product.
            for (Map.Entry<Product, Integer> item : items.entrySet()) {
                long total = (long) stock.get(item.getKey()) + reserved.get(item.getKey()) + item.getValue();
                if (total > Integer.MAX_VALUE) throw new IllegalArgumentException("Stock limit exceeded");
            }
            for (Map.Entry<Product, Integer> item : items.entrySet()) {
                stock.put(item.getKey(), stock.get(item.getKey()) + item.getValue());
            }
        } finally {
            stateLock.unlock();
        }
        stockChangeListener.run();
    }

    @Override
    public void cancelClient(UUID clientId) {
        List<Order> canceled = new ArrayList<>();
        stateLock.lock();
        try {
            Set<Order> orders = ordersByClient.remove(clientId);
            if (orders == null) return;
            for (Order order : orders) {
                if (order.state == State.CANCELED || order.state == State.READY) continue;
                order.state = State.CANCELED;
                unfinishedOrders--;
                waitingOrders.remove(order); // A worker may already have taken it.
                for (Map.Entry<Product, Integer> item : order.items.entrySet()) {
                    stock.put(item.getKey(), stock.get(item.getKey()) + item.getValue());
                    reserved.put(item.getKey(), reserved.get(item.getKey()) - item.getValue());
                }
                canceled.add(order);
            }
        } finally {
            stateLock.unlock();
        }
        for (Order order : canceled) order.cancellation.countDown();
        if (!canceled.isEmpty()) stockChangeListener.run();
    }

    @Override
    public void setStockChangeListener(Runnable listener) {
        if (listener == null) throw new IllegalArgumentException("Missing stock listener");
        stockChangeListener = listener;
    }

    private void work() {
        while (true) {
            Order order;
            try {
                order = waitingOrders.take();
            } catch (InterruptedException ignored) {
                continue;
            }
            stateLock.lock();
            try {
                if (order.state != State.QUEUED) continue;
                order.state = State.PREPARING;
            } finally {
                stateLock.unlock();
            }

            try {
                order.cancellation.await(order.delayMillis, TimeUnit.MILLISECONDS);
            } catch (InterruptedException e) {
                cancelOrderAfterWorkerInterrupt(order);
                continue;
            }

            boolean ready = false;
            stateLock.lock();
            try {
                if (order.state == State.PREPARING) {
                    order.state = State.READY;
                    unfinishedOrders--;
                    for (Map.Entry<Product, Integer> item : order.items.entrySet()) {
                        reserved.put(item.getKey(), reserved.get(item.getKey()) - item.getValue());
                    }
                    removeFromClient(order);
                    ready = true;
                }
            } finally {
                stateLock.unlock();
            }
            if (ready) {
                try {
                    order.whenReady.accept(order.id);
                } catch (RuntimeException e) {
                    System.err.println("Order callback failed for #" + order.id + ": " + e.getMessage());
                }
            }
        }
    }

    private void cancelOrderAfterWorkerInterrupt(Order order) {
        boolean refunded = false;
        stateLock.lock();
        try {
            if (order.state == State.PREPARING) {
                order.state = State.CANCELED;
                unfinishedOrders--;
                removeFromClient(order);
                for (Map.Entry<Product, Integer> item : order.items.entrySet()) {
                    stock.put(item.getKey(), stock.get(item.getKey()) + item.getValue());
                    reserved.put(item.getKey(), reserved.get(item.getKey()) - item.getValue());
                }
                refunded = true;
            }
        } finally {
            stateLock.unlock();
        }
        if (refunded) stockChangeListener.run();
    }

    /** Caller holds stateLock. */
    private void removeFromClient(Order order) {
        Set<Order> orders = ordersByClient.get(order.clientId);
        if (orders == null) return;
        orders.remove(order);
        if (orders.isEmpty()) ordersByClient.remove(order.clientId);
    }

    private static EnumMap<Product, Integer> checkedItems(Map<Product, Integer> supplied) {
        if (supplied == null || supplied.isEmpty()) throw new IllegalArgumentException("Missing products");
        EnumMap<Product, Integer> copy = new EnumMap<>(Product.class);
        for (Map.Entry<Product, Integer> item : supplied.entrySet()) {
            if (item.getKey() == null || item.getValue() == null || item.getValue() <= 0) {
                throw new IllegalArgumentException("Invalid product quantity");
            }
            copy.put(item.getKey(), item.getValue());
        }
        return copy;
    }

    private enum State { QUEUED, PREPARING, READY, CANCELED }

    private static final class Order {
        final long id;
        final UUID clientId;
        final EnumMap<Product, Integer> items;
        final long delayMillis;
        final LongConsumer whenReady;
        final CountDownLatch cancellation = new CountDownLatch(1);
        State state = State.QUEUED; // Guarded by stateLock.

        Order(long id, UUID clientId, EnumMap<Product, Integer> items,
              long delayMillis, LongConsumer whenReady) {
            this.id = id;
            this.clientId = clientId;
            this.items = items;
            this.delayMillis = delayMillis;
            this.whenReady = whenReady;
        }
    }
}
