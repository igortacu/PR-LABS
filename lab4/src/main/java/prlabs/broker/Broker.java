package prlabs.broker;

import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import java.io.IOException;
import java.lang.reflect.Type;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.LinkedBlockingQueue;

/** One shared broker for either HTTP or gRPC. */
public class Broker {
    public record Message(long id, String topic, String sender, String body, String time) {}
    public record TopicInfo(String topic, int size) {}

    public static class BrokerException extends Exception {
        public final String kind;
        public BrokerException(String kind, String message) { super(message); this.kind = kind; }
    }

    private record Publisher(String name, Set<String> topics) {}

    private static class Topic {
        final List<Message> messages = new ArrayList<>();
        final BlockingQueue<Message> pending = new LinkedBlockingQueue<>();
        final CopyOnWriteArrayList<BlockingQueue<Message>> subscribers = new CopyOnWriteArrayList<>();
        boolean workerStarted;
    }

    private final Path dataFile;
    private final Gson gson = new Gson();
    private final Map<String, Publisher> tokens = new HashMap<>();
    private final Map<String, Topic> topics = new HashMap<>();

    public Broker(Path dataFile, Path tokenFile) throws IOException {
        this.dataFile = dataFile;
        for (String line : Files.readAllLines(tokenFile, StandardCharsets.UTF_8)) {
            if (line.isBlank() || line.startsWith("#")) continue;
            String[] fields = line.split("\\|", -1);
            if (fields.length != 3 || fields[0].isBlank() || fields[1].isBlank())
                throw new IOException("Bad line in token file: " + line);
            tokens.put(fields[0], new Publisher(fields[1], Set.of(fields[2].split(","))));
        }
        if (Files.exists(dataFile)) {
            Type type = new TypeToken<Map<String, List<Message>>>() {}.getType();
            Map<String, List<Message>> saved = gson.fromJson(Files.readString(dataFile), type);
            if (saved == null) throw new IOException("Empty data file");
            for (var entry : saved.entrySet()) {
                Topic topic = new Topic();
                topic.messages.addAll(entry.getValue());
                topics.put(entry.getKey(), topic);
            }
        }
    }

    private static void checkTopic(String name) throws BrokerException {
        if (!name.matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"))
            throw new BrokerException("invalid", "Invalid topic name");
    }

    public synchronized Message publish(String name, String sender, String body, String token)
            throws BrokerException {
        checkTopic(name);
        Publisher publisher = tokens.get(token);
        if (publisher == null) throw new BrokerException("unauthenticated", "Missing or unknown token");
        if (!publisher.name().equals(sender) || !publisher.topics().contains(name))
            throw new BrokerException("forbidden", "Token cannot publish for this sender and topic");
        if (body == null || body.isBlank() || body.getBytes(StandardCharsets.UTF_8).length > 65536)
            throw new BrokerException("invalid", "Body must contain 1 to 65536 UTF-8 bytes");

        Topic topic = topics.computeIfAbsent(name, ignored -> new Topic());
        Message message = new Message(topic.messages.size() + 1L, name, sender, body, Instant.now().toString());
        topic.messages.add(message);
        try {
            save();
        } catch (IOException error) {
            topic.messages.remove(topic.messages.size() - 1);
            throw new BrokerException("storage", "Could not save message: " + error.getMessage());
        }
        startWorker(name, topic);
        topic.pending.add(message);
        return message;
    }

    private void save() throws IOException {
        Map<String, List<Message>> snapshot = new HashMap<>();
        topics.forEach((name, topic) -> snapshot.put(name, topic.messages));
        Path parent = dataFile.toAbsolutePath().getParent();
        Files.createDirectories(parent);
        Path temporary = Files.createTempFile(parent, "broker-", ".tmp");
        try {
            Files.writeString(temporary, gson.toJson(snapshot), StandardCharsets.UTF_8);
            try (var channel = java.nio.channels.FileChannel.open(temporary, java.nio.file.StandardOpenOption.WRITE)) {
                channel.force(true);
            }
            Files.move(temporary, dataFile, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally {
            Files.deleteIfExists(temporary);
        }
    }

    private void startWorker(String name, Topic topic) {
        if (topic.workerStarted) return;
        topic.workerStarted = true;
        Thread worker = new Thread(() -> {
            while (true) {
                try {
                    Message message = topic.pending.take();
                    for (BlockingQueue<Message> subscriber : topic.subscribers) subscriber.add(message);
                } catch (InterruptedException ignored) { return; }
            }
        }, "delivery-" + name);
        worker.setDaemon(true);
        worker.start();
    }

    public synchronized BlockingQueue<Message> subscribe(String name) throws BrokerException {
        checkTopic(name);
        Topic topic = topics.computeIfAbsent(name, ignored -> new Topic());
        BlockingQueue<Message> mailbox = new LinkedBlockingQueue<>();
        topic.subscribers.add(mailbox);
        return mailbox;
    }

    public synchronized void unsubscribe(String name, BlockingQueue<Message> mailbox) {
        Topic topic = topics.get(name);
        if (topic != null) topic.subscribers.remove(mailbox);
    }

    public synchronized List<TopicInfo> listTopics() {
        return topics.entrySet().stream().filter(e -> !e.getValue().messages.isEmpty())
                .map(e -> new TopicInfo(e.getKey(), e.getValue().messages.size()))
                .sorted(java.util.Comparator.comparing(TopicInfo::topic)).toList();
    }

    public static void log(String client, String topic, long id, String result) {
        System.out.printf("%s client=%s topic=%s id=%d result=%s%n", Instant.now(), client, topic, id, result);
    }
}
