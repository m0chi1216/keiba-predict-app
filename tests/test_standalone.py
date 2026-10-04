import contextlib
import io
import json
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

import numpy as np

from apps.race_predict import service, server
from apps.race_predict.assets import verify_assets


class StandaloneTests(unittest.TestCase):
    def test_packaged_assets_are_complete(self):
        self.assertEqual(verify_assets(), 10)

    def test_both_packaged_models_match_original_cli(self):
        expected = json.loads((Path(__file__).parent / "expected_sample.json").read_text(encoding="utf-8"))
        with contextlib.redirect_stdout(io.StringIO()):
            result = service.run_prediction({"race_id": "202608040211", "strategies": ["recovery", "accuracy"], "use_saved": True})
        for model in result["models"]:
            rows = expected[model["key"]]
            self.assertEqual(len(model["horses"]), 5)
            self.assertEqual([int(row["horse_num"]) for row in model["horses"]], [row["horse_num"] for row in rows])
            for actual, original in zip(model["horses"], rows):
                np.testing.assert_allclose(actual["purchase_score"], original["purchase_score"], rtol=1e-12)
                self.assertEqual(actual["selected"], original["selected"])
                self.assertEqual(actual["bet_amount"], original["bet_amount"])

    def test_public_origin_and_healthcheck(self):
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        base = f"http://127.0.0.1:{http.server_port}"
        with patch.dict(os.environ, {"APP_ORIGIN": "https://keiba.example.com"}):
            request = Request(base, headers={"Host": "keiba.example.com", "Origin": "https://keiba.example.com"})
            with urlopen(request) as response:
                self.assertEqual(response.status, 200)
            request = Request(base, headers={"Host": "keiba.example.com", "Origin": "https://other.example.com"})
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 403)
            request = Request(base, headers={"Host": "keiba.example.com", "Origin": "http://127.0.0.1:" + str(http.server_port)})
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 403)
            with urlopen(base + "/healthz") as response:
                self.assertEqual(json.load(response), {"status": "ok"})
            # Docker may map a different loopback port to the internal 8000 port.
            request = Request(base, headers={"Host": "127.0.0.1:8001", "Origin": "http://127.0.0.1:8001"})
            with urlopen(request) as response:
                self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
