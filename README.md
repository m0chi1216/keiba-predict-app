# 競馬予想Webアプリ

このリポジトリだけで起動できる予測専用アプリです。Pythonコード、2種類のLightGBMモデルとLabelEncoder、購入条件JSON、血統・騎手・厩舎の参照CSVを同梱しています。元の学習リポジトリやGPU/Torchは不要です。

- race idの入力、またはnetkeibaの開催日・競馬場・レース選択
- 回収率重視AI（v8_classification_auto）/ 的中率重視AI（v8_regression_softmax）/ 両方
- 勝率上位5頭（回帰は予測着順上位5頭）のうちオッズ条件を満たす馬を購入スコア順に表示
- 購入対象、条件適合、見送り理由、購入額の表示
- ページを閉じてもデータ取得・予測を継続し、開き直すと最新ジョブの進捗・結果を復元（サーバー稼働中）

## ローカル起動

Docker Engine / Docker DesktopとComposeプラグインがある場合:

```sh
docker compose -f compose.yaml -f compose.local.yaml up -d --build
```

http://127.0.0.1:8000 を開きます。DockerにはPython、Chromium、対応するDriverを含めています。OSに別のブラウザを入れる必要はありません。

Dockerを使わない場合はPython 3.11、Chrome/Chromiumを準備します。

```sh
python -m venv .venv
# Linux/macOS
.venv/bin/pip install -r requirements.lock
.venv/bin/python -m apps.race_predict.server
# Windowsの場合
# .venv\Scripts\pip.exe install -r requirements.lock
# .venv\Scripts\python.exe -m apps.race_predict.server
```

ソース起動時、DriverはSeleniumの自動取得か`SE_CHROMEDRIVER`で指定。`CHROME_BINARY`でブラウザ実行ファイルを指定できます。

## EC2でドメイン・HTTPS公開

[EC2デプロイ手順](docs/ec2-deployment.md)に従って、DNSと`.env`を設定します。

```sh
docker compose -f compose.yaml -f compose.public.yaml up -d --build
```

CaddyがHTTPS証明書を取得・更新し、標準でログイン認証を行います。`.env` の `AUTH_ENABLED=false` でログインを無効にできます。その場合、URLにアクセスできる人がアプリを利用できます。アプリの8000番ポートは外部公開しません。モデルはイメージに含まれ、取得データはDocker volumeに永続化します。

## モデルとデータ

| AI | モデル | 設定 |
|---|---|---|
| 回収率重視 | models/v8/model_jsp_23.pkl | configs/strategies/v8_classification_auto.json |
| 的中率重視 | models/v8_regression/model_rank_23.pkl | configs/strategies/v8_regression_softmax.json |

各モデルの隣に`label_encoders_23.pkl`が必要です。参照CSVは`data/ped_data/`・`data/jockey_data/`・`data/stable_data/`。実行に必要な10ファイルのチェックサムを`asset-manifest.json`に記録し、起動時に検証します。

小さな実レース入力`data/predict/20261004/京都_11.csv`を同梱しています。race id `202608040211`で「保存済みの予測用データを利用」を選ぶと、外部サイト取得なしで両モデルの動作を確認できます。オッズはサンプル取得時点の値です。

取得した入力は`data/webapp/inputs/`、結果とログは`data/webapp/jobs/`に保存します。これらはGitに含めません。取得単位で保存し、過去のオッズを保持します。モデル更新時はモデル・エンコーダー・設定を揃えて変更し、`asset-manifest.json`のチェックサムも更新してください。

チェックサム更新は`python tools/update_asset_manifest.py`。設定JSONの`test_data`は元の条件探索データの来歴で、予測実行では参照しません。学習・評価用の大きなCSVは同梱していません。

チェックサム対象のCSV・設定JSONは`.gitattributes`でGitの改行変換を無効にしています。WindowsでpushしてLinuxでcloneしても同じバイト列を保持します。

購入候補は回収率設定で上位5頭、的中率設定で上位1頭です。画面はモデル順位上位5頭から、1倍を超え各AIのオッズ上限以下の馬だけを表示します。5頭未満でも下位から補充しません。表示数と購入候補数は別です。回帰のrankスコアはsoftmax値で、校正済み勝率ではありません。条件適合馬の中で購入スコア最大1頭を購入対象とします。

## 検証

```sh
python -m unittest apps.race_predict.test_app tests.test_standalone
```

同梱した実モデルの表示対象馬のスコア・購入対象・購入額が元CLIと一致すること、オッズ条件、背景ジョブと再照会、開催一覧解析、公開ドメインのOriginとヘルスチェックをテストします。GitHub ActionsでもテストとDockerビルドを実行します。

Chromeと対応Driverがある環境では `python -m tools.verify_webapp_ui` で、ページ離脱中の実モデル予測と再表示時の復元を確認できます。保存データを使い、外部レースサイトにはアクセスしません。

Pythonの直接依存は`requirements.txt`、間接依存も固定した実行用ファイルは`requirements.lock`。更新時は`uv pip compile requirements.txt --output-file requirements.lock`で再生成し、同梱モデルのテストを実行してください。

モデル・設定・参照データの来歴、検証結果と制約は[作業記録](.agents/docs/README.md)を参照。

## 運用上の仕様

1インスタンス・同時予測1件を想定しています。取得は数分かかることがあり、進捗ログを表示します。新馬・障害スキップ、天候・馬場未取得時の既定値は元の取得処理を引き継ぎます。外部サイトのHTML変更やEC2からのアクセス制限は別途対応が必要です。サーバー再起動後のジョブ照会復元は未対応です。自動購入は行いません。

## GitHubへのpush

mainブランチでGit初期化済みです。GitHubで空のリポジトリを作成し、このディレクトリで実行します。

```sh
git add .
git commit -m "Initial standalone prediction app"
git remote add origin https://github.com/YOUR_ACCOUNT/keiba-predict-app.git
git push -u origin main
```

モデルは1ファイル約8MB以下のため通常のGitで管理できます。`.env`・仮想環境・実行時取得データは除外しています。
