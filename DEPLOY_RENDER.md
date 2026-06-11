# Render 公開テスト手順

## 1. GitHubへアップ

このフォルダをGitHubリポジトリにアップします。

`.official-cache/` はGitHubへ含めません。Render側で必要な公式データを再取得します。

## 2. RenderでWeb Service作成

Render Dashboardで:

- New
- Web Service
- GitHubリポジトリを選択

設定値:

- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `python3 server.py`
- Instance Type: Free でテスト可

環境変数:

- `PYTHON_VERSION`: `3.11.9`
- `BOAT_STARTUP_WARMUP`: `1`

`render.yaml` からBlueprintとして作成してもOKです。

## 3. 公開URL確認

デプロイ完了後、RenderのURLを開きます。

例:

`https://boat-predict-ai.onrender.com/`

## 注意

- Render Freeはアクセスがないとスリープすることがあります。
- 起動直後は当日データの先読みが走るため、初回だけ少し遅くなります。
- 公式サイト取得に失敗した場合は、時間を置いて再読み込みしてください。
- 本格運用では有料インスタンスかVPSの方が安定します。
