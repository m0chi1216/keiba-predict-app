"""
予測スクリプト

予測用CSVファイルから学習済みモデルを使用して予測を行います。
"""

import pandas as pd
import numpy as np
import pickle
import argparse
import json
from pathlib import Path
from datetime import datetime

if __package__:
    from .betting_strategy import make_candidates, select_purchases, eligible_candidates
    from .strategy_config import apply_config_defaults
    from .validators import positive_float
    from .validators import positive_int
else:
    from betting_strategy import make_candidates, select_purchases, eligible_candidates
    from strategy_config import apply_config_defaults
    from validators import positive_float
    from validators import positive_int


def apply_purchase_strategy(predictions, top_n=5, normalization='auto', temperature=1.0,
                            ev_threshold=1.0, max_odds=30.0, staking='expected-value',
                            base_bet=100, exclude_grade=6.0):
    """全頭の予測値から、シミュレーションと同じ候補・購入馬を決める。"""
    result = predictions.copy().reset_index(drop=True)
    if 'race_id' not in result:
        result['race_id'] = 'single_race'
    if result['race_id'].isna().any():
        raise ValueError('race_idに欠損があります。')
    if 'ods' not in result:
        raise ValueError('購入条件の判定にはodsカラムが必要です。')
    result['ods'] = pd.to_numeric(result['ods'], errors='raise')
    excluded = (result['race_grade'].eq(exclude_grade) if exclude_grade is not None and 'race_grade' in result
                else pd.Series(False, index=result.index))
    allowed = result.loc[~excluded].copy()
    regression = 'predicted_rank' in result
    result['model_score'] = np.nan
    result['purchase_score'] = np.nan
    result['candidate_rank'] = np.nan
    result['is_candidate'] = False
    result['selected'] = False
    result['bet_amount'] = 0
    result['recommend_rank'] = pd.Series(pd.NA, index=result.index, dtype='Int64')
    if not allowed.empty:
        all_horses = make_candidates(allowed, int(allowed.groupby('race_id').size().max()), normalization, temperature)
        candidates = make_candidates(allowed, top_n, normalization, temperature)
        recommended = eligible_candidates(candidates, ev_threshold, max_odds)
        selected = select_purchases(candidates, ev_threshold, max_odds, staking, base_bet)
        result.loc[all_horses.index, 'model_score'] = all_horses['pred_prob']
        result.loc[all_horses.index, 'purchase_score'] = all_horses['expected_value']
        rank = (all_horses.groupby('race_id', sort=False)['predicted_rank'].rank(method='first') if regression
                else all_horses.groupby('race_id', sort=False)['pred_prob'].rank(method='first', ascending=False))
        result.loc[rank.index, 'candidate_rank'] = rank
        result.loc[candidates.index, 'is_candidate'] = True
        result.loc[selected.index, 'selected'] = True
        result.loc[selected.index, 'bet_amount'] = selected['bet_amount']
        recommend_rank = recommended.groupby('race_id', sort=False)['expected_value'].rank(method='first', ascending=False).astype('Int64')
        result.loc[recommended.index, 'recommend_rank'] = recommend_rank
    if regression:
        result['rank_score'] = result['model_score']
        result['predicted_order'] = result['candidate_rank']
        result['rank_score_rank'] = result.groupby('race_id', sort=False)['rank_score'].rank(method='first', ascending=False)
    else:
        result['win_rate_raw'] = result['pred_prob_first']
        result['win_rate'] = result['model_score']
        result['win_rate_rank'] = result['candidate_rank']
        result['expected_value'] = result['purchase_score']
        result['expected_value_rank'] = result.groupby('race_id', sort=False)['expected_value'].rank(method='first', ascending=False)
    result['purchase_score_rank'] = result.groupby('race_id', sort=False)['purchase_score'].rank(method='first', ascending=False)
    result['excluded_grade'] = excluded
    return result


def prediction_csv(result):
    """CSVは識別情報・オッズ・順位だけに絞る。CLI用の実数値は内部に保持する。"""
    fields = ['race_id', 'horse_id', 'horse_name', 'gate_num', 'horse_num', 'ods']
    ranks = (['predicted_order', 'rank_score_rank', 'purchase_score_rank'] if 'predicted_rank' in result
             else ['win_rate_rank', 'expected_value_rank'])
    fields += ranks + ['recommend_rank']
    output = result[[field for field in fields if field in result]].copy()
    for field in ranks + ['recommend_rank']:
        output[field] = output[field].astype('Int64')
    return output


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


