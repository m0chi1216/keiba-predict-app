# EC2へのデプロイ（ドメイン・HTTPS）

対象はUbuntu 24.04 LTSのEC2、Docker Compose、1インスタンス構成です。まずはx86_64・メモリ4GB以上を目安にしてください。これは容量の推奨値であり、EC2での負荷実測ではありません。モデルはCPU推論です。

自分のPCからだけ利用する場合は、下記の「SSHトンネルで接続する場合」を使えます。独自ドメイン、DNS設定、HTTPS証明書は不要です。

## SSHトンネルで接続する場合

### 1. EC2を準備する

UbuntuのEC2を用意し、セキュリティグループではTCP 22を自分のPCの公開IPからのみ許可します。この方法ではTCP 80/443/8000のインバウンド許可は不要です。EC2のPublic IPv4 DNSまたは公開IPv4アドレスをSSH接続先として使います。

下記の「2. DockerとGit」に従ってDockerのインストールとリポジトリのcloneを行います。独自ドメインの取得、Aレコード設定、および「3. HTTPSとログイン設定」は省略します。

### 2. EC2上でアプリを起動する

EC2上のリポジトリのディレクトリで、`.env` の `APP_ORIGIN` を未設定または空（`APP_ORIGIN=`）にします。`APP_DOMAIN`、`ACME_EMAIL`、認証情報はこの構成では使いません。

すでに公開用構成を起動している場合は、同じディレクトリ・同じComposeプロジェクト名で、ローカル用構成を使って先に停止します。`--remove-orphans` は、この構成に含まれない同じプロジェクトのCaddyコンテナも削除します。データと証明書のvolumeを保持するため `-v` は付けません。まだ何も起動していない場合、この停止操作は不要です。

```sh
sudo docker compose -f compose.yaml -f compose.local.yaml down --remove-orphans
```

公開用構成は `down` 時にも `APP_DOMAIN`、`ACME_EMAIL` の必須変数を検査するため、未設定のまま `compose.public.yaml` を指定すると停止前にエラーになります。旧版では `AUTH_PASSWORD_HASH` も必須でした。SSHトンネル用の操作には `compose.local.yaml` を指定してください。以前の起動で `-p` によるプロジェクト名を指定していた場合は、停止時にも同じ `-p` を指定します。

既存の `compose.local.yaml` を使って、EC2のループバックアドレスだけに8000番を公開します。

```sh
sudo docker compose -f compose.yaml -f compose.local.yaml up -d --build
sudo docker compose -f compose.yaml -f compose.local.yaml ps
curl -fsS http://127.0.0.1:8000/healthz
```

ヘルスチェックの期待値は `{"status": "ok"}` です。起動直後に失敗する場合は少し待ち、コンテナ状態とログを確認します。

### 3. 自分のPCからトンネルを開く

自分のPCのターミナル（WindowsならPowerShell）で実行します。鍵ファイルとEC2の公開DNS名を実際の値へ置き換えてください。Ubuntu AMIの標準ユーザー名は `ubuntu` です。

```powershell
ssh -i "C:\path\to\your-key.pem" -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8000:127.0.0.1:8000 ubuntu@ec2-xxx.compute.amazonaws.com
```

初回のSSH接続ではサーバーのホスト鍵を確認します。`-N` によりリモートのシェルは開かず、接続中は通常何も表示されません。このターミナルを開いたまま、**自分のPCのブラウザで `http://127.0.0.1:8000`** を開きます。EC2の公開DNS名はSSH接続先にだけ使います。

PC側の8000番が使用中なら、`-L 127.0.0.1:18000:127.0.0.1:8000` に変更し、ブラウザでは `http://127.0.0.1:18000` を開きます。

ブラウザからPC内のトンネル入口まではHTTPですが、PCとEC2間の通信はSSHで暗号化されます。この構成ではCaddyのログイン画面はなく、SSH鍵による接続が入口になります。トンネルは `Ctrl+C` で閉じられます。EC2上のアプリはその後も稼働します。

