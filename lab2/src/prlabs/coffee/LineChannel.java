package prlabs.coffee;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;

/** A bounded, strict UTF-8, newline-framed protocol over a plain TCP socket. */
public final class LineChannel {
    public static final int MAX_LINE_BYTES = 4096;
    private final InputStream input;
    private final OutputStream output;
    private final Object sendLock = new Object();
    private final ByteArrayOutputStream pending = new ByteArrayOutputStream();
    private boolean discardingLongFrame;

    public LineChannel(Socket socket) throws IOException {
        input = new BufferedInputStream(socket.getInputStream());
        output = socket.getOutputStream();
    }

    /** Returns null on EOF. An invalid frame is consumed through its newline. */
    public String readLine() throws IOException, InvalidFrameException {
        while (true) {
            int next = input.read();
            if (next == -1) {
                if (pending.size() == 0 && !discardingLongFrame) return null;
                throw new IOException("Connection ended in the middle of a message");
            }
            if (discardingLongFrame) {
                if (next == '\n') discardingLongFrame = false;
                continue;
            }
            if (next == '\n') break;
            if (pending.size() < MAX_LINE_BYTES) pending.write(next);
            else {
                pending.reset();
                discardingLongFrame = true;
                throw new InvalidFrameException("Message too long");
            }
        }
        byte[] bytes = pending.toByteArray();
        pending.reset();
        int length = bytes.length;
        if (length > 0 && bytes[length - 1] == '\r') length--;
        try {
            return StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes, 0, length)).toString();
        } catch (CharacterCodingException e) {
            throw new InvalidFrameException("Invalid UTF-8");
        }
    }

    /** Safe to call from a connection thread and a worker thread at once. */
    public void send(String line) throws IOException {
        if (line.indexOf('\n') >= 0 || line.indexOf('\r') >= 0) {
            throw new IllegalArgumentException("Protocol message contains a newline");
        }
        byte[] bytes = (line + "\n").getBytes(StandardCharsets.UTF_8);
        if (bytes.length - 1 > MAX_LINE_BYTES) throw new IllegalArgumentException("Message too long");
        synchronized (sendLock) {
            output.write(bytes);
            output.flush();
        }
    }

    public static final class InvalidFrameException extends Exception {
        public InvalidFrameException(String message) { super(message); }
    }
}
