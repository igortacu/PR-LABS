package prlabs.coffee;

import java.util.Map;
import java.util.UUID;
import java.util.function.LongConsumer;

/** Implement this interface in the shop-logic part of the project. */
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

    record Accepted(long orderId, long preparationSeconds) implements OrderResult {}

    /** A stable stock snapshot at the instant the order was refused. */
    record Refused(Map<Product, Integer> available) implements OrderResult {}
}
