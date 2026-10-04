"""
予測データ作成スクリプト

指定されたrace_idの馬柱URLから、学習済みモデルで予測するためのデータを作成します。
"""

import pandas as pd
import numpy as np
import requests
if __package__:
    from .browser import create_chrome_driver
else:
    from browser import create_chrome_driver
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import re
import time
import os
from datetime import datetime


# ============================================================
# ユーザ設定: ここを編集してください
# ============================================================

# レースID取得モード設定
# MODE = "list"  # リストモード: RACE_IDSを使用
# MODE = "csv"   # CSVモード: CSV_PATHからレースIDを読み込む
MODE = "list"

# リストモード用: 複数のレースIDをリストで指定可能（単一の場合は文字列でも可）
RACE_IDS = [
    "202608040211",
]

# CSVモード用: レースIDが記載されたCSVファイルのパス
# CSVファイルは "race_id" という列名を持つ必要があります
CSV_PATH = "data/predict/20260607/race_id_list_tokyo.csv"

# レースフィルタ設定
SKIP_SHINBA = True  # 新馬戦をスキップする（RACE_GRADEに"新馬"が含まれるレース）
SKIP_SHOGAI = True  # 障害レースをスキップする（RACE_GRADEに"障害"が含まれるレース）

# 以下は自動取得が失敗した場合のデフォルト値として使用されます
# 競馬場ごとに天候と馬場状態を設定できます
DEFAULT_WEATHER_BY_TRACK = {
    "東京": "晴",
    "中山": "晴",
    "阪神": "晴",
    "京都": "晴",
    "中京": "晴",
    "新潟": "晴",
    "札幌": "晴",
    "函館": "晴",
    "福島": "晴",
    "小倉": "晴",
}

DEFAULT_COURSE_CONDITION_BY_TRACK = {
    "東京": "良",
    "中山": "良",
    "阪神": "良",
    "京都": "良",
    "中京": "良",
    "新潟": "良",
    "札幌": "良",
    "函館": "良",
    "福島": "良",
    "小倉": "良",
}

# 上記辞書に存在しない競馬場用のフォールバックデフォルト値
FALLBACK_WEATHER = "晴"
FALLBACK_COURSE_CONDITION = "良"

# 出力ファイル名とディレクトリは自動生成されます
# data/predict/YYYYMMDD/{RACE_TRACK}_{RACE_NUM}.csv の形式で保存されます

# ============================================================


def extract_race_track(text):
    """開催情報から競馬場名を抽出"""
    if not text:
        return None
    match = re.search(r'\d+([^\d]+)\d+', text)
    return match.group(1) if match else None


def extract_course_info(text):
    """コース情報から種別と距離を抽出"""
    if not text:
        return None, None
    
    course_type = None
    if '芝' in text:
        course_type = '芝'
    elif 'ダ' in text:
        course_type = 'ダ'
    
    distance_match = re.search(r'(\d+)', text)
    distance = distance_match.group(1) if distance_match else None
    
    return course_type, distance


def extract_race_grade(race_name):
    """レース名からグレードを抽出する"""
    if not race_name:
        return None
    
    match = re.search(r'\(([^)]+)\)$', race_name)
    if match:
        return match.group(1)
    
    return race_name


def extract_race_id(url):
    """URLからrace_idを抽出"""
    if not url:
        return None
    match = re.search(r'/race/(\d+)', url)
    return match.group(1) if match else None


def extract_jockey_id(url):
    """URLからjockey_idを抽出"""
    if not url:
        return None
    match = re.search(r'/jockey/result/recent/(\d+)', url)
    return match.group(1) if match else None


def extract_pass_positions(text):
    """通過順位から開始・中間・最後の位置を抽出する"""
    if not text or text == '-':
        return None, None, None
    
    positions = text.split('-')
    
    try:
        positions = [int(p) for p in positions]
    except:
        return None, None, None
    
    if len(positions) == 0:
        return None, None, None
    elif len(positions) == 1:
        return positions[0], positions[0], positions[0]
    elif len(positions) == 2:
        middle = sum(positions) / 2.0
        return positions[0], middle, positions[1]
    elif len(positions) == 3:
        return positions[0], positions[1], positions[2]
    else:
        middle = (positions[1] + positions[2]) / 2.0
        return positions[0], middle, positions[-1]


def extract_pace(text):
    """ペースを抽出"""
    if not text or text == '-':
        return None, None
    
    pace_parts = text.split('-')
    pace_first = pace_parts[0] if len(pace_parts) > 0 else None
    pace_last = pace_parts[1] if len(pace_parts) > 1 else None
    
    return pace_first, pace_last


def extract_horse_weight(text):
    """馬体重と増減を抽出"""
    if not text or text == '-':
        return None, None
    
    match = re.search(r'(\d+)\(([\+\-]?\d+)\)', text)
    if match:
        horse_weight = int(match.group(1))
        horse_weight_diff = int(match.group(2))
        return horse_weight, horse_weight_diff
    
    return None, None


def convert_time_to_seconds(time_str):
    """
    レースタイムを秒数に変換

    Args:
        time_str (str): タイム文字列（例: "2:11.0", "1:35.5"）

    Returns:
        float: 秒数（例: 131.0, 95.5）、変換できない場合はNone
    """
    if not time_str or time_str == '-':
        return None

    try:
        # "分:秒.小数" の形式をパース
        match = re.search(r'(\d+):(\d+\.?\d*)', time_str)
        if match:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            return minutes * 60 + seconds

        # 秒のみの場合（念のため）
        return float(time_str)
    except:
        return None


def categorize_race_track(track):
    """競馬場をカテゴリに分類"""
    if pd.isna(track):
        return None

    east_japan_tracks = ["東京", "中山"]
    west_japan_tracks = ["中京", "京都", "阪神"]
    local_japan_tracks = ["札幌", "函館", "福島", "新潟", "小倉"]

    if track in east_japan_tracks:
        return 'east'
    elif track in west_japan_tracks:
        return 'west'
    elif track in local_japan_tracks:
        return 'local'
    else:
        return 'other'


def extract_producer_id(url):
    """生産者リンクからproducer_idを抽出する"""
    if not url:
        return None
    
    match = re.search(r'/breeder/(\d+)/', url)
    if match:
        return match.group(1)
    return None


def extract_pedigree_id(url):
    """血統リンクから馬のIDを抽出する"""
    if not url:
        return None
    
    match = re.search(r'/horse/([a-zA-Z0-9]+)/?', url)
    if match:
        return match.group(1)
    return None


