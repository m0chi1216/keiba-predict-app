# 頭数不足を許容して再学習した回帰モデルのtestシミュレーション

## 対象・実行条件

2026-10-11実施。モデル models/race_model/20261011_regression_jsp_partial_fields。normalized-rank-mse（rank/num_of_horse）、best_epoch=5、trained_epochs=20、学習末2023-12-31、検証末2025-12-31。データはdata/learn_data/learn_data_jsp.csv。testは2025-12-31より後、採用期間2026-01-04〜2026-09-27。CUDA、batch_size=64、threads=4、1購入100円、単勝。

各レースで予測値が最小の馬を先に選び、その馬のオッズが1〜50倍の場合のみ購入する。50倍超の場合は次点馬に置き換えない。しきい値はpredicted_normalized_rank <= threshold。全1,817個の境界を探索。最低30購入は少数購入への偏りを確認する補足条件。

入力SHA256: de8490805245c13df591655ebd04391159989cc5ffea6215107fa9e8db88f50f
モデルpolicy.pt SHA256: 191f2427c63054001dc1e21ed21e8df851cf51ebef31716cbf6cdaa9b6dafbd0

## 実測結果

| 条件 | 購入 | 的中 | 的中率 | 回収率 | 概算収支 |
|---|---:|---:|---:|---:|---:|
| オッズ制限なし（参考） | 1,828 | 534 | 29.21% | 95.85% | -7,580円 |
| 50倍以下・全購入 | 1,817 | 533 | 29.33% | 93.06% | -12,610円 |
| 50倍以下・しきい値探索最高 | 6 | 5 | 83.33% | 121.67% | +130円 |
| 50倍以下・最低30購入での最高 | 1,816 | 533 | 29.35% | 93.11% | -12,510円 |

探索最高のしきい値は0.08433634042739868。600円購入、概算払戻730円、1,822レース見送り、採用率0.33%。表示用に0.08433635と上方向に丸めても同じ購入集合。最低30購入の最良しきい値は0.4383743405342102。181,600円購入、概算払戻169,090円、12レース見送り。最低10/20/30/50/100件すべて同じ最良条件で、10件以上では回収率100%超の条件なし。

50倍超の11頭を除いたため、制限なしに含まれる61.3倍の的中1件（払戻6,130円）も除かれた。

## データ検査・比較上の制約

元testは19,335行・2,331レース、採用1,828、除外503。採用には頭数と行数の不一致1,688レースを含む。頭数不一致は除外理由になっていない。不正着順124レース、勝ち馬不在/非対応同着394レースが残る（理由の重複あり）。学習メタデータのtest1,828と一致。

前回の完全レースモデルの対象140レースから対象が増えた。前回の50倍以下全購入の的中率16.03%・回収率70.31%に対し今回は29.33%・93.06%だが、モデルと評価母集団の両方が異なるため同一条件でのモデル改善幅とは解釈できない。

testでしきい値を探索した事後結果（independent_validation=false）。最高121.67%は6件のみの結果であり、未使用データの性能を示さない。払戻はods×100の概算で、確定払戻との照合は未実施。追加の再学習・別期間でのしきい値検証は実施していない。

## 検証（実測）

- 全1,828レースの選択馬IDと払戻がモデル保存済みtest_bets.csvと一致。予測値は絶対誤差1e-7以内。
- 1,817しきい値をCSVから直接フィルタして件数・的中数・回収率を再計算し一致。
- 最良2条件の購入明細から件数・的中・収支を再計算し一致。全購入のオッズ上限50を確認。
- コード変更はないためテストスイートの再実行は行っていない。

## 保存先・再実行

data/simulation/neural/20261011_regression_jsp_partial_fields_max50_rank_search/ にsummary.json、data_report.json、test_selections.csv、baseline_bets.csv、threshold_search.csv、best_unconstrained_bets.csv、best_min_bets_bets.csv、verification.jsonを新規保存。旧結果は保持。

学習リポジトリのルートで実行（再実行は新しい出力先にする）:

```powershell
.\.venv\Scripts\python.exe -m src.evaluation.simulate_neural --model models/race_model/20261011_regression_jsp_partial_fields --output data/simulation/neural/20261011_regression_jsp_partial_fields_max50_rank_search_r02 --max-odds 50 --min-bets 30
```

検証はtest_selectionsとモデルtest_betsをrace_idでone_to_one結合し、horse_id・payout_yen・predicted_normalized_rankを比較。baseline_betsをthreshold_searchの各しきい値以下に絞り、bet_yen・payout_yen・hitの合計から再集計する。
