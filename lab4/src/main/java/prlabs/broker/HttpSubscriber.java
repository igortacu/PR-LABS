package prlabs.broker;

import com.google.gson.Gson;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

public class HttpSubscriber {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.out.println("Usage: HttpSubscriber <broker-url> <topic>");
            return;
        }
        URI url = URI.create(args[0] + "/topics/" + args[1] + "/stream");
        HttpRequest request = HttpRequest.newBuilder(url).GET().build();
        HttpResponse<java.util.stream.Stream<String>> response = HttpClient.newHttpClient()
                .send(request, HttpResponse.BodyHandlers.ofLines());
        if (response.statusCode() != 200) {
            System.out.println("Subscribe failed: " + response.statusCode());
            return;
        }
        Gson gson = new Gson();
        response.body().filter(line -> !line.isBlank()).forEach(line -> {
            Broker.Message message = gson.fromJson(line, Broker.Message.class);
            System.out.printf("[%s] %s: %s%n", message.topic(), message.sender(), message.body());
        });
    }
}
