# アラートメール自動起票システム 詳細設計書

## 文書情報

| 項目 | 内容 |
|------|------|
| 文書名 | アラートメール自動起票システム 詳細設計書 |
| バージョン | 1.0 |
| 作成日 | 2025-11-11 |
| ステータス | 初版 |

---

## 目次

1. [システム概要](#1-システム概要)
2. [システム構成](#2-システム構成)
3. [機能詳細設計](#3-機能詳細設計)
4. [データ設計](#4-データ設計)
5. [インターフェース設計](#5-インターフェース設計)
6. [処理フロー設計](#6-処理フロー設計)
7. [エラーハンドリング設計](#7-エラーハンドリング設計)
8. [セキュリティ設計](#8-セキュリティ設計)
9. [性能設計](#9-性能設計)
10. [運用設計](#10-運用設計)
11. [テスト設計](#11-テスト設計)
12. [付録](#12-付録)

---

## 1. システム概要

### 1.1 目的

監視システムから送信されるアラートメールを自動的に受信し、特定の条件（ブラックリスト）に該当しないメールのみをRedmineチケットとして自動起票することで、障害対応業務の効率化と対応漏れの防止を実現する。

### 1.2 システムの位置づけ

```
┌─────────────────┐
│  監視システム    │
│ (Zabbix/Nagios) │
└────────┬────────┘
         │ メール送信
         ↓
┌─────────────────┐
│  メールサーバー  │
│   (IMAP/SMTP)   │
└────────┬────────┘
         │ メール受信
         ↓
┌─────────────────────────┐
│ アラートメール自動起票   │ ← 本システム
│      システム           │
└────────┬────────────────┘
         │ REST API
         ↓
┌─────────────────┐
│    Redmine      │
│ (チケット管理)   │
└─────────────────┘
         │
         ↓
┌─────────────────┐
│   運用担当者     │
└─────────────────┘
```

### 1.3 システム方針

- **ブラックボックス方式**: 除外対象を定義し、それ以外はすべて起票
- **自動実行**: バッチ処理による定期実行
- **冪等性**: 同一メールの重複起票を防止
- **監査性**: すべての処理履歴をログに記録

### 1.4 前提条件

- メールサーバーへのIMAP/POP3アクセスが可能
- Redmine REST APIが有効化されている
- Python 3.8以上の実行環境
- インターネット接続が可能（メールサーバー、Redmineサーバーへのアクセス用）

### 1.5 制約事項

- メールの処理は受信順で行う
- 1メールにつき1チケットを起票（複数チケットへの分割は行わない）
- HTML形式のメールはテキスト変換して処理
- 添付ファイルは現バージョンでは未対応

---

## 2. システム構成

### 2.1 システムアーキテクチャ

```
┌────────────────────────────────────────────────────┐
│         アラートメール自動起票システム              │
│                                                    │
│  ┌──────────────┐    ┌──────────────┐           │
│  │  メール監視   │───→│  フィルター   │           │
│  │   モジュール  │    │   モジュール  │           │
│  └──────────────┘    └──────┬───────┘           │
│                              │                    │
│  ┌──────────────┐            │                    │
│  │   ログ管理    │←───────────┤                    │
│  │   モジュール  │            │                    │
│  └──────────────┘            ↓                    │
│                     ┌──────────────┐              │
│                     │  データ抽出   │              │
│                     │   モジュール  │              │
│                     └──────┬───────┘              │
│                            │                      │
│                            ↓                      │
│                     ┌──────────────┐              │
│                     │  Redmine連携  │              │
│                     │   モジュール  │              │
│                     └──────────────┘              │
│                                                    │
└────────────────────────────────────────────────────┘
         │                              │
         ↓                              ↓
  ┌──────────┐                   ┌──────────┐
  │メールサーバー│                   │ Redmine  │
  └──────────┘                   └──────────┘
```

### 2.2 ディレクトリ構成

```
alert-mail-redmine/
├── config/
│   ├── config.yaml              # メイン設定ファイル
│   ├── blacklist.yaml           # ブラックリスト設定
│   └── redmine_mapping.yaml     # Redmineマッピング設定
├── src/
│   ├── main.py                  # メインエントリーポイント
│   ├── mail_monitor.py          # メール監視モジュール
│   ├── blacklist_filter.py      # フィルターモジュール
│   ├── mail_parser.py           # メール解析モジュール
│   ├── redmine_client.py        # Redmine APIクライアント
│   ├── duplicate_checker.py     # 重複チェックモジュール
│   └── logger.py                # ログ管理モジュール
├── data/
│   ├── processed_mails.db       # 処理済みメールDB (SQLite)
│   └── cache/                   # キャッシュディレクトリ
├── logs/
│   ├── application.log          # アプリケーションログ
│   ├── error.log                # エラーログ
│   └── ticket_created.log       # 起票履歴ログ
├── tests/
│   ├── test_mail_monitor.py
│   ├── test_blacklist_filter.py
│   └── test_redmine_client.py
├── requirements.txt             # 依存パッケージ
├── .env.example                 # 環境変数テンプレート
└── README.md                    # システム説明書
```

### 2.3 技術スタック

| レイヤー | 技術 | 用途 |
|---------|------|------|
| 言語 | Python 3.8+ | メイン実装言語 |
| メール処理 | imaplib, email | メール受信・解析 |
| HTTP通信 | requests | Redmine API連携 |
| 設定管理 | PyYAML | YAML設定ファイル読み込み |
| データベース | SQLite3 | 処理履歴管理 |
| ログ管理 | logging | ログ出力 |
| スケジューリング | APScheduler | 定期実行 |
| テスト | pytest | ユニットテスト |

---

## 3. 機能詳細設計

### 3.1 メール監視機能

#### 3.1.1 機能概要
メールサーバーに接続し、未読メールまたは未処理メールを取得する。

#### 3.1.2 処理仕様

**入力**
- メールサーバー接続情報（設定ファイルから取得）
- チェック対象フォルダ（デフォルト: INBOX）

**処理内容**
1. メールサーバーへIMAP接続
2. 指定フォルダの未読メールを検索
3. メールのヘッダー情報と本文を取得
4. メールオブジェクトとして返却

**出力**
- メールオブジェクトのリスト

#### 3.1.3 クラス設計

```python
class MailMonitor:
    """メール監視クラス"""
    
    def __init__(self, config: dict):
        """
        初期化
        Args:
            config: メールサーバー設定
        """
        self.server = config['server']
        self.port = config['port']
        self.username = config['username']
        self.password = config['password']
        self.folder = config.get('folder', 'INBOX')
        self.connection = None
    
    def connect(self) -> bool:
        """
        メールサーバーへ接続
        Returns:
            接続成功時True
        """
        pass
    
    def disconnect(self) -> None:
        """メールサーバーから切断"""
        pass
    
    def fetch_unread_mails(self) -> List[Mail]:
        """
        未読メールを取得
        Returns:
            メールオブジェクトのリスト
        """
        pass
    
    def mark_as_read(self, mail_id: str) -> bool:
        """
        メールを既読にする
        Args:
            mail_id: メールID
        Returns:
            成功時True
        """
        pass
    
    def move_to_folder(self, mail_id: str, folder: str) -> bool:
        """
        メールを指定フォルダに移動
        Args:
            mail_id: メールID
            folder: 移動先フォルダ名
        Returns:
            成功時True
        """
        pass
```

#### 3.1.4 メールオブジェクト定義

```python
@dataclass
class Mail:
    """メールデータクラス"""
    mail_id: str              # メールID
    from_address: str         # 送信元アドレス
    to_address: str           # 宛先アドレス
    subject: str              # 件名
    body: str                 # 本文（プレーンテキスト）
    html_body: str            # 本文（HTML）
    received_date: datetime   # 受信日時
    headers: dict             # ヘッダー情報
    attachments: List[dict]   # 添付ファイル情報（将来対応）
```

### 3.2 ブラックリストフィルター機能

#### 3.2.1 機能概要
受信メールがブラックリストの除外条件に該当するかを判定する。

#### 3.2.2 フィルタリングルール

| ルール種別 | 判定方法 | 優先度 |
|-----------|---------|-------|
| 送信元アドレス | 完全一致 | 高 |
| 件名パターン | 正規表現マッチ | 高 |
| 本文キーワード | 部分一致 | 中 |
| 組み合わせ条件 | 複数条件のAND | 高 |

#### 3.2.3 クラス設計

```python
class BlacklistFilter:
    """ブラックリストフィルタークラス"""
    
    def __init__(self, config: dict):
        """
        初期化
        Args:
            config: ブラックリスト設定
        """
        self.exclude_from_addresses = config.get('exclude_from_addresses', [])
        self.exclude_subject_patterns = config.get('exclude_subject_patterns', [])
        self.exclude_body_keywords = config.get('exclude_body_keywords', [])
        self.exclude_combinations = config.get('exclude_combinations', [])
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """正規表現パターンをコンパイル"""
        pass
    
    def is_blacklisted(self, mail: Mail) -> Tuple[bool, str]:
        """
        ブラックリスト判定
        Args:
            mail: メールオブジェクト
        Returns:
            (除外対象か, 除外理由)
        """
        pass
    
    def check_from_address(self, mail: Mail) -> Tuple[bool, str]:
        """送信元アドレスチェック"""
        pass
    
    def check_subject_pattern(self, mail: Mail) -> Tuple[bool, str]:
        """件名パターンチェック"""
        pass
    
    def check_body_keywords(self, mail: Mail) -> Tuple[bool, str]:
        """本文キーワードチェック"""
        pass
    
    def check_combinations(self, mail: Mail) -> Tuple[bool, str]:
        """組み合わせ条件チェック"""
        pass
```

#### 3.2.4 判定フローチャート

```
開始
 ↓
送信元アドレスチェック
 ├─ 該当 → 除外 (終了)
 └─ 非該当
    ↓
件名パターンチェック
 ├─ 該当 → 除外 (終了)
 └─ 非該当
    ↓
本文キーワードチェック
 ├─ 該当 → 除外 (終了)
 └─ 非該当
    ↓
組み合わせ条件チェック
 ├─ 該当 → 除外 (終了)
 └─ 非該当
    ↓
起票対象 (終了)
```

### 3.3 重複チェック機能

#### 3.3.1 機能概要
過去に処理したメールと同一内容のメールを検出し、重複起票を防止する。

#### 3.3.2 重複判定ロジック

**判定基準**
- 件名の完全一致
- 送信元アドレスの一致
- 指定時間窓内（デフォルト30分）の受信

**判定式**
```
重複 = (件名が一致) AND (送信元が一致) AND (受信時刻差 < 時間窓)
```

#### 3.3.3 クラス設計

```python
class DuplicateChecker:
    """重複チェッククラス"""
    
    def __init__(self, db_path: str, time_window: int = 1800):
        """
        初期化
        Args:
            db_path: SQLiteデータベースパス
            time_window: 重複判定時間窓（秒）
        """
        self.db_path = db_path
        self.time_window = time_window
        self._init_database()
    
    def _init_database(self) -> None:
        """データベース初期化"""
        pass
    
    def is_duplicate(self, mail: Mail) -> Tuple[bool, Optional[str]]:
        """
        重複判定
        Args:
            mail: メールオブジェクト
        Returns:
            (重複か, 既存のチケット番号)
        """
        pass
    
    def register_mail(self, mail: Mail, ticket_id: str) -> bool:
        """
        処理済みメールを登録
        Args:
            mail: メールオブジェクト
            ticket_id: 起票したチケット番号
        Returns:
            登録成功時True
        """
        pass
    
    def cleanup_old_records(self, days: int = 30) -> int:
        """
        古いレコードを削除
        Args:
            days: 保持日数
        Returns:
            削除件数
        """
        pass
```

#### 3.3.4 データベーススキーマ

```sql
CREATE TABLE processed_mails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mail_id TEXT NOT NULL,
    from_address TEXT NOT NULL,
    subject TEXT NOT NULL,
    subject_hash TEXT NOT NULL,
    received_date TIMESTAMP NOT NULL,
    processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ticket_id TEXT,
    status TEXT DEFAULT 'processed',
    INDEX idx_subject_hash (subject_hash),
    INDEX idx_received_date (received_date)
);
```

### 3.4 メール解析機能

#### 3.4.1 機能概要
メール本文から重要情報を抽出し、構造化データに変換する。

#### 3.4.2 抽出対象情報

| 項目 | 抽出方法 | 用途 |
|-----|---------|-----|
| アラートレベル | 正規表現 | チケット優先度決定 |
| サーバー名 | パターンマッチ | チケットタイトル・説明 |
| エラーコード | 正規表現 | チケット説明 |
| IPアドレス | 正規表現 | チケットカスタムフィールド |
| タイムスタンプ | 日時解析 | チケット説明 |

#### 3.4.3 クラス設計

```python
class MailParser:
    """メール解析クラス"""
    
    def __init__(self, config: dict):
        """
        初期化
        Args:
            config: 解析設定
        """
        self.patterns = config.get('patterns', {})
        self._compile_patterns()
    
    def parse(self, mail: Mail) -> ParsedData:
        """
        メールを解析
        Args:
            mail: メールオブジェクト
        Returns:
            解析済みデータ
        """
        pass
    
    def extract_alert_level(self, text: str) -> str:
        """アラートレベルを抽出"""
        pass
    
    def extract_server_name(self, text: str) -> Optional[str]:
        """サーバー名を抽出"""
        pass
    
    def extract_error_code(self, text: str) -> Optional[str]:
        """エラーコードを抽出"""
        pass
    
    def extract_ip_address(self, text: str) -> List[str]:
        """IPアドレスを抽出"""
        pass
    
    def convert_html_to_text(self, html: str) -> str:
        """HTMLをプレーンテキストに変換"""
        pass
```

#### 3.4.4 解析データ定義

```python
@dataclass
class ParsedData:
    """解析済みデータクラス"""
    alert_level: str                    # CRITICAL, WARNING, INFO等
    server_name: Optional[str]          # サーバー名
    error_code: Optional[str]           # エラーコード
    ip_addresses: List[str]             # IPアドレスリスト
    timestamps: List[datetime]          # タイムスタンプリスト
    raw_subject: str                    # 元の件名
    raw_body: str                       # 元の本文
    extracted_summary: str              # 抽出したサマリー
    custom_fields: dict                 # カスタムフィールド用データ
```

### 3.5 Redmine連携機能

#### 3.5.1 機能概要
Redmine REST APIを使用してチケットを起票する。

#### 3.5.2 API仕様

**エンドポイント**
```
POST /issues.json
```

**リクエストヘッダー**
```
Content-Type: application/json
X-Redmine-API-Key: {api_key}
```

**リクエストボディ例**
```json
{
  "issue": {
    "project_id": 1,
    "tracker_id": 1,
    "subject": "[CRITICAL] DB接続エラー - server01",
    "description": "メール本文の内容...",
    "priority_id": 5,
    "assigned_to_id": 10,
    "custom_fields": [
      {
        "id": 1,
        "value": "192.168.1.100"
      }
    ]
  }
}
```

#### 3.5.3 クラス設計

```python
class RedmineClient:
    """Redmine APIクライアントクラス"""
    
    def __init__(self, config: dict):
        """
        初期化
        Args:
            config: Redmine接続設定
        """
        self.base_url = config['url']
        self.api_key = config['api_key']
        self.default_project_id = config['default_project_id']
        self.default_tracker_id = config['default_tracker_id']
        self.timeout = config.get('timeout', 30)
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """HTTPセッションを作成"""
        pass
    
    def create_issue(self, parsed_data: ParsedData, mail: Mail) -> str:
        """
        チケットを起票
        Args:
            parsed_data: 解析済みデータ
            mail: メールオブジェクト
        Returns:
            作成されたチケットID
        """
        pass
    
    def _build_issue_payload(self, parsed_data: ParsedData, mail: Mail) -> dict:
        """チケット作成用ペイロードを構築"""
        pass
    
    def _determine_priority(self, alert_level: str) -> int:
        """アラートレベルから優先度IDを決定"""
        pass
    
    def get_issue(self, issue_id: str) -> dict:
        """チケット情報を取得"""
        pass
    
    def update_issue(self, issue_id: str, updates: dict) -> bool:
        """チケットを更新"""
        pass
    
    def test_connection(self) -> bool:
        """接続テスト"""
        pass
```

#### 3.5.4 優先度マッピング

| アラートレベル | Redmine優先度 | 優先度ID |
|--------------|-------------|---------|
| CRITICAL | 緊急 | 5 |
| ERROR | 高 | 4 |
| WARNING | 通常 | 3 |
| INFO | 低 | 2 |
| その他 | 通常 | 3 |

#### 3.5.5 チケットテンプレート

```
件名: [{アラートレベル}] {メール件名}

説明:
## アラート情報
- **アラートレベル**: {アラートレベル}
- **発生日時**: {受信日時}
- **送信元**: {送信元アドレス}
- **サーバー**: {サーバー名}
- **エラーコード**: {エラーコード}
- **IPアドレス**: {IPアドレス}

## メール本文
{メール本文}

---
※このチケットは自動生成されました
メールID: {メールID}
処理日時: {処理日時}
```

### 3.6 ログ管理機能

#### 3.6.1 ログレベル定義

| レベル | 用途 | 出力先 |
|-------|------|-------|
| DEBUG | デバッグ情報 | application.log |
| INFO | 通常処理情報 | application.log |
| WARNING | 警告 | application.log |
| ERROR | エラー | application.log, error.log |
| CRITICAL | 致命的エラー | application.log, error.log |

#### 3.6.2 ログフォーマット

```
[{日時}] [{レベル}] [{モジュール名}] - {メッセージ}

例:
[2025-11-11 10:00:01] [INFO] [mail_monitor] - メール受信: 件名=[CRITICAL] DB接続エラー
[2025-11-11 10:00:02] [INFO] [blacklist_filter] - フィルター通過
[2025-11-11 10:00:03] [INFO] [redmine_client] - チケット起票完了: #1234
```

#### 3.6.3 特殊ログ

**起票履歴ログ (ticket_created.log)**
```json
{
  "timestamp": "2025-11-11T10:00:03+09:00",
  "mail_id": "abc123@example.com",
  "from": "monitoring@example.com",
  "subject": "[CRITICAL] DB接続エラー",
  "ticket_id": "1234",
  "ticket_url": "https://redmine.example.com/issues/1234",
  "priority": "緊急"
}
```

#### 3.6.4 ログローテーション設定

```python
logging_config = {
    'handlers': {
        'file': {
            'filename': 'logs/application.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 10,
            'encoding': 'utf-8'
        }
    }
}
```

---

## 4. データ設計

### 4.1 設定ファイル設計

#### 4.1.1 config.yaml

```yaml
# メールサーバー設定
mail_settings:
  server: imap.example.com
  port: 993
  ssl: true
  username: alert@example.com
  password: ${MAIL_PASSWORD}  # 環境変数から取得
  folder: INBOX
  check_interval: 60  # 秒
  mark_as_read: true
  archive_folder: Processed  # 処理済みメール移動先

# Redmine設定
redmine_settings:
  url: https://redmine.example.com
  api_key: ${REDMINE_API_KEY}  # 環境変数から取得
  default_project_id: 1
  default_tracker_id: 1
  default_priority_id: 3
  default_assigned_to_id: null
  timeout: 30
  retry_count: 3
  retry_interval: 5

# 重複チェック設定
duplicate_check:
  enabled: true
  time_window: 1800  # 秒（30分）
  check_field: subject
  database_path: data/processed_mails.db

# ログ設定
logging:
  level: INFO
  format: "[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s"
  file_path: logs/application.log
  max_bytes: 10485760  # 10MB
  backup_count: 10

# スケジューリング設定
scheduler:
  enabled: true
  interval: 60  # 秒
  max_instances: 1  # 同時実行数
```

#### 4.1.2 blacklist.yaml

```yaml
# ブラックリスト設定ファイル

# 送信元アドレスによる除外
exclude_from_addresses:
  - noreply@example.com
  - newsletter@example.com
  - info@marketing.example.com
  - no-reply@notification.com

# 件名パターンによる除外（正規表現）
exclude_subject_patterns:
  - "^\\[INFO\\].*"                    # INFOレベルは除外
  - "^\\[OK\\].*"                      # OKステータスは除外
  - "^定期レポート.*"                   # 定期レポートは除外
  - ".*テストメール.*"                  # テストメールは除外
  - "^Re:.*"                           # 返信メールは除外
  - "^Fwd:.*"                          # 転送メールは除外
  - "^自動応答:.*"                      # 自動応答は除外
  - ".*バックアップ完了.*"              # バックアップ完了通知は除外

# 本文キーワードによる除外
exclude_body_keywords:
  - "自動送信メールです"
  - "配信停止はこちら"
  - "This is a test"
  - "テスト送信"
  - "unsubscribe"
  - "正常に完了しました"
  - "処理が完了しました"

# 組み合わせ条件による除外
exclude_combinations:
  - name: "定期メンテナンス通知"
    description: "定期メンテナンスの通知は除外"
    from: maintenance@example.com
    subject_pattern: ".*メンテナンス.*"
    enabled: true
  
  - name: "監視システムの正常通知"
    description: "監視システムからの正常通知は除外"
    from: monitoring@example.com
    subject_pattern: "\\[OK\\].*"
    enabled: true
  
  - name: "バッチ処理の正常終了"
    description: "バッチ処理の正常終了通知は除外"
    from: batch@example.com
    body_keywords:
      - "正常終了"
      - "成功"
    enabled: true

# 除外ルールの設定
settings:
  case_sensitive: false          # 大文字小文字を区別するか
  use_regex_cache: true         # 正規表現のキャッシュを使用
  log_excluded_mails: true      # 除外メールをログに記録
```

#### 4.1.3 redmine_mapping.yaml

```yaml
# Redmineマッピング設定ファイル

# アラートレベルと優先度のマッピング
priority_mapping:
  CRITICAL:
    priority_id: 5
    priority_name: 緊急
  ERROR:
    priority_id: 4
    priority_name: 高
  WARNING:
    priority_id: 3
    priority_name: 通常
  INFO:
    priority_id: 2
    priority_name: 低
  DEFAULT:
    priority_id: 3
    priority_name: 通常

# アラートレベルの検出パターン
alert_level_patterns:
  CRITICAL:
    - "\\[CRITICAL\\]"
    - "\\[CRIT\\]"
    - "緊急"
    - "致命的"
  ERROR:
    - "\\[ERROR\\]"
    - "\\[ERR\\]"
    - "エラー"
  WARNING:
    - "\\[WARNING\\]"
    - "\\[WARN\\]"
    - "警告"
  INFO:
    - "\\[INFO\\]"
    - "情報"

# チケットテンプレート
ticket_template:
  subject: "[{alert_level}] {original_subject}"
  description: |
    ## アラート情報
    - **アラートレベル**: {alert_level}
    - **発生日時**: {received_date}
    - **送信元**: {from_address}
    - **サーバー**: {server_name}
    - **エラーコード**: {error_code}
    - **IPアドレス**: {ip_addresses}
    
    ## メール本文
    {mail_body}
    
    ---
    ※このチケットは自動生成されました
    - メールID: {mail_id}
    - 処理日時: {processed_date}

# カスタムフィールドマッピング
custom_fields:
  - field_id: 1
    field_name: "サーバー名"
    source: server_name
    required: false
  
  - field_id: 2
    field_name: "IPアドレス"
    source: ip_addresses
    required: false
    format: "comma_separated"  # カンマ区切りで結合
  
  - field_id: 3
    field_name: "エラーコード"
    source: error_code
    required: false
  
  - field_id: 4
    field_name: "アラート送信元"
    source: from_address
    required: true

# プロジェクト・トラッカー選択ルール
routing_rules:
  - name: "データベースアラート"
    condition:
      subject_pattern: ".*DB.*|.*database.*"
    redmine_settings:
      project_id: 2
      tracker_id: 1
      assigned_to_id: 15
  
  - name: "ネットワークアラート"
    condition:
      subject_pattern: ".*network.*|.*ネットワーク.*"
    redmine_settings:
      project_id: 3
      tracker_id: 1
      assigned_to_id: 20
  
  - name: "デフォルトルーティング"
    condition: {}
    redmine_settings:
      project_id: 1
      tracker_id: 1
      assigned_to_id: null
```

### 4.2 環境変数設計

#### 4.2.1 .env ファイル

```bash
# メールサーバー認証情報
MAIL_PASSWORD=your_mail_password_here

# Redmine API認証情報
REDMINE_API_KEY=your_redmine_api_key_here

# データベース設定
DATABASE_PATH=data/processed_mails.db

# ログレベル（DEBUG, INFO, WARNING, ERROR, CRITICAL）
LOG_LEVEL=INFO

# 実行モード（development, production）
ENVIRONMENT=production

# タイムゾーン
TIMEZONE=Asia/Tokyo
```

---

## 5. インターフェース設計

### 5.1 外部システムインターフェース

#### 5.1.1 メールサーバーインターフェース

**プロトコル**: IMAP over SSL/TLS

**接続パラメータ**
```python
{
    "host": "imap.example.com",
    "port": 993,
    "ssl": True,
    "username": "alert@example.com",
    "password": "***"
}
```

**使用コマンド**
- LOGIN: 認証
- SELECT: メールボックス選択
- SEARCH: メール検索
- FETCH: メール取得
- STORE: フラグ設定
- COPY: メール移動
- LOGOUT: 切断

#### 5.1.2 Redmine REST APIインターフェース

**ベースURL**: `https://redmine.example.com`

**認証方式**: APIキー認証（X-Redmine-API-Keyヘッダー）

**使用エンドポイント**

| メソッド | エンドポイント | 用途 |
|---------|--------------|-----|
| GET | /issues.json | チケット一覧取得 |
| GET | /issues/{id}.json | チケット詳細取得 |
| POST | /issues.json | チケット作成 |
| PUT | /issues/{id}.json | チケット更新 |
| GET | /projects.json | プロジェクト一覧取得 |
| GET | /trackers.json | トラッカー一覧取得 |

**レート制限対応**
- リトライロジック実装
- 指数バックオフ
- 最大リトライ回数: 3回

### 5.2 内部モジュールインターフェース

#### 5.2.1 モジュール間データフロー

```
MailMonitor
    ↓ List[Mail]
BlacklistFilter
    ↓ Mail (フィルター通過)
DuplicateChecker
    ↓ Mail (重複なし)
MailParser
    ↓ ParsedData
RedmineClient
    ↓ ticket_id (str)
Logger
```

---

## 6. 処理フロー設計

### 6.1 メインフロー

```
┌─────────────────────────────────────────┐
│          システム起動                    │
└───────────────┬─────────────────────────┘
                ↓
┌─────────────────────────────────────────┐
│      設定ファイル読み込み                │
│  - config.yaml                          │
│  - blacklist.yaml                       │
│  - redmine_mapping.yaml                 │
└───────────────┬─────────────────────────┘
                ↓
┌─────────────────────────────────────────┐
│    各モジュール初期化                    │
│  - MailMonitor                          │
│  - BlacklistFilter                      │
│  - DuplicateChecker                     │
│  - MailParser                           │
│  - RedmineClient                        │
└───────────────┬─────────────────────────┘
                ↓
┌─────────────────────────────────────────┐
│      メールサーバー接続                  │
└───────────────┬─────────────────────────┘
                │
                ↓
        ┌───────────────┐
        │  定期実行ループ  │←─────┐
        └───────┬───────┘        │
                ↓                │
┌─────────────────────────────────────────┐
│      未読メール取得                      │
└───────────────┬─────────────────────────┘
                │
                ↓
        ┌───────────────┐
        │  メールあり？  │
        └───┬───────┬───┘
          No│       │Yes
            │       ↓
            │ ┌─────────────────────┐
            │ │  各メールに対して    │←──┐
            │ │  以下を実行         │   │
            │ └──────┬──────────────┘   │
            │        ↓                 │
            │ ┌─────────────────────┐   │
            │ │ ブラックリスト判定  │   │
            │ └──────┬──────────────┘   │
            │        │                 │
            │   ┌────┴────┐            │
            │   │除外対象？│            │
            │   └─┬────┬──┘            │
            │   Yes│   │No             │
            │     ↓    │               │
            │ ┌─────┐  │               │
            │ │既読化│  │               │
            │ │ログ │  │               │
            │ └──┬──┘  │               │
            │    │     ↓               │
            │    │ ┌─────────────────┐ │
            │    │ │  重複チェック   │ │
            │    │ └────┬────────────┘ │
            │    │      │              │
            │    │ ┌────┴────┐         │
            │    │ │重複あり？│         │
            │    │ └─┬────┬──┘         │
            │    │ Yes│   │No          │
            │    │   ↓    │            │
            │    │┌─────┐ │            │
            │    ││既読化│ │            │
            │    ││ログ │ │            │
            │    │└──┬──┘ │            │
            │    │   │    ↓            │
            │    │   │┌──────────────┐ │
            │    │   ││メール解析    │ │
            │    │   │└──────┬───────┘ │
            │    │   │       ↓         │
            │    │   │┌──────────────┐ │
            │    │   ││Redmine起票   │ │
            │    │   │└──────┬───────┘ │
            │    │   │       ↓         │
            │    │   │┌──────────────┐ │
            │    │   ││処理履歴登録  │ │
            │    │   │└──────┬───────┘ │
            │    │   │       ↓         │
            │    │   │┌──────────────┐ │
            │    │   ││既読化/移動   │ │
            │    │   │└──────┬───────┘ │
            │    │   │       │         │
            │    └───┴───────┴─────────┘
            │                 │
            │    ┌────────────┘
            │    │
            │    ↓
            │ ┌─────────────┐
            │ │次のメール？ │
            │ └──┬──────┬───┘
            │  Yes│     │No
            │    │     │
            │    └─────┘
            │
            ↓
┌─────────────────────────────────────────┐
│      待機（設定秒数）                    │
└───────────────┬─────────────────────────┘
                │
                └──────────────────────────┘
```

### 6.2 エラー発生時のフロー

```
エラー発生
    ↓
エラー種別判定
    ├─ 接続エラー
    │    ↓
    │  リトライ処理
    │    ├─ 成功 → 処理続行
    │    └─ 失敗（最大回数） → エラーログ → アラート通知
    │
    ├─ 認証エラー
    │    ↓
    │  エラーログ → アラート通知 → システム停止
    │
    ├─ データエラー
    │    ↓
    │  エラーログ → 該当メールをスキップ → 次のメールへ
    │
    └─ システムエラー
         ↓
       エラーログ → アラート通知 → システム停止
```

### 6.3 シーケンス図

```
User     MailMonitor  BlacklistFilter  DuplicateChecker  MailParser  RedmineClient  DB
 |            |              |                |              |            |          |
 |--start---->|              |                |              |            |          |
 |            |--connect---->|                |              |            |          |
 |            |<---OK--------|                |              |            |          |
 |            |              |                |              |            |          |
 |            |--fetch------>|                |              |            |          |
 |            |<---mails-----|                |              |            |          |
 |            |              |                |              |            |          |
 |            |--check------>|                |              |            |          |
 |            |<---pass------|                |              |            |          |
 |            |              |                |              |            |          |
 |            |--------------+--check-------->|              |            |          |
 |            |              |<---not dup-----|              |            |          |
 |            |              |                |              |            |          |
 |            |--------------+--------------+--parse-------->|            |          |
 |            |              |                |<---data------|            |          |
 |            |              |                |              |            |          |
 |            |--------------+--------------+---------------+--create---->|          |
 |            |              |                |              |<---id------|          |
 |            |              |                |              |            |          |
 |            |--------------+--------------+--register-------------------+--------->|
 |            |              |                |              |            |<---OK----|
 |            |              |                |              |            |          |
 |            |--mark read-->|                |              |            |          |
 |            |              |                |              |            |          |
 |<--success--|              |                |              |            |          |
```

---

## 7. エラーハンドリング設計

### 7.1 エラー分類

| エラー種別 | 重要度 | 対応方法 |
|-----------|-------|---------|
| 接続エラー | 高 | リトライ後、失敗時は通知 |
| 認証エラー | 高 | 即座に通知、システム停止 |
| タイムアウト | 中 | リトライ |
| データ形式エラー | 低 | ログ記録、該当データスキップ |
| API制限エラー | 中 | 待機後リトライ |
| ディスク容量不足 | 高 | 即座に通知、システム停止 |

### 7.2 リトライロジック

```python
class RetryHandler:
    """リトライハンドラー"""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    def execute_with_retry(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        指数バックオフでリトライ実行
        
        リトライ間隔: base_delay * (2 ** attempt)
        例: 1秒, 2秒, 4秒
        """
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except RetryableError as e:
                if attempt == self.max_retries - 1:
                    raise
                delay = self.base_delay * (2 ** attempt)
                logger.warning(f"リトライ {attempt + 1}/{self.max_retries}: {delay}秒後")
                time.sleep(delay)
        
        raise MaxRetriesExceededError()
```

### 7.3 例外クラス設計

```python
class AlertMailSystemError(Exception):
    """基底例外クラス"""
    pass

class MailConnectionError(AlertMailSystemError):
    """メール接続エラー"""
    pass

class MailAuthenticationError(AlertMailSystemError):
    """メール認証エラー"""
    pass

class RedmineConnectionError(AlertMailSystemError):
    """Redmine接続エラー"""
    pass

class RedmineAPIError(AlertMailSystemError):
    """Redmine APIエラー"""
    pass

class ConfigurationError(AlertMailSystemError):
    """設定エラー"""
    pass

class DataParseError(AlertMailSystemError):
    """データ解析エラー"""
    pass

class RetryableError(AlertMailSystemError):
    """リトライ可能エラー"""
    pass

class MaxRetriesExceededError(AlertMailSystemError):
    """最大リトライ回数超過エラー"""
    pass
```

### 7.4 エラー通知設計

```python
class ErrorNotifier:
    """エラー通知クラス"""
    
    def notify(
        self,
        error: Exception,
        context: dict,
        severity: str = "ERROR"
    ) -> None:
        """
        エラー通知を送信
        
        通知先:
        - メール
        - Slack（オプション）
        - PagerDuty（オプション）
        """
        message = self._format_error_message(error, context, severity)
        
        # メール通知
        self._send_mail_notification(message)
        
        # Slack通知（設定されている場合）
        if self.slack_webhook:
            self._send_slack_notification(message)
        
        # PagerDuty通知（Critical時のみ）
        if severity == "CRITICAL" and self.pagerduty_key:
            self._send_pagerduty_alert(message)
```

---

## 8. セキュリティ設計

### 8.1 認証情報管理

#### 8.1.1 環境変数による管理

```bash
# 推奨: システム環境変数に設定
export MAIL_PASSWORD="secure_password"
export REDMINE_API_KEY="secure_api_key"

# または .env ファイル（権限: 600）
chmod 600 .env
```

#### 8.1.2 暗号化ストレージ（オプション）

```python
from cryptography.fernet import Fernet

class SecureCredentialStore:
    """暗号化された認証情報ストア"""
    
    def __init__(self, key_file: str):
        with open(key_file, 'rb') as f:
            self.cipher = Fernet(f.read())
    
    def encrypt_credential(self, value: str) -> bytes:
        """認証情報を暗号化"""
        return self.cipher.encrypt(value.encode())
    
    def decrypt_credential(self, encrypted: bytes) -> str:
        """認証情報を復号化"""
        return self.cipher.decrypt(encrypted).decode()
```

### 8.2 通信セキュリティ

#### 8.2.1 TLS/SSL通信

- メールサーバー: IMAP over SSL/TLS (ポート993)
- Redmine: HTTPS通信必須
- 証明書検証の有効化

```python
import ssl

# IMAPの場合
context = ssl.create_default_context()
mail = imaplib.IMAP4_SSL(host, port, ssl_context=context)

# HTTPSの場合
session = requests.Session()
session.verify = True  # 証明書検証を有効化
```

#### 8.2.2 証明書検証

```python
# 自己署名証明書の場合（開発環境のみ）
# config.yaml
ssl_settings:
  verify_cert: true
  ca_cert_path: /path/to/ca_cert.pem  # カスタムCA証明書
```

### 8.3 アクセス制御

#### 8.3.1 ファイル権限

```bash
# 設定ファイル
chmod 600 config/*.yaml
chmod 600 .env

# データベース
chmod 600 data/processed_mails.db

# ログファイル
chmod 640 logs/*.log

# 実行ファイル
chmod 750 src/*.py
```

#### 8.3.2 実行ユーザー

```bash
# 専用ユーザーで実行
useradd -r -s /bin/false alert-system
chown -R alert-system:alert-system /opt/alert-mail-redmine
```

### 8.4 ログセキュリティ

#### 8.4.1 機密情報のマスキング

```python
class SecureLogger:
    """セキュアログ出力"""
    
    SENSITIVE_KEYS = ['password', 'api_key', 'token', 'secret']
    
    def mask_sensitive_data(self, data: dict) -> dict:
        """機密情報をマスク"""
        masked = data.copy()
        for key in masked:
            if any(s in key.lower() for s in self.SENSITIVE_KEYS):
                masked[key] = '***MASKED***'
        return masked
    
    def log_config(self, config: dict) -> None:
        """設定をログ出力（機密情報をマスク）"""
        masked_config = self.mask_sensitive_data(config)
        logger.info(f"Configuration: {masked_config}")
```

#### 8.4.2 ログファイルへのアクセス制限

```python
# ログファイルハンドラー設定
file_handler = RotatingFileHandler(
    'logs/application.log',
    maxBytes=10485760,
    backupCount=10,
    encoding='utf-8'
)

# ファイル作成時のパーミッション設定
os.chmod('logs/application.log', 0o640)
```

### 8.5 脆弱性対策

#### 8.5.1 インジェクション対策

```python
# SQLインジェクション対策（プレースホルダー使用）
cursor.execute(
    "SELECT * FROM processed_mails WHERE subject_hash = ?",
    (subject_hash,)
)

# コマンドインジェクション対策（シェル実行を避ける）
# 悪い例: os.system(f"command {user_input}")
# 良い例: subprocess.run(['command', user_input], check=True)
```

#### 8.5.2 依存パッケージの脆弱性管理

```bash
# 定期的な脆弱性チェック
pip install safety
safety check

# 依存パッケージの更新
pip list --outdated
pip install --upgrade package_name
```

---

## 9. 性能設計

### 9.1 性能要件

| 項目 | 目標値 | 測定方法 |
|-----|-------|---------|
| メール処理時間 | 5秒/件以下 | ログから測定 |
| チケット起票時間 | 3秒/件以下 | API応答時間 |
| 同時処理メール数 | 100件/分 | スループット測定 |
| メモリ使用量 | 512MB以下 | プロセス監視 |
| CPU使用率 | 50%以下 | プロセス監視 |

### 9.2 性能最適化

#### 9.2.1 メール取得の最適化

```python
# バッチ取得
def fetch_unread_mails(self, limit: int = 50) -> List[Mail]:
    """
    未読メールをバッチ取得
    
    Args:
        limit: 1回あたりの取得件数上限
    """
    # SEARCHで未読メールIDを一括取得
    status, messages = self.connection.search(None, 'UNSEEN')
    mail_ids = messages[0].split()[:limit]
    
    # FETCHで一括取得
    mails = []
    for mail_id in mail_ids:
        # ヘッダーのみ先に取得して高速化
        status, data = self.connection.fetch(mail_id, '(BODY.PEEK[HEADER])')
        # 必要な場合のみ本文取得
        if self._should_fetch_body(data):
            status, data = self.connection.fetch(mail_id, '(RFC822)')
            mails.append(self._parse_mail(data))
    
    return mails
```

#### 9.2.2 正規表現のキャッシュ

```python
import re
from functools import lru_cache

class BlacklistFilter:
    def __init__(self, config: dict):
        self.patterns = self._compile_patterns(
            config.get('exclude_subject_patterns', [])
        )
    
    @lru_cache(maxsize=128)
    def _compile_pattern(self, pattern: str) -> re.Pattern:
        """正規表現をコンパイル（キャッシュあり）"""
        return re.compile(pattern, re.IGNORECASE)
    
    def _compile_patterns(self, patterns: List[str]) -> List[re.Pattern]:
        """複数の正規表現をコンパイル"""
        return [self._compile_pattern(p) for p in patterns]
```

#### 9.2.3 データベースインデックス

```sql
-- 処理済みメールテーブルのインデックス
CREATE INDEX idx_subject_hash ON processed_mails(subject_hash);
CREATE INDEX idx_received_date ON processed_mails(received_date);
CREATE INDEX idx_from_address ON processed_mails(from_address);

-- 複合インデックス（重複チェック用）
CREATE INDEX idx_duplicate_check 
ON processed_mails(subject_hash, from_address, received_date);
```

#### 9.2.4 コネクションプーリング

```python
class RedmineClient:
    def __init__(self, config: dict):
        # HTTPセッションの再利用
        self.session = requests.Session()
        
        # コネクションプール設定
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=3
        )
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
```

### 9.3 性能監視

#### 9.3.1 処理時間の計測

```python
import time
from contextlib import contextmanager

@contextmanager
def timer(name: str):
    """処理時間計測コンテキストマネージャー"""
    start = time.time()
    yield
    elapsed = time.time() - start
    logger.info(f"{name}: {elapsed:.2f}秒")

# 使用例
with timer("メール取得"):
    mails = mail_monitor.fetch_unread_mails()

with timer("チケット起票"):
    ticket_id = redmine_client.create_issue(parsed_data, mail)
```

#### 9.3.2 メトリクス収集

```python
class Metrics:
    """メトリクス収集クラス"""
    
    def __init__(self):
        self.counters = defaultdict(int)
        self.timings = defaultdict(list)
    
    def increment(self, key: str, value: int = 1):
        """カウンターをインクリメント"""
        self.counters[key] += value
    
    def record_timing(self, key: str, duration: float):
        """処理時間を記録"""
        self.timings[key].append(duration)
    
    def get_summary(self) -> dict:
        """サマリーを取得"""
        return {
            'counters': dict(self.counters),
            'timings': {
                k: {
                    'count': len(v),
                    'avg': sum(v) / len(v) if v else 0,
                    'min': min(v) if v else 0,
                    'max': max(v) if v else 0
                }
                for k, v in self.timings.items()
            }
        }
```

---

## 10. 運用設計

### 10.1 デプロイメント

#### 10.1.1 インストール手順

```bash
# 1. リポジトリのクローン
git clone https://github.com/company/alert-mail-redmine.git
cd alert-mail-redmine

# 2. 仮想環境の作成
python3 -m venv venv
source venv/bin/activate

# 3. 依存パッケージのインストール
pip install -r requirements.txt

# 4. ディレクトリの作成
mkdir -p data logs config

# 5. 設定ファイルのコピーと編集
cp config/config.yaml.example config/config.yaml
cp config/blacklist.yaml.example config/blacklist.yaml
cp .env.example .env

# 6. 環境変数の設定
vim .env

# 7. ファイルパーミッションの設定
chmod 600 config/*.yaml
chmod 600 .env
chmod 755 src/*.py

# 8. データベースの初期化
python src/init_db.py

# 9. 接続テスト
python src/test_connection.py
```

#### 10.1.2 systemdサービス設定

```ini
# /etc/systemd/system/alert-mail-redmine.service
[Unit]
Description=Alert Mail to Redmine Ticket System
After=network.target

[Service]
Type=simple
User=alert-system
Group=alert-system
WorkingDirectory=/opt/alert-mail-redmine
Environment="PATH=/opt/alert-mail-redmine/venv/bin"
ExecStart=/opt/alert-mail-redmine/venv/bin/python /opt/alert-mail-redmine/src/main.py
Restart=always
RestartSec=10

# ログ設定
StandardOutput=journal
StandardError=journal
SyslogIdentifier=alert-mail-redmine

[Install]
WantedBy=multi-user.target
```

```bash
# サービスの有効化と起動
sudo systemctl daemon-reload
sudo systemctl enable alert-mail-redmine
sudo systemctl start alert-mail-redmine

# ステータス確認
sudo systemctl status alert-mail-redmine

# ログ確認
sudo journalctl -u alert-mail-redmine -f
```

### 10.2 監視設計

#### 10.2.1 ヘルスチェック

```python
class HealthChecker:
    """ヘルスチェッククラス"""
    
    def check_all(self) -> dict:
        """全コンポーネントのヘルスチェック"""
        return {
            'mail_server': self.check_mail_server(),
            'redmine': self.check_redmine(),
            'database': self.check_database(),
            'disk_space': self.check_disk_space(),
            'timestamp': datetime.now().isoformat()
        }
    
    def check_mail_server(self) -> dict:
        """メールサーバーのヘルスチェック"""
        try:
            with MailMonitor(config) as monitor:
                monitor.connect()
            return {'status': 'OK', 'message': '接続成功'}
        except Exception as e:
            return {'status': 'ERROR', 'message': str(e)}
    
    def check_redmine(self) -> dict:
        """Redmineのヘルスチェック"""
        try:
            client = RedmineClient(config)
            client.test_connection()
            return {'status': 'OK', 'message': '接続成功'}
        except Exception as e:
            return {'status': 'ERROR', 'message': str(e)}
    
    def check_database(self) -> dict:
        """データベースのヘルスチェック"""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute('SELECT 1')
            return {'status': 'OK', 'message': '接続成功'}
        except Exception as e:
            return {'status': 'ERROR', 'message': str(e)}
    
    def check_disk_space(self) -> dict:
        """ディスク容量のチェック"""
        import shutil
        total, used, free = shutil.disk_usage('/')
        free_gb = free // (2**30)
        
        if free_gb < 1:
            return {'status': 'CRITICAL', 'free_gb': free_gb}
        elif free_gb < 5:
            return {'status': 'WARNING', 'free_gb': free_gb}
        else:
            return {'status': 'OK', 'free_gb': free_gb}
```

#### 10.2.2 監視項目

| 項目 | 閾値 | アクション |
|-----|------|----------|
| プロセス稼働状態 | - | 停止時に再起動 |
| メモリ使用量 | 80%超 | アラート |
| CPU使用率 | 80%超（5分） | アラート |
| ディスク使用量 | 90%超 | アラート |
| エラー発生率 | 10%超 | アラート |
| メール処理遅延 | 5分超 | アラート |
| ログファイルサイズ | 1GB超 | ローテーション |

#### 10.2.3 Zabbix連携（オプション）

```python
# Zabbixにメトリクスを送信
from pyzabbix import ZabbixMetric, ZabbixSender

def send_metrics_to_zabbix(metrics: dict):
    """Zabbixにメトリクスを送信"""
    zabbix_server = config['zabbix']['server']
    hostname = config['zabbix']['hostname']
    
    packet = [
        ZabbixMetric(hostname, 'alert_mail.processed_count', metrics['processed']),
        ZabbixMetric(hostname, 'alert_mail.error_count', metrics['errors']),
        ZabbixMetric(hostname, 'alert_mail.processing_time', metrics['avg_time'])
    ]
    
    sender = ZabbixSender(zabbix_server)
    sender.send(packet)
```

### 10.3 バックアップ・リストア

#### 10.3.1 バックアップ対象

- 設定ファイル (`config/`)
- データベース (`data/processed_mails.db`)
- ログファイル (`logs/`)（オプション）

#### 10.3.2 バックアップスクリプト

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backup/alert-mail-redmine"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/backup_${TIMESTAMP}.tar.gz"

# バックアップディレクトリ作成
mkdir -p ${BACKUP_DIR}

# アーカイブ作成
tar -czf ${BACKUP_FILE} \
    config/ \
    data/processed_mails.db \
    .env

# 古いバックアップを削除（30日以上前）
find ${BACKUP_DIR} -name "backup_*.tar.gz" -mtime +30 -delete

echo "バックアップ完了: ${BACKUP_FILE}"
```

#### 10.3.3 リストアスクリプト

```bash
#!/bin/bash
# restore.sh

if [ -z "$1" ]; then
    echo "使用法: $0 <backup_file>"
    exit 1
fi

BACKUP_FILE=$1

# システム停止
sudo systemctl stop alert-mail-redmine

# リストア
tar -xzf ${BACKUP_FILE}

# システム起動
sudo systemctl start alert-mail-redmine

echo "リストア完了"
```

### 10.4 ログ管理

#### 10.4.1 ログローテーション設定

```bash
# /etc/logrotate.d/alert-mail-redmine
/opt/alert-mail-redmine/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 alert-system alert-system
    sharedscripts
    postrotate
        systemctl reload alert-mail-redmine > /dev/null 2>&1 || true
    endscript
}
```

#### 10.4.2 ログ監視

```bash
# エラーログの監視
tail -f logs/error.log | while read line; do
    if echo "$line" | grep -q "CRITICAL"; then
        # アラート送信
        echo "$line" | mail -s "CRITICAL: Alert Mail System" admin@example.com
    fi
done
```

### 10.5 トラブルシューティング

#### 10.5.1 よくある問題と対処法

| 問題 | 原因 | 対処法 |
|-----|------|-------|
| メール接続失敗 | 認証情報エラー | .envファイルを確認 |
| Redmine API エラー | APIキー無効 | Redmineで再発行 |
| 重複チケット作成 | 重複チェック無効 | config.yamlを確認 |
| ディスク容量不足 | ログ肥大化 | ログローテーション設定 |
| メモリ不足 | メール処理数過多 | バッチサイズを削減 |

#### 10.5.2 デバッグモード

```bash
# デバッグモードで実行
LOG_LEVEL=DEBUG python src/main.py

# 特定モジュールのデバッグ
LOG_LEVEL=DEBUG LOG_MODULE=mail_monitor python src/main.py
```

#### 10.5.3 診断スクリプト

```python
# diagnose.py
def run_diagnostics():
    """システム診断を実行"""
    print("=== システム診断開始 ===\n")
    
    # 1. 設定ファイルチェック
    print("1. 設定ファイルチェック")
    check_config_files()
    
    # 2. 接続テスト
    print("\n2. 接続テスト")
    test_mail_connection()
    test_redmine_connection()
    
    # 3. データベースチェック
    print("\n3. データベースチェック")
    check_database()
    
    # 4. ディスク容量チェック
    print("\n4. ディスク容量チェック")
    check_disk_space()
    
    # 5. ログファイルチェック
    print("\n5. ログファイルチェック")
    check_log_files()
    
    print("\n=== システム診断完了 ===")

if __name__ == '__main__':
    run_diagnostics()
```

---

## 11. テスト設計

### 11.1 テスト戦略

| テストレベル | 対象 | 実施タイミング |
|------------|------|--------------|
| ユニットテスト | 各モジュール | コミット時 |
| 統合テスト | モジュール間連携 | PR時 |
| E2Eテスト | システム全体 | リリース前 |
| 負荷テスト | 性能 | リリース前 |

### 11.2 ユニットテスト

#### 11.2.1 テストケース例

```python
# tests/test_blacklist_filter.py
import pytest
from src.blacklist_filter import BlacklistFilter
from src.mail_monitor import Mail
from datetime import datetime

class TestBlacklistFilter:
    """ブラックリストフィルターのテスト"""
    
    @pytest.fixture
    def filter(self):
        """フィルターのフィクスチャ"""
        config = {
            'exclude_from_addresses': ['test@example.com'],
            'exclude_subject_patterns': ['^\\[INFO\\].*'],
            'exclude_body_keywords': ['テスト'],
            'exclude_combinations': []
        }
        return BlacklistFilter(config)
    
    def test_exclude_from_address(self, filter):
        """送信元アドレスによる除外"""
        mail = Mail(
            mail_id='1',
            from_address='test@example.com',
            to_address='alert@example.com',
            subject='テストメール',
            body='これはテストです',
            html_body='',
            received_date=datetime.now(),
            headers={},
            attachments=[]
        )
        
        is_excluded, reason = filter.is_blacklisted(mail)
        assert is_excluded is True
        assert '送信元' in reason
    
    def test_exclude_subject_pattern(self, filter):
        """件名パターンによる除外"""
        mail = Mail(
            mail_id='2',
            from_address='alert@example.com',
            to_address='alert@example.com',
            subject='[INFO] システム情報',
            body='情報です',
            html_body='',
            received_date=datetime.now(),
            headers={},
            attachments=[]
        )
        
        is_excluded, reason = filter.is_blacklisted(mail)
        assert is_excluded is True
        assert '件名パターン' in reason
    
    def test_not_excluded(self, filter):
        """除外されないケース"""
        mail = Mail(
            mail_id='3',
            from_address='alert@example.com',
            to_address='alert@example.com',
            subject='[CRITICAL] 障害発生',
            body='障害が発生しました',
            html_body='',
            received_date=datetime.now(),
            headers={},
            attachments=[]
        )
        
        is_excluded, reason = filter.is_blacklisted(mail)
        assert is_excluded is False
```

#### 11.2.2 モックの使用

```python
# tests/test_redmine_client.py
import pytest
from unittest.mock import Mock, patch
from src.redmine_client import RedmineClient

class TestRedmineClient:
    """Redmineクライアントのテスト"""
    
    @patch('requests.Session.post')
    def test_create_issue_success(self, mock_post):
        """チケット作成成功のテスト"""
        # モックのレスポンス設定
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            'issue': {'id': 1234}
        }
        mock_post.return_value = mock_response
        
        # テスト実行
        client = RedmineClient(config)
        ticket_id = client.create_issue(parsed_data, mail)
        
        # 検証
        assert ticket_id == '1234'
        mock_post.assert_called_once()
    
    @patch('requests.Session.post')
    def test_create_issue_failure(self, mock_post):
        """チケット作成失敗のテスト"""
        # モックのレスポンス設定
        mock_response = Mock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response
        
        # テスト実行と検証
        client = RedmineClient(config)
        with pytest.raises(RedmineAPIError):
            client.create_issue(parsed_data, mail)
```

### 11.3 統合テスト

```python
# tests/test_integration.py
import pytest
from src.main import AlertMailSystem

class TestIntegration:
    """統合テスト"""
    
    def test_full_workflow(self, test_config, test_mail):
        """メール受信からチケット起票までの全体フロー"""
        system = AlertMailSystem(test_config)
        
        # メール処理
        results = system.process_mails()
        
        # 検証
        assert len(results['processed']) > 0
        assert len(results['errors']) == 0
        assert results['processed'][0]['ticket_id'] is not None
```

### 11.4 E2Eテスト

```python
# tests/test_e2e.py
import pytest
import time
from src.main import AlertMailSystem

class TestE2E:
    """E2Eテスト"""
    
    @pytest.mark.slow
    def test_real_mail_to_redmine(self):
        """実際のメールサーバーとRedmineを使用したテスト"""
        # テストメールを送信
        send_test_mail()
        
        # システム起動
        system = AlertMailSystem(production_config)
        
        # 処理実行
        time.sleep(5)  # メール到着待ち
        results = system.process_mails()
        
        # 検証
        assert len(results['processed']) == 1
        
        # Redmineでチケット確認
        ticket_id = results['processed'][0]['ticket_id']
        ticket = get_redmine_ticket(ticket_id)
        assert ticket is not None
        assert 'テストメール' in ticket['subject']
```

### 11.5 テストカバレッジ

```bash
# カバレッジ測定
pytest --cov=src --cov-report=html tests/

# 目標カバレッジ: 80%以上
```

---

## 12. 付録

### 12.1 用語集

| 用語 | 説明 |
|-----|------|
| アラートメール | 監視システムから送信される障害・異常通知メール |
| ブラックリスト | 起票対象から除外するメールの条件リスト |
| チケット | Redmineで管理される課題・タスク |
| 重複チェック | 同一内容のメールを検出する機能 |
| 冪等性 | 同じ処理を複数回実行しても結果が変わらない性質 |

### 12.2 参考資料

- [Redmine REST API Documentation](https://www.redmine.org/projects/redmine/wiki/Rest_api)
- [Python imaplib Documentation](https://docs.python.org/3/library/imaplib.html)
- [Python email Documentation](https://docs.python.org/3/library/email.html)
- [Python requests Documentation](https://requests.readthedocs.io/)

### 12.3 変更履歴

| バージョン | 日付 | 変更内容 | 作成者 |
|----------|------|---------|-------|
| 1.0 | 2025-11-11 | 初版作成 | - |

### 12.4 設定例

#### 12.4.1 開発環境設定

```yaml
# config/config.dev.yaml
mail_settings:
  server: imap.dev.example.com
  port: 993
  username: dev-alert@example.com
  password: ${MAIL_PASSWORD}
  check_interval: 300  # 5分

redmine_settings:
  url: https://redmine-dev.example.com
  api_key: ${REDMINE_API_KEY}
  default_project_id: 999  # 開発用プロジェクト

logging:
  level: DEBUG
```

#### 12.4.2 本番環境設定

```yaml
# config/config.prod.yaml
mail_settings:
  server: imap.example.com
  port: 993
  username: alert@example.com
  password: ${MAIL_PASSWORD}
  check_interval: 60  # 1分

redmine_settings:
  url: https://redmine.example.com
  api_key: ${REDMINE_API_KEY}
  default_project_id: 1

logging:
  level: INFO
```

### 12.5 FAQ

**Q1: ブラックリストの条件はどこで管理しますか？**

A: `config/blacklist.yaml` ファイルで管理します。YAML形式で読みやすく、運用中でも編集可能です。

**Q2: 同じメールが複数回送られてきた場合、重複して起票されますか？**

A: いいえ。重複チェック機能により、指定時間窓内（デフォルト30分）の同一メールは起票されません。

**Q3: HTMLメールの処理はどうなりますか？**

A: HTMLメールは自動的にプレーンテキストに変換されて処理されます。

**Q4: 処理に失敗したメールはどうなりますか？**

A: エラーログに記録され、メールは既読にされません。次回の実行時に再処理されます。

**Q5: 本番運用前に何をテストすべきですか？**

A: 以下をテストしてください：
1. メールサーバーへの接続
2. Redmine APIへの接続
3. テストメールの送信と起票確認
4. ブラックリストフィルターの動作確認
5. エラーハンドリングの確認

---

## 文書の終わり

本設計書に関する質問や修正依頼は、プロジェクトチームまでご連絡ください。
