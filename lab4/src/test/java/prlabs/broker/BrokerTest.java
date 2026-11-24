package prlabs.broker;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class BrokerTest {
    @TempDir Path directory;

    @Test void twoPublishersTwoSubscribersAndRestart() throws Exception {
        Path tokens = directory.resolve("tokens.txt");
        Path data = directory.resolve("data.json");
        Files.writeString(tokens, "secret|teacher|grades\n");
        Broker broker = new Broker(data, tokens);
        var first = broker.subscribe("grades");
        var second = broker.subscribe("grades");

        var publishers = Executors.newFixedThreadPool(2);
        try {
            List<java.util.concurrent.Future<Broker.Message>> results = new ArrayList<>();
            for (int i = 0; i < 20; i++) {
                int number = i;
                results.add(publishers.submit(() -> broker.publish("grades", "teacher", "line " + number, "secret")));
            }
            List<Long> ids = new ArrayList<>();
            for (var result : results) ids.add(result.get().id());
            ids.sort(Long::compareTo);
            for (int i = 0; i < 20; i++) assertEquals(i + 1L, ids.get(i));
        } finally {
            publishers.shutdownNow();
        }
        for (var mailbox : List.of(first, second)) {
            for (int id = 1; id <= 20; id++) {
                assertEquals(id, mailbox.poll(2, TimeUnit.SECONDS).id());
            }
        }
        assertEquals(20, broker.listTopics().get(0).size());
        Broker restarted = new Broker(data, tokens);
        assertEquals(21, restarted.publish("grades", "teacher", "after restart", "secret").id());
    }

    @Test void tokenErrors() throws Exception {
        Path tokens = directory.resolve("tokens.txt");
        Files.writeString(tokens, "secret|teacher|grades\n");
        Broker broker = new Broker(directory.resolve("data.json"), tokens);
        assertEquals("unauthenticated", assertThrows(Broker.BrokerException.class,
                () -> broker.publish("grades", "teacher", "hello", "bad")).kind);
        assertEquals("forbidden", assertThrows(Broker.BrokerException.class,
                () -> broker.publish("news", "teacher", "hello", "secret")).kind);
    }

    @Test void logFieldsCannotAddLines() {
        assertEquals("grades?2026 client=fake", Broker.clean("grades\n2026 client=fake"));
        assertEquals("-", Broker.clean(null));
    }
}