更新・停止にも同じComposeファイルの組を使います。

```sh
git pull --ff-only
sudo docker compose -f compose.yaml -f compose.local.yaml up -d --build
# アプリ停止（データは保持）
sudo docker compose -f compose.yaml -f compose.local.yaml down
```

EC2への実接続による検証は未実施です。

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

ログイン認証は標準で有効です。認証を使う場合はログインパスワードのハッシュを作ります。パスワードそのものをGitやコマンド引数に記録せず、対話プロンプトに入力してください。認証を無効にする場合はハッシュ生成を省略できます。

```sh
sudo docker run --rm -it caddy:2-alpine caddy hash-password
```

`.env`を編集してドメイン、証明書の連絡先、ユーザー名、出力されたハッシュを設定します。

```dotenv
APP_DOMAIN=keiba.example.com
ACME_EMAIL=you@example.com
AUTH_ENABLED=true
AUTH_USER=admin
AUTH_PASSWORD_HASH='$2a$...生成されたハッシュ全体...'
```

ハッシュは必ず**シングルクォート**で囲みます。Composeのドル記号展開を防ぎます。`.env`はGitとDockerビルド対象から除外しています。[Caddyの認証設定](https://caddyserver.com/docs/caddyfile/directives/basic_auth)ではハッシュを使用します。

ログインを無効にする場合は `.env` に次を設定します。`AUTH_USER` と `AUTH_PASSWORD_HASH` は省略または空にできます。HTTPSとアプリのHost/Origin制限は維持しますが、URLにアクセスできる人は予測・データ取得を実行できます。

```dotenv
AUTH_ENABLED=false
```

`AUTH_ENABLED` は `true` または `false` を指定します。未指定・空の場合は `true` です。認証有効時にハッシュが未設定、または値が不正な場合、Caddyは設定エラーで起動しません。

設定変更後は次のコマンドでCaddyを再作成します。`.env` の変更は `restart` だけでは反映されません。認証を再び有効にするには `AUTH_ENABLED=true` とユーザー名・ハッシュを設定して同じコマンドを実行します。

```sh
sudo docker compose -f compose.yaml -f compose.public.yaml up -d --force-recreate caddy
sudo docker compose -f compose.yaml -f compose.public.yaml logs --tail=100 caddy
```

## 4. 起動と確認

```sh
sudo docker compose -f compose.yaml -f compose.public.yaml up -d --build
sudo docker compose -f compose.yaml -f compose.public.yaml ps
sudo docker compose -f compose.yaml -f compose.public.yaml logs --tail=100 app caddy
```

DNSと80/443の疎通が正しければCaddyが証明書を取得します。`https://keiba.example.com`を開き、認証が有効なら設定したユーザー名・パスワードでログインします。無効ならそのままアプリが表示されます。サンプルのrace id `202608040211`で保存済みデータを選び、両AIの結果が表示されることを確認。その後、開催一覧取得・最新データ取得を確認してください。

コンテナ内でテスト:

```sh
sudo docker compose -f compose.yaml -f compose.public.yaml exec app \
  python -m unittest apps.race_predict.test_app tests.test_standalone
```

予測中でもヘルスチェックは応答します。`app`はDocker内で8000番を待ち受け、外部からはCaddy経由でのみアクセスします。

データ取得・予測はサーバー側のジョブとして実行するため、開始が受け付けられた後はページを閉じても継続します。ページを開き直すと、このアプリで最後に開始したジョブの進捗・結果を復元します。単一の共有ワークスペースであり、利用者ごとの履歴ではありません。サーバー再起動・コンテナ再作成をまたぐジョブ復元には対応していません。

結果表示は勝率上位5頭（回帰は予測着順上位5頭）から、有限の単勝オッズが1倍を超え、各AIのオッズ上限以下である馬だけを購入スコア順に表示します。該当馬が少なければ5頭未満になります。6位以下からの補充は行わず、モデルスコア・購入判定は従来の設定を維持します。

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
