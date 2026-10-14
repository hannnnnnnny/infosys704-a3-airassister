"""Keep the local server and serverless entry point on one HTTP contract."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class HandlerFactoryTests(unittest.TestCase):
    def test_handler_can_be_created_without_binding_a_network_socket(self):
        self.assertTrue(callable(getattr(server, "make_handler", None)))
        with tempfile.TemporaryDirectory() as directory:
            store = server.ApplicationStore(Path(directory) / "data.sqlite3")
            handler = server.make_handler(store, server.SAPClient(server.SAPConfig()))
            self.assertTrue(callable(handler.do_GET))
            self.assertTrue(callable(handler.do_POST))


if __name__ == "__main__":
    unittest.main()