def extract_race_info_from_shutuba(soup, race_id):
    """
    出馬表ページからレース情報を抽出

    Parameters:
    -----------
    soup : BeautifulSoup
        出馬表ページのBeautifulSoupオブジェクト
    race_id : str
        レースID

    Returns:
    --------
    dict
        レース情報の辞書 (RACE_YEAR, RACE_MONTH, RACE_DATE, RACE_TRACK, RACE_NUM, RACE_GRADE, RACE_TYPE, DISTANCE, WEATHER, COURSE_CONDITION)
    """
    race_info = {}

    # RACE_YEARをRACE_IDの先頭4桁から取得
    if race_id and len(race_id) >= 4:
        race_info['RACE_YEAR'] = int(race_id[:4])

    # RACE_MONTHとRACE_DATEを取得
    date_list = soup.find('dl', id='RaceList_DateList')
    if date_list:
        active_dd = date_list.find('dd', class_='Active')
        if active_dd:
            date_text = active_dd.get_text(strip=True)
            # "12月22日"や"12/22"の形式から月日を抽出
            date_match = re.search(r'(\d+)[月/](\d+)', date_text)
            if date_match:
                race_info['RACE_MONTH'] = int(date_match.group(1))
                race_info['RACE_DATE'] = int(date_match.group(2))

    # RaceList_NameBox要素を取得
    race_name_box = soup.find('div', class_='RaceList_NameBox')

    if not race_name_box:
        print("WARNING: RaceList_NameBoxが見つかりません")
        return race_info

    # レース番号を取得
    race_num_elem = race_name_box.find('span', class_='RaceNum')
    if race_num_elem:
        race_num_text = race_num_elem.get_text(strip=True)
        race_num_match = re.search(r'(\d+)R', race_num_text)
        if race_num_match:
            race_info['RACE_NUM'] = int(race_num_match.group(1))

    # レース名とグレード情報を取得
    race_title = race_name_box.find('h1', class_='RaceName')
    if race_title:
        # グレードアイコンから判定
        grade_icon = race_title.find('span', class_=re.compile(r'Icon_GradeType\d+'))
        if grade_icon:
            icon_classes = grade_icon.get('class', [])
            for cls in icon_classes:
                if cls == 'Icon_GradeType1':
                    race_info['RACE_GRADE'] = 'GI'
                    break
                elif cls == 'Icon_GradeType2':
                    race_info['RACE_GRADE'] = 'GII'
                    break
                elif cls == 'Icon_GradeType3':
                    race_info['RACE_GRADE'] = 'GIII'
                    break
                elif cls == 'Icon_GradeType4':
                    race_info['RACE_GRADE'] = 'OP'
                    break
                elif cls == 'Icon_GradeType15':
                    race_info['RACE_GRADE'] = 'L'
                    break

    # グレードがアイコンから取得できない場合、RaceData02から取得
    if 'RACE_GRADE' not in race_info:
        race_data02 = race_name_box.find('div', class_='RaceData02')
        if race_data02:
            # RaceData02の4つ目と5つ目のspanタグを取得
            spans = race_data02.find_all('span')
            if len(spans) >= 5:
                # 4つ目と5つ目のspanのテキストを取得
                span4_text = spans[3].get_text(strip=True)
                span5_text = spans[4].get_text(strip=True)

                # 5つ目のspanが「3勝クラス」の場合のみ、連結せずにそのまま使用
                # 全角数字を半角に変換してからチェック
                span5_normalized = span5_text.translate(str.maketrans('０１２３４５６７８９', '0123456789'))

                if span5_normalized == '3勝クラス':
                    race_info['RACE_GRADE'] = span5_normalized
                else:
                    # 連結して処理
                    combined_text = span4_text + span5_text

                    # 「サラ系」を除去
                    combined_text = combined_text.replace('サラ系', '')

                    # 全角数字を半角に変換
                    combined_text = combined_text.translate(str.maketrans('０１２３４５６７８９', '0123456789'))

                    race_info['RACE_GRADE'] = combined_text

    # レースデータ（距離、馬場、天候など）を取得
    race_data = race_name_box.find('div', class_='RaceData01')
    if race_data:
        race_data_text = race_data.get_text(strip=True)

        # 距離とコースタイプを抽出 (例: "芝2400m")
        distance_match = re.search(r'(芝|ダ|障害)(\d+)m', race_data_text)
        if distance_match:
            course_type = distance_match.group(1)
            distance = distance_match.group(2)

            # コースタイプを数値化
            if course_type == '芝':
                race_info['COURSE_TYPE'] = '芝'
            elif course_type == 'ダ':
                race_info['COURSE_TYPE'] = 'ダ'
            else:  # 障害
                race_info['COURSE_TYPE'] = '障害'

            race_info['DISTANCE'] = int(distance)

        # 天候を抽出 (例: "晴")
        weather_match = re.search(r'天候\s*:\s*([晴曇雨雪小雨小雪]+)', race_data_text)
        if weather_match:
            weather = weather_match.group(1)
            race_info['WEATHER'] = weather

        # 馬場状態を抽出 (例: "良")
        course_condition_match = re.search(r'馬場\s*:\s*([良稍重不良]+)', race_data_text)
        if course_condition_match:
            condition = course_condition_match.group(1)
            race_info['COURSE_CONDITION'] = condition

    # 競馬場を抽出
    race_data02 = race_name_box.find('div', class_='RaceData02')
    if race_data02:
        race_data02_text = race_data02.get_text(strip=True)
        track_match = re.search(r'(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)', race_data02_text)
        if track_match:
            race_info['RACE_TRACK'] = track_match.group(1)

    return race_info


