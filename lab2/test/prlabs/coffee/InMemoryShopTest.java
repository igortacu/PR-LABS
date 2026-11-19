package prlabs.coffee;

import java.util.ArrayList;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Behavior checks for the real shop implementation, using a faster preparation clock. */
public final class InMemoryShopTest {
    private InMemoryShopTest() {}

    public static void main(String[] args) throws Exception {
        randomInitialStock();
        atomicLastProduct();
        fifoAndPreparationTime();
        cancellationRefundsOnceAndStopsWorker();
        System.out.println("In-memory shop tests passed");
    }

    private static void randomInitialStock() {
        Map<Product, Integer> stock = new InMemoryShop().stockSnapshot();
        for (Product product : Product.values()) {
            int quantity = stock.get(product);
            check(quantity >= 10 && quantity <= 50, "Initial stock outside 10..50");
        }
    }

    private static void atomicLastProduct() throws Exception {
        InMemoryShop shop = new InMemoryShop(stock(0, 0, 1), 1, 100);
        CountDownLatch start = new CountDownLatch(1);
        AtomicInteger accepted = new AtomicInteger();
        List<Thread> clients = new ArrayList<>();
        for (int i = 0; i < 2; i++) {
            Thread client = new Thread(() -> {
                try { start.await(); }
                catch (InterruptedException e) { throw new AssertionError(e); }
                ShopService.OrderResult result = shop.placeOrder(
                        UUID.randomUUID(), Map.of(Product.CROISSANT, 1), ignored -> {});
                if (result instanceof ShopService.Accepted) accepted.incrementAndGet();
            });
            clients.add(client);
            client.start();
        }
        start.countDown();
        for (Thread client : clients) client.join();
        check(accepted.get() == 1, "The last croissant was sold twice");
        check(shop.stockSnapshot().get(Product.CROISSANT) == 0, "Wrong stock after concurrent orders");
    }

    private static void fifoAndPreparationTime() throws Exception {
        InMemoryShop shop = new InMemoryShop(stock(1, 1, 3), 1, 100);
        CountDownLatch ready = new CountDownLatch(3);
        List<Long> completionOrder = java.util.Collections.synchronizedList(new ArrayList<>());
        for (int i = 0; i < 3; i++) {
            ShopService.OrderResult result = shop.placeOrder(UUID.randomUUID(),
                    Map.of(Product.CROISSANT, 1), id -> {
                        completionOrder.add(id);
                        ready.countDown();
                    });
            check(result instanceof ShopService.Accepted accepted
                            && accepted.preparationSeconds() == 2
                            && accepted.queuePosition() == i,
                    "Croissant preparation time is wrong");
        }
        check(ready.await(3, TimeUnit.SECONDS), "Orders did not finish");
        check(completionOrder.equals(List.of(1L, 2L, 3L)), "Worker did not follow FIFO order");

        ShopService.OrderResult mixed = shop.placeOrder(UUID.randomUUID(),
                Map.of(Product.COFFEE, 1, Product.TEA, 1), ignored -> {});
        check(mixed instanceof ShopService.Accepted accepted && accepted.preparationSeconds() == 7,
                "Preparation time was not summed");
    }

    private static void cancellationRefundsOnceAndStopsWorker() throws Exception {
        InMemoryShop shop = new InMemoryShop(stock(1, 1, 0), 1, 200);
        UUID firstClient = UUID.randomUUID();
        UUID secondClient = UUID.randomUUID();
        AtomicInteger canceledReady = new AtomicInteger();
        shop.placeOrder(firstClient, Map.of(Product.COFFEE, 1), id -> canceledReady.incrementAndGet());
        shop.placeOrder(secondClient, Map.of(Product.TEA, 1), id -> canceledReady.incrementAndGet());
        Thread.sleep(100); // First order is preparing; second is still queued.
        shop.cancelClient(firstClient);
        shop.cancelClient(secondClient);
        shop.cancelClient(firstClient); // Repeated cancellation must not refund twice.
        check(shop.stockSnapshot().get(Product.COFFEE) == 1, "Preparing order was not refunded");
        check(shop.stockSnapshot().get(Product.TEA) == 1, "Queued order was not refunded");

        CountDownLatch replacementReady = new CountDownLatch(1);
        long started = System.nanoTime();
        ShopService.OrderResult replacement = shop.placeOrder(
                UUID.randomUUID(), Map.of(Product.COFFEE, 1), id -> replacementReady.countDown());
        check(replacement instanceof ShopService.Accepted accepted && accepted.queuePosition() == 0,
                "Canceled orders still occupied queue capacity");
        check(replacementReady.await(2, TimeUnit.SECONDS), "Worker did not start the replacement order");
        long elapsedMillis = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);
        check(elapsedMillis >= 700, "Replacement order did not get its full preparation time");
        check(canceledReady.get() == 0, "Canceled order was reported ready");
    }

    private static Map<Product, Integer> stock(int coffee, int tea, int croissant) {
        EnumMap<Product, Integer> result = new EnumMap<>(Product.class);
        result.put(Product.COFFEE, coffee);
        result.put(Product.TEA, tea);
        result.put(Product.CROISSANT, croissant);
        return result;
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
