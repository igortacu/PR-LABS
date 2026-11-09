package prlabs.coffee;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** Interactive client or provider. The main thread receives while a daemon reads the keyboard. */
public final class ConsolePeer {
    private ConsolePeer() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 3 || (!args[0].equals("client") && !args[0].equals("provider"))) {
            System.err.println("Usage: ConsolePeer <client|provider> <server-address> <port>");
            System.exit(2);
        }
        String role = args[0];
        int port = Integer.parseInt(args[2]);
        try (Socket socket = new Socket(args[1], port)) {
            socket.setKeepAlive(true);
            LineChannel channel = new LineChannel(socket);
            channel.send("ROLE " + role.toUpperCase(Locale.ROOT));
            System.out.println("Connected. Commands: menu, "
                    + (role.equals("client") ? "order coffee=1 tea=2" : "deliver coffee=20 tea=10")
                    + ", quit");

            Thread keyboard = new Thread(() -> readKeyboard(channel, socket), "keyboard");
            keyboard.setDaemon(true);
            keyboard.start();

            try {
                while (true) {
                    String line;
                    try {
                        line = channel.readLine();
                    } catch (LineChannel.InvalidFrameException e) {
                        System.err.println("Invalid server message: " + e.getMessage());
                        continue;
                    }
                    if (line == null) {
                        System.out.println("Server disconnected.");
                        break;
                    }
                    if (line.equals("PING")) {
                        channel.send("PONG");
                    } else if (!line.equals("PONG")) {
                        System.out.println(line);
                        if (line.equals("BYE")) break;
                    }
                }
            } catch (IOException e) {
                System.err.println("Connection lost: " + e.getMessage());
            }
        }
    }

    private static void readKeyboard(LineChannel channel, Socket socket) {
        try {
            BufferedReader keyboard = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
            String line;
            while ((line = keyboard.readLine()) != null) {
                String message = normalize(line);
                if (message.isEmpty()) continue;
                try {
                    channel.send(message);
                } catch (IllegalArgumentException e) {
                    System.err.println("Invalid input: " + e.getMessage());
                    continue;
                }
                if (message.equals("QUIT")) return;
            }
            channel.send("QUIT");
        } catch (IOException | IllegalArgumentException e) {
            if (!socket.isClosed()) System.err.println("Input/send error: " + e.getMessage());
        }
    }

    private static String normalize(String line) {
        String trimmed = line.trim();
        int space = trimmed.indexOf(' ');
        String command = space < 0 ? trimmed : trimmed.substring(0, space);
        return command.toUpperCase(Locale.ROOT) + (space < 0 ? "" : trimmed.substring(space));
    }
}
