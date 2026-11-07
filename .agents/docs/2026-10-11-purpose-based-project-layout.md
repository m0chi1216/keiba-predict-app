# 学習側スクリプトの用途別整理

2026-10-11。ユーザー依頼により隣接プロジェクト `C:/Users/mochi/dev/keiba-predict` のsrc直下と旧win_policy（改名後race_model）を整理した。

取得はsrc/collection、整形はsrc/preparation、両モデルの学習入口はsrc/training、予測はsrc/prediction、収支評価・探索はsrc/evaluation、共通購入ルールはsrc/common、ニューラル内部処理はsrc/neural。ノートブックはnotebooks、ニューラルテストもtestsへ集約。過去成果物をmodels/race_model/artifactsへ移動し、旧専用環境をarchive/race_modelへ保管。過去実験の内容・メタデータは保持。

import・__file__によるルート計算・Webアプリ・テスト・独立アプリ書き出しを更新した。独立アプリの出力構成は従来を維持。本予測アプリのコード・モデルは変更していない。現行コマンドは学習側READMEとdocs/neural-model.mdに記載。

実測検証: 既存93テスト（40.123秒）、Webアプリ8テスト（0.629秒）、一時書き出し独立アプリ11テスト（2.537秒）が成功。新規構成2テストと探索5テストも修正後7件成功（13.769秒）。新規検証で既存の探索--helpの%補間エラーを見つけ、help文字列をエスケープして修正。データ取得はモック、学習は合成データの機能検証。実サイト取得・実データ本学習・精度比較・全ノートブック実行・Dockerは未実施。

再実行: 学習側ルートから `uv run python -m unittest discover -s tests -v`。新しい正規化着順の学習入口は `uv run python -m src.training.train_neural --data data/learn_data/learn_data.csv --output models/race_model/20261011_normalized_rank_mse --loss normalized-rank-mse --epochs 100`。出力は新しい空の保存先を指定する。

詳細は `C:/Users/mochi/dev/keiba-predict/.agents/docs/2026-10-11-purpose-based-project-layout.md` と `C:/Users/mochi/dev/keiba-predict/README.md` に記録した。
