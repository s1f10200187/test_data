# Glue Workflow ETL ファイルダウンローダー

AWS Glue Workflow をトリガーし、データレイク各層に生成されるファイルをローカル環境へまとめて取得するための Python ツールです。正規表現ベースの柔軟なフィルタリング、ワークフロー実行状態の監視、詳細レポート出力を備えており、ETL パイプライン検証やデバッグに役立ちます。

## 主な特徴

- **Glue Workflow 実行制御**: Workflow の起動、進行状況ポーリング、タイムアウト管理を自動化
- **複数パターンのファイル収集**: 各層ごとに複数の正規表現パターンを指定し一括取得
- **並列ダウンロード**: ThreadPoolExecutor による高速ダウンロードとリトライ制御
- **ローカルファイルの S3 反映**: `local_override_path` を持つ層のファイルをアップロード。必要に応じてアップロード前に S3 側を空にできる
- **フォーマット制約と展開制御**: `file_formats` で拡張子を制限し、`extract_zip_on_download` により Zip の自動展開を制御
- **詳細レポート生成**: テキスト / JSON レポートで実行結果と取得ファイルを一覧化
- **柔軟な設定**: YAML 設定ファイルで AWS 情報・層定義・ダウンロード挙動を管理

## 前提条件

- Python 3.9 以上
- AWS 認証情報 (環境変数、プロファイル、もしくは IAM ロール)
- Glue Workflow および対象 S3 バケットへの必要な権限

## インストール

```powershell
cd c:\Users\TIE309502\Documents\PJ\ルミネ\src\tools_lab\local_ETL_runner
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 設定ファイル

`config.yaml` の例:

```yaml
version: "1.0"
aws:
  region: ap-northeast-1
workflow:
  name: "etl-data-pipeline-workflow"
  execute: true
  validate_before_run: true
  execution_timeout: 3600
  polling_interval: 30
layers:
  - name: source
    display_name: "ソース層"
    s3_bucket: "my-datalake-bronze"
    s3_prefix: "raw/sales/"
    file_patterns:
      - "^sales_\\d{8}\\.csv$"
    file_formats:
      - "csv"
    required: true
    min_files: 1
    download_before_execution: true  # Workflow 実行前に取得したい層では true を指定
    local_override_path: "./local_overrides/source"  # 指定するとアップロード対象になる
    clear_destination_before_upload: true  # アップロード前に S3 側を空にする
  - name: final
    display_name: "最終層"
    s3_bucket: "my-datalake-gold"
    s3_prefix: "analytics/sales/"
    file_patterns:
      - "^sales_final_\\d{8}\\.(csv|parquet)$"
    file_formats:
      - "zip"
    extract_zip_on_download: true
download:
  local_base_dir: "./downloads"
  preserve_structure: true
  overwrite: false
  max_workers: 5
logging:
  level: INFO
  console: true
```

## 使い方

### CLI から実行

```powershell
python -m glue_workflow_downloader \
    --config config.yaml \
    --workflow etl-data-pipeline-workflow
```

主なオプション:
必須:
- `--config`: YAML 設定ファイルのパス
- `--workflow`: Glue Workflow 名

任意:
- `--no-execute`: Workflow を実行せず既存ファイルのみ取得
- `--dry-run`: ダウンロードを実施せず対象ファイル一覧を確認
- `--execution-timeout`: Workflow のタイムアウト秒数を上書き
- `--max-workers`: 並列ダウンロード数を変更
- `--overwrite`: 同名ファイルを上書き
- `--skip-validation`: Workflow 存在チェックや初期レイヤー確認をスキップ
- `--wait`: Config で `wait_for_completion: false` の場合でも完了まで待機
- `--polling-interval`: Workflow ステータスのポーリング間隔を上書き

### ライブラリとして使用

```python
from glue_workflow_downloader import GlueWorkflowDownloader

downloader = GlueWorkflowDownloader("config.yaml")
result = downloader.run("etl-data-pipeline-workflow")
print(result.successful, result.failed)
```

## 出力

- `downloads/layers/<layer_name>/` 以下に各層のファイルを保存
- `downloads/report_YYYYMMDD_HHMMSS.txt` / `.json` に実行サマリーを出力

## ログ

デフォルト設定ではコンソールに INFO レベルでログが出力されます。`logging.file` を設定するとファイル出力に切り替えられます。

## ローカルオーバーライドの補足

- `local_override_path` を指定した層では、ディレクトリ配下のファイルを S3 の `s3_prefix` 配下へアップロードしてからダウンロード処理を実施します。
- `clear_destination_before_upload: true` を併用すると、アップロード前に該当プレフィックス配下の既存オブジェクトを削除してクリーンな状態で差し替えられます。
- ファイル名は層の `file_patterns` にマッチしたものだけが対象となります。

## ファイル形式オプションの補足

- `file_formats` に拡張子 (例: `csv`, `xml`, `zip`) を列挙すると、その層で処理対象とするファイル形式を制限できます。
- `extract_zip_on_download: true` を指定した層では、Zip 形式をダウンロード後に自動で `<ファイル名 without .zip>/` ディレクトリへ展開します (Zip ファイル自体は保持されます)。
- フォーマット制限と Zip 展開はローカルオーバーライドのアップロード処理にも適用されます。

## テスト

ユニットテストの実行:

```powershell
pytest
```

## ライセンス

社内利用を想定しているため、必要に応じてリポジトリポリシーに従ってください。
