# 2026-10-04 独立予測アプリとEC2公開構成

## 対象と実行条件

元の`keiba-predict`から予測専用の`keiba-predict-app`へ分離。約21.2MB（仮想環境・Git・実行ログを除いた初回エクスポート実測）のアプリ資産をまとめた。

同梱モデルはLightGBM分類`models/v8/model_jsp_23.pkl`と着順回帰`models/v8_regression/model_rank_23.pkl`、それぞれの`label_encoders_23.pkl`。購入設定は`v8_classification_auto.json`と`v8_regression_softmax.json`。血統系統、騎手、厩舎の参照CSVと、2026-10-04京都11Rの小さな入力例を同梱。`asset-manifest.json`の10ファイルを起動時SHA256検証する。

予測処理・購入ロジックは元と同じ。`predict.py`の引数検証だけ学習・シミュレーションモジュールから独立させた。取得ブラウザを共通化し、DockerではDebianのChromium/Driverを明示。外部HTTP取得に30秒のタイムアウトを付けた。

Python3.11、LightGBM4.6.0、scikit-learn1.8.0、pandas2.3.3、numpy2.3.5。直接依存9件、固定した間接依存を含め34パッケージ。Torch/学習モジュール・学習CSVは不要。設定の`test_data`は元の評価データの来歴で、実行では読まない。

## 実測した検証

- 新しい専用`.venv`に依存をインストールし、元リポジトリをPython importパスに入れず11テスト成功。
- 最終Dockerイメージ（Linux/amd64、Python3.11、非rootユーザー）で11テスト成功。同梱実モデル・入力例の各5頭の購入スコア（rtol=1e-12）・購入対象・購入額が元CLI保存結果に一致。
- 公開HTTPS Origin、異なるOrigin、公開ドメインに対するローカルOrigin、Dockerのローカルポート変換とhealthzを確認。
- HTTP経由で非同期子プロセス予測を実行し、両AI各5頭を取得。分類は見送り、回帰は馬番3・単勝600円。サンプルオッズによる結果であり将来の成績ではない。
- Linuxコンテナ内のChromiumで2026-10-04のnetkeiba開催一覧を実取得。東京・京都24レース。
- 最終LinuxコンテナのHTTP APIで最新データ取得→両AI予測まで成功（2026-10-04 09:38:44 JST）。京都11R `202608040211`、18頭・307列。入力`data/webapp/inputs/0cbf823abe664dae81a756158b97c821/20261004/京都_11.csv`、全ログと結果`data/webapp/jobs/779ed5c8211e4b30b5b73047b90ecabb/`。分類は見送り、回帰は馬番3・単勝600円。この取得時点のオッズは6.6倍で、先のサンプル6.5倍とは別スナップショット。
- `.gitattributes`と`git hash-object`のフィルタ有無を検証し、チェックサム対象10件がGitの改行変換で変わらないことを確認。
- Compose local/public設定とCaddyのHTTPS・Basic認証設定が`caddy validate`で有効。テスト用のハッシュとexample.comのドメインを使い、実公開はしていない。

## 再実行

`python -m unittest apps.race_predict.test_app tests.test_standalone`。

ローカル: `docker compose -f compose.yaml -f compose.local.yaml up -d --build`。

公開: `docs/ec2-deployment.md`に従いDNS・`.env`を設定し、`docker compose -f compose.yaml -f compose.public.yaml up -d --build`。CaddyがHTTPSとBasic認証を担当し、アプリ8000番は外部に公開しない。取得データ・証明書はnamed volumeに永続化。

## 制約・未実施

実EC2上の起動・負荷測定・DNS変更・証明書発行・GitHub pushは未実施。4GB以上というEC2メモリ目安は実測容量保証ではない。Gitリポジトリはmainで初期化し、remote設定・commitは利用者が行う。

単一インスタンス・1ジョブずつ。再起動後の実行中ジョブ照会復元、複数ユーザー向けのキューや権限管理は未実装。netkeibaのHTML変更やEC2のIPに対するアクセス制限は外部依存。新馬・障害スキップ、天候/馬場未取得時の既定値は元の処理を継承する。

モデル・設定・参照CSVの更新は対にして行い、`python tools/update_asset_manifest.py`でチェックサムを更新して実モデルテストを実行する。取得結果・ログ・秘密設定・仮想環境はGit対象から除外する。