def add_features(df, verbose=True):
    """
    特徴量を追加する（learn_model.ipynbのセル6の処理）

    Args:
        df: 予測データのDataFrame
        verbose: 詳細表示モード

    Returns:
        特徴量を追加したDataFrame
    """
    if verbose:
        print("特徴量を追加しています...")
    
    # time_per_distance特徴量（過去5レース分）
    for i in range(1, 6):
        time_col = f'time_pre{i}'
        distance_col = f'distance_pre{i}'
        time_per_distance_col = f'time_per_distance_pre{i}'
        
        if time_col in df.columns and distance_col in df.columns:
            df[time_per_distance_col] = df.apply(
                lambda row: (row[time_col] / row[distance_col]) * 1000 if pd.notna(row[distance_col]) and row[distance_col] != 0 else None,
                axis=1
            )
    
    if verbose:
        print("  - time_per_distance特徴量を作成しました（過去5レース分）")

    # jockey_weight_per_horse_weight特徴量（過去5レース分）
    for i in range(1, 6):
        jockey_weight_col = f'jockey_weight_pre{i}'
        horse_weight_col = f'horse_weight_pre{i}'
        weight_rate_col = f'jockey_weight_per_horse_weight_pre{i}'
        
        if jockey_weight_col in df.columns and horse_weight_col in df.columns:
            df[weight_rate_col] = df.apply(
                lambda row: (row[jockey_weight_col] / row[horse_weight_col]) * 100 if pd.notna(row[jockey_weight_col]) and pd.notna(row[horse_weight_col]) else None,
                axis=1
            )
    
    if verbose:
        print("  - weight_rate特徴量を作成しました（過去5レース分）")

    # race_interval特徴量
    def calculate_race_interval(year1, month1, date1, year2, month2, date2):
        """2つのレース間の日数差を計算"""
        try:
            if pd.isna(year1) or pd.isna(month1) or pd.isna(date1) or \
               pd.isna(year2) or pd.isna(month2) or pd.isna(date2):
                return None
            
            date_1 = datetime(int(year1), int(month1), int(date1))
            date_2 = datetime(int(year2), int(month2), int(date2))
            
            return (date_1 - date_2).days
        except:
            return None
    
    # race_interval: 現在のレースとpre1の間隔
    if 'race_year' in df.columns and 'race_year_pre1' in df.columns:
        df['race_interval'] = df.apply(
            lambda row: calculate_race_interval(
                row.get('race_year'), row.get('race_month'), row.get('race_date'),
                row.get('race_year_pre1'), row.get('race_month_pre1'), row.get('race_date_pre1')
            ),
            axis=1
        )
    
    # race_interval_pre1～pre4: 過去レース間の間隔
    for i in range(1, 5):
        year_col_1 = f'race_year_pre{i}'
        month_col_1 = f'race_month_pre{i}'
        date_col_1 = f'race_date_pre{i}'
        
        year_col_2 = f'race_year_pre{i+1}'
        month_col_2 = f'race_month_pre{i+1}'
        date_col_2 = f'race_date_pre{i+1}'
        
        interval_col = f'race_interval_pre{i}'
        
        if year_col_1 in df.columns and year_col_2 in df.columns:
            df[interval_col] = df.apply(
                lambda row: calculate_race_interval(
                    row.get(year_col_1), row.get(month_col_1), row.get(date_col_1),
                    row.get(year_col_2), row.get(month_col_2), row.get(date_col_2)
                ),
                axis=1
            )
    
    if verbose:
        print("  - race_interval特徴量を作成しました（現在 + 過去4レース分）")

    # race_track_category特徴量
    # 現在のレース
    if 'race_track' in df.columns:
        df['race_track_category'] = df['race_track'].apply(categorize_race_track)

    # 過去レース分（_pre1～_pre5）
    for i in range(1, 6):
        race_track_col = f'race_track_pre{i}'
        category_col = f'race_track_category_pre{i}'

        if race_track_col in df.columns:
            df[category_col] = df[race_track_col].apply(categorize_race_track)

    if verbose:
        print("  - race_track_category特徴量を作成しました（現在 + 過去5レース分）")
    
    
    def combine_columns(val1, val2):
        """2つの値を'_'で結合（いずれかがNaNの場合はNoneを返す）"""
        if pd.isna(val1) or pd.isna(val2):
            return None
        return f"{val1}_{val2}"

    # jockey_idとrace_trackの組み合わせ
    # # 現在のレース
    if 'jockey_id' in df.columns and 'race_track' in df.columns:
        df['jockey_id_and_race_track'] = df.apply(
            lambda row: combine_columns(row.get('jockey_id'), row.get('race_track')),
            axis=1
        )

    # 過去レース分（_pre1～_pre5）
    for i in range(1, 6):
        jockey_col = f'jockey_id_pre{i}'
        track_col = f'race_track_pre{i}'
        combined_col = f'jockey_id_and_race_track_pre{i}'
        
        if jockey_col in df.columns and track_col in df.columns:
            df[combined_col] = df.apply(
                lambda row: combine_columns(row.get(jockey_col), row.get(track_col)),
                axis=1
            )
    if verbose:
        print(f"jockey_id_and_race_track特徴量を作成しました（現在 + 過去5レース分）")

    # jockey_idとstable_idの組み合わせ（現在のレース）
    if 'jockey_id' in df.columns and 'stable_id' in df.columns:
        df['jockey_id_and_stable_id'] = df.apply(
            lambda row: combine_columns(row.get('jockey_id'), row.get('stable_id')),
            axis=1
        )

    # 過去レース分（_pre1～_pre5）
    for i in range(1, 6):
        jockey_col = f'jockey_id_pre{i}'
        stable_col = f'stable_id'
        combined_col = f'jockey_id_and_stable_id_pre{i}'
        
        if jockey_col in df.columns and stable_col in df.columns:
            df[combined_col] = df.apply(
                lambda row: combine_columns(row.get(jockey_col), row.get(stable_col)),
                axis=1
            )
    if verbose:
        print(f"jockey_id_and_stable_id特徴量を作成しました（現在 + 過去5レース分）")

    return df


