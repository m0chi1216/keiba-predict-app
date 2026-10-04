import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

import pandas as pd

from apps.race_predict import server, service
from src.predict import apply_purchase_strategy


class AppTests(unittest.TestCase):
    def test_request_validation(self):
        for value in ("123", "202699010111", "202605010199", "１２３４５６７８９０１２"):
            with self.assertRaises(ValueError):
                service.validate_race_id(value)
        with self.assertRaises(ValueError):
            service.validate_request({"race_id": "202608040211", "strategies": []})

    def test_race_list_parses_deduplicates_and_filters_external_races(self):
        html = '''<li class="RaceList_DataItem"><a href="/race/shutuba.html?race_id=202608040211"><span class="ItemTitle">京都大賞典</span></a></li>
        <a href="/race/result.html?race_id=202608040211">結果</a>
        <a href="?race_id=202645010111">地方</a>'''
        self.assertEqual(service.parse_races(html), [{"race_id": "202608040211", "track": "京都", "number": 11, "name": "京都大賞典"}])

    def fixture(self, regression=False, exclude_grade=None):
        data = pd.DataFrame({"race_id": ["202608040211"] * 6, "horse_num": range(1, 7),
                             "horse_name": list("ABCDEF"), "ods": [2, 12, 15, 5, 4, 100],
                             "race_grade": [6] * 6})
        data["predicted_rank" if regression else "pred_prob_first"] = ([1, 2, 3, 4, 5, 6] if regression else [.4, .25, .15, .1, .06, .04])
        result = apply_purchase_strategy(data, top_n=1 if regression else 5, normalization="auto",
                                          temperature=1, ev_threshold=1.1, max_odds=50, exclude_grade=exclude_grade)
        settings = dict(normalization="auto", temperature=1, top_n=1 if regression else 5,
                        score_threshold=1.1, max_odds=50)
        return result, settings

    def test_five_by_probability_then_purchase_score_and_purchase_badges(self):
        result, settings = self.fixture()
        horses = service.present_result(result, settings)
        self.assertEqual([horse["horse_name"] for horse in horses], ["B", "C", "A", "D", "E"])
        self.assertTrue(horses[0]["selected"])
        self.assertTrue(horses[1]["eligible"])
        self.assertFalse(horses[1]["selected"])
        self.assertFalse(horses[2]["eligible"])
        json.dumps(horses, allow_nan=False)

    def test_regression_displays_five_but_preserves_top_one_purchase_rule(self):
        result, settings = self.fixture(regression=True)
        horses = service.present_result(result, settings)
        self.assertEqual(len(horses), 5)
        self.assertTrue(all(not horse["eligible"] for horse in horses if horse["horse_name"] != "A"))

    def test_excluded_grade_still_displays_five_without_purchases(self):
        result, settings = self.fixture(exclude_grade=6)
        horses = service.present_result(result, settings)
        self.assertEqual(len(horses), 5)
        self.assertTrue(all(not horse["selected"] and "対象外のレース区分" in horse["reasons"] for horse in horses))

    def test_missing_odds_is_not_displayed(self):
        result, settings = self.fixture()
        result.loc[result.horse_name.eq("A"), "ods"] = float("nan")
        result = apply_purchase_strategy(result, exclude_grade=None)
        horses = service.present_result(result, settings)
        self.assertNotIn("A", [horse["horse_name"] for horse in horses])
        json.dumps(horses, allow_nan=False)

    def test_display_odds_boundary_and_no_backfill_for_both_models(self):
        for regression in (False, True):
            with self.subTest(regression=regression):
                result, settings = self.fixture(regression=regression)
                result["ods"] = [50, 50.01, float("inf"), 1, 2, 3]
                result = apply_purchase_strategy(result, top_n=settings["top_n"], max_odds=50,
                                                 ev_threshold=1.1, exclude_grade=None)
                horses = service.present_result(result, settings)
                self.assertEqual({horse["horse_name"] for horse in horses}, {"A", "E"})
                self.assertTrue(next(h for h in horses if h["horse_name"] == "A")["selected"])
                json.dumps(horses, allow_nan=False)

    def test_no_horses_when_none_meet_odds_condition(self):
        result, settings = self.fixture()
        result["ods"] = [51, 100, float("nan"), -2, 1, 2]
        self.assertEqual(service.present_result(result, settings), [])
        self.assertEqual(service.present_result(result.iloc[:0], settings), [])

    def test_background_worker_runs_without_polling_and_latest_job_is_recoverable(self):
        entered, finish, complete = threading.Event(), threading.Event(), threading.Event()
        request = {"action": "predict", "race_id": "202608040211", "strategies": ["recovery"], "use_saved": True}
        payload = {"status": "done", "result": {"models": []}}

        def fake_worker(command, **kwargs):
            self.assertEqual(json.loads(kwargs["input"]), request)
            entered.set()
            if not finish.wait(5):
                raise RuntimeError("Test worker was not released")
            Path(command[-1]).write_text(json.dumps(payload), encoding="utf-8")
            return type("Process", (), {"returncode": 0})()

        execute = server.execute_job
        def tracked_execute(*args):
            try:
                execute(*args)
            finally:
                complete.set()

        with tempfile.TemporaryDirectory() as folder, patch.object(server, "ROOT", Path(folder)), \
                patch.object(server, "JOBS", {}), patch.object(server.subprocess, "run", side_effect=fake_worker), \
                patch.object(server, "execute_job", side_effect=tracked_execute):
            http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            threading.Thread(target=http.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{http.server_port}"
            try:
                with urlopen(base + "/api/jobs") as response:
                    self.assertIsNone(json.load(response)["job"])
                with urlopen(Request(base + "/api/jobs", data=json.dumps(request).encode(),
                                     headers={"Content-Type": "application/json"})) as response:
                    job_id = json.load(response)["id"]
                self.assertTrue(entered.wait(5))
                # Reopen the page while running, then disconnect without polling.
                with urlopen(base + "/api/jobs") as response:
                    current = json.load(response)["job"]
                self.assertEqual(current["status"], "running")
                self.assertEqual(current["request"], request)
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/api/jobs", data=json.dumps(request).encode()))
                self.assertEqual(error.exception.code, 409)
                finish.set()
                self.assertTrue(complete.wait(5))
                with urlopen(base + "/api/jobs") as response:
                    restored = json.load(response)["job"]
                self.assertEqual(restored["id"], job_id)
                self.assertEqual(restored["status"], "done")
                self.assertEqual(restored["result"], payload["result"])
                with urlopen(base + "/api/jobs/" + job_id) as response:
                    self.assertEqual(json.load(response), restored)
            finally:
                finish.set()
                complete.wait(5)
                http.shutdown()
                http.server_close()

    def test_positive_subnanosecond_score_is_preserved_in_json(self):
        result, settings = self.fixture(regression=True)
        settings["temperature"] = .042925
        horse = next(horse for horse in service.present_result(result, settings) if horse["horse_name"] == "B")
        self.assertGreater(horse["score"], 0)
        self.assertLess(horse["score"], 1e-9)

    def test_http_static_validation_and_foreign_origin(self):
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        base = f"http://127.0.0.1:{http.server_port}"
        with urlopen(base) as response:
            self.assertIn("RACE", response.read().decode())
        request = Request(base+"/api/jobs", data=b'{}', headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 400)
        request = Request(base+"/api/jobs", data=b'{}', headers={"Origin":"https://example.com"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
