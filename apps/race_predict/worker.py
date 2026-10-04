"""Run scraping in an isolated process (the legacy scraper uses module globals)."""
import json
import sys
import traceback
from pathlib import Path

from .service import configure_cached_chromedriver, fetch_races, run_prediction


def main():
    destination = Path(sys.argv[1])
    request = json.loads(sys.stdin.read())
    try:
        configure_cached_chromedriver()
        result = (fetch_races(request["date"]) if request["action"] == "races"
                  else run_prediction(request))
        payload = {"status": "done", "result": result}
    except Exception as error:
        traceback.print_exc()
        from selenium.common.exceptions import NoSuchDriverException, WebDriverException
        message = str(error)
        if isinstance(error, NoSuchDriverException):
            message = "ChromeDriverを起動できません。Chromeと対応するDriverを確認してください（詳細は進捗ログ）。"
        elif isinstance(error, WebDriverException):
            message = "Chromeでレース情報を取得できませんでした。ブラウザの起動環境とネットワークを確認してください（詳細は進捗ログ）。"
        payload = {"status": "error", "error": message}
    destination.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
