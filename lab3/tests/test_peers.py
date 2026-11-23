import unittest

from lab3.lan_chat.peers import PeerDirectory, PeerInfo, duplicate_name_loser


class PeerDirectoryTests(unittest.TestCase):
    def test_upsert_tracks_join_and_endpoint_updates(self):
        directory = PeerDirectory()

        joined = directory.upsert("peer-a", "Ana", ("192.168.1.10", 41000), now=10.0)
        updated = directory.upsert("peer-a", "Ana", ("192.168.1.11", 42000), now=12.0)

        self.assertTrue(joined)
        self.assertFalse(updated)
        self.assertEqual(
            directory.get_by_name("Ana"),
            PeerInfo("peer-a", "Ana", ("192.168.1.11", 42000), 12.0),
        )

    def test_snapshot_is_an_immutable_name_sorted_copy(self):
        directory = PeerDirectory()
        directory.upsert("2", "Zoe", ("10.0.0.2", 2), now=2.0)
        directory.upsert("1", "Ana", ("10.0.0.1", 1), now=1.0)

        snapshot = directory.snapshot()
        directory.remove("1")

        self.assertIsInstance(snapshot, tuple)
        self.assertEqual([peer.name for peer in snapshot], ["Ana", "Zoe"])
        self.assertEqual([peer.name for peer in directory.snapshot()], ["Zoe"])

    def test_expire_removes_peers_not_heard_for_15_seconds(self):
        directory = PeerDirectory()
        directory.upsert("old", "Old", ("10.0.0.1", 1), now=10.0)
        directory.upsert("edge", "Edge", ("10.0.0.2", 2), now=10.1)

        expired = directory.expire(now=25.0)

        self.assertEqual([peer.name for peer in expired], ["Old"])
        self.assertIsNotNone(directory.get_by_name("Edge"))

    def test_graceful_remove_returns_departed_peer(self):
        directory = PeerDirectory()
        directory.upsert("peer-a", "Ana", ("127.0.0.1", 5001), now=1.0)

        removed = directory.remove("peer-a")

        self.assertEqual(removed.name, "Ana")
        self.assertIsNone(directory.remove("peer-a"))

    def test_duplicate_name_conflict_has_exactly_one_deterministic_loser(self):
        self.assertFalse(duplicate_name_loser("0000", "ffff"))
        self.assertTrue(duplicate_name_loser("ffff", "0000"))


if __name__ == "__main__":
    unittest.main()
