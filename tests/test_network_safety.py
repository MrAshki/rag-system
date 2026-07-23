import socket
import unittest


class NetworkSafetyTests(unittest.TestCase):
    def test_non_local_connections_are_blocked(self):
        sock = socket.socket()
        try:
            with self.assertRaisesRegex(AssertionError, "non-local network connection blocked"):
                sock.connect(("203.0.113.1", 443))
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
