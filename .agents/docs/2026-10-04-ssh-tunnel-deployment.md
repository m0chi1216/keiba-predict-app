# SSHトンネルによるEC2利用手順

- 対象: `compose.yaml`、既存の `compose.local.yaml`、`apps/race_predict/server.py`。モデル・入力データの変更なし。
- 実行条件: 2026-10-04、WindowsのDocker Compose CLIで構成を展開。想定デプロイ先はUbuntu EC2、PC側はOpenSSH。
- 調査結果: `compose.local.yaml` は `127.0.0.1:8000:8000` を公開する。サーバーは空の `APP_ORIGIN` でローカルHost/Originを許可し、localhost/127.0.0.1の別ポートも許可する。公開用構成はHTTPS originを設定するため、トンネルではローカル用構成を使う。
- 変更: `docs/ec2-deployment.md` に準備、起動、PC側のSSHコマンド、ポート競合時の18000番、停止と更新を追加。公開構成からの切り替えは先に公開構成を `down` する。
- 実測・検証方法: `docker compose -f compose.yaml -f compose.local.yaml config --format json` が終了コード0。展開後の `APP_ORIGIN` は空、portsのhost_ipは `127.0.0.1`、published/targetは8000。ソース読解でHost/Origin許可と起動時のHTTPS制約を確認した。
- 再実行: 上記configコマンドで構成を確認。EC2上で同じファイルの組を `up -d --build` し、`curl -fsS http://127.0.0.1:8000/healthz`、PC側で手順書のSSHコマンド、ブラウザでローカルURLを確認する。
- 制約・未検証: EC2作成、SSH実接続、コンテナ起動、ブラウザ操作は未実施。SSH経由で動作するという判断は構成・ソースに基づくもので、EC2での実測ではない。公開80/443/8000は不要で、22番だけを管理PCの公開IPへ許可する。

## 公開用設定が未完了の場合の停止手順修正

- ユーザー報告: EC2上の `compose.public.yaml down` が空の `AUTH_PASSWORD_HASH` による補間エラーで停止した。
- 原因: 公開用Composeの必須変数指定は起動以外のコマンドでも評価される。初版の切り替え手順は公開設定が未完了のケースを扱えていなかった。
- 修正: 同一プロジェクトで `docker compose -f compose.yaml -f compose.local.yaml down --remove-orphans` を使用する手順へ変更。公開用必須変数を参照せず、同一プロジェクトのCaddyも停止・削除する。`-v` を付けずデータ・証明書volumeを保持。未起動なら停止不要と明記。
- 検証: 公開構成で空のハッシュが補間エラーになること、ローカル構成のconfig展開が終了コード0になることをWindowsのCompose CLIで確認。EC2上の停止・削除自体は未実施。プロジェクト名が以前の起動と一致することが必要。