def prepare_features(df, label_encoders, verbose=True, feature_cols=None):
    """
    予測用の特徴量を準備する（learn_model.ipynbのセル9、10の処理）

    Args:
        df: 特徴量追加済みのDataFrame
        label_encoders: 学習時に保存されたLabelEncoderの辞書
        verbose: 詳細表示モード
        feature_cols: モデルが要求する特徴量名（保存モデルの順序で指定）

    Returns:
        tuple: (処理済みDataFrame, 特徴量カラムのリスト)
    """
    if verbose:
        print("\n特徴量を準備しています...")
    
    # 学習に使用しないカラムを除外（learn_model.ipynbのセル9）
    base_exclude_cols = ['horse_id', 'horse_name', 'ods', 'favorite', 'race_id', 'rank']
    rank_cols = [col for col in df.columns if col.startswith('rank')]
    time_diff_cols = [col for col in df.columns if col.startswith('time_diff')]
    race_id_cols = ['race_id', 'race_id_pre1', 'race_id_pre2', 'race_id_pre3', 'race_id_pre4', 'race_id_pre5']
    jockey_id_cols = ['jockey_id', 'jockey_id_pre1', 'jockey_id_pre2', 'jockey_id_pre3', 'jockey_id_pre4', 'jockey_id_pre5']
    stable_id_cols = ['stable_id']
    ods_cols = [col for col in df.columns if 'ods' in col]
    
    exclude_cols = base_exclude_cols + rank_cols + time_diff_cols + ods_cols + jockey_id_cols + stable_id_cols + race_id_cols 
    # exclude_cols = base_exclude_cols + ods_cols + jockey_id_cols + stable_id_cols + race_id_cols

    # モデルの指定がない場合は現在の学習スクリプトの除外条件に合わせる。
    exclude_cols += ['win_rate', 'top_2_rate', 'top_3_rate']
    
    # 除外カラムがデータに存在しない場合は除外リストから削除
    exclude_cols = [col for col in exclude_cols if col in df.columns]
    
    if feature_cols is None:
        feature_cols = sorted(col for col in df.columns if col not in exclude_cols)
    else:
        feature_cols = list(feature_cols)
        missing = [col for col in feature_cols if col not in df.columns]
        if missing:
            raise ValueError(
                f"モデルが要求する特徴量が予測CSVにありません: {missing}。"
                "create_data_for_predict.pyで入力データを確認・再作成してください。"
            )
        if verbose:
            extra = [col for col in df.columns if col not in feature_cols and col not in exclude_cols]
            if extra:
                print(f"  - モデルが使用しないカラムを除外: {extra}")
    
    if verbose:
        print(f"  - 除外カラム数: {len(exclude_cols)}")
        print(f"  - 特徴量数: {len(feature_cols)}")

    # 学習時に保存されたLabelEncoderを使用してエンコード
    if verbose:
        print("\n文字列カラムをエンコードしています...")
    df_processed = df.copy()
    
    for col in feature_cols:
        if col in label_encoders:
            if verbose:
                print(f"  - エンコード中: {col}")
            le = label_encoders[col]
            mask = df_processed[col].notna()
            if mask.sum() > 0:
                if not hasattr(le, 'classes_') or len(le.classes_) == 0:
                    raise ValueError(f"'{col}' のLabelEncoderに学習済みカテゴリがありません。モデルとエンコーダーを確認してください。")
                values = df_processed.loc[mask, col].astype(str)
                unknown_values = set(values.unique()) - set(le.classes_)
                if unknown_values:
                    if verbose:
                        print(f"    警告: '{col}' に学習時に見なかったカテゴリがあります: {unknown_values}")
                        print("    これらはカテゴリコード0に置き換えます")
                    values = values.where(values.isin(le.classes_), le.classes_[0])
                # 学習済みのカテゴリだけで変換し、欠損は欠損のまま保持する。
                df_processed[col] = np.nan
                df_processed.loc[mask, col] = le.transform(values)
        elif df_processed[col].dtype == 'object' and verbose:
            print(f"  - '{col}' は数値として処理します。")
    
    if verbose:
        print(f"\nエンコード完了")
    
    # すべてのカラムを数値化（変換不能な値はNaNにする）
    # 例: pace_first_pre* に含まれる '**' のような欠損記号を安全に処理
    for col in feature_cols:
        df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce').astype(float)
    
    if verbose:
        print("型変換完了: すべての特徴量をfloatに変換")
    
    return df_processed, feature_cols


