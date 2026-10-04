# 公開HTTPS構成の任意ログイン認証

- 対象: `deploy/Caddyfile`、`compose.public.yaml`、`.env.example`、READMEとEC2手順書。データ・予測モデル変更なし。
- 実行条件: 2026-10-04、Windows PowerShell、ローカルDockerの `caddy:2-alpine`。テスト用ドメイン `example.com` とテスト専用パスワードから生成したbcryptハッシュを使用。テストコンテナは `--rm --network none`。
- 変更: `AUTH_ENABLED` を追加し、未設定・空の既定値はtrue。Caddyの `auth_true` / `auth_false` snippetをimportで選択。falseはbasic_authを追加しない。ハッシュの必須判定をCompose補間からCaddy設定解析に移し、falseではユーザー名とハッシュを不要にした。HTTPS、プロキシ、Host/Origin制限は維持。
- 実測: `caddy adapt` はtrueと未設定で終了コード0・authentication handlerあり、falseで終了コード0・handlerなし。invalidとtrueでハッシュ未設定の場合は終了コード1。認証無効・ユーザー名とハッシュ未設定の `caddy validate` は終了コード0で自動HTTPSとHTTPからHTTPSへのリダイレクトを確認。Compose展開もfalse・空ハッシュで成功し、アプリのoriginは `https://example.com`。
- 検証方法・再実行: `docker compose -f compose.yaml -f compose.public.yaml config --quiet`。Caddy設定のマウントと `APP_DOMAIN`、`ACME_EMAIL`、`AUTH_ENABLED`、必要時の `AUTH_USER`、`AUTH_PASSWORD_HASH` を環境変数で与え、`caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile` または `caddy validate` を実行。ハッシュ値は出力・記録しない。公式 `caddy fmt` で整形した。
- 仕様根拠: [Caddy import](https://caddyserver.com/docs/caddyfile/directives/import)、[環境変数とsnippet](https://caddyserver.com/docs/caddyfile/concepts)。不明なsnippet名はエラーとなり、誤ったAUTH_ENABLEDが無認証に切り替わることはない。
- 運用: `.env` に `AUTH_ENABLED=false` を記載し `docker compose -f compose.yaml -f compose.public.yaml up -d --force-recreate caddy` で反映。認証を再有効化する場合はtrueとユーザー名・ハッシュを設定して同様に再作成。
- 制約・未検証: EC2への反映、実際のHTTPリクエストによる認証と証明書発行の確認は未実施。無効時はアクセス可能な人がアプリの予測・取得APIを使用できる。稼働中EC2の設定は変更していない。
