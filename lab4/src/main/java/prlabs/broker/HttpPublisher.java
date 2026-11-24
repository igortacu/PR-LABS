package prlabs.broker;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.Scanner;
import com.google.gson.Gson;

public class HttpPublisher {
    public static void main(String[] args) throws Exception {
        if (args.length != 4) {
            System.out.println("Usage: BROKER_TOKEN=... HttpPublisher <https://broker:port> <topic> <name> <broker.crt>");
            return;
        }
        String token = Tls.token();
        HttpClient client = HttpClient.newBuilder().sslContext(Tls.clientContext(java.nio.file.Path.of(args[3]))).build();
        Gson gson = new Gson();
        URI url = URI.create(args[0] + "/topics/" + args[1] + "/messages");
        Scanner keyboard = new Scanner(System.in, StandardCharsets.UTF_8);
        while (keyboard.hasNextLine()) {
            String body = keyboard.nextLine();
            String json = gson.toJson(java.util.Map.of("sender", args[2], "body", body));
            HttpRequest request = HttpRequest.newBuilder(url)
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + token)
                    .POST(HttpRequest.BodyPublishers.ofString(json)).build();
            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
            System.out.println(response.statusCode() + " " + response.body());
        }
    }
}
