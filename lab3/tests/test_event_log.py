import json
import tempfile
import unittest
from pathlib import Path

from lab3.lan_chat.event_log import DatagramLogger


class DatagramLoggerTests(unittest.TestCase):
    def test_sent_received_and_dropped_datagrams_are_json_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peer.log"
            logger = DatagramLogger(path)

            logger.sent(("192.168.1.255", 5000), "general", 123)
            logger.received(("192.168.1.9", 5000), "join", 87)
            logger.dropped(("192.168.1.8", 6000), "invalid", 1401, "too large")

            records = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual([item["action"] for item in records], ["sent", "received", "dropped"])
        self.assertEqual(records[0]["endpoint"], "192.168.1.255:5000")
        self.assertEqual(records[0]["kind"], "general")
        self.assertEqual(records[0]["size"], 123)
        self.assertEqual(records[2]["reason"], "too large")
        self.assertRegex(records[0]["time"], r"^\d{4}-\d{2}-\d{2}T")


if __name__ == "__main__":
    unittest.main()
