# アラートメール自動起票システム（Windows Outlook対応版）詳細設計書

## 文書情報

| 項目 | 内容 |
|------|------|
| 文書名 | アラートメール自動起票システム（Windows Outlook対応版）詳細設計書 |
| バージョン | 1.0 |
| 作成日 | 2025-11-11 |
| 対象OS | Windows 10/11 |
| 対象アプリ | Microsoft Outlook 2016/2019/2021/365 |

---

## 目次

1. [システム概要](#1-システム概要)
2. [システム構成](#2-システム構成)
3. [Outlook連携設計](#3-outlook連携設計)
4. [機能詳細設計](#4-機能詳細設計)
5. [データ設計](#5-データ設計)
6. [処理フロー設計](#6-処理フロー設計)
7. [エラーハンドリング設計](#7-エラーハンドリング設計)
8. [セキュリティ設計](#8-セキュリティ設計)
9. [運用設計](#9-運用設計)
10. [インストール・セットアップ手順](#10-インストールセットアップ手順)
11. [付録](#11-付録)

---

## 1. システム概要

### 1.1 目的

ローカルWindows端末のMicrosoft Outlookで受信したアラートメールを自動的に監視し、特定の条件（ブラックリスト）に該当しないメールのみをRedmineチケットとして自動起票する。

### 1.2 システムの位置づけ

```
┌─────────────────┐
│  監視システム    │
│ (Zabbix/Nagios) │
└────────┬────────┘
         │ メール送信
         ↓
┌─────────────────────────┐
│   メールサーバー          │
│   (Exchange/SMTP)        │
└────────┬────────────────┘
         │ 同期
         ↓
┌─────────────────────────┐
│  Windows PC              │
│  ┌───────────────────┐  │
│  │  Outlook          │  │
│  │  (受信トレイ)     │  │
│  └─────┬─────────────┘  │
│        │                 │
│        ↓                 │
│  ┌───────────────────┐  │
│  │アラートメール      │  │ ← 本システム
│  │自動起票システム   │  │
│  └─────┬─────────────┘  │
└────────┼─────────────────┘
         │ REST API (HTTPS)
         ↓
┌─────────────────┐
│    Redmine      │
│ (チケット管理)   │
└─────────────────┘
```

### 1.3 システム方針

- **Outlook連携**: Win32 COM APIを使用してOutlookと連携
- **ローカル実行**: Windows端末上で常駐またはタスクスケジューラで定期実行
- **ブラックリスト方式**: 除外対象を定義し、それ以外はすべて起票
- **非侵襲**: Outlookの通常操作を妨げない
- **GUI対応**: 設定用のGUIツール提供（オプション）

### 1.4 前提条件

- Windows 10/11
- Microsoft Outlook 2016以降がインストール済み
- Python 3.8以上
- Outlookが起動している状態（COMアクセスに必要）
- インターネット接続（Redmineサーバーへのアクセス用）
- 管理者権限（初回セットアップ時のみ）

### 1.5 制約事項

- Outlookが起動していない場合は処理できない
- Outlook起動後にシステムを起動する必要がある
- 複数のOutlookプロファイルがある場合は、デフォルトプロファイルを使用
- Outlook 2013以前は未対応
- macOS版Outlookは未対応（Win32 COM非対応のため）

---

## 2. システム構成

### 2.1 システムアーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│         Windows ローカル環境                             │
│                                                          │
│  ┌────────────────────┐                                │
│  │   Microsoft        │                                │
│  │   Outlook          │                                │
│  └──────┬─────────────┘                                │
│         │ Win32 COM                                     │
│         ↓                                               │
│  ┌────────────────────────────────────────────────┐   │
│  │  アラートメール自動起票システム                │   │
│  │                                                 │   │
│  │  ┌──────────────┐    ┌──────────────┐         │   │
│  │  │  Outlook監視  │───→│  フィルター   │         │   │
│  │  │   モジュール  │    │   モジュール  │         │   │
│  │  └──────────────┘    └──────┬───────┘         │   │
│  │                              │                  │   │
│  │  ┌──────────────┐            │                  │   │
│  │  │   ログ管理    │←───────────┤                  │   │
│  │  │   モジュール  │            │                  │   │
│  │  └──────────────┘            ↓                  │   │
│  │                     ┌──────────────┐            │   │
│  │                     │  データ抽出   │            │   │
│  │                     │   モジュール  │            │   │
│  │                     └──────┬───────┘            │   │
│  │                            │                     │   │
│  │                            ↓                     │   │
│  │                     ┌──────────────┐            │   │
│  │                     │  Redmine連携  │            │   │
│  │                     │   モジュール  │            │   │
│  │                     └──────────────┘            │   │
│  │                                                 │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
└─────────────────────────┼───────────────────────────────┘
                          │ HTTPS
                          ↓
                   ┌──────────┐
                   │ Redmine  │
                   └──────────┘
```

### 2.2 ディレクトリ構成

```
C:\AlertMailRedmine\
├── config\
│   ├── config.yaml              # メイン設定ファイル
│   ├── blacklist.yaml           # ブラックリスト設定
│   └── redmine_mapping.yaml     # Redmineマッピング設定
├── src\
│   ├── main.py                  # メインエントリーポイント
│   ├── outlook_monitor.py       # Outlook監視モジュール
│   ├── blacklist_filter.py      # フィルターモジュール
│   ├── mail_parser.py           # メール解析モジュール
│   ├── redmine_client.py        # Redmine APIクライアント
│   ├── duplicate_checker.py     # 重複チェックモジュール
│   ├── logger.py                # ログ管理モジュール
│   └── gui_config.py            # GUI設定ツール（オプション）
├── data\
│   └── processed_mails.db       # 処理済みメールDB (SQLite)
├── logs\
│   ├── application.log          # アプリケーションログ
│   ├── error.log                # エラーログ
│   └── ticket_created.log       # 起票履歴ログ
├── tests\
│   └── (テストファイル群)
├── venv\                        # Python仮想環境
├── requirements.txt             # 依存パッケージ
├── .env                         # 環境変数
├── setup.bat                    # セットアップスクリプト
├── start.bat                    # 起動スクリプト
├── stop.bat                     # 停止スクリプト
└── README.md                    # システム説明書
```

### 2.3 技術スタック

| レイヤー | 技術 | 用途 |
|---------|------|------|
| 言語 | Python 3.8+ | メイン実装言語 |
| Outlook連携 | pywin32 | Win32 COM APIアクセス |
| HTTP通信 | requests | Redmine API連携 |
| 設定管理 | PyYAML | YAML設定ファイル読み込み |
| データベース | SQLite3 | 処理履歴管理 |
| ログ管理 | logging | ログ出力 |
| スケジューリング | APScheduler | 定期実行 |
| GUI (オプション) | tkinter | 設定画面 |
| サービス化 | NSSM | Windowsサービス化 |

---

## 3. Outlook連携設計

### 3.1 Win32 COM API概要

Microsoft OutlookはWin32 COM (Component Object Model) APIを提供しており、Pythonの`pywin32`ライブラリを通じてアクセス可能。

### 3.2 Outlookオブジェクトモデル

```
Application
  └─ NameSpace (MAPI)
      └─ Folders
          └─ Folder (受信トレイなど)
              └─ Items (メールアイテム群)
                  └─ MailItem (個別メール)
                      ├─ Subject (件名)
                      ├─ Body (本文)
                      ├─ SenderEmailAddress
                      ├─ ReceivedTime
                      └─ Unread (未読フラグ)
```

### 3.3 Outlook接続方法

#### 3.3.1 基本接続

```python
import win32com.client
import pythoncom

class OutlookMonitor:
    """Outlook監視クラス"""
    
    def __init__(self):
        self.outlook = None
        self.namespace = None
        self.inbox = None
    
    def connect(self) -> bool:
        """
        Outlookに接続
        Returns:
            接続成功時True
        """
        try:
            # COMの初期化（マルチスレッド対応）
            pythoncom.CoInitialize()
            
            # Outlookアプリケーションに接続
            self.outlook = win32com.client.Dispatch("Outlook.Application")
            
            # MAPIネームスペースを取得
            self.namespace = self.outlook.GetNamespace("MAPI")
            
            # 受信トレイを取得
            # olFolderInbox = 6
            self.inbox = self.namespace.GetDefaultFolder(6)
            
            logger.info("Outlook接続成功")
            return True
            
        except Exception as e:
            logger.error(f"Outlook接続エラー: {e}")
            return False
    
    def disconnect(self) -> None:
        """Outlookから切断"""
        if self.outlook:
            self.outlook = None
            pythoncom.CoUninitialize()
            logger.info("Outlook切断")
```

#### 3.3.2 フォルダ構造の取得

```python
def get_folder_by_path(self, folder_path: str):
    """
    パスを指定してフォルダを取得
    
    Args:
        folder_path: フォルダパス（例: "受信トレイ/アラート"）
    
    Returns:
        Folderオブジェクト
    """
    folder = self.inbox
    
    if folder_path and folder_path != "受信トレイ":
        path_parts = folder_path.split('/')
        
        # 受信トレイ配下を探索
        for part in path_parts[1:]:  # 最初の"受信トレイ"はスキップ
            try:
                folder = folder.Folders[part]
            except:
                logger.warning(f"フォルダが見つかりません: {part}")
                return None
    
    return folder
```

### 3.4 メール取得方法

#### 3.4.1 未読メールの取得

```python
def fetch_unread_mails(self, limit: int = 50) -> List[MailItem]:
    """
    未読メールを取得
    
    Args:
        limit: 取得件数上限
    
    Returns:
        MailItemオブジェクトのリスト
    """
    try:
        mails = []
        items = self.inbox.Items
        
        # 受信日時の降順でソート
        items.Sort("[ReceivedTime]", True)
        
        # 未読メールをフィルター
        filtered = items.Restrict("[Unread] = True")
        
        count = 0
        for item in filtered:
            if count >= limit:
                break
            
            # メールアイテムのみを対象
            if item.Class == 43:  # olMail
                mails.append(item)
                count += 1
        
        logger.info(f"未読メール取得: {len(mails)}件")
        return mails
        
    except Exception as e:
        logger.error(f"メール取得エラー: {e}")
        return []
```

#### 3.4.2 特定フォルダのメール取得

```python
def fetch_mails_from_folder(
    self,
    folder_path: str,
    unread_only: bool = True,
    limit: int = 50
) -> List[MailItem]:
    """
    特定フォルダからメールを取得
    
    Args:
        folder_path: フォルダパス
        unread_only: 未読のみ取得するか
        limit: 取得件数上限
    """
    folder = self.get_folder_by_path(folder_path)
    if not folder:
        return []
    
    items = folder.Items
    items.Sort("[ReceivedTime]", True)
    
    if unread_only:
        items = items.Restrict("[Unread] = True")
    
    mails = []
    count = 0
    for item in items:
        if count >= limit:
            break
        if item.Class == 43:  # olMail
            mails.append(item)
            count += 1
    
    return mails
```

### 3.5 メール操作方法

#### 3.5.1 既読にする

```python
def mark_as_read(self, mail_item) -> bool:
    """
    メールを既読にする
    
    Args:
        mail_item: MailItemオブジェクト
    """
    try:
        mail_item.UnRead = False
        mail_item.Save()
        logger.debug(f"既読化: {mail_item.Subject}")
        return True
    except Exception as e:
        logger.error(f"既読化エラー: {e}")
        return False
```

#### 3.5.2 フォルダに移動

```python
def move_to_folder(self, mail_item, folder_path: str) -> bool:
    """
    メールを指定フォルダに移動
    
    Args:
        mail_item: MailItemオブジェクト
        folder_path: 移動先フォルダパス
    """
    try:
        target_folder = self.get_folder_by_path(folder_path)
        if not target_folder:
            # フォルダが存在しない場合は作成
            target_folder = self.create_folder(folder_path)
        
        mail_item.Move(target_folder)
        logger.debug(f"移動完了: {mail_item.Subject} -> {folder_path}")
        return True
    except Exception as e:
        logger.error(f"移動エラー: {e}")
        return False
```

#### 3.5.3 フォルダ作成

```python
def create_folder(self, folder_path: str):
    """
    フォルダを作成
    
    Args:
        folder_path: 作成するフォルダパス
    """
    path_parts = folder_path.split('/')
    parent = self.inbox
    
    for part in path_parts[1:]:  # 受信トレイ配下に作成
        try:
            # 既存フォルダを取得
            folder = parent.Folders[part]
        except:
            # 存在しない場合は作成
            folder = parent.Folders.Add(part)
            logger.info(f"フォルダ作成: {part}")
        
        parent = folder
    
    return parent
```

#### 3.5.4 カテゴリの設定

```python
def set_category(self, mail_item, category: str) -> bool:
    """
    メールにカテゴリを設定
    
    Args:
        mail_item: MailItemオブジェクト
        category: カテゴリ名（例: "Redmine起票済み"）
    """
    try:
        mail_item.Categories = category
        mail_item.Save()
        logger.debug(f"カテゴリ設定: {category}")
        return True
    except Exception as e:
        logger.error(f"カテゴリ設定エラー: {e}")
        return False
```

### 3.6 メールデータの抽出

```python
def extract_mail_data(self, mail_item) -> Mail:
    """
    MailItemからMailオブジェクトを生成
    
    Args:
        mail_item: Outlook MailItemオブジェクト
    
    Returns:
        Mailデータクラス
    """
    try:
        # EntryIDをメールIDとして使用
        mail_id = mail_item.EntryID
        
        # 送信者アドレスの取得
        sender = self._get_sender_address(mail_item)
        
        # 受信者アドレスの取得
        recipient = mail_item.To
        
        # 件名
        subject = mail_item.Subject or "(件名なし)"
        
        # 本文（プレーンテキスト）
        body = mail_item.Body or ""
        
        # 本文（HTML）
        html_body = mail_item.HTMLBody or ""
        
        # 受信日時
        received_date = mail_item.ReceivedTime
        
        # ヘッダー情報（一部のみ）
        headers = {
            'MessageClass': mail_item.MessageClass,
            'Importance': mail_item.Importance,
            'Sensitivity': mail_item.Sensitivity
        }
        
        return Mail(
            mail_id=mail_id,
            from_address=sender,
            to_address=recipient,
            subject=subject,
            body=body,
            html_body=html_body,
            received_date=received_date,
            headers=headers,
            attachments=[]  # 将来対応
        )
        
    except Exception as e:
        logger.error(f"メールデータ抽出エラー: {e}")
        raise

def _get_sender_address(self, mail_item) -> str:
    """
    送信者のメールアドレスを取得
    
    複数の方法を試行してアドレスを取得
    """
    try:
        # 方法1: SenderEmailAddressプロパティ
        if mail_item.SenderEmailAddress:
            # Exchange形式の場合は変換が必要
            if mail_item.SenderEmailAddress.startswith('/'):
                # SMTPアドレスに変換
                try:
                    sender = mail_item.Sender
                    return sender.GetExchangeUser().PrimarySmtpAddress
                except:
                    pass
            else:
                return mail_item.SenderEmailAddress
        
        # 方法2: Senderプロパティ経由
        if mail_item.Sender:
            return mail_item.Sender.Address
        
        # 方法3: SenderNameを返す（最終手段）
        return mail_item.SenderName
        
    except Exception as e:
        logger.warning(f"送信者アドレス取得エラー: {e}")
        return "unknown@example.com"
```

### 3.7 イベント監視（リアルタイム対応）

```python
import win32com.client

class OutlookEventHandler:
    """Outlookイベントハンドラー"""
    
    def OnNewMailEx(self, receivedItemsIDs):
        """
        新着メールイベント
        
        Args:
            receivedItemsIDs: 受信したメールのIDリスト（カンマ区切り）
        """
        logger.info("新着メールを検出")
        
        # メールIDを分割
        mail_ids = receivedItemsIDs.split(',')
        
        for mail_id in mail_ids:
            try:
                # メールアイテムを取得
                mail_item = self.namespace.GetItemFromID(mail_id)
                
                # メール処理を実行
                self.process_mail(mail_item)
                
            except Exception as e:
                logger.error(f"新着メール処理エラー: {e}")

# イベントハンドラーの登録
def register_event_handler(self):
    """イベントハンドラーを登録"""
    # WithEventsでイベントを購読
    self.inbox = win32com.client.WithEvents(
        self.namespace.GetDefaultFolder(6),
        OutlookEventHandler
    )
    logger.info("イベントハンドラー登録完了")
```

---

## 4. 機能詳細設計

### 4.1 Outlook監視機能

#### 4.1.1 機能概要
Outlookの受信トレイを監視し、未読メールまたは未処理メールを取得する。

#### 4.1.2 監視方式

**方式1: ポーリング方式（推奨）**
- 定期的に未読メールをチェック
- 安定性が高い
- CPU負荷が低い

**方式2: イベント駆動方式**
- 新着メール受信時にリアルタイム処理
- 即座に対応可能
- COM接続が不安定になる可能性

#### 4.1.3 クラス設計

```python
import win32com.client
import pythoncom
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Mail:
    """メールデータクラス"""
    mail_id: str
    from_address: str
    to_address: str
    subject: str
    body: str
    html_body: str
    received_date: datetime
    headers: dict
    attachments: List[dict]

class OutlookMonitor:
    """Outlook監視クラス"""
    
    def __init__(self, config: dict):
        """
        初期化
        Args:
            config: Outlook設定
        """
        self.config = config
        self.outlook = None
        self.namespace = None
        self.inbox = None
        self.target_folder = config.get('target_folder', '受信トレイ')
        self.processed_folder = config.get('processed_folder', '受信トレイ/Processed')
        self.category_name = config.get('category_name', 'Redmine起票済み')
    
    def connect(self) -> bool:
        """Outlookに接続"""
        try:
            pythoncom.CoInitialize()
            self.outlook = win32com.client.Dispatch("Outlook.Application")
            self.namespace = self.outlook.GetNamespace("MAPI")
            
            # ログオンを確認
            self.namespace.Logon()
            
            # ターゲットフォルダを取得
            if self.target_folder == '受信トレイ':
                self.inbox = self.namespace.GetDefaultFolder(6)
            else:
                self.inbox = self.get_folder_by_path(self.target_folder)
            
            if not self.inbox:
                raise Exception(f"フォルダが見つかりません: {self.target_folder}")
            
            logger.info(f"Outlook接続成功: {self.target_folder}")
            return True
            
        except Exception as e:
            logger.error(f"Outlook接続エラー: {e}")
            return False
    
    def disconnect(self) -> None:
        """Outlookから切断"""
        try:
            if self.namespace:
                self.namespace.Logoff()
            self.outlook = None
            pythoncom.CoUninitialize()
            logger.info("Outlook切断")
        except Exception as e:
            logger.warning(f"切断時エラー: {e}")
    
    def fetch_unread_mails(self, limit: int = 50) -> List[Mail]:
        """
        未読メールを取得
        Args:
            limit: 取得件数上限
        Returns:
            Mailオブジェクトのリスト
        """
        if not self.inbox:
            logger.error("Outlookに接続されていません")
            return []
        
        try:
            mails = []
            items = self.inbox.Items
            items.Sort("[ReceivedTime]", True)
            
            # 未読かつ、処理済みカテゴリが設定されていないメールを取得
            filtered = items.Restrict(
                f"[Unread] = True AND [Categories] <> '{self.category_name}'"
            )
            
            count = 0
            for item in filtered:
                if count >= limit:
                    break
                
                if item.Class == 43:  # olMail
                    mail = self.extract_mail_data(item)
                    mails.append(mail)
                    count += 1
            
            logger.info(f"未読メール取得: {len(mails)}件")
            return mails
            
        except Exception as e:
            logger.error(f"メール取得エラー: {e}")
            return []
    
    def get_mail_item_by_id(self, mail_id: str):
        """
        メールIDからMailItemを取得
        Args:
            mail_id: EntryID
        Returns:
            MailItemオブジェクト
        """
        try:
            return self.namespace.GetItemFromID(mail_id)
        except Exception as e:
            logger.error(f"メールアイテム取得エラー: {e}")
            return None
    
    def mark_as_processed(self, mail_id: str, ticket_id: str = None) -> bool:
        """
        メールを処理済みとしてマーク
        - カテゴリを設定
        - 既読にする
        - オプション: フォルダに移動
        
        Args:
            mail_id: メールID
            ticket_id: チケット番号（オプション）
        """
        try:
            mail_item = self.get_mail_item_by_id(mail_id)
            if not mail_item:
                return False
            
            # カテゴリを設定
            mail_item.Categories = self.category_name
            
            # 既読にする
            mail_item.UnRead = False
            
            # チケット番号をメモ欄に追加（オプション）
            if ticket_id and self.config.get('add_ticket_to_body', False):
                note = f"\n\n--- Redmineチケット: #{ticket_id} ---"
                mail_item.Body = mail_item.Body + note
            
            mail_item.Save()
            
            # 処理済みフォルダに移動（オプション）
            if self.config.get('move_processed_mails', False):
                self.move_to_folder(mail_item, self.processed_folder)
            
            logger.info(f"処理済みマーク完了: {mail_item.Subject}")
            return True
            
        except Exception as e:
            logger.error(f"処理済みマークエラー: {e}")
            return False
    
    def extract_mail_data(self, mail_item) -> Mail:
        """MailItemからMailオブジェクトを生成"""
        # (前述のコードを使用)
        pass
    
    def get_folder_by_path(self, folder_path: str):
        """パス指定でフォルダを取得"""
        # (前述のコードを使用)
        pass
    
    def move_to_folder(self, mail_item, folder_path: str) -> bool:
        """メールをフォルダに移動"""
        # (前述のコードを使用)
        pass
```

### 4.2 ブラックリストフィルター機能

（基本設計は前述のドキュメントと同じ）

```python
class BlacklistFilter:
    """ブラックリストフィルタークラス"""
    
    # 実装は前述のドキュメントと同じ
    pass
```

### 4.3 重複チェック機能

（基本設計は前述のドキュメントと同じ）

```python
class DuplicateChecker:
    """重複チェッククラス"""
    
    # 実装は前述のドキュメントと同じ
    pass
```

### 4.4 メール解析機能

（基本設計は前述のドキュメントと同じ）

```python
class MailParser:
    """メール解析クラス"""
    
    # 実装は前述のドキュメントと同じ
    pass
```

### 4.5 Redmine連携機能

（基本設計は前述のドキュメントと同じ）

```python
class RedmineClient:
    """Redmine APIクライアントクラス"""
    
    # 実装は前述のドキュメントと同じ
    pass
```

---

## 5. データ設計

### 5.1 設定ファイル設計

#### 5.1.1 config.yaml（Outlook対応版）

```yaml
# Outlook設定
outlook_settings:
  # 監視対象フォルダ（デフォルト: 受信トレイ）
  target_folder: "受信トレイ"
  
  # 処理済みメール移動先（nullの場合は移動しない）
  processed_folder: "受信トレイ/Processed"
  
  # 処理済みメールを移動するか
  move_processed_mails: false
  
  # 処理済みカテゴリ名
  category_name: "Redmine起票済み"
  
  # チケット番号を本文に追記するか
  add_ticket_to_body: false
  
  # メール取得件数上限（1回あたり）
  fetch_limit: 50
  
  # チェック間隔（秒）
  check_interval: 60
  
  # 監視方式（polling または event）
  monitoring_mode: "polling"

# Redmine設定
redmine_settings:
  url: https://redmine.example.com
  api_key: ${REDMINE_API_KEY}
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
  console_output: true  # コンソールにも出力

# スケジューリング設定
scheduler:
  enabled: true
  interval: 60  # 秒
  max_instances: 1  # 同時実行数
  
  # Windowsタスクスケジューラ使用時
  use_task_scheduler: false
  task_name: "AlertMailRedmine"

# 通知設定（オプション）
notification:
  enabled: false
  # Windowsトースト通知
  toast_notification: true
  # エラー時のメール通知
  email_notification:
    enabled: false
    smtp_server: smtp.example.com
    smtp_port: 587
    from_address: alert@example.com
    to_address: admin@example.com
```

#### 5.1.2 blacklist.yaml

（前述のドキュメントと同じ）

#### 5.1.3 redmine_mapping.yaml

（前述のドキュメントと同じ）

### 5.2 環境変数設計

#### 5.2.1 .env ファイル（Windows版）

```bash
# Redmine API認証情報
REDMINE_API_KEY=your_redmine_api_key_here

# データベース設定
DATABASE_PATH=C:\AlertMailRedmine\data\processed_mails.db

# ログレベル（DEBUG, INFO, WARNING, ERROR, CRITICAL）
LOG_LEVEL=INFO

# 実行モード（development, production）
ENVIRONMENT=production

# タイムゾーン
TIMEZONE=Asia/Tokyo

# Outlook設定（オプション）
OUTLOOK_PROFILE=

# 通知設定（オプション）
NOTIFICATION_EMAIL=
```

---

## 6. 処理フロー設計

### 6.1 メインフロー（Windows版）

```
┌─────────────────────────────────────────┐
│          システム起動                    │
│  - Outlook起動確認                      │
│  - COM初期化                            │
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
│  - OutlookMonitor                       │
│  - BlacklistFilter                      │
│  - DuplicateChecker                     │
│  - MailParser                           │
│  - RedmineClient                        │
└───────────────┬─────────────────────────┘
                ↓
┌─────────────────────────────────────────┐
│      Outlookへ接続                       │
│  - COM接続                              │
│  - ターゲットフォルダ取得                │
└───────────────┬─────────────────────────┘
                │
                ↓
        ┌───────────────┐
        │  定期実行ループ  │←─────┐
        │  (ポーリング)   │        │
        └───────┬───────┘        │
                ↓                │
┌─────────────────────────────────────────┐
│      未読メール取得                      │
│  - Outlook Items取得                    │
│  - 未読フィルター適用                    │
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
            │    │   ││処理済みマーク│ │
            │    │   ││- カテゴリ設定│ │
            │    │   ││- 既読化      │ │
            │    │   ││- フォルダ移動│ │
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

### 6.2 起動時チェックフロー

```
システム起動
    ↓
Outlook起動確認
    ├─ 起動している → 続行
    └─ 起動していない
         ↓
       Outlook自動起動試行
         ├─ 成功 → 続行
         └─ 失敗
              ↓
            エラー通知
              ↓
            システム終了
```

### 6.3 エラーリカバリーフロー

```
COM接続エラー発生
    ↓
COM再初期化
    ↓
Outlook再接続試行
    ├─ 成功（3回まで） → 処理続行
    └─ 失敗
         ↓
       エラーログ
         ↓
       待機（60秒）
         ↓
       再試行
```

---

## 7. エラーハンドリング設計

### 7.1 Outlook固有のエラー

| エラー種別 | 原因 | 対応方法 |
|-----------|------|---------|
| COM初期化エラー | Outlook未起動 | 起動確認後リトライ |
| 接続タイムアウト | Outlook応答なし | COM再初期化 |
| アクセス権限エラー | Outlookロック | 待機後リトライ |
| フォルダ未存在 | 設定ミス | フォルダ作成 |
| メールアイテム取得失敗 | メール削除済み | スキップして続行 |

### 7.2 Windows固有のエラーハンドリング

```python
class WindowsErrorHandler:
    """Windows固有エラーハンドラー"""
    
    @staticmethod
    def is_outlook_running() -> bool:
        """Outlookの起動確認"""
        import psutil
        
        for proc in psutil.process_iter(['name']):
            if proc.info['name'].lower() == 'outlook.exe':
                return True
        return False
    
    @staticmethod
    def start_outlook() -> bool:
        """Outlookを起動"""
        import subprocess
        
        try:
            # Outlookを起動（バックグラウンド）
            subprocess.Popen(['outlook.exe'])
            
            # 起動待機（最大30秒）
            for _ in range(30):
                time.sleep(1)
                if WindowsErrorHandler.is_outlook_running():
                    logger.info("Outlook起動完了")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Outlook起動エラー: {e}")
            return False
    
    @staticmethod
    def reinitialize_com():
        """COMを再初期化"""
        try:
            pythoncom.CoUninitialize()
            time.sleep(1)
            pythoncom.CoInitialize()
            logger.info("COM再初期化完了")
            return True
        except Exception as e:
            logger.error(f"COM再初期化エラー: {e}")
            return False
```

### 7.3 例外クラス（Windows版追加）

```python
class OutlookConnectionError(AlertMailSystemError):
    """Outlook接続エラー"""
    pass

class OutlookNotRunningError(AlertMailSystemError):
    """Outlook未起動エラー"""
    pass

class COMInitializationError(AlertMailSystemError):
    """COM初期化エラー"""
    pass

class FolderNotFoundError(AlertMailSystemError):
    """フォルダ未存在エラー"""
    pass
```

---

## 8. セキュリティ設計

### 8.1 Windows環境でのセキュリティ

#### 8.1.1 認証情報の保護

**方法1: Windows資格情報マネージャー使用**

```python
import keyring

# 認証情報の保存
keyring.set_password("AlertMailRedmine", "redmine_api_key", api_key)

# 認証情報の取得
api_key = keyring.get_password("AlertMailRedmine", "redmine_api_key")
```

**方法2: 暗号化ストレージ**

```python
from cryptography.fernet import Fernet
import os

class WindowsCredentialStore:
    """Windows用認証情報ストア"""
    
    def __init__(self):
        # 鍵ファイルをユーザーディレクトリに保存
        self.key_file = os.path.join(
            os.environ['USERPROFILE'],
            '.alert_mail_redmine',
            'key.bin'
        )
        self._ensure_key_file()
    
    def _ensure_key_file(self):
        """鍵ファイルの確認・生成"""
        if not os.path.exists(self.key_file):
            os.makedirs(os.path.dirname(self.key_file), exist_ok=True)
            key = Fernet.generate_key()
            with open(self.key_file, 'wb') as f:
                f.write(key)
            # 鍵ファイルのアクセス権限を制限
            os.chmod(self.key_file, 0o600)
```

#### 8.1.2 ファイルアクセス制御

```python
import win32security
import ntsecuritycon as con

def set_file_permissions(file_path: str):
    """ファイルのアクセス権限を設定（現在のユーザーのみ）"""
    # 現在のユーザーのSIDを取得
    user_sid = win32security.GetTokenInformation(
        win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32security.TOKEN_QUERY
        ),
        win32security.TokenUser
    )[0]
    
    # 新しいDACLを作成
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        con.FILE_ALL_ACCESS,
        user_sid
    )
    
    # ファイルにDACLを適用
    sd = win32security.SECURITY_DESCRIPTOR()
    sd.SetSecurityDescriptorDacl(1, dacl, 0)
    win32security.SetFileSecurity(
        file_path,
        win32security.DACL_SECURITY_INFORMATION,
        sd
    )
```

### 8.2 Outlook操作の監査

```python
def audit_log_mail_operation(operation: str, mail_subject: str, user: str):
    """メール操作の監査ログ"""
    audit_logger.info(
        f"Operation: {operation}, "
        f"Subject: {mail_subject}, "
        f"User: {user}, "
        f"Timestamp: {datetime.now().isoformat()}"
    )
```

---

## 9. 運用設計

### 9.1 Windowsサービス化

#### 9.1.1 NSSMを使用したサービス化

```batch
:: install_service.bat

@echo off
echo AlertMailRedmineシステムをWindowsサービスとして登録します...

:: NSSM (Non-Sucking Service Manager) のパス
set NSSM_PATH=C:\AlertMailRedmine\tools\nssm.exe

:: Pythonインタープリターのパス
set PYTHON_PATH=C:\AlertMailRedmine\venv\Scripts\python.exe

:: メインスクリプトのパス
set SCRIPT_PATH=C:\AlertMailRedmine\src\main.py

:: サービスをインストール
%NSSM_PATH% install AlertMailRedmine %PYTHON_PATH% %SCRIPT_PATH%

:: サービスの設定
%NSSM_PATH% set AlertMailRedmine AppDirectory C:\AlertMailRedmine
%NSSM_PATH% set AlertMailRedmine DisplayName "Alert Mail to Redmine Service"
%NSSM_PATH% set AlertMailRedmine Description "アラートメールをRedmineチケットに自動起票するサービス"
%NSSM_PATH% set AlertMailRedmine Start SERVICE_AUTO_START
%NSSM_PATH% set AlertMailRedmine AppStdout C:\AlertMailRedmine\logs\service_stdout.log
%NSSM_PATH% set AlertMailRedmine AppStderr C:\AlertMailRedmine\logs\service_stderr.log
%NSSM_PATH% set AlertMailRedmine AppRotateFiles 1
%NSSM_PATH% set AlertMailRedmine AppRotateBytes 10485760

echo サービスの登録が完了しました。
echo サービスを開始するには: net start AlertMailRedmine
pause
```

#### 9.1.2 サービスの管理

```batch
:: start_service.bat
net start AlertMailRedmine

:: stop_service.bat
net stop AlertMailRedmine

:: restart_service.bat
net stop AlertMailRedmine
timeout /t 5
net start AlertMailRedmine

:: uninstall_service.bat
sc delete AlertMailRedmine
```

### 9.2 Windowsタスクスケジューラ使用

#### 9.2.1 タスク登録スクリプト

```batch
:: register_task.bat

@echo off
echo Windowsタスクスケジューラにタスクを登録します...

:: タスクスケジューラにタスクを作成
schtasks /create /tn "AlertMailRedmine" ^
  /tr "C:\AlertMailRedmine\venv\Scripts\python.exe C:\AlertMailRedmine\src\main.py" ^
  /sc minute /mo 1 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

echo タスクの登録が完了しました。
pause
```

#### 9.2.2 XMLベースのタスク定義

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>2025-11-11T10:00:00</Date>
    <Author>AlertMailRedmine</Author>
    <Description>アラートメールをRedmineチケットに自動起票</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT1M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2025-11-11T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-21-...</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>C:\AlertMailRedmine\venv\Scripts\python.exe</Command>
      <Arguments>C:\AlertMailRedmine\src\main.py</Arguments>
      <WorkingDirectory>C:\AlertMailRedmine</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
```

### 9.3 ログ管理（Windows版）

#### 9.3.1 Windowsイベントログへの出力

```python
import win32evtlog
import win32evtlogutil

class WindowsEventLogger:
    """Windowsイベントログ出力クラス"""
    
    def __init__(self, source_name: str = "AlertMailRedmine"):
        self.source_name = source_name
        self._register_event_source()
    
    def _register_event_source(self):
        """イベントソースを登録"""
        try:
            win32evtlogutil.AddSourceToRegistry(
                self.source_name,
                msgDLL="",
                eventLogType="Application"
            )
        except Exception as e:
            logger.warning(f"イベントソース登録エラー: {e}")
    
    def log_info(self, message: str):
        """情報レベルのログ"""
        win32evtlogutil.ReportEvent(
            self.source_name,
            1,  # EventID
            eventType=win32evtlog.EVENTLOG_INFORMATION_TYPE,
            strings=[message]
        )
    
    def log_error(self, message: str):
        """エラーレベルのログ"""
        win32evtlogutil.ReportEvent(
            self.source_name,
            2,  # EventID
            eventType=win32evtlog.EVENTLOG_ERROR_TYPE,
            strings=[message]
        )
```

### 9.4 監視とアラート

#### 9.4.1 Windowsパフォーマンスカウンター

```python
import win32pdh

class PerformanceMonitor:
    """パフォーマンス監視クラス"""
    
    def get_process_memory_usage(self, process_name: str) -> float:
        """プロセスのメモリ使用量を取得（MB）"""
        import psutil
        
        for proc in psutil.process_iter(['name', 'memory_info']):
            if proc.info['name'].lower() == process_name.lower():
                return proc.info['memory_info'].rss / 1024 / 1024
        return 0.0
    
    def get_cpu_usage(self) -> float:
        """CPU使用率を取得"""
        import psutil
        return psutil.cpu_percent(interval=1)
```

#### 9.4.2 Windowsトースト通知

```python
from win10toast import ToastNotifier

class WindowsNotifier:
    """Windows通知クラス"""
    
    def __init__(self):
        self.toaster = ToastNotifier()
    
    def show_notification(
        self,
        title: str,
        message: str,
        duration: int = 10
    ):
        """トースト通知を表示"""
        try:
            self.toaster.show_toast(
                title,
                message,
                duration=duration,
                threaded=True
            )
        except Exception as e:
            logger.warning(f"通知表示エラー: {e}")
    
    def show_ticket_created(self, ticket_id: str, subject: str):
        """チケット作成通知"""
        self.show_notification(
            "チケット作成完了",
            f"#{ticket_id}: {subject}"
        )
    
    def show_error(self, error_message: str):
        """エラー通知"""
        self.show_notification(
            "エラー発生",
            error_message
        )
```

### 9.5 バックアップ（Windows版）

```batch
:: backup.bat

@echo off
setlocal

set BACKUP_DIR=D:\Backup\AlertMailRedmine
set TIMESTAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
set BACKUP_FILE=%BACKUP_DIR%\backup_%TIMESTAMP%.zip

:: バックアップディレクトリ作成
if not exist %BACKUP_DIR% mkdir %BACKUP_DIR%

:: 7-Zipでアーカイブ作成
"C:\Program Files\7-Zip\7z.exe" a -tzip %BACKUP_FILE% ^
  C:\AlertMailRedmine\config\*.yaml ^
  C:\AlertMailRedmine\data\processed_mails.db ^
  C:\AlertMailRedmine\.env

:: 古いバックアップを削除（30日以上前）
forfiles /p %BACKUP_DIR% /s /m backup_*.zip /d -30 /c "cmd /c del @path"

echo バックアップ完了: %BACKUP_FILE%
```

---

## 10. インストール・セットアップ手順

### 10.1 前提条件の確認

```batch
:: check_prerequisites.bat

@echo off
echo ====================================
echo 前提条件チェック
echo ====================================
echo.

:: Windows バージョン確認
ver
echo.

:: Python インストール確認
python --version
if %errorlevel% neq 0 (
    echo [エラー] Python 3.8以上がインストールされていません。
    pause
    exit /b 1
)
echo [OK] Python がインストールされています。
echo.

:: Outlook インストール確認
reg query "HKEY_CLASSES_ROOT\Outlook.Application" >nul 2>&1
if %errorlevel% neq 0 (
    echo [エラー] Microsoft Outlook がインストールされていません。
    pause
    exit /b 1
)
echo [OK] Microsoft Outlook がインストールされています。
echo.

:: インターネット接続確認
ping -n 1 google.com >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] インターネット接続が確認できません。
) else (
    echo [OK] インターネット接続が確認できました。
)
echo.

echo すべての前提条件が満たされています。
pause
```

### 10.2 インストールスクリプト

```batch
:: setup.bat

@echo off
echo ====================================
echo AlertMailRedmine セットアップ
echo ====================================
echo.

:: 1. ディレクトリ作成
echo [1/7] ディレクトリを作成しています...
if not exist data mkdir data
if not exist logs mkdir logs
if not exist config mkdir config
echo 完了
echo.

:: 2. 仮想環境作成
echo [2/7] Python仮想環境を作成しています...
python -m venv venv
call venv\Scripts\activate.bat
echo 完了
echo.

:: 3. 依存パッケージインストール
echo [3/7] 依存パッケージをインストールしています...
pip install --upgrade pip
pip install -r requirements.txt
echo 完了
echo.

:: 4. 設定ファイルのコピー
echo [4/7] 設定ファイルを作成しています...
if not exist config\config.yaml (
    copy config\config.yaml.example config\config.yaml
)
if not exist config\blacklist.yaml (
    copy config\blacklist.yaml.example config\blacklist.yaml
)
if not exist config\redmine_mapping.yaml (
    copy config\redmine_mapping.yaml.example config\redmine_mapping.yaml
)
if not exist .env (
    copy .env.example .env
)
echo 完了
echo.

:: 5. データベース初期化
echo [5/7] データベースを初期化しています...
python src\init_db.py
echo 完了
echo.

:: 6. 接続テスト
echo [6/7] 接続テストを実行しています...
python src\test_connection.py
if %errorlevel% neq 0 (
    echo [警告] 接続テストに失敗しました。設定を確認してください。
)
echo 完了
echo.

:: 7. ショートカット作成
echo [7/7] デスクトップショートカットを作成しています...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%USERPROFILE%\Desktop\AlertMailRedmine.lnk'); $s.TargetPath = '%CD%\start.bat'; $s.WorkingDirectory = '%CD%'; $s.Save()"
echo 完了
echo.

echo ====================================
echo セットアップが完了しました！
echo ====================================
echo.
echo 次の手順:
echo 1. .envファイルを編集してRedmine APIキーを設定
echo 2. config\config.yamlを編集して設定をカスタマイズ
echo 3. start.batを実行してシステムを起動
echo.
pause
```

### 10.3 設定ガイド

#### 10.3.1 .envファイルの設定

```batch
:: config_wizard.bat

@echo off
setlocal enabledelayedexpansion

echo ====================================
echo 設定ウィザード
echo ====================================
echo.

:: Redmine API キーの入力
set /p REDMINE_API_KEY="Redmine APIキーを入力してください: "
echo REDMINE_API_KEY=%REDMINE_API_KEY%> .env

echo.
echo 設定が完了しました。
echo .envファイルに保存されました。
pause
```

#### 10.3.2 GUI設定ツール（オプション）

```python
# src/gui_config.py
import tkinter as tk
from tkinter import ttk, messagebox
import yaml

class ConfigGUI:
    """設定GUI"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AlertMailRedmine 設定")
        self.root.geometry("600x400")
        
        self.create_widgets()
    
    def create_widgets(self):
        """ウィジェット作成"""
        # タブ作成
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Outlook設定タブ
        outlook_frame = ttk.Frame(notebook)
        notebook.add(outlook_frame, text="Outlook設定")
        self.create_outlook_tab(outlook_frame)
        
        # Redmine設定タブ
        redmine_frame = ttk.Frame(notebook)
        notebook.add(redmine_frame, text="Redmine設定")
        self.create_redmine_tab(redmine_frame)
        
        # ブラックリストタブ
        blacklist_frame = ttk.Frame(notebook)
        notebook.add(blacklist_frame, text="ブラックリスト")
        self.create_blacklist_tab(blacklist_frame)
        
        # 保存ボタン
        save_btn = ttk.Button(
            self.root,
            text="設定を保存",
            command=self.save_config
        )
        save_btn.pack(pady=10)
    
    def create_outlook_tab(self, parent):
        """Outlook設定タブを作成"""
        # ターゲットフォルダ
        ttk.Label(parent, text="監視フォルダ:").grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.target_folder_var = tk.StringVar(value="受信トレイ")
        ttk.Entry(
            parent,
            textvariable=self.target_folder_var,
            width=40
        ).grid(row=0, column=1, padx=5, pady=5)
        
        # チェック間隔
        ttk.Label(parent, text="チェック間隔（秒）:").grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.check_interval_var = tk.StringVar(value="60")
        ttk.Entry(
            parent,
            textvariable=self.check_interval_var,
            width=20
        ).grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        
        # 処理済みメール移動
        self.move_processed_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="処理済みメールを移動する",
            variable=self.move_processed_var
        ).grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky=tk.W)
    
    def create_redmine_tab(self, parent):
        """Redmine設定タブを作成"""
        # RedmineURL
        ttk.Label(parent, text="Redmine URL:").grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.redmine_url_var = tk.StringVar()
        ttk.Entry(
            parent,
            textvariable=self.redmine_url_var,
            width=40
        ).grid(row=0, column=1, padx=5, pady=5)
        
        # APIキー
        ttk.Label(parent, text="API キー:").grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.api_key_var = tk.StringVar()
        ttk.Entry(
            parent,
            textvariable=self.api_key_var,
            width=40,
            show="*"
        ).grid(row=1, column=1, padx=5, pady=5)
        
        # プロジェクトID
        ttk.Label(parent, text="プロジェクトID:").grid(
            row=2, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.project_id_var = tk.StringVar(value="1")
        ttk.Entry(
            parent,
            textvariable=self.project_id_var,
            width=20
        ).grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)
        
        # 接続テストボタン
        ttk.Button(
            parent,
            text="接続テスト",
            command=self.test_connection
        ).grid(row=3, column=0, columnspan=2, pady=10)
    
    def create_blacklist_tab(self, parent):
        """ブラックリストタブを作成"""
        # 除外送信元アドレス
        ttk.Label(parent, text="除外する送信元アドレス:").pack(
            anchor=tk.W, padx=5, pady=5
        )
        
        self.exclude_from_text = tk.Text(parent, height=10, width=60)
        self.exclude_from_text.pack(padx=5, pady=5)
    
    def save_config(self):
        """設定を保存"""
        try:
            # 設定を辞書に格納
            config = {
                'outlook_settings': {
                    'target_folder': self.target_folder_var.get(),
                    'check_interval': int(self.check_interval_var.get()),
                    'move_processed_mails': self.move_processed_var.get()
                },
                'redmine_settings': {
                    'url': self.redmine_url_var.get(),
                    'api_key': '${REDMINE_API_KEY}',
                    'default_project_id': int(self.project_id_var.get())
                }
            }
            
            # YAMLファイルに保存
            with open('config/config.yaml', 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True)
            
            # .envファイルに保存
            with open('.env', 'w') as f:
                f.write(f"REDMINE_API_KEY={self.api_key_var.get()}\n")
            
            messagebox.showinfo("成功", "設定を保存しました。")
            
        except Exception as e:
            messagebox.showerror("エラー", f"設定の保存に失敗しました:\n{e}")
    
    def test_connection(self):
        """接続テスト"""
        # テスト処理（省略）
        messagebox.showinfo("接続テスト", "接続テストを実行しました。")
    
    def run(self):
        """GUIを実行"""
        self.root.mainloop()

if __name__ == '__main__':
    app = ConfigGUI()
    app.run()
```

### 10.4 起動スクリプト

```batch
:: start.bat

@echo off
echo AlertMailRedmine システムを起動しています...

:: 仮想環境をアクティベート
call venv\Scripts\activate.bat

:: Outlook起動確認
tasklist /FI "IMAGENAME eq OUTLOOK.EXE" 2>NUL | find /I /N "OUTLOOK.EXE">NUL
if "%ERRORLEVEL%"=="1" (
    echo Outlookが起動していません。Outlookを起動します...
    start outlook.exe
    timeout /t 10
)

:: メインスクリプト実行
python src\main.py

pause
```

### 10.5 停止スクリプト

```batch
:: stop.bat

@echo off
echo AlertMailRedmine システムを停止しています...

:: Pythonプロセスを終了
taskkill /F /IM python.exe /FI "WINDOWTITLE eq AlertMailRedmine*"

echo システムを停止しました。
pause
```

---

## 11. 付録

### 11.1 requirements.txt

```
# Outlook連携
pywin32==305
pythoncom==305

# HTTP通信
requests==2.31.0

# 設定管理
PyYAML==6.0.1

# スケジューリング
APScheduler==3.10.4

# ログ管理
python-logging-loki==0.3.1

# データベース
# SQLite3は標準ライブラリ

# Windows通知（オプション）
win10toast==0.9

# Windows資格情報マネージャー（オプション）
keyring==24.2.0

# セキュリティ
cryptography==41.0.7

# システム情報
psutil==5.9.6

# GUI（オプション）
# tkinterは標準ライブラリ

# テスト
pytest==7.4.3
pytest-cov==4.1.0

# ユーティリティ
python-dotenv==1.0.0
```

### 11.2 よくある質問（Windows版）

**Q1: Outlookが起動していないとどうなりますか？**

A: システムはOutlookの起動を検出し、必要に応じて自動的にOutlookを起動します。ただし、Outlookのプロファイル設定が必要な場合は手動起動が必要です。

**Q2: 複数のメールアカウントがある場合は？**

A: 設定ファイルで`target_folder`を指定することで、特定のアカウントの受信トレイを監視できます。例: `mailbox@example.com/受信トレイ`

**Q3: Outlookが固まった場合は？**

A: システムはCOM接続エラーを検出し、自動的に再接続を試みます。それでも復旧しない場合は、Outlookを再起動してください。

**Q4: Windows起動時に自動的に実行したい**

A: Windowsサービス化（NSSM使用）またはタスクスケジューラで「ログオン時」にトリガー設定してください。

**Q5: ネットワークドライブに設置できますか？**

A: 推奨しません。ローカルドライブ（C:ドライブなど）に設置してください。ネットワーク遅延がCOM操作に影響する可能性があります。

### 11.3 トラブルシューティング（Windows版）

| 問題 | 原因 | 対処法 |
|-----|------|-------|
| COM初期化エラー | Outlook未起動 | Outlookを起動してから実行 |
| `pywintypes.com_error` | COM接続失敗 | Outlookを再起動、システムを再起動 |
| フォルダが見つからない | 設定ミス | config.yamlのフォルダパスを確認 |
| メール取得できない | アクセス権限 | Outlookを管理者権限で起動 |
| サービス起動失敗 | 権限不足 | 管理者権限でサービスをインストール |

### 11.4 パフォーマンスチューニング

```yaml
# config.yaml (高負荷時の設定例)

outlook_settings:
  # 取得件数を減らす
  fetch_limit: 20
  
  # チェック間隔を長くする
  check_interval: 120
  
  # バッチ処理を有効化
  batch_processing: true
  batch_size: 10

# メモリ使用量削減
performance:
  # メール本文の最大長
  max_body_length: 10000
  
  # 古いログの削除
  log_retention_days: 7
  
  # データベースの自動VACUUM
  db_auto_vacuum: true
```

### 11.5 変更履歴

| バージョン | 日付 | 変更内容 | 作成者 |
|----------|------|---------|-------|
| 1.0 | 2025-11-11 | Windows Outlook対応版初版作成 | - |

---

## 文書の終わり

本設計書はWindows環境でローカルのOutlookを使用する場合の実装ガイドです。
ご質問やサポートが必要な場合は、プロジェクトチームまでご連絡ください。
