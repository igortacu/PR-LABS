package prlabs.coffee;

import java.util.Locale;

public enum Product {
    COFFEE(4), TEA(3), CROISSANT(2);

    private final int preparationSeconds;

    Product(int preparationSeconds) {
        this.preparationSeconds = preparationSeconds;
    }

    public int preparationSeconds() {
        return preparationSeconds;
    }

    public String wireName() {
        return name().toLowerCase(Locale.ROOT);
    }

    public static Product fromWireName(String name) {
        for (Product product : values()) {
            if (product.wireName().equals(name)) return product;
        }
        throw new IllegalArgumentException("Unknown product");
    }
}