def print_horse_scores(horses, regression, recommended=False):
    fields = [name for name in ('recommend_rank', 'horse_num', 'horse_name', 'horse_id', 'ods',
              'win_rate_raw', 'predicted_rank', 'model_score', 'purchase_score', 'selected', 'bet_amount') if name in horses]
    display = horses[fields].copy()
    if 'win_rate_raw' in display:
        display['win_rate_raw'] = display['win_rate_raw'].map(lambda value: f'{value * 100:.2f}%')
    if not recommended:
        display.insert(0, '表示順位', range(1, len(display) + 1))
    display = display.rename(columns={
        'recommend_rank': '推奨順位', 'horse_num': '馬番', 'horse_name': '馬名', 'ods': 'オッズ',
        'win_rate_raw': '勝率', 'predicted_rank': '予測rank',
        'model_score': 'rankスコア' if regression else '適用スコア',
        'purchase_score': '購入スコア', 'selected': '購入', 'bet_amount': '購入額',
    })
    print(display.to_string(index=False, float_format=lambda value: f'{value:.6g}'))


def print_recommendations(result):
    """購入条件に該当する全頭を、レースごとに推奨順位で表示する。"""
    regression = 'predicted_rank' in result
    for race_id, horses in result.groupby('race_id', sort=False):
        recommended = horses[horses['recommend_rank'].notna()].sort_values('recommend_rank', kind='stable')
        print(f'\n【レース {race_id}：推奨馬】')
        if recommended.empty:
            print('購入条件に該当する馬はいません')
        else:
            print_horse_scores(recommended, regression, recommended=True)