def scrape_shutuba_data(race_id, wait_time=5):
    """
    馬柱ページから出走馬のデータを取得

    Parameters:
    -----------
    race_id : str
        レースID
    wait_time : int
        オッズの読み込み待機時間（秒）

    Returns:
    --------
    tuple
        (DataFrame: 出走馬のデータ, dict: レース情報)
    """
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    
    print(f"race_id: {race_id}")
    
    print("ブラウザを起動中...")
    driver = create_chrome_driver()

    try:
        print(f"ページにアクセス中...")
        driver.get(url)
        
        print(f"オッズの読み込みを待機中（{wait_time}秒）...")
        time.sleep(wait_time)
        
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')

        # レース情報を抽出
        print("レース情報を抽出中...")
        race_info = extract_race_info_from_shutuba(soup, race_id)
        print(f"抽出されたレース情報: {race_info}")

        table = soup.find('table', class_='Shutuba_Table')
        
        if not table:
            raise ValueError("Shutuba_Tableが見つかりません")
        
        tbody = table.find('tbody')
        if tbody:
            rows = tbody.find_all('tr')
        else:
            rows = [tr for tr in table.find_all('tr') if tr.find_parent('thead') is None]
        
        num_of_horse = len(rows)
        print(f"出走頭数: {num_of_horse}")
        
        horses_data = []
        
        for i, row in enumerate(rows, 1):
            horse_info = {
                'race_id': race_id,
                'num_of_horse': num_of_horse
            }
            cells = row.find_all('td')
            
            if len(cells) < 11:
                continue
            
            horse_info['gate_num'] = cells[0].get_text(strip=True)
            horse_info['horse_num'] = cells[1].get_text(strip=True)
            
            horse_link = cells[3].find('a')
            if horse_link:
                href = horse_link.get('href', '')
                match = re.search(r'/horse/(\d+)', href)
                if match:
                    horse_info['horse_id'] = match.group(1)
                horse_info['horse_name'] = horse_link.get_text(strip=True)
            else:
                horse_info['horse_name'] = None
            
            sex_age_text = cells[4].get_text(strip=True)
            if sex_age_text:
                horse_info['sex'] = sex_age_text[0]
                age_match = re.search(r'(\d+)$', sex_age_text)
                if age_match:
                    horse_info['horse_age'] = age_match.group(1)
            
            horse_info['jockey_weight'] = cells[5].get_text(strip=True)
            
            jockey_link = cells[6].find('a')
            if jockey_link:
                href = jockey_link.get('href', '')
                match = re.search(r'/jockey/result/recent/(\d+)', href)
                if match:
                    horse_info['jockey_id'] = match.group(1)
            
            stable_link = cells[7].find('a')
            if stable_link:
                href = stable_link.get('href', '')
                match = re.search(r'/trainer/result/recent/(\d+)', href)
                if match:
                    horse_info['stable_id'] = match.group(1)
            
            ods_text = cells[9].get_text(strip=True)
            
            if ods_text and ods_text not in ['---.-', '取消', '除外', '中止', '']:
                try:
                    horse_info['ods'] = float(ods_text)
                except:
                    horse_info['ods'] = None
            else:
                horse_info['ods'] = None
            
            horses_data.append(horse_info)
        
        df = pd.DataFrame(horses_data)
        
        column_order = ['race_id', 'num_of_horse', 'gate_num', 'horse_num', 'horse_id', 'horse_name',
                        'ods', 'jockey_id', 'jockey_weight', 'sex', 'horse_age', 'stable_id']
        df = df[column_order]
        
        print(f"✓ {len(df)}頭のデータを取得しました")

        return df, race_info
        
    finally:
        driver.quit()


def get_horse_result(horse_id):
    """
    指定されたhorse_idの競走成績を取得してDataFrameに変換する
    
    Parameters:
    -----------
    horse_id : str
        馬のID
        
    Returns:
    --------
    DataFrame
        競走成績データ（過去レース情報）
    """
    url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"  エラー: {e}")
        return None
    
    table = soup.find('table', class_='db_h_race_results nk_tb_common')
    
    if table is None:
        return None
    
    rows = table.find_all('tr')
    data = []
    
    for row in rows[1:]:
        cols = row.find_all('td')
        if len(cols) < 16:
            continue
        
        date_text = cols[0].get_text(strip=True)
        try:
            date_parts = date_text.split('/')
            if len(date_parts) == 3:
                race_year = int(date_parts[0])
                race_month = int(date_parts[1])
                race_date = int(date_parts[2])
            else:
                race_year = None
                race_month = None
                race_date = None
        except:
            race_year = None
            race_month = None
            race_date = None
        
        race_track_text = cols[1].get_text(strip=True)
        race_track = extract_race_track(race_track_text)
        
        weather = cols[2].get_text(strip=True)
        race_num = cols[3].get_text(strip=True)
        
        race_link = cols[4].find('a')
        race_id = extract_race_id(race_link['href']) if race_link else None
        race_name = cols[4].get_text(strip=True)
        race_grade = extract_race_grade(race_name)
        
        num_of_horse = cols[6].get_text(strip=True)
        gate_num = cols[7].get_text(strip=True)
        horse_num = cols[8].get_text(strip=True)
        
        ods_text = cols[9].get_text(strip=True)
        try:
            ods = float(ods_text) if ods_text else None
        except:
            ods = None
        
        rank = cols[11].get_text(strip=True)
        
        jockey_link = cols[12].find('a')
        jockey_id = extract_jockey_id(jockey_link['href']) if jockey_link else None
        
        jockey_weight = cols[13].get_text(strip=True)
        
        course_text = cols[14].get_text(strip=True)
        course_type, distance = extract_course_info(course_text)
        
        course_condition = cols[16].get_text(strip=True) if len(cols) > 16 else None
        
        # タイムを取得して秒数に変換
        time_str = cols[18].get_text(strip=True) if len(cols) > 18 else None
        time = convert_time_to_seconds(time_str)
        
        time_diff_text = cols[19].get_text(strip=True) if len(cols) > 19 else None
        try:
            time_diff = float(time_diff_text) if time_diff_text and time_diff_text != '-' else None
        except:
            time_diff = None
        
        pass_text = cols[21].get_text(strip=True) if len(cols) > 21 else None
        pass_start, pass_middle, pass_last = extract_pass_positions(pass_text)
        
        pace_text = cols[22].get_text(strip=True) if len(cols) > 22 else None
        pace_first, pace_last = extract_pace(pace_text)
        
        agari_text = cols[23].get_text(strip=True) if len(cols) > 23 else None
        try:
            agari = float(agari_text) if agari_text and agari_text != '-' else None
        except:
            agari = None
        
        weight_text = cols[24].get_text(strip=True) if len(cols) > 24 else None
        horse_weight, horse_weight_diff = extract_horse_weight(weight_text)
        
        data.append({
            'horse_id': horse_id,
            'race_year': race_year,
            'race_month': race_month,
            'race_date': race_date,
            'race_track': race_track,
            'race_num': race_num,
            'race_id': race_id,
            'race_grade': race_grade,
            'weather': weather,
            'course_condition': course_condition,
            'num_of_horse': num_of_horse,
            'gate_num': gate_num,
            'horse_num': horse_num,
            'ods': ods,
            'rank': rank,
            'course_type': course_type,
            'distance': distance,
            'jockey_id': jockey_id,
            'jockey_weight': jockey_weight,
            'time': time,
            'time_diff': time_diff,
            'pass_start': pass_start,
            'pass_middle': pass_middle,
            'pass_last': pass_last,
            'pace_first': pace_first,
            'pace_last': pace_last,
            'agari': agari,
            'horse_weight': horse_weight,
            'horse_weight_diff': horse_weight_diff
        })
    
    return pd.DataFrame(data)


