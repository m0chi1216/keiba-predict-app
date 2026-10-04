# EC2へのデプロイ（ドメイン・HTTPS）

対象はUbuntu 24.04 LTSのEC2、Docker Compose、1インスタンス構成です。まずはx86_64・メモリ4GB以上を目安にしてください。これは容量の推奨値であり、EC2での負荷実測ではありません。モデルはCPU推論です。

## 1. EC2とDNS

1. EC2にUbuntu 24.04 LTSを用意し、固定の公開IP（Elastic IPなど）を割り当てます。
2. セキュリティグループのインバウンドはTCP 80/443を利用者に公開、TCP 22は管理者のIPに限定します。TCP 8000は開けません。アウトバウンドはHTTPSによるnetkeibaへの取得・証明書取得・依存のダウンロードを許可します。
3. 所有するドメインのAレコード（例: `keiba.example.com`）をEC2の公開IPへ向けます。IPv6を使わないならAAAAレコードを設定しません。
4. SSHでEC2へ接続します。

[AWSのセキュリティグループ説明](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-rules-reference.html)、[Caddyの自動HTTPS要件](https://caddyserver.com/docs/automatic-https)も参照。

## 2. DockerとGit

[Docker公式Ubuntuインストール手順](https://docs.docker.com/engine/install/ubuntu/)に従って、Docker EngineとComposeプラグインをインストールします。

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

Dockerリポジトリを登録:

```sh
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

下記のDocker操作は`sudo docker`で実行します。GitHub URLは自分のリポジトリに置き換えます。privateリポジトリの場合はGitHubのSSHキー等を設定してcloneしてください。

```sh
git clone https://github.com/YOUR_ACCOUNT/keiba-predict-app.git
cd keiba-predict-app
cp .env.example .env
chmod 600 .env
```

## 3. HTTPSとログイン設定

ログインパスワードのハッシュを作ります。パスワードそのものをGitやコマンド引数に記録せず、対話プロンプトに入力してください。

```sh
sudo docker run --rm -it caddy:2-alpine caddy hash-password
```

`.env`を編集してドメイン、証明書の連絡先、ユーザー名、出力されたハッシュを設定します。

```dotenv
APP_DOMAIN=keiba.example.com
ACME_EMAIL=you@example.com
AUTH_USER=admin
AUTH_PASSWORD_HASH='$2a$...生成されたハッシュ全体...'
```

ハッシュは必ず**シングルクォート**で囲みます。Composeのドル記号展開を防ぎます。`.env`はGitとDockerビルド対象から除外しています。[Caddyの認証設定](https://caddyserver.com/docs/caddyfile/directives/basic_auth)ではハッシュを使用します。

## 4. 起動と確認

```sh
sudo docker compose -f compose.yaml -f compose.public.yaml up -d --build
sudo docker compose -f compose.yaml -f compose.public.yaml ps
sudo docker compose -f compose.yaml -f compose.public.yaml logs --tail=100 app caddy
```

DNSと80/443の疎通が正しければCaddyが証明書を取得します。`https://keiba.example.com`を開き、設定したユーザー名・パスワードでログインします。サンプルのrace id `202608040211`で保存済みデータを選び、両AIの結果が表示されることを確認。その後、開催一覧取得・最新データ取得を確認してください。

コンテナ内でテスト:

```sh
sudo docker compose -f compose.yaml -f compose.public.yaml exec app \
  python -m unittest apps.race_predict.test_app tests.test_standalone
```

予測中でもヘルスチェックは応答します。`app`はDocker内で8000番を待ち受け、外部からはCaddy経由でのみアクセスします。

## 更新・停止・バックアップ

```sh
git pull --ff-only
sudo docker compose -f compose.yaml -f compose.public.yaml up -d --build
# 停止（データは保持）
sudo docker compose -f compose.yaml -f compose.public.yaml down
```

取得データ・予測ログ、証明書はnamed volumeに保存します。`down -v`は使わないでください。EBSスナップショット、またはDocker volumeのバックアップを取ります。コンテナ再作成後も入力CSVと保存結果は残りますが、稼働中ジョブの状態は復元しません。

起動時にアセットのSHA256を検証するため、モデルを置換したらエンコーダー・設定と`asset-manifest.json`も同時更新します。モデルと参照CSVは通常のGitで管理できるサイズで、Git LFSを必須にしていません。

## トラブル対応

- 証明書が取れない: DNS A/AAAA、EC2の80/443、他プロセスによるポート利用、Caddyログを確認。
- 403: `.env`のAPP_DOMAINとアクセスURLが一致しているかを確認。公開設定では`https://APP_DOMAIN`のHost/Originだけを許可する。
- Chrome起動失敗: アプリログ・ジョブログ、メモリ、`shm_size`を確認。イメージ内でChromiumとDriverを同時インストールし、Driverの自動ダウンロードに依存しない。
- 取得失敗: `data/webapp/jobs/<ID>/worker.log`を確認。外部サイトのHTMLやEC2のIPに対するアクセス制限はアプリのモデル動作とは別問題。
- 同時実行409: 別ジョブの完了を待つ。現状は1件ずつ実行する構成。

本作業ではEC2作成・DNS変更・証明書の実発行は実施していません。必要な接続先やドメインはデプロイ時に設定します。