def print_top5(result):
    """各レースの勝率（回帰ではrankスコア）の上位5頭を追加表示する。"""
    regression = 'predicted_rank' in result
    column = 'model_score' if regression else 'win_rate_raw'
    title = 'rankスコア 上位5頭' if regression else '勝率 上位5頭（label 0の確率）'
    for race_id, horses in result.groupby('race_id', sort=False):
        print(f'\n【レース {race_id}：{title}】')
        horses = horses[horses['model_score'].notna()]
        top = horses.dropna(subset=[column]).sort_values(column, ascending=False, kind='stable').head(5)
        if top.empty:
            print('対象馬がいません（グレード除外など）')
        else:
            print_horse_scores(top, regression)


def predict(model_path, input_csv_path, output_csv_path=None, verbose=True, odds_threshold=30.0,
            win_rate_rank_threshold=5, use_softmax=None, seed_list=None, *, normalization='auto',
            temperature=1.0, ev_threshold=1.0, staking='expected-value', base_bet=100,
            exclude_grade=6.0, expected_task=None, show_top5=False):
    """
    予測を実行する（複数モデルのアンサンブル対応）

    Args:
        model_path: 学習済みモデルのパス（seed_listが指定された場合はベースパスとして使用）
        input_csv_path: 予測用CSVファイルのパス
        output_csv_path: 結果を保存するCSVファイルのパス（オプション）
        verbose: 詳細表示モード（True: 詳細表示, False: 簡易表示）
        odds_threshold: 推奨馬のオッズ上限閾値
        win_rate_rank_threshold: 候補頭数top-n（分類は確率順、回帰は予測rank順）
        use_softmax: 旧API互換。指定するとnormalizationを上書きする
        seed_list: アンサンブルに使用するseedのリスト（指定された場合、複数モデルの平均を取る）
        normalization: auto / none / softmax
        temperature: レース全頭のsoftmax温度
        ev_threshold: 購入スコアが厳密に超える必要のあるしきい値
        staking: expected-value / fixed / kelly
        base_bet: 購入額計算の基準額
        exclude_grade: 除外するエンコード済みグレード（Noneで無効）
        show_top5: 推奨馬に加えて各レースの勝率上位5頭をCLIに表示

    Returns:
        DataFrame: 予測結果
    """
    if use_softmax is not None:
        normalization = 'softmax' if use_softmax else 'none'
    if verbose:
        print("=" * 80)
        print("予測スクリプト" + (" (アンサンブルモード)" if seed_list else ""))
        print("=" * 80)

    # モデルとエンコーダーの読み込み
    models = []
    label_encoders_list = []  # 各モデルに対応するエンコーダーのリスト

    if seed_list:
        # アンサンブルモード: 複数のモデルを読み込む
        if verbose:
            print(f"\nアンサンブルモード: {len(seed_list)} 個のモデルを読み込みます")

        model_dir = Path(model_path).parent

        for seed in seed_list:
            model_prefix = Path(model_path).stem.rsplit("_", 1)[0]
            model_file = model_dir / f"{model_prefix}_{seed}.pkl"
            encoders_file = model_dir / f"label_encoders_{seed}.pkl"

            if verbose:
                print(f"  - モデル {seed} を読み込み中: {model_file.name}")

            if not model_file.exists():
                print(f"    警告: モデルファイルが見つかりません: {model_file}")
                continue

            # モデルを読み込み
            with open(model_file, 'rb') as f:
                model = pickle.load(f)
                models.append(model)

            # 対応するLabelEncoderを読み込み
            if encoders_file.exists():
                if verbose:
                    print(f"    - LabelEncoderを読み込み中: {encoders_file.name}")
                with open(encoders_file, 'rb') as f:
                    encoders = pickle.load(f)
                    label_encoders_list.append(encoders)
            else:
                print(f"    警告: LabelEncoderファイルが見つかりません: {encoders_file}")
                label_encoders_list.append({})

        if not models:
            raise ValueError("有効なモデルが1つも読み込めませんでした")

        if verbose:
            print(f"\n{len(models)} 個のモデルと {len(label_encoders_list)} 個のLabelEncoderを読み込み完了")
    else:
        # 単一モデルモード
        if verbose:
            print(f"\nモデルを読み込んでいます: {model_path}")
        with open(model_path, 'rb') as f:
            model = pickle.load(f)
            models.append(model)
        if verbose:
            print("モデルの読み込み完了")

        # LabelEncoderの読み込み
        model_dir = Path(model_path).parent
        model_name = Path(model_path).stem
        # モデル名からSEED番号を抽出（例: "model_jsp_23" -> "23"）
        seed_match = model_name.split('_')[-1]
        encoders_path = model_dir / f"label_encoders_{seed_match}.pkl"

        if verbose:
            print(f"\nLabelEncoderを読み込んでいます: {encoders_path}")
        if encoders_path.exists():
            with open(encoders_path, 'rb') as f:
                label_encoders = pickle.load(f)
                label_encoders_list.append(label_encoders)
            if verbose:
                print(f"LabelEncoderの読み込み完了: {len(label_encoders)} カラム")
        else:
            if verbose:
                print(f"警告: LabelEncoderファイルが見つかりません: {encoders_path}")
                print("新しいLabelEncoderを作成しますが、学習時と異なるエンコーディングになる可能性があります。")
            label_encoders_list.append({})

    if not label_encoders_list:
        label_encoders_list.append({})

    # 予測データの読み込み
    if verbose:
        print(f"\n予測データを読み込んでいます: {input_csv_path}")
    
    # _idを含むカラムを文字列として読み込む
    sample_df = pd.read_csv(input_csv_path, nrows=0)
    id_columns = [col for col in sample_df.columns if '_id' in col]
    dtype_dict = {col: str for col in id_columns}
    
    df = pd.read_csv(input_csv_path, dtype=dtype_dict)
    if verbose:
        print(f"予測データ件数: {len(df)} 件")

    # 欠損オッズの馬もsoftmax全頭計算には含め、購入条件で除外する。
    df = df.reset_index(drop=True)
    if df.empty:
        raise ValueError('予測対象のデータが0件です。')
    # 識別情報を保存（horse_id, horse_name, gate_num, horse_num, ods, race_idなど）
    info_cols = ['race_id', 'horse_id', 'horse_name', 'gate_num', 'horse_num', 'ods']
    info_cols = [col for col in info_cols if col in df.columns]
    df_info = df[info_cols].copy()
    
    # 特徴量を追加
    df = add_features(df, verbose=verbose)

    # 予測実行
    if verbose:
        print("\n予測を実行しています...")

    # 複数モデルで予測し、平均を取る（各モデルごとに対応するエンコーダーを使用）
    all_predictions = []
    for i, (model, label_encoders) in enumerate(zip(models, label_encoders_list), 1):
        if verbose and len(models) > 1:
            print(f"  - モデル {i}/{len(models)} で予測中...")

        # 各モデルに対応するエンコーダーで特徴量を準備
        df_processed, feature_cols = prepare_features(
            df, label_encoders, verbose=verbose, feature_cols=model.feature_name()
        )

        # 予測用データを準備
        X_pred = df_processed[feature_cols]

        # モデルに保存された特徴量の順序で準備する（各アンサンブルモデルも個別に対応）。

        # 予測実行
        y_pred = model.predict(X_pred, num_iteration=model.best_iteration, validate_features=True)
        y_pred = np.asarray(y_pred)
        if y_pred.shape == (len(df),):
            if model.params.get('objective') in ('binary', 'lambdarank', 'rank_xendcg'):
                raise ValueError('4クラス分類または着順回帰モデルを指定してください。')
        elif y_pred.shape != (len(df), 4):
            raise ValueError('4クラス分類または着順回帰モデルを指定してください。')
        if not np.isfinite(y_pred).all():
            raise ValueError('モデルの予測値が不正です。')
        if y_pred.ndim == 2 and ((y_pred < 0) | (y_pred > 1)).any():
            raise ValueError('モデルの予測確率が不正です。')
        if all_predictions and y_pred.shape != all_predictions[0].shape:
            raise ValueError('分類と回帰のモデルを混ぜたアンサンブルは使用できません。')
        all_predictions.append(y_pred)

    # 予測値の平均を計算
    y_pred_proba = np.mean(all_predictions, axis=0)

    if verbose:
        if len(models) > 1:
            print(f"予測完了: {len(models)} 個のモデルの予測を平均化")
        print(f"予測結果の形状: {y_pred_proba.shape}")
    
    task = 'regression' if y_pred_proba.ndim == 1 else 'classification'
    if expected_task and expected_task != task:
        raise ValueError(f'設定のモデル種別 {expected_task} と読み込んだモデル {task} が一致しません。')
    result_df = df_info.copy()
    if task == 'regression':
        result_df['predicted_rank'] = y_pred_proba
    else:
        result_df['pred_prob_first'] = y_pred_proba[:, 0]
    # グレード除外には学習時と同じカテゴリコードを使う。
    if 'race_grade' in df_processed:
        result_df['race_grade'] = df_processed['race_grade']
    result_df = apply_purchase_strategy(
        result_df, win_rate_rank_threshold, normalization, temperature, ev_threshold,
        odds_threshold, staking, base_bet, exclude_grade,
    )
    actual_normalization = ('softmax' if task == 'regression' else 'none') if normalization == 'auto' else normalization
    settings = dict(task=task, model=str(Path(model_path).resolve()), seed_list=seed_list,
                    normalization=actual_normalization, temperature=temperature,
                    top_n=win_rate_rank_threshold, score_threshold=ev_threshold,
                    max_odds=odds_threshold, staking=staking, base_bet=base_bet,
                    exclude_grade=exclude_grade, bet_type='win')
    result_df.attrs['settings'] = settings
    if output_csv_path:
        output = Path(output_csv_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        prediction_csv(result_df).to_csv(output, index=False, encoding='utf-8-sig')
        metadata = dict(settings=settings, request=prediction_request(
            model_path, input_csv_path, odds_threshold, win_rate_rank_threshold,
            normalization, temperature, ev_threshold, staking, base_bet, exclude_grade,
            seed_list, expected_task))
        # 簡略化したCSVからはCLI表示用の数値を復元できないためJSONに保持する。
        metadata['predictions'] = result_df.astype(object).where(result_df.notna(), None).to_dict(orient='records')
        output.with_suffix('.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    if verbose:
        columns = [col for col in ('race_id', 'horse_name', 'horse_num', 'ods', 'predicted_rank',
                   'model_score', 'candidate_rank', 'purchase_score', 'selected', 'bet_amount') if col in result_df]
        print(result_df[columns].to_string(index=False))
        print(f"購入: {result_df['selected'].sum()}頭 / {result_df['race_id'].nunique()}レース")
        if output_csv_path:
            print(f'結果の保存先: {output_csv_path}')
    print_recommendations(result_df)
    if show_top5:
        print_top5(result_df)
    return result_df


def prediction_request(model_path, input_csv_path, max_odds, top_n, normalization,
                       temperature, ev_threshold, staking, base_bet, exclude_grade,
                       seed_list, expected_task):
    def file_info(path):
        path = Path(path).resolve()
        return [str(path), path.stat().st_size, path.stat().st_mtime_ns] if path.exists() else [str(path), None, None]
    model_path = Path(model_path)
    models = ([model_path.parent / f'{model_path.stem.rsplit("_", 1)[0]}_{seed}.pkl' for seed in seed_list]
              if seed_list else [model_path])
    files = [file_info(input_csv_path)]
    for model in models:
        files.extend([file_info(model), file_info(model.parent / f'label_encoders_{model.stem.split("_")[-1]}.pkl')])
    return dict(result_schema_version=3, files=files, max_odds=max_odds, top_n=top_n, normalization=normalization,
                temperature=temperature, ev_threshold=ev_threshold, staking=staking,
                base_bet=base_bet, exclude_grade=exclude_grade, seed_list=seed_list,
                expected_task=expected_task)


def predict_batch(model_path, date_dir, overwrite=False, ev_threshold=1.0, odds_threshold=30.0,
                  win_rate_rank_threshold=5, use_softmax=None, seed_list=None, *,
                  normalization='auto', temperature=1.0, staking='expected-value', base_bet=100,
                  exclude_grade=6.0, expected_task=None, show_top5=False):
    """同じ購入条件で一括予測する。入力・モデル・条件が変われば再計算する。"""
    if use_softmax is not None:
        normalization = 'softmax' if use_softmax else 'none'
    files = sorted(p for p in Path(date_dir).glob('*.csv') if not p.stem.endswith('_pred') and not p.stem.startswith('race_id'))
    if not files:
        raise ValueError(f'予測対象のCSVがありません: {date_dir}')
    recommended = []
    for csv in files:
        output = csv.with_name(f'{csv.stem}_pred.csv')
        metadata = output.with_suffix('.json')
        request = prediction_request(model_path, csv, odds_threshold, win_rate_rank_threshold,
                                     normalization, temperature, ev_threshold, staking, base_bet,
                                     exclude_grade, seed_list, expected_task)
        cached = False
        if output.exists() and metadata.exists() and not overwrite:
            try:
                saved = json.loads(metadata.read_text(encoding='utf-8'))
                cached = saved.get('request') == request and isinstance(saved.get('predictions'), list)
            except (ValueError, OSError):
                pass
        if cached:
            result = pd.DataFrame(saved['predictions'])
            print(f'{csv.name}: 同じ入力・モデル・条件の保存済み結果を使用')
            print_recommendations(result)
        else:
            result = predict(model_path, csv, output, verbose=False, odds_threshold=odds_threshold,
                             win_rate_rank_threshold=win_rate_rank_threshold, seed_list=seed_list,
                             normalization=normalization, temperature=temperature, ev_threshold=ev_threshold,
                             staking=staking, base_bet=base_bet, exclude_grade=exclude_grade,
                             expected_task=expected_task)
        horses = result[result['recommend_rank'].notna()].sort_values(['race_id', 'recommend_rank'], kind='stable').to_dict('records')
        print(f'{csv.name}: 推奨{len(horses)}頭、購入{int(result.selected.sum())}頭')
        if show_top5:
            print_top5(result)
        if horses:
            recommended.append(dict(race_name=csv.stem, file_path=str(csv), horses=horses))
    return recommended


def main(argv=None):
    parser = argparse.ArgumentParser(description='保存モデルと購入条件による競馬予測')
    parser.add_argument('input_csv', nargs='?', default='data/predict/predict_data.csv')
    parser.add_argument('--config', type=Path, help='保存済み購入条件JSON（明示CLI引数を優先）')
    parser.add_argument('--model', type=Path, default=Path('models/v8/model_jsp_23.pkl'))
    parser.add_argument('--output', type=Path, help='結果CSV（既定: 入力名_pred.csv）')
    parser.add_argument('--batch', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--show-top5', action='store_true', help='常時表示する推奨馬に加えて、勝率上位5頭を表示（回帰はrankスコア）')
    parser.add_argument('--ev-threshold', '--score-threshold', dest='ev_threshold', type=positive_float, default=1.0)
    parser.add_argument('--odds-threshold', '--max-odds', dest='max_odds', type=positive_float, default=30.0)
    parser.add_argument('--win-rate-rank-threshold', '--top-n', dest='top_n', type=positive_int, default=5)
    parser.add_argument('--normalization', choices=('auto', 'none', 'softmax'), default='auto')
    parser.add_argument('--temperature', type=positive_float, default=1.0)
    parser.add_argument('--staking', choices=('expected-value', 'fixed', 'kelly'), default='expected-value')
    parser.add_argument('--base-bet', type=positive_int, default=100)
    parser.add_argument('--exclude-grade', type=float, default=6.0)
    parser.add_argument('--include-all-grades', action='store_true')
    parser.add_argument('--seeds', type=int, nargs='+', help='指定した場合だけアンサンブルを使用')
    apply_config_defaults(parser, argv)
    args = parser.parse_args(argv)
    if getattr(args, 'bet_type', 'win') != 'win':
        parser.error('predict.pyの購入判定は単勝です。単勝のconfigを指定してください。')
    kwargs = dict(ev_threshold=args.ev_threshold, odds_threshold=args.max_odds,
                  win_rate_rank_threshold=args.top_n, normalization=args.normalization,
                  temperature=args.temperature, staking=args.staking, base_bet=args.base_bet,
                  exclude_grade=None if args.include_all_grades else args.exclude_grade,
                  expected_task=getattr(args, 'expected_task', None), seed_list=args.seeds,
                  show_top5=args.show_top5)
    if args.batch:
        predict_batch(args.model, args.input_csv, overwrite=args.overwrite, **kwargs)
    else:
        input_path = Path(args.input_csv)
        output = args.output or input_path.with_name(f'{input_path.stem}_pred.csv')
        predict(args.model, input_path, output, **kwargs)


if __name__ == '__main__':
    main()
