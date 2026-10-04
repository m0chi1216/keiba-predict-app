"""Prediction adapter. Existing CLI scripts remain the source of purchase decisions."""
import json
import re
import math
import uuid
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
STRATEGIES = {
    "recovery": ("回収率重視AI", "v8_classification_auto.json"),
    "accuracy": ("的中率重視AI", "v8_regression_softmax.json"),
}
TRACKS = dict(zip((f"{i:02}" for i in range(1, 11)),
                  ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")))


def configure_cached_chromedriver():
    """Use an already-installed matching Windows driver without a metadata download."""
    if os.name != "nt" or os.environ.get("SE_CHROMEDRIVER"):
        return
    installations = [Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application",
                     Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application"]
    for installation in installations:
        if not (installation / "chrome.exe").exists():
            continue
        versions = sorted((path.name for path in installation.iterdir()
                           if path.is_dir() and re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", path.name)),
                          key=lambda version: tuple(map(int, version.split("."))), reverse=True)
        if not versions:
            continue
        major = versions[0].split(".")[0]
        cached = sorted((Path.home() / ".cache/selenium/chromedriver/win64").glob(f"{major}.*/*driver.exe"))
        if cached:
            os.environ["SE_CHROMEDRIVER"] = str(cached[-1])
            print(f"保存済みChromeDriverを使用: {cached[-1]}", flush=True)
            return


def validate_race_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{12}", value):
        raise ValueError("race idは半角数字12桁で入力してください。")
    if value[4:6] not in TRACKS or not 1 <= int(value[-2:]) <= 12:
        raise ValueError("JRAの競馬場・レース番号を持つrace idを指定してください。")
    return value


def validate_request(request):
    race_id = validate_race_id(request.get("race_id"))
    strategies = request.get("strategies")
    if (not isinstance(strategies, list) or not strategies
            or any(not isinstance(key, str) or key not in STRATEGIES for key in strategies)):
        raise ValueError("AIを1つ以上選択してください。")
    if not isinstance(request.get("use_saved", False), bool):
        raise ValueError("use_savedは真偽値で指定してください。")
    return race_id, list(dict.fromkeys(strategies))


def parse_races(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    races = {}
    for link in soup.select("a[href]"):
        race_id = parse_qs(urlparse(link["href"]).query).get("race_id", [""])[0]
        try:
            validate_race_id(race_id)
        except ValueError:
            continue
        container = link.find_parent("li", class_=re.compile("RaceList_DataItem")) or link
        name = container.select_one(".ItemTitle, .RaceName")
        title = name.get_text(" ", strip=True) if name else link.get_text(" ", strip=True)
        if race_id not in races or len(title) > len(races[race_id]["name"]):
            races[race_id] = {"race_id": race_id, "track": TRACKS[race_id[4:6]],
                              "number": int(race_id[-2:]), "name": title or "レース"}
    return sorted(races.values(), key=lambda race: (race["race_id"][4:6], race["number"]))


def fetch_races(date):
    from src.browser import create_chrome_driver
    from selenium.webdriver.support.ui import WebDriverWait
    datetime.strptime(date, "%Y-%m-%d")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
        raise ValueError("開催日をYYYY-MM-DD形式で指定してください。")
    driver = create_chrome_driver()
    try:
        driver.set_page_load_timeout(45)
        print(f"netkeibaの開催レースを取得中: {date}", flush=True)
        driver.get("https://race.netkeiba.com/top/race_list.html?kaisai_date=" + date.replace("-", ""))
        # The race list is populated by JavaScript; plain requests may return an empty shell.
        from selenium.common.exceptions import TimeoutException
        try:
            WebDriverWait(driver, 20).until(lambda browser: bool(parse_races(browser.page_source)))
        except TimeoutException:
            pass
        races = parse_races(driver.page_source)
        if not races:
            raise ValueError("開催レースを取得できませんでした。開催日を確認するかrace idで指定してください。")
        return {"date": date, "races": races}
    finally:
        driver.quit()


def find_saved_input(race_id):
    import pandas as pd
    # Never consume compact prediction CSVs as model inputs.
    paths = list((ROOT / "data/predict").glob("*/*.csv"))
    paths += list((ROOT / "data/webapp/inputs").glob("*/*/*.csv"))
    for path in sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True):
        if path.stem.endswith("_pred") or path.stem.startswith("race_id"):
            continue
        try:
            header = pd.read_csv(path, nrows=0)
            if "race_id" not in header or "horse_name" not in header or "distance" not in header:
                continue
            ids = pd.read_csv(path, usecols=["race_id"], dtype=str)["race_id"]
            if not ids.empty and ids.eq(race_id).all():
                return path
        except (ValueError, OSError):
            continue
    raise ValueError("このrace idの保存済み入力CSVがありません。保存済みデータの利用を解除してください。")


def present_result(result, settings):
    import pandas as pd
    from src.betting_strategy import make_candidates
    # Start with the top five even when the strategy only allows one, or excludes the race grade.
    display = make_candidates(result, 5, settings["normalization"], settings["temperature"])
    # Keep the original model ranking and purchase decisions; do not backfill excluded horses.
    display = display[display["ods"].map(lambda odds: pd.notna(odds) and math.isfinite(odds)
                                        and 1 < odds <= settings["max_odds"]).astype(bool)]
    display = display.sort_values("expected_value", ascending=False, kind="stable", na_position="last")
    horses = []
    for _, row in display.iterrows():
        reasons = []
        if row["excluded_grade"]:
            reasons.append("対象外のレース区分")
        if not row["is_candidate"]:
            reasons.append(f"購入候補の上位{settings['top_n']}頭の範囲外")
        odds = row["ods"]
        if pd.isna(row["expected_value"]) or row["expected_value"] <= settings["score_threshold"]:
            reasons.append("購入スコア条件未達")
        eligible = pd.notna(row["recommend_rank"])
        if eligible and not row["selected"]:
            reasons.append("条件適合（購入はスコア最大の1頭）")
        horses.append({"horse_num": row.get("horse_num"), "horse_name": row.get("horse_name"),
                       "odds": odds, "score": row["pred_prob"], "purchase_score": row["expected_value"],
                       "rank": row.get("candidate_rank"), "eligible": eligible,
                       "selected": bool(row["selected"]), "bet_amount": int(row["bet_amount"]),
                       "reasons": reasons})
    # Convert numpy scalars, pandas missing values and NaN into JSON-safe native values.
    def native(value):
        if isinstance(value, list):
            return [native(item) for item in value]
        if isinstance(value, dict):
            return {key: native(item) for key, item in value.items()}
        if pd.isna(value):
            return None
        if hasattr(value, "item"):
            value = value.item()
        return None if isinstance(value, float) and not math.isfinite(value) else value
    return native(horses)


def run_prediction(request):
    import pandas as pd
    from src import create_data_for_predict as creation
    from src.predict import predict
    race_id, keys = validate_request(request)
    if request.get("use_saved", False):
        path = find_saved_input(race_id)
        print(f"保存済み入力を利用: {path}", flush=True)
    else:
        print("最新の出馬表・オッズから予測データを作成します。数分かかる場合があります。", flush=True)
        # Each acquisition is kept independently, including its odds snapshot.
        output_root = ROOT / "data/webapp/inputs" / uuid.uuid4().hex
        path = creation.process_race(race_id, output_root=str(output_root))
        if path is None:
            raise ValueError("新馬戦・障害レースは既存のデータ作成設定で対象外です。")
        path = ROOT / path
    data = pd.read_csv(path, dtype={"race_id": str})
    if data.empty or not data["race_id"].eq(race_id).all():
        raise ValueError("取得したデータのrace idが指定と一致しません。")
    models = []
    for key in keys:
        label, filename = STRATEGIES[key]
        settings = json.loads((ROOT / "configs/strategies" / filename).read_text(encoding="utf-8"))["settings"]
        print(f"{label}で予測中…", flush=True)
        result = predict(ROOT / settings["model"], path, verbose=False,
                         win_rate_rank_threshold=settings["top_n"], normalization=settings["normalization"],
                         temperature=settings["temperature"], ev_threshold=settings["score_threshold"],
                         odds_threshold=settings["max_odds"], staking=settings["staking"],
                         base_bet=settings["base_bet"], exclude_grade=settings["exclude_grade"],
                         expected_task=settings["task"])
        models.append({"key": key, "label": label, "config": filename, "settings": settings,
                       "horses": present_result(result, settings)})
    first = data.iloc[0]
    return {"race_id": race_id, "track": str(first.get("race_track", TRACKS[race_id[4:6]])),
            "number": int(race_id[-2:]), "input_csv": str(path.relative_to(ROOT)),
            "input_modified": datetime.fromtimestamp(path.stat().st_mtime, ZoneInfo("Asia/Tokyo")).isoformat(),
            "created_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
            "use_saved": request.get("use_saved", False), "models": models}
