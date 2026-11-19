package prlabs.coffee;

import java.util.Map;
import java.util.UUID;
import java.util.function.LongConsumer;

/** Contract between the TCP server and its thread-safe shop implementation. */
public interface ShopService {
    /** Return a stable copy, never the mutable stock map. */
    Map<Product, Integer> stockSnapshot();

    /** Reserve all requested items atomically, or reserve none. */
    OrderResult placeOrder(UUID clientId, Map<Product, Integer> items, LongConsumer whenReady);

    /** Add all delivered items atomically. */
    void deliver(Map<Product, Integer> items);

    /** Cancel every order belonging to this client and refund each exactly once. */
    void cancelClient(UUID clientId);

    /** Invoke after each stock change, outside any shop lock. */
    void setStockChangeListener(Runnable listener);

    sealed interface OrderResult permits Accepted, Refused {}

    /** queuePosition is 0 when a worker slot is available, otherwise 1-based. */
    record Accepted(long orderId, long preparationSeconds, long queuePosition) implements OrderResult {
        public Accepted(long orderId, long preparationSeconds) {
            this(orderId, preparationSeconds, 0);
        }
    }

    /** A stable stock snapshot at the instant the order was refused. */
    record Refused(Map<Product, Integer> available) implements OrderResult {}
}
