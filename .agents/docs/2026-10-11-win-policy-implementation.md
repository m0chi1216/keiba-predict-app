# win_policyでの正規化着順学習実装

2026-10-11再配置追記: 現在の学習入口は `src/training/train_neural.py`、内部実装は `src/neural` です。現行手順は学習側の `C:/Users/mochi/dev/keiba-predict/docs/neural-model.md` を参照してください。以下の旧パスは当時の記録です。

2026-10-11追記: 学習ディレクトリは `race_model/` に改名済みです。以下は改名前の記録です。現在の手順は学習側の `C:/Users/mochi/dev/keiba-predict/race_model/README.md` を参照してください。

2026-10-11。ユーザーからwin_policyの所在を示されたため、隣接の `C:/Users/mochi/dev/keiba-predict/win_policy` を調査し、同ディレクトリの実装を変更した。本予測アプリの学習入口を新設する案は実施していない。

確認した従来損失はPyTorchの全候補に対する期待純利益の負値と任意のエントロピー正則化。`--loss expected-profit` として保持（既定）。`--loss normalized-rank-mse` を追加し、教師値を `rank/num_of_horse`、損失をレース内平均の二乗誤差のレース間平均とした。検証MSEで最良モデルと早期終了を判定し、最小の予測値の馬を選択する。保存方式を予測・評価に引き継ぎ、旧モデル読み込みも保持。

実測: 既存仮想環境のPyTorch 2.11.0+cu128で、win_policyの17テストが21.207秒で全成功。従来方式の機能、新方式のCPU合成データ3エポック学習・保存・読込・予測・評価、頭数正規化・レース等重み・パディング勾配を確認。本学習や実データの精度比較、新方式のGPU検証は未実施。本アプリのモデル・購入設定は変更していない。

実装詳細と再実行手順は学習側の `C:/Users/mochi/dev/keiba-predict/.agents/docs/2026-10-11-win-policy-normalized-rank-loss.md` と `win_policy/README.md` に記録。再実行は学習プロジェクトのルートで `uv run python win_policy/train.py --data data/learn_data/learn_data.csv --output models/win_policy/20261011_normalized_rank_mse --loss normalized-rank-mse --epochs 100`。既存結果を上書きせず、新しい空の出力先を使う。