def merge_current_and_past_races(shutuba_df, race_year, race_month, race_date):
    """
    馬柱データと過去5レースのデータを結合
    
    Parameters:
    -----------
    shutuba_df : DataFrame
        馬柱から取得した現在のレース情報
    race_year : int
        予測したいレースの年
    race_month : int
        予測したいレースの月
    race_date : int
        予測したいレースの日
        
    Returns:
    --------
    DataFrame
        過去5レースのデータを_pre1～_pre5の接尾辞付きで結合したデータ
    """
    all_data = []
    
    exclude_columns = ['race_name', 'jockey_name', 'favorite']
    
    total_horses = len(shutuba_df)
    print(f"\n全{total_horses}頭の過去戦績を取得します")
    print(f"基準日: {race_year}/{race_month}/{race_date}")
    
    for idx, row in shutuba_df.iterrows():
        horse_id = row['horse_id']
        print(f"[{idx+1}/{total_horses}] horse_id: {horse_id}")
        
        current_race = row.to_dict()
        
        past_races_df = get_horse_result(horse_id)
        
        if past_races_df is not None and not past_races_df.empty:
            # 予測したいレースの日付以前のデータのみをフィルタリング
            past_races_df = past_races_df[
                (past_races_df['race_year'] < race_year) |
                ((past_races_df['race_year'] == race_year) & (past_races_df['race_month'] < race_month)) |
                ((past_races_df['race_year'] == race_year) & (past_races_df['race_month'] == race_month) & (past_races_df['race_date'] < race_date))
            ]
            
            # フィルタリング後の最新5件を取得
            past_races_df = past_races_df.head(5)
            
            for i in range(1, 6):
                if i <= len(past_races_df):
                    past_race = past_races_df.iloc[i-1]
                    
                    for col in past_races_df.columns:
                        if col not in exclude_columns and col != 'horse_id':
                            current_race[f"{col}_pre{i}"] = past_race[col]
                else:
                    for col in past_races_df.columns:
                        if col not in exclude_columns and col != 'horse_id':
                            current_race[f"{col}_pre{i}"] = None
        else:
            past_columns = [
                'race_year', 'race_month', 'race_date', 'race_track', 'race_num', 
                'race_id', 'race_grade', 'weather', 'course_condition', 'num_of_horse',
                'gate_num', 'horse_num', 'ods', 'rank', 'course_type', 'distance',
                'jockey_id', 'jockey_weight', 'time', 'time_diff', 'pass_start',
                'pass_middle', 'pass_last', 'pace_first', 'pace_last', 'agari',
                'horse_weight', 'horse_weight_diff'
            ]
            
            for i in range(1, 6):
                for col in past_columns:
                    current_race[f"{col}_pre{i}"] = None
        
        all_data.append(current_race)
        time.sleep(3)
    
    result_df = pd.DataFrame(all_data)
    
    print(f"\n✓ 過去戦績の結合が完了しました")
    
    return result_df


def get_pedigree_info(horse_id):
    """
    馬の詳細ページと血統ページから血統情報を取得する
    
    Args:
        horse_id (str): 馬のID
        
    Returns:
        dict: 血統情報の辞書
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    result = {
        'horse_id': horse_id,
        'birth_year': None,
        'stable_place': None,
        'producer_id': None,
        'sire_id': None,
        'mare_id': None,
        'bms_id': None
    }
    
    url = f"https://db.netkeiba.com/horse/{horse_id}/"
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        return None
    
    prof_table = soup.find('table', class_='db_prof_table')
    if prof_table:
        rows = prof_table.find_all('tr')
        
        if len(rows) > 0:
            td = rows[0].find('td')
            if td:
                date_text = td.get_text(strip=True)
                match = re.search(r'(\d{4})年', date_text)
                if match:
                    result['birth_year'] = int(match.group(1))
        
        if len(rows) > 1:
            td = rows[1].find('td')
            if td:
                td_copy = BeautifulSoup(str(td), 'html.parser')
                for a in td_copy.find_all('a'):
                    a.decompose()
                td_text = td_copy.get_text(strip=True)
                
                if '栗東' in td_text:
                    result['stable_place'] = '西'
                elif '美浦' in td_text:
                    result['stable_place'] = '東'
                else:
                    result['stable_place'] = None
        
        for row in rows:
            th = row.find('th')
            if th and th.get_text(strip=True) == '生産者':
                td = row.find('td')
                if td:
                    a_tag = td.find('a')
                    if a_tag and 'href' in a_tag.attrs:
                        result['producer_id'] = extract_producer_id(a_tag['href'])
                break
    
    ped_url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
    try:
        response = requests.get(ped_url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        return result
    
    blood_table = soup.find('table', class_='blood_table')
    if blood_table:
        rows = blood_table.find_all('tr')
        
        if len(rows) > 0:
            tds = rows[0].find_all('td')
            if len(tds) > 0:
                a_tag = tds[0].find('a')
                if a_tag and 'href' in a_tag.attrs:
                    result['sire_id'] = extract_pedigree_id(a_tag['href'])
        
        if len(rows) > 16:
            tds = rows[16].find_all('td')
            if len(tds) > 0:
                a_tag = tds[0].find('a')
                if a_tag and 'href' in a_tag.attrs:
                    result['mare_id'] = extract_pedigree_id(a_tag['href'])
            if len(tds) > 1:
                a_tag = tds[1].find('a')
                if a_tag and 'href' in a_tag.attrs:
                    result['bms_id'] = extract_pedigree_id(a_tag['href'])
    
    return result


def get_jockey_stats(jockey_id):
    """
    指定されたjockey_idの通算成績を取得する
    
    Parameters:
    -----------
    jockey_id : str
        騎手ID
        
    Returns:
    --------
    dict
        騎手の通算成績データ
    """
    if not jockey_id or pd.isna(jockey_id):
        return None
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    url = f"https://db.netkeiba.com/jockey/result.html?id={jockey_id}"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        table = soup.find('table', class_='race_table_01')
        
        if table is None:
            return None
        
        trs = table.find_all('tr')
        
        if len(trs) < 3:
            return None
        
        third_tr = trs[2]
        tds = third_tr.find_all('td')
        
        if len(tds) == 0:
            return None
        
        first_td_text = tds[0].get_text(strip=True)
        if first_td_text != '通算':
            return None
        
        values = [td.get_text(strip=True) for td in tds[2:-1]]
        values = [v.replace('%', '').replace(',', '') for v in values]
        
        numeric_values = []
        for v in values:
            try:
                numeric_values.append(float(v) if '.' in v else int(v))
            except:
                numeric_values.append(None)
        
        result = {
            'jockey_id': jockey_id,
            'first_place_count': numeric_values[0] if len(numeric_values) > 0 else None,
            'second_place_count': numeric_values[1] if len(numeric_values) > 1 else None,
            'third_place_count': numeric_values[2] if len(numeric_values) > 2 else None,
            'other_place_count': numeric_values[3] if len(numeric_values) > 3 else None,
            'grade_race_count': numeric_values[4] if len(numeric_values) > 4 else None,
            'grade_race_win_count': numeric_values[5] if len(numeric_values) > 5 else None,
            'special_race_count': numeric_values[6] if len(numeric_values) > 6 else None,
            'special_race_win_count': numeric_values[7] if len(numeric_values) > 7 else None,
            'normal_race_count': numeric_values[8] if len(numeric_values) > 8 else None,
            'normal_race_win_count': numeric_values[9] if len(numeric_values) > 9 else None,
            'turf_race_count': numeric_values[10] if len(numeric_values) > 10 else None,
            'turf_race_win_count': numeric_values[11] if len(numeric_values) > 11 else None,
            'dirt_race_count': numeric_values[12] if len(numeric_values) > 12 else None,
            'dirt_race_win_count': numeric_values[13] if len(numeric_values) > 13 else None,
            'win_rate': numeric_values[14] if len(numeric_values) > 14 else None,
            'top_2_rate': numeric_values[15] if len(numeric_values) > 15 else None,
            'top_3_rate': numeric_values[16] if len(numeric_values) > 16 else None,
            'earnings': numeric_values[17] if len(numeric_values) > 17 else None
        }
        
        return result
        
    except Exception as e:
        return None


def get_html_content_for_ped(url):
    """
    指定されたURLからHTMLコンテンツを取得する（血統データ用）
    
    Args:
        url (str): スクレイピング対象のURL
        
    Returns:
        BeautifulSoup: パースされたHTMLコンテンツ
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        return soup
    except:
        return None


