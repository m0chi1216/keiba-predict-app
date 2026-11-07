# ニューラル回帰の全レース購入設定とpredict対応（2026-10-11）

## 対象・変更

モデルmodels/race_model/20261011_regression_jsp_partial_fields、元データlearn_data_jsp.csv、test2026-01-04〜2026-09-27。直前のシミュレーションbaseline（50倍以下、予測最小馬各レース1頭、しきい値なし、固定100円）の条件をconfigs/strategies/20261011_regression_jsp_partial_fields_all_max50.jsonに登録。評価情報はそのままJSONに記録し、独立検証でないこととods×100概算を明記。

src/neural/strategy.pyでneural用schema_version=1設定の読込・検証・購入判定を追加。CLI指定はJSON既定値より優先し、設定内の相対モデルパスは学習リポジトリルートで解決。src/neural/cli.pyでpredict_neuralに--config/--max-odds/--rank-threshold/--base-betを追加。設定適用時はnormalized-rank-mseモデルとods列を必要とする。評価CLIの既存挙動は維持。

src/neural/workflow.pyの回帰選択はmask外を+infにして生出力を直接argmin。softmax丸めで最小予測の選択が変わる可能性を避け、シミュレーションと同じ方法にした。回収率モデルのargmax選択は維持。予測後にオッズ判定し、条件外なら見送り、次点馬を買わない。オッズは別途読んで選択結果に結合しモデル特徴量へは加えない。

## 実測検証

27テスト成功（19.807秒）。新規3件は50/51倍境界・欠損・1倍・次点に置換しないこと、しきい値と購入額、相対モデルパス、明示CLI優先、不正設定を確認。既存24件は学習・推論・マスク・シミュレーションの回帰検証。

同じtest CSVから既存データ検査を通過する1,828レース16,433行を抽出し、rankとpayout_100を除いた予測用CSVを作成。購入設定でpredict_neuralを実行し1,817購入/11見送り。シミュレーションbaseline_bets.csvとのrace_id・horse_idが全件一致、全購入100円かつ50倍以下を確認。モデルの再学習は実施していない。

保存先data/prediction/neural/20261011_partial_fields_all_max50_verification/。test_input.csv、prediction/{selections.csv,purchases.csv,purchase_settings.json,data_report.json}、verification.json。以前のモデル・結果は上書きしない。元データ・モデルのSHA256は直前のシミュレーションsummary.jsonに保存済み。

## 結果と制約

設定のtest全購入結果は1,817購入533的中、的中率29.33%、概算回収率93.06%、概算収支-12,610円。今回の検証は購入集合の再現であり未使用期間の性能検証ではない。予測入力では着順を検査しないので、生の学習CSV全体を渡すとtestシミュレーションとは母集団が変わる。比較検証には同じ採用レース集合を使用した。実運用でのオッズ変動・取消は未検証。

selections.csvは見送りを含みselected=false、bet_yen=0。購入用途はpurchases.csvを使用する。設定なしの従来予測はオッズ不要のまま。

## 再実行

```powershell
uv run python -m unittest tests.test_neural_strategy tests.test_neural_policy tests.test_neural_simulation -q
uv run python -m src.prediction.predict_neural --config configs/strategies/20261011_regression_jsp_partial_fields_all_max50.json --data data/prediction/neural/20261011_partial_fields_all_max50_verification/test_input.csv --output data/prediction/neural/20261011_partial_fields_all_max50_verification_r02
```

一般の予測用CSVでの使用方法はdocs/neural-model.mdに記載。
