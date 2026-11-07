# 学習側のwin_policyからrace_modelへの改名

2026-10-11再配置追記: スクリプトは用途別の `src/` に整理済みです。現行手順は学習側の `C:/Users/mochi/dev/keiba-predict/docs/neural-model.md` に移りました。以下は改名時の記録です。

2026-10-11。対象は隣接プロジェクト `C:/Users/mochi/dev/keiba-predict/win_policy`。ユーザーの名称変更依頼により `race_model` へ改名し、学習側のREADMEの現行コマンドとリンクを更新した。回収率を目的とした期待収益方針と正規化着順回帰の両用途を含む名称とした。

学習・予測・評価スクリプト、テストと既存成果物をディレクトリごと保持。過去の実験メタデータや検証記録内の旧パスは当時の来歴として保持し、以前の記録には移行先案内を追記した。本予測アプリのモデルや実行コードは変更していない。

実測: 新しいrace_modelディレクトリで既存ルート仮想環境のPythonを使い `python -m unittest discover -s tests -v` を実行。17テスト、20.834秒、全成功。実データ本学習・過去モデルの実データ再評価は未実施。

現在の実行例は学習プロジェクトルートから `uv run python race_model/train.py --data data/learn_data/learn_data.csv --output models/race_model/20261011_normalized_rank_mse --loss normalized-rank-mse --epochs 100`。詳細は `C:/Users/mochi/dev/keiba-predict/race_model/README.md` と学習側の `.agents/docs/2026-10-11-race-model-directory-rename.md` を参照。