def get_blood_table_first_cell(ped_id):
    """
    指定されたped_idから血統テーブルの最初のセルを取得する
    
    Args:
        ped_id (str): 血統ID
        
    Returns:
        BeautifulSoup element: 取得したtd要素
    """
    url = f"https://db.netkeiba.com/horse/ped/{ped_id}"
    soup = get_html_content_for_ped(url)
    
    if soup is None:
        return None
    
    blood_table = soup.find('table', class_='blood_table')
    
    if blood_table is None:
        return None
    
    first_tr = blood_table.find('tr')
    
    if first_tr is None:
        return None
    
    first_td = first_tr.find('td')
    
    if first_td is None:
        return None
    
    return first_td


def extract_lineage(text):
    """
    テキストから[産駒]に続く系統情報を抽出する
    
    Args:
        text (str): 血統情報のテキスト
        
    Returns:
        str: 系統名（例: "Raise a Native系"）
    """
    if not text:
        return None
    
    match = re.search(r'\[産駒\](.+)', text)
    if match:
        return match.group(1).strip()
    
    return None


def get_ped_category(ped_id):
    """
    指定されたped_idの系統カテゴリを取得する
    
    Args:
        ped_id (str): 血統ID
        
    Returns:
        str: 系統カテゴリ
    """
    if not ped_id or pd.isna(ped_id):
        return None
    
    first_td = get_blood_table_first_cell(ped_id)
    
    if first_td is not None:
        text = first_td.get_text(strip=True)
        lineage = extract_lineage(text)
        return lineage
    
    return None


def get_stable_stats(stable_id):
    """
    指定されたstable_idの通算成績を取得する
    
    Parameters:
    -----------
    stable_id : str
        厩舎ID
        
    Returns:
    --------
    dict
        厩舎の通算成績データ
    """
    if not stable_id or pd.isna(stable_id):
        return None
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    url = f"https://db.netkeiba.com/trainer/result.html?id={stable_id}"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        table = soup.find('table', class_='race_table_01')
        
        if table is None:
            return None
        
        trs = table.find_all('tr')
        
        if len(trs) < 3:
            return None
        
        third_tr = trs[2]
        tds = third_tr.find_all('td')
        
        if len(tds) == 0:
            return None
        
        first_td_text = tds[0].get_text(strip=True)
        if first_td_text != '通算':
            return None
        
        values = [td.get_text(strip=True) for td in tds[2:-1]]
        values = [v.replace('%', '').replace(',', '') for v in values]
        
        numeric_values = []
        for v in values:
            try:
                numeric_values.append(float(v) if '.' in v else int(v))
            except:
                numeric_values.append(None)
        
        result = {
            'stable_id': stable_id,
            'stable_first_place_count': numeric_values[0] if len(numeric_values) > 0 else None,
            'stable_second_place_count': numeric_values[1] if len(numeric_values) > 1 else None,
            'stable_third_place_count': numeric_values[2] if len(numeric_values) > 2 else None,
            'stable_other_place_count': numeric_values[3] if len(numeric_values) > 3 else None,
            'stable_grade_race_count': numeric_values[4] if len(numeric_values) > 4 else None,
            'stable_grade_race_win_count': numeric_values[5] if len(numeric_values) > 5 else None,
            'stable_special_race_count': numeric_values[6] if len(numeric_values) > 6 else None,
            'stable_special_race_win_count': numeric_values[7] if len(numeric_values) > 7 else None,
            'stable_normal_race_count': numeric_values[8] if len(numeric_values) > 8 else None,
            'stable_normal_race_win_count': numeric_values[9] if len(numeric_values) > 9 else None,
            'stable_turf_race_count': numeric_values[10] if len(numeric_values) > 10 else None,
            'stable_turf_race_win_count': numeric_values[11] if len(numeric_values) > 11 else None,
            'stable_dirt_race_count': numeric_values[12] if len(numeric_values) > 12 else None,
            'stable_dirt_race_win_count': numeric_values[13] if len(numeric_values) > 13 else None,
            'stable_win_rate': numeric_values[14] if len(numeric_values) > 14 else None,
            'stable_top_2_rate': numeric_values[15] if len(numeric_values) > 15 else None,
            'stable_top_3_rate': numeric_values[16] if len(numeric_values) > 16 else None,
            'stable_earnings': numeric_values[17] if len(numeric_values) > 17 else None
        }
        
        return result
        
    except Exception as e:
        return None


