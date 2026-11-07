# 学習側の既定CSVをlearn_data_jsp.csvに変更

2026-10-11。対象は隣接学習プロジェクトのsrc/neural/cli.pyとテスト・現行README。ユーザー指定によりニューラル学習の--dataを任意とし、既定を学習プロジェクトルートのdata/learn_data/learn_data_jsp.csvへ変更。明示指定は優先し、予測・評価の--data必須は維持。損失の既定expected-profitは維持し、正規化着順回帰では--loss normalized-rank-mseを指定する。

実測: 対象CSVの存在、学習--helpの既定値表示、2つの新規CLIテストの成功（0.022秒）を確認。CSV読み込みはモックで停止し、本学習や実CSV全体の検証は未実施。本予測アプリの実行コードは変更していない。

学習プロジェクトルートから `uv run python -m src.training.train_neural --loss normalized-rank-mse --output models/race_model/20261011_regression_jsp --epochs 100`。出力先は新しい空のディレクトリを使う。詳細は学習側の `.agents/docs/2026-10-11-default-neural-training-data.md` と `docs/neural-model.md` に記録。
