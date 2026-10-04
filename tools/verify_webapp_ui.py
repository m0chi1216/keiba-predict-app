"""Headless Chrome check: reopen an active job, leave, then restore real model results.

Run from repository root: python -m tools.verify_webapp_ui
Uses saved inputs only; no race-site requests. Requires Chrome and its driver.
"""
import json
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from apps.race_predict import server, service
from src.browser import create_chrome_driver


def main():
    service.configure_cached_chromedriver()
    release, finished = threading.Event(), threading.Event()
    execute = server.execute_job

    def delayed_execute(*args):
        try:
            if not release.wait(30):
                raise RuntimeError("Browser check did not release the worker")
            execute(*args)
        finally:
            finished.set()

    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{http.server_port}"
    driver = None
    try:
        with patch.object(server, "execute_job", side_effect=delayed_execute):
            driver = create_chrome_driver()
            wait = WebDriverWait(driver, 20)
            driver.get(base)
            wait.until(lambda browser: browser.find_element(By.ID, "predict").is_enabled())
            assert driver.find_element(By.TAG_NAME, "h1").text == "競馬予想アプリ"
            driver.find_element(By.ID, "race-id").send_keys("202608040211")
            driver.find_element(By.ID, "use-saved").click()
            driver.find_element(By.ID, "predict").click()
            wait.until(lambda _: bool(server.JOBS))
            driver.refresh()
            wait.until(lambda browser: browser.find_element(By.ID, "race-id").get_attribute("value") == "202608040211")
            assert not driver.find_element(By.ID, "predict").is_enabled()
            assert driver.find_element(By.ID, "progress").is_displayed()
            driver.get("about:blank")
            release.set()
            assert finished.wait(30), "Worker did not finish while page was closed"
            job_id = next(reversed(server.JOBS))
            snapshot = server.job_snapshot(job_id)
            assert snapshot["status"] == "done", snapshot
            driver.get(base)
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, ".model-result")) == 2)
            assert driver.find_element(By.ID, "predict").is_enabled()
            models = snapshot["result"]["models"]
            sections = driver.find_elements(By.CSS_SELECTOR, ".model-result")
            counts = []
            for model, section in zip(models, sections):
                count = len(section.find_elements(By.CSS_SELECTOR, "tbody tr"))
                assert count == len(model["horses"])
                assert all(1 < horse["odds"] <= model["settings"]["max_odds"] for horse in model["horses"])
                counts.append(count)
            errors = [entry for entry in driver.get_log("browser") if entry["level"] == "SEVERE"
                      and "favicon.ico" not in entry["message"]]
            assert not errors, errors
            # Race-list jobs and worker errors must also restore on reopening.
            with server.LOCK:
                server.JOBS["ui-check-races"] = {
                    "status": "done", "request": {"action": "races", "date": "2026-10-04"},
                    "result": {"date": "2026-10-04", "races": [
                        {"race_id": "202608040211", "track": "京都", "number": 11, "name": "復元テスト"}]}}
            driver.refresh()
            wait.until(lambda browser: browser.find_element(By.ID, "race-select").get_attribute("value") == "202608040211")
            assert driver.find_element(By.ID, "list-mode").is_displayed()
            with server.LOCK:
                server.JOBS["ui-check-error"] = {"status": "error", "error": "復元エラーテスト",
                                                "request": snapshot["request"]}
            driver.refresh()
            wait.until(lambda browser: browser.find_element(By.ID, "notice").text == "復元エラーテスト")
            assert driver.find_element(By.ID, "predict").is_enabled()
            print(json.dumps({"job_id": job_id, "input_csv": snapshot["result"]["input_csv"],
                              "displayed_counts": counts, "reopen_running": True,
                              "completed_without_page": True, "restored_results": True,
                              "restored_races_and_errors": True}, ensure_ascii=False))
    finally:
        release.set()
        if driver:
            driver.quit()
        if server.JOBS:
            finished.wait(30)
        http.shutdown()
        http.server_close()


if __name__ == "__main__":
    main()