def process_race(race_id, *, output_root="data/predict"):
    """
    単一レースの予測データを作成

    Parameters:
    -----------
    race_id : str
        レースID
    output_root : str or Path, keyword-only
        CSV保存先のルート。Webアプリは取得ごとに別のルートを指定する。
    """
    print("\n" + "=" * 80)
    print(f"レースID: {race_id} の処理を開始")
    print("=" * 80)

    # 1. 馬柱データとレース情報を取得
    print("\n[1/5] 馬柱データを取得中...")
    shutuba_df, auto_race_info = scrape_shutuba_data(race_id, wait_time=3)

    # 自動取得したレース情報を表示
    print("\n自動取得したレース情報:")
    for key, value in auto_race_info.items():
        print(f"  {key}: {value}")

    # レースフィルタリングチェック
    skip_reason = None

    # 新馬戦チェック
    if SKIP_SHINBA and 'RACE_GRADE' in auto_race_info:
        if '新馬' in str(auto_race_info['RACE_GRADE']):
            skip_reason = "新馬戦のためスキップします"

    # 障害レースチェック
    if SKIP_SHOGAI and 'RACE_GRADE' in auto_race_info:
        if '障害' in str(auto_race_info['RACE_GRADE']):
            skip_reason = "障害レースのためスキップします"

    if skip_reason:
        print(f"\n⊘ {skip_reason}")
        return None

    # グローバル変数を自動取得した値で上書き（存在する場合のみ）
    global RACE_YEAR, RACE_MONTH, RACE_DATE, RACE_TRACK, RACE_NUM, RACE_GRADE, DISTANCE, WEATHER, COURSE_CONDITION, COURSE_TYPE

    if 'RACE_YEAR' in auto_race_info:
        RACE_YEAR = auto_race_info['RACE_YEAR']
    if 'RACE_MONTH' in auto_race_info:
        RACE_MONTH = auto_race_info['RACE_MONTH']
    if 'RACE_DATE' in auto_race_info:
        RACE_DATE = auto_race_info['RACE_DATE']
    if 'RACE_TRACK' in auto_race_info:
        RACE_TRACK = auto_race_info['RACE_TRACK']
    if 'RACE_NUM' in auto_race_info:
        RACE_NUM = auto_race_info['RACE_NUM']
    if 'RACE_GRADE' in auto_race_info:
        RACE_GRADE = auto_race_info['RACE_GRADE']
    if 'DISTANCE' in auto_race_info:
        DISTANCE = auto_race_info['DISTANCE']
    if 'WEATHER' in auto_race_info:
        WEATHER = auto_race_info['WEATHER']
    else:
        # 自動取得できなかった場合、競馬場ごとのデフォルト値を使用
        WEATHER = DEFAULT_WEATHER_BY_TRACK.get(RACE_TRACK, FALLBACK_WEATHER)
    if 'COURSE_CONDITION' in auto_race_info:
        COURSE_CONDITION = auto_race_info['COURSE_CONDITION']
    else:
        # 自動取得できなかった場合、競馬場ごとのデフォルト値を使用
        COURSE_CONDITION = DEFAULT_COURSE_CONDITION_BY_TRACK.get(RACE_TRACK, FALLBACK_COURSE_CONDITION)
    if 'COURSE_TYPE' in auto_race_info:
        COURSE_TYPE = auto_race_info['COURSE_TYPE']

    print("\n使用するレース情報:")
    print(f"  RACE_YEAR: {RACE_YEAR}")
    print(f"  RACE_MONTH: {RACE_MONTH}")
    print(f"  RACE_DATE: {RACE_DATE}")
    print(f"  RACE_TRACK: {RACE_TRACK}")
    print(f"  RACE_NUM: {RACE_NUM}")
    print(f"  RACE_GRADE: {RACE_GRADE}")
    print(f"  COURSE_TYPE: {COURSE_TYPE}")
    print(f"  DISTANCE: {DISTANCE}")

    # WEATHERとCOURSE_CONDITIONは取得できない場合があるため、デフォルト値の使用有無を表示
    weather_source = "自動取得" if 'WEATHER' in auto_race_info else f"デフォルト値({RACE_TRACK}用)"
    condition_source = "自動取得" if 'COURSE_CONDITION' in auto_race_info else f"デフォルト値({RACE_TRACK}用)"
    print(f"  WEATHER: {WEATHER} ({weather_source})")
    print(f"  COURSE_CONDITION: {COURSE_CONDITION} ({condition_source})")
    
    # 2. 過去5レースのデータを結合
    print("\n[2/5] 過去5レースのデータを結合中...")
    merged_df = merge_current_and_past_races(shutuba_df, RACE_YEAR, RACE_MONTH, RACE_DATE)
    
    # 3. 血統情報を取得してマージ
    print("\n[3/5] 血統情報を取得中...")
    pedigree_list = []
    
    for idx, row in merged_df.iterrows():
        horse_id = row['horse_id']
        print(f"[{idx+1}/{len(merged_df)}] 馬ID: {horse_id}")
        
        pedigree_info = get_pedigree_info(horse_id)
        if pedigree_info:
            pedigree_list.append(pedigree_info)

        time.sleep(3)
    
    pedigree_df = pd.DataFrame(pedigree_list)
    merged_with_pedigree = merged_df.merge(pedigree_df, on='horse_id', how='left')
    
    # 過去の戦績時の馬齢を計算
    print("\n過去の戦績時の馬齢を計算中...")
    for i in range(1, 6):
        race_year_col = f'race_year_pre{i}'
        horse_age_col = f'horse_age_pre{i}'
        
        if race_year_col in merged_with_pedigree.columns:
            merged_with_pedigree[horse_age_col] = merged_with_pedigree.apply(
                lambda row: row[race_year_col] - row['birth_year'] 
                if pd.notna(row[race_year_col]) and pd.notna(row['birth_year']) 
                else None,
                axis=1
            )
    
    # 4. 系統情報（ped_category）をローカルCSVから取得
    print("\n[4/7] 系統情報をローカルCSVから取得中...")

    merged_with_ped_category = merged_with_pedigree.copy()

    # 系統情報CSVを読み込み
    ped_data_path = os.path.join("data", "ped_data", "ped_data.csv")
    try:
        ped_data_df = pd.read_csv(ped_data_path)
        # ped_idを文字列型に変換
        ped_data_df['ped_id'] = ped_data_df['ped_id'].astype(str)
        # 辞書に変換（ped_id -> ped_category）
        ped_category_dict = dict(zip(ped_data_df['ped_id'], ped_data_df['ped_category']))
        print(f"✓ 系統情報を読み込みました: {len(ped_category_dict)}件")
    except Exception as e:
        print(f"✗ エラー: 系統情報CSVの読み込みに失敗しました: {e}")
        ped_category_dict = {}

    # sire_idをすべて文字列型に変換（NaNは保持）
    if 'sire_id' in merged_with_ped_category.columns:
        merged_with_ped_category['sire_id'] = merged_with_ped_category['sire_id'].astype(str).replace('nan', None)

    # bms_idをすべて文字列型に変換（NaNは保持）
    if 'bms_id' in merged_with_ped_category.columns:
        merged_with_ped_category['bms_id'] = merged_with_ped_category['bms_id'].astype(str).replace('nan', None)

    # すべてのユニークなped_id（sire_idとbms_id）を収集
    all_ped_ids = set()
    if 'sire_id' in merged_with_ped_category.columns:
        all_ped_ids.update(merged_with_ped_category['sire_id'].dropna().unique())
    if 'bms_id' in merged_with_ped_category.columns:
        all_ped_ids.update(merged_with_ped_category['bms_id'].dropna().unique())

    all_ped_ids = [pid for pid in all_ped_ids if pid and pid != 'None']

    # 系統情報をCSVから取得
    ped_category_cache = {}
    missing_ped_ids = []

    for ped_id in all_ped_ids:
        if ped_id in ped_category_dict:
            ped_category_cache[ped_id] = ped_category_dict[ped_id]
        else:
            ped_category_cache[ped_id] = None
            missing_ped_ids.append(ped_id)

    if missing_ped_ids:
        print(f"⚠ 警告: {len(missing_ped_ids)}件の系統情報が見つかりませんでした")
        for pid in missing_ped_ids:
            print(f"  - ped_id: {pid}")

    # sire_categoryを追加
    if 'sire_id' in merged_with_ped_category.columns:
        merged_with_ped_category['sire_category'] = merged_with_ped_category['sire_id'].apply(
            lambda sid: ped_category_cache.get(sid) if pd.notna(sid) and sid != 'None' else None
        )
        print("✓ sire_categoryを追加しました")

    # bms_categoryを追加
    if 'bms_id' in merged_with_ped_category.columns:
        merged_with_ped_category['bms_category'] = merged_with_ped_category['bms_id'].apply(
            lambda bid: ped_category_cache.get(bid) if pd.notna(bid) and bid != 'None' else None
        )
        print("✓ bms_categoryを追加しました")
    
    # 5. 騎手戦績をローカルCSVから取得
    print("\n[5/7] 騎手戦績をローカルCSVから取得中...")

    jockey_stat_columns = [
        'first_place_count', 'second_place_count', 'third_place_count', 'other_place_count',
        'grade_race_count', 'grade_race_win_count', 'special_race_count', 'special_race_win_count',
        'normal_race_count', 'normal_race_win_count', 'turf_race_count', 'turf_race_win_count',
        'dirt_race_count', 'dirt_race_win_count', 'win_rate', 'top_2_rate', 'top_3_rate', 'earnings'
    ]

    # 騎手戦績CSVを読み込み
    jockey_data_path = os.path.join("data", "jockey_data", "jockey_data.csv")
    try:
        jockey_data_df = pd.read_csv(jockey_data_path, dtype={'jockey_id': str})
        # jockey_idを文字列型に変換
        jockey_data_df['jockey_id'] = jockey_data_df['jockey_id'].astype(str)
        print(f"✓ 騎手戦績を読み込みました: {len(jockey_data_df)}件")
    except Exception as e:
        print(f"✗ エラー: 騎手戦績CSVの読み込みに失敗しました: {e}")
        jockey_data_df = pd.DataFrame()

    all_jockey_ids = set()
    all_jockey_ids.update(merged_with_ped_category['jockey_id'].dropna().unique())

    for i in range(1, 6):
        col_name = f'jockey_id_pre{i}'
        if col_name in merged_with_ped_category.columns:
            all_jockey_ids.update(merged_with_ped_category[col_name].dropna().unique())

    all_jockey_ids = list(all_jockey_ids)

    # 騎手戦績をCSVから取得
    jockey_stats_dict = {}
    missing_jockey_ids = []

    for jockey_id in all_jockey_ids:
        jockey_id_str = str(jockey_id)
        jockey_row = jockey_data_df[jockey_data_df['jockey_id'] == jockey_id_str]

        if not jockey_row.empty:
            # DataFrameから辞書に変換
            stats = jockey_row.iloc[0].to_dict()
            jockey_stats_dict[jockey_id] = stats
        else:
            missing_jockey_ids.append(jockey_id)

    if missing_jockey_ids:
        print(f"⚠ 警告: {len(missing_jockey_ids)}件の騎手戦績が見つかりませんでした")
        for jid in missing_jockey_ids:
            print(f"  - jockey_id: {jid}")

    merged_with_jockey = merged_with_ped_category.copy()

    for col in jockey_stat_columns:
        merged_with_jockey[col] = merged_with_jockey['jockey_id'].apply(
            lambda jid: jockey_stats_dict.get(jid, {}).get(col) if pd.notna(jid) else None
        )

    for i in range(1, 6):
        jockey_id_col = f'jockey_id_pre{i}'

        if jockey_id_col in merged_with_jockey.columns:
            for col in jockey_stat_columns:
                col_with_suffix = f'{col}_pre{i}'
                merged_with_jockey[col_with_suffix] = merged_with_jockey[jockey_id_col].apply(
                    lambda jid: jockey_stats_dict.get(jid, {}).get(col) if pd.notna(jid) else None
                )
    
    # 6. 厩舎戦績をローカルCSVから取得
    print("\n[6/7] 厩舎戦績をローカルCSVから取得中...")

    stable_stat_columns = [
        'stable_first_place_count', 'stable_second_place_count', 'stable_third_place_count', 'stable_other_place_count',
        'stable_grade_race_count', 'stable_grade_race_win_count', 'stable_special_race_count', 'stable_special_race_win_count',
        'stable_normal_race_count', 'stable_normal_race_win_count', 'stable_turf_race_count', 'stable_turf_race_win_count',
        'stable_dirt_race_count', 'stable_dirt_race_win_count', 'stable_win_rate', 'stable_top_2_rate', 'stable_top_3_rate', 'stable_earnings'
    ]

    # 厩舎戦績CSVを読み込み
    stable_data_path = os.path.join("data", "stable_data", "stable_data.csv")
    try:
        stable_data_df = pd.read_csv(stable_data_path, dtype={'stable_id': str})
        # stable_idを文字列型に変換
        stable_data_df['stable_id'] = stable_data_df['stable_id'].astype(str)
        print(f"✓ 厩舎戦績を読み込みました: {len(stable_data_df)}件")
    except Exception as e:
        print(f"✗ エラー: 厩舎戦績CSVの読み込みに失敗しました: {e}")
        stable_data_df = pd.DataFrame()

    all_stable_ids = set()
    all_stable_ids.update(merged_with_jockey['stable_id'].dropna().unique())

    for i in range(1, 6):
        col_name = f'stable_id_pre{i}'
        if col_name in merged_with_jockey.columns:
            all_stable_ids.update(merged_with_jockey[col_name].dropna().unique())

    all_stable_ids = list(all_stable_ids)

    # 厩舎戦績をCSVから取得
    stable_stats_dict = {}
    missing_stable_ids = []

    for stable_id in all_stable_ids:
        stable_id_str = str(stable_id)
        stable_row = stable_data_df[stable_data_df['stable_id'] == stable_id_str]

        if not stable_row.empty:
            # DataFrameから辞書に変換
            stats = stable_row.iloc[0].to_dict()
            stable_stats_dict[stable_id] = stats
        else:
            missing_stable_ids.append(stable_id)

    if missing_stable_ids:
        print(f"⚠ 警告: {len(missing_stable_ids)}件の厩舎戦績が見つかりませんでした")
        for sid in missing_stable_ids:
            print(f"  - stable_id: {sid}")

    merged_with_stable = merged_with_jockey.copy()

    for col in stable_stat_columns:
        merged_with_stable[col] = merged_with_stable['stable_id'].apply(
            lambda sid: stable_stats_dict.get(sid, {}).get(col) if pd.notna(sid) else None
        )

    for i in range(1, 6):
        stable_id_col = f'stable_id_pre{i}'

        if stable_id_col in merged_with_stable.columns:
            for col in stable_stat_columns:
                col_with_suffix = f'{col}_pre{i}'
                merged_with_stable[col_with_suffix] = merged_with_stable[stable_id_col].apply(
                    lambda sid: stable_stats_dict.get(sid, {}).get(col) if pd.notna(sid) else None
                )
    
    # 7. 手動入力のレース情報を追加
    print("\n[7/7] 手動入力のレース情報を追加中...")
    merged_with_stable['race_year'] = RACE_YEAR
    merged_with_stable['race_month'] = RACE_MONTH
    merged_with_stable['race_date'] = RACE_DATE
    merged_with_stable['race_track'] = RACE_TRACK
    merged_with_stable['race_num'] = RACE_NUM
    merged_with_stable['race_grade'] = RACE_GRADE
    merged_with_stable['course_type'] = COURSE_TYPE
    merged_with_stable['distance'] = DISTANCE
    merged_with_stable['weather'] = WEATHER
    merged_with_stable['course_condition'] = COURSE_CONDITION

    # 競馬場カテゴリを追加
    print("\n競馬場カテゴリを追加中...")
    # 現在のレース
    if 'race_track' in merged_with_stable.columns:
        merged_with_stable['race_track_category'] = merged_with_stable['race_track'].apply(categorize_race_track)

    # 過去レース分（_pre1～_pre5）
    for i in range(1, 6):
        race_track_col = f'race_track_pre{i}'
        category_col = f'race_track_category_pre{i}'

        if race_track_col in merged_with_stable.columns:
            merged_with_stable[category_col] = merged_with_stable[race_track_col].apply(categorize_race_track)

    print("✓ race_track_category特徴量を作成しました（現在 + 過去5レース分）")

    # 8. 出力ファイルパスを自動生成
    # data/predict/YYYYMMDD/{RACE_TRACK}_{RACE_NUM}.csv の形式
    date_dir = f"{RACE_YEAR:04d}{RACE_MONTH:02d}{RACE_DATE:02d}"
    output_dir = os.path.join(output_root, date_dir)

    # ディレクトリが存在しない場合は作成
    os.makedirs(output_dir, exist_ok=True)

    # ファイル名を生成
    output_filename = f"{RACE_TRACK}_{RACE_NUM}.csv"
    output_filepath = os.path.join(output_dir, output_filename)

    print(f"\n出力先: {output_filepath}")

    # 9. CSVに保存
    merged_with_stable.to_csv(output_filepath, index=False, encoding='utf-8-sig')

    print("\n" + "=" * 80)
    print(f"✓ 予測データの作成が完了しました")
    print(f"✓ 出力ファイル: {output_filepath}")
    print(f"✓ データ行数: {len(merged_with_stable)}")
    print(f"✓ カラム数: {len(merged_with_stable.columns)}")
    print("=" * 80)

    return output_filepath


