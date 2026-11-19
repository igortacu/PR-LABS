import io
import socket
import sys
import threading
import time
import unittest
from pathlib import Path


PYTHON_CLIENT_DIR = Path(__file__).resolve().parents[1] / "python"
sys.path.insert(0, str(PYTHON_CLIENT_DIR))

from coffee_peer import InvalidFrameError, LineChannel, normalize_command, run_peer


class LineChannelTest(unittest.TestCase):
    def test_reassembles_fragmented_messages_and_preserves_combined_messages(self):
        reader_socket, writer_socket = socket.socketpair()
        self.addCleanup(reader_socket.close)
        self.addCleanup(writer_socket.close)
        channel = LineChannel(reader_socket)

        def write_fragments():
            writer_socket.sendall(b"MENU cof")
            time.sleep(0.02)
            writer_socket.sendall(b"fee=4\nREADY 7\n")

        writer = threading.Thread(target=write_fragments)
        writer.start()
        self.assertEqual("MENU coffee=4", channel.read_line())
        self.assertEqual("READY 7", channel.read_line())
        writer.join()

    def test_rejects_invalid_utf8_and_recovers_at_the_next_line(self):
        reader_socket, writer_socket = socket.socketpair()
        self.addCleanup(reader_socket.close)
        self.addCleanup(writer_socket.close)
        channel = LineChannel(reader_socket)
        writer_socket.sendall(b"\xff\nMENU\n")

        with self.assertRaisesRegex(InvalidFrameError, "Invalid UTF-8"):
            channel.read_line()
        self.assertEqual("MENU", channel.read_line())

    def test_rejects_oversized_message_and_recovers_at_the_next_line(self):
        reader_socket, writer_socket = socket.socketpair()
        self.addCleanup(reader_socket.close)
        self.addCleanup(writer_socket.close)
        channel = LineChannel(reader_socket)
        writer_socket.sendall(b"x" * 4097 + b"\nMENU\n")

        with self.assertRaisesRegex(InvalidFrameError, "Message too long"):
            channel.read_line()
        self.assertEqual("MENU", channel.read_line())

    def test_send_adds_one_lf_terminator(self):
        sender_socket, reader_socket = socket.socketpair()
        self.addCleanup(sender_socket.close)
        self.addCleanup(reader_socket.close)
        channel = LineChannel(sender_socket)

        channel.send("ORDER coffee=1")

        self.assertEqual(b"ORDER coffee=1\n", reader_socket.recv(100))


class PythonPeerTest(unittest.TestCase):
    def test_normalizes_only_the_command_word(self):
        self.assertEqual("ORDER coffee=1 tea=2", normalize_command("  order coffee=1 tea=2  "))
        self.assertEqual("MENU", normalize_command("menu"))

    def test_client_exchanges_messages_and_writes_traces_to_stderr(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        received = []
        allow_commands = threading.Event()

        def delayed_input():
            allow_commands.wait()
            yield "menu\n"
            yield "quit\n"

        def serve():
            connection, _ = listener.accept()
            with connection:
                channel = LineChannel(connection)
                received.append(channel.read_line())
                allow_commands.set()
                connection.sendall(b"OK CLIENT\n")
                received.append(channel.read_line())
                connection.sendall(b"MENU coffee=10 tea=11 croissant=12\n")
                received.append(channel.read_line())
                connection.sendall(b"BYE\n")

        server = threading.Thread(target=serve)
        server.start()
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_peer(
            "client",
            "127.0.0.1",
            listener.getsockname()[1],
            input_stream=delayed_input(),
            output_stream=stdout,
            error_stream=stderr,
        )
        server.join()

        self.assertEqual(0, exit_code)
        self.assertEqual(["ROLE CLIENT", "MENU", "QUIT"], received)
        self.assertIn("OK CLIENT", stdout.getvalue())
        self.assertIn("MENU coffee=10 tea=11 croissant=12", stdout.getvalue())
        self.assertIn("[TRACE] CONNECT", stderr.getvalue())
        self.assertIn("[TRACE] SEND ROLE CLIENT", stderr.getvalue())
        self.assertIn("[TRACE] RECV BYE", stderr.getvalue())
        self.assertIn("[TRACE] CLOSE", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
