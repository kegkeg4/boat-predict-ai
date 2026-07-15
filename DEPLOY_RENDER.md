# Render 本公開手順

## 推奨構成

本番公開では、無料プランではなく有料インスタンス + 永続ディスクを使います。

- Service: Render Web Service
- Runtime: Python
- Region: Singapore
- Instance Type: Standard
- Persistent Disk: 5GB
- Build Command: `pip install -r requirements.txt`
- Start Command: `python3 server.py`
- Health Check Path: `/api/warmup`

## なぜこの構成にするか

無料インスタンスはアクセスがないとスリープし、初回表示が遅くなります。

また、Renderの通常ファイルシステムは再起動や再デプロイで消えるため、公式データのキャッシュや学習データを残すには永続ディスクが必要です。

このアプリでは、以下を永続ディスクに保存します。

- 公式出走表・結果などのキャッシュ
- 学習データ
- 予測改善用の履歴データ

## Render環境変数

Render Dashboardの Environment で以下を設定します。

| Key | Value |
| --- | --- |
| `PYTHON_VERSION` | `3.11.13` |
| `BOAT_STARTUP_WARMUP` | `0` |
| `BOAT_AUTO_BACKFILL` | `0` |
| `BOAT_RESULT_WARMER` | `0` |
| `BOAT_PAY_WARMER` | `1` |
| `BOAT_PAY_WARM_INTERVAL` | `90` |
| `BOAT_FETCH_TIMEOUT` | `6` |
| `BOAT_PROGRAM_INDEX_TIMEOUT` | `7` |
| `BOAT_ADMIN_BACKFILL_WORKERS` | `1` |
| `BOAT_RESULT_FETCH_WORKERS` | `1` |
| `BOAT_VENUE_FALLBACK_WORKERS` | `2` |
| `BOAT_MAX_HTTP_THREADS` | `32` |
| `BOAT_DATA_DIR` | `/var/data/boat-predict` |
| `ADMIN_PASSWORD` | 管理画面用の任意のパスワード |
| `BOAT_PUBLIC_ORIGIN` | 本番の公開URL（例 `https://www.example.jp`） |

管理画面は `/admin` から開けます。ログインユーザー名は `admin`、パスワードは `ADMIN_PASSWORD` に設定した値です。

## 永続ディスク

Renderの Disks で以下を設定します。

| Name | Mount Path | Size |
| --- | --- | --- |
| `boat-predict-data` | `/var/data` | `5GB` |

`BOAT_DATA_DIR` は `/var/data/boat-predict` にします。

## GitHubへアップロードするファイル

最低限、以下は毎回アップロードします。

- `index.html`
- `app.js`
- `styles.css`
- `server.py`
- `admin.html`
- `admin.js`
- `guide.html`
- `operator.html`
- `terms.html`
- `privacy.html`
- `disclaimer.html`
- `commerce.html`
- `requirements.txt`
- `render.yaml`
- `DEPLOY_RENDER.md`

`.official-cache/` はアップロードしません。Render側の永続ディスクに保存します。

## デプロイ手順

1. GitHubの `kegkeg4/boat-predict-ai` に最新ファイルをアップロードします。
2. Render Dashboardで `boat-predict-ai` を開きます。
3. `Manual Deploy` または GitHub連携の自動デプロイで反映します。
4. `Events` に `Deploy live` が出るまで待ちます。
5. 公開URLを開きます。

公開URL:

`https://boat-predict-ai.onrender.com/`

## 独自ドメインを使う場合

Render Dashboardの `Settings` -> `Custom Domains` からドメインを追加します。

DNS側では、Renderに表示される接続先へ以下のように設定します。

- `www` を使う場合: CNAMEでRenderの指定先へ向ける
- ルートドメインを使う場合: DNSサービス側が対応していれば ALIAS / ANAME を使う

SSLはRender側で自動発行されます。DNS反映には数分から数時間かかることがあります。

接続確認後、Environment の `BOAT_PUBLIC_ORIGIN` を独自ドメインへ変更して再デプロイします。canonical、OG URL、sitemap.xml、robots.txtはこの値を本番URLとして出力します。`https://` を含め、末尾の `/` は付けません。

検索エンジンへ送信する前に、次を確認します。

1. `https://独自ドメイン/guide.html` が200で開く
2. `https://独自ドメイン/sitemap.xml` 内が独自ドメインになっている
3. Google Search Consoleへ独自ドメインを登録し、sitemap.xmlを送信する
4. Renderサブドメイン側のcanonicalも独自ドメインを示している

## 月額費用の目安

Renderの目安:

- Web Service Standard: 約 $25/月
- Persistent Disk 5GB: 約 $1.25/月
- 合計: 約 $26.25/月

アクセスが増えて重くなった場合は、Pro以上やDB分離を検討します。

## 注意

- `render.yaml` を使うと、Render側の設定をコードで管理できます。
- 既存サービスにBlueprintを同期する場合、設定変更が反映されます。
- Regionは作成後に変更できないため、最初から `singapore` 推奨です。
- 永続ディスクを付けたサービスは水平スケールできないため、将来的にユーザー数が増えたらPostgreSQLやRedisへ分離します。