def main():
    """メイン処理 - 複数レースに対応"""
    print("=" * 80)
    print("予測データ作成スクリプト")
    print("=" * 80)

    # モードに応じてレースIDを取得
    if MODE == "csv":
        print(f"\nモード: CSVファイルから読み込み")
        print(f"CSVパス: {CSV_PATH}")

        if not os.path.exists(CSV_PATH):
            print(f"\n✗ エラー: CSVファイルが見つかりません: {CSV_PATH}")
            return

        try:
            race_id_df = pd.read_csv(CSV_PATH)

            # "race_id"列が存在するか確認
            if 'race_id' not in race_id_df.columns:
                print(f"\n✗ エラー: CSVファイルに 'race_id' 列が見つかりません")
                print(f"   利用可能な列: {list(race_id_df.columns)}")
                return

            # race_idを文字列のリストとして取得
            race_ids = race_id_df['race_id'].astype(str).tolist()
            print(f"✓ {len(race_ids)} 件のレースIDを読み込みました")

        except Exception as e:
            print(f"\n✗ CSVファイルの読み込みエラー: {e}")
            return

    elif MODE == "list":
        print(f"\nモード: リストから取得")
        # RACE_IDsが文字列の場合はリストに変換
        race_ids = RACE_IDS if isinstance(RACE_IDS, list) else [RACE_IDS]

    else:
        print(f"\n✗ エラー: 無効なMODE設定: {MODE}")
        print(f"   MODE は 'list' または 'csv' である必要があります")
        return

    print(f"\n処理対象レース数: {len(race_ids)}")
    for i, race_id in enumerate(race_ids):
        print(f"  {i+1}. {race_id}")

    # 各レースを処理
    results = []
    for i, race_id in enumerate(race_ids):
        try:
            print(f"\n\n{'='*80}")
            print(f"[{i+1}/{len(race_ids)}] レースID: {race_id}")
            print(f"{'='*80}")

            output_file = process_race(race_id)

            # process_raceがNoneを返した場合はスキップされたレース
            if output_file is None:
                results.append({
                    'race_id': race_id,
                    'status': 'SKIPPED',
                    'reason': 'フィルタ条件によりスキップ'
                })
            else:
                results.append({
                    'race_id': race_id,
                    'status': 'SUCCESS',
                    'output_file': output_file
                })

            # 次のレースの前に5秒待機（最後のレースの後は不要）
            if i < len(race_ids) - 1:
                print(f"\n次のレースの処理前に5秒待機...")
                time.sleep(20)

        except Exception as e:
            print(f"\n✗ エラーが発生しました: {e}")
            results.append({
                'race_id': race_id,
                'status': 'ERROR',
                'error': str(e)
            })
            # エラーが発生しても次のレースは処理する
            if i < len(race_ids) - 1:
                print(f"\n次のレースの処理前に5秒待機...")
                time.sleep(20)

    # 最終結果のサマリーを表示
    print("\n\n" + "=" * 80)
    print("処理結果サマリー")
    print("=" * 80)
    for i, result in enumerate(results, 1):
        if result['status'] == 'SUCCESS':
            status_mark = "✓"
        elif result['status'] == 'SKIPPED':
            status_mark = "⊘"
        else:
            status_mark = "✗"

        print(f"{i}. {status_mark} {result['race_id']}: {result['status']}")
        if result['status'] == 'SUCCESS':
            print(f"   → {result['output_file']}")
        elif result['status'] == 'SKIPPED':
            print(f"   → {result.get('reason', 'スキップされました')}")
        else:
            print(f"   → エラー: {result.get('error', 'Unknown error')}")

    success_count = sum(1 for r in results if r['status'] == 'SUCCESS')
    skipped_count = sum(1 for r in results if r['status'] == 'SKIPPED')
    error_count = sum(1 for r in results if r['status'] == 'ERROR')

    print(f"\n成功: {success_count} / スキップ: {skipped_count} / エラー: {error_count} / 合計: {len(results)}")
    print("=" * 80)


if __name__ == "__main__":
    main()
