# LightGBMの頭数不足レース監査（2026-10-11）

## 結論

現行LightGBMの前処理・分類/回帰学習・予測・シミュレーションには、CSVの出走馬行数とnum_of_horseを比較してレースを除外する処理はない。したがって今回の条件による修正は不要。実行コード・モデル・既存成果物は変更しない。

## 対象と確認箇所

- src/preparation/create_data_for_learn.py: create_dataは非数値の着順を行単位で除去し、新馬戦を除外。残ったレースの頭数照合はしない。
- src/training/learn_model.py: prepare_training_dataは分類・回帰とも残った各行を利用。無効な着順にはエラー。勝ち馬の有無によるレース除外もない。
- src/prediction/predict.py: prepare_features・apply_purchase_strategyに頭数照合はない。
- src/evaluation/simulate_model.py・search_simulation.py・src/common/betting_strategy.py: 購入候補・集計は入力に存在する行を使い、宣言頭数との照合はしない。
- src/preparation/create_merged_data.pyおよび旧ノートブックのコードセルも検索。buy.ipynbは既存の空ファイルで実行コードなし。

## 実測

合成データはaレースが18頭表記で2行（着順1・3）、bレースが9頭表記で1行（着順2、勝ち馬なし）。race_gradeは1勝クラス。分類・回帰それぞれの予測は固定値を返すモックモデル。学習やモデル精度の計測ではない。

前処理、学習データ準備、予測特徴量準備、シミュレーション予測、購入判定のいずれも3行・2レースを保持。num_of_horseは18/18/9を保持。top_n=5、ev_threshold=0.01、max_odds=50、staking=fixed、exclude_grade=Noneで両レースの購入を確認。候補3行から各レース1頭の購入となり計2件。これは購入戦略であり頭数不足による除外ではない。

既存LightGBM関連テスト47件成功（20.887秒）。測定結果はdata/validation/20261011_lightgbm_partial_fields_audit/summary.jsonに保存。

## 再検証

プロジェクトルートで実行:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_learn_model tests.test_predict tests.test_simulate_model tests.test_search_simulation tests.test_strategy_config -q
```

合成入力は上記3行とods=3/10/5、distance=1600、horse_num=1/2/5、horse_id=1/2/3でCSVを作り、create_data→prepare_training_data（両task）→prepare_features→prepare_predictions→make_candidates→simulateの順に渡して行数とrace_idを確認。購入APIはmax_odds引数を使用する。

## 制約

実データでの再学習や再シミュレーションは行っていない。中止・除外など非数値着順の行除去、新馬戦の前処理除外、設定されたrace_gradeの購入除外は従来通り。今回は頭数不足の条件のみを監査した。LightGBM回帰の目的変数は従来通りrankであり、ニューラルモデルのrank/num_of_horseへの変更とは別。
