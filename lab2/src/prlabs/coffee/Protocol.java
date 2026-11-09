package prlabs.coffee;

import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;

public final class Protocol {
    private Protocol() {}

    public static Map<Product, Integer> parseItems(String arguments) {
        if (arguments.isBlank()) throw new IllegalArgumentException("Missing products");
        Map<Product, Integer> items = new EnumMap<>(Product.class);
        for (String token : arguments.split(" ", -1)) {
            if (token.isEmpty()) throw new IllegalArgumentException("Use one space between products");
            int equals = token.indexOf('=');
            if (equals <= 0 || equals != token.lastIndexOf('=')) {
                throw new IllegalArgumentException("Expected product=quantity");
            }
            Product product = Product.fromWireName(token.substring(0, equals));
            String number = token.substring(equals + 1);
            if (!number.matches("[1-9][0-9]*")) {
                throw new IllegalArgumentException("Quantity must be a positive number");
            }
            int quantity;
            try {
                quantity = Integer.parseInt(number);
            } catch (NumberFormatException e) {
                throw new IllegalArgumentException("Quantity is too large");
            }
            if (items.putIfAbsent(product, quantity) != null) {
                throw new IllegalArgumentException("Duplicate product: " + product.wireName());
            }
        }
        return Collections.unmodifiableMap(items);
    }

    public static String formatStock(Map<Product, Integer> stock) {
        StringBuilder result = new StringBuilder();
        for (Product product : Product.values()) {
            Integer quantity = stock.get(product);
            if (quantity == null || quantity < 0) {
                throw new IllegalStateException("Missing or negative stock for " + product.wireName());
            }
            result.append(' ').append(product.wireName()).append('=').append(quantity);
        }
        return result.toString();
    }

    public static String formatItems(Map<Product, Integer> items) {
        StringBuilder result = new StringBuilder();
        for (Product product : Product.values()) {
            Integer quantity = items.get(product);
            if (quantity != null) result.append(' ').append(product.wireName()).append('=').append(quantity);
        }
        return result.toString();
    }
}
