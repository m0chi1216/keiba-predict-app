# 学習側で行数と頭数の不一致を許容

2026-10-11。ユーザー指定により隣接学習プロジェクトのsrc/neural/data.pyの共通検査から、CSV行数とnum_of_horseの不一致によるレース除外を削除。学習・検証・test・シミュレーション・予測に共通で適用。rank/num_of_horseの教師値を維持し、CSV行数で頭数を書き換えない。その他の頭数値・重複・日付・着順・勝ち馬・払戻の検査は維持。

実測: 関連24テストが19.977秒で成功。実CSV全期間の再検査で学習832→24,758、検証792→5,744、test140→1,828レース。検査レポートは学習側data/validation/20261011_allow_partial_fields/summary.json。既存モデル・過去成績は変更せず、本再学習は未実施。

再学習は学習側ルートから `uv run python -m src.training.train_neural --loss normalized-rank-mse --output models/race_model/20261011_regression_jsp_partial_fields --epochs 100`。詳細・条件・検証・未実施事項は学習側.agents/docs/2026-10-11-allow-partial-race-fields.md。本予測アプリの実行コード・モデルは変更していない。
