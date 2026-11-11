<p align="center">
  <img src="docs/banner.png" alt="CleanYourMail — ノイズを取り除いた受信トレイ" width="100%">
</p>

<p align="center">
  <a href="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml"><img src="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/license-MIT-b9f36a?labelColor=08110d" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12%2B-b9f36a?labelColor=08110d" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/windows-10%2F11%20x64-b9f36a?labelColor=08110d" alt="Windows 10/11 x64">
  <img src="https://img.shields.io/badge/local--by--default-opt%20in%20feedback-b9f36a?labelColor=08110d" alt="デフォルトでローカル、フィードバックは任意">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português (BR)</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <b>日本語</b> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ko.md">한국어</a>
</p>

# CleanYourMail アプリ

**ノイズを取り除いた受信トレイを、ネイティブ Windows アプリで。** CleanYourMail アプリは、[CleanYourMail](https://github.com/jparedesDS/cleanyourmail) CLI の PySide6 フロントエンドです。メールボックスの接続、片付ける対象の選択、元に戻せるプランの確認、取り消しまでをガイドします。

ブラウザなし、ローカルサーバーなし、アカウントなし、テレメトリーなし、本文へのアクセスなし、完全削除なし。アプリ自身が行うネットワークリクエストは、あなたが明示的に送信するフィードバックの POST だけです。

> **ステータス:** `0.4.0` は現在の Windows 向け Early MVP リリースです。アプリのヘッダーとウェブサイトから送れるオプションのフィードバックを追加しました。インストーラーには、固定された CleanYourMail CLI `1.2.2` がサイドカーとして同梱されています。Gmail は検証済みです。Outlook は Microsoft の同意モデルに依存します。[プロバイダーの状態](#provider-status)を参照してください。

## ダウンロード

[Windows 10/11 x64 用 CleanYourMail アプリ 0.4.0](https://github.com/jparedesDS/cleanyourmail-app/releases/latest) は、固定された CleanYourMail CLI `1.2.2` をサイドカーとして同梱するユーザー単位のインストーラーで、管理者権限は不要です。

0.4.0 のインストーラーはコード署名されていません。初回起動時に Windows SmartScreen が「不明な発行元」の警告を表示することがあります。**詳細情報** を選び、次に **実行** を選んでから、リリースで公開されている SHA-256 を `CleanYourMail-Setup-0.4.0.exe` と照合してください:

```powershell
Get-FileHash .\CleanYourMail-Setup-0.4.0.exe -Algorithm SHA256
```

リリースでは `HASH  filename` 形式の `.sha256` ファイルも公開されています。

Gmail はアプリパスワードと 2 段階認証で動作します。Outlook / Microsoft 365 はワンクリックでは動作しません。Microsoft 365 にはテナント管理者の同意が必要で、個人の Outlook.com アカウントには検証済みの発行元が必要です。macOS と Linux は 0.4.0 の対象外です。

## このアプリが必要な理由

CleanYourMail CLI はエンジンであり、唯一の正となる情報源です。IMAP アクセス、分類、プラン、元に戻せる移動、取り消しジャーナルはすでに CLI が担っています。足りないのは、ターミナルを使いたくない人、TOML ファイルを編集したくない人のための短い道筋です。

このアプリは、エンジンを複製せずにその道筋を追加します:

- プロバイダーを選び、設定を手書きせずに接続できます。
- チェックボックスとラジオボタンでカテゴリとモードを選べます。
- 何かが変わる前に、スキャンしてレポートを読み、プランを確認できます。
- 明示的なレビューの後にだけ適用し、同じウィンドウから取り消せます。
- すべての画面を英語またはスペイン語で読めます。

アプリ自身が IMAP、プランニング、移動、取り消し、配信停止を実装することはありません。固定された CleanYourMail CLI サイドカーを呼び出して結果を表示するため、安全モデルもルールも 1 つに保たれます。

## スクリーンショット

<p align="center">
  <img src="docs/images/app-provider.png" alt="プロバイダーを選び、メールボックスアドレスを入力" width="49%">
  <img src="docs/images/app-review.png" alt="適用前にプランを確認" width="49%">
</p>

<p align="center"><em>合成デモデータです。プロバイダーを選び、適用する前にプランを確認してください。</em></p>

## 要件

- インストーラーは Windows 10/11 x64 向けです。
- ソースから実行する場合のみ Python **3.12+** が必要です。
- CleanYourMail CLI `1.2.2` のサイドカー。インストーラーには同梱されています。開発時は、同じ JSON 契約を持つビルド済みの `cym-cli.exe` を `CYM_CLI` に指定してください。アプリが `mail.py` を直接実行することはありません。

## 開発

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` は `CleanYourMail app 0.4.0` を出力します。

テストを実行:

```bash
python -m pytest -q
```

スイートはダミーの CLI フィクスチャを使います。実際のメールボックス、認証情報、ネットワークアクセスは必要ありません。

## アプリの機能

1. **ようこそ / プロバイダー。** Gmail、Outlook / Microsoft 365、Yahoo、iCloud、Fastmail、Proton Bridge、カスタム IMAP から選び、メールアドレスを入力します。
2. **接続。** Gmail はアプリパスワードのガイド付きフロー、Outlook はデバイスコードフロー、その他はプロバイダー別のアプリパスワードのヘルプを用意しています。通常のパスワードを求められることはありません。
3. **設定。** 片付けるカテゴリ、フォルダーかアーカイブか、保護、上限、言語。
4. **確認と整理。** スキャン、レポート、プラン、必須レビュー、上限付きの適用、取り消しジャーナル。プランの配信停止列は情報表示のみです。このビルドは配信停止リクエストを送信せず、適用は常に `--action move` で実行されます。

## フィードバック

フィードバックは **オプトインで手動** です。アプリのヘッダーにある **フィードバック** ボタン、または[ウェブサイトのフォーム](https://cleanyourmail.org/#feedback)から開けます。バックグラウンドで収集されるものはなく、**送信** を押して同意行に同意するまで、アプリは何も送信しません。

- アプリは、アプリとサイドカーのバージョン、Windows のバージョン、プロバイダー名、フォルダー／アーカイブのモード、選択したカテゴリ、言語を **編集可能なチェックリスト** に事前入力します。
- 共有したくないものは編集または削除してください。パスワード、トークン、メールアドレス、メールの件名、メッセージ ID、ファイルパスをメッセージやチェックリストに **含めないでください**。
- 任意の連絡先フィールドは、Discord のハンドル、GitHub ユーザー名、メールアドレスを残せる唯一の場所です。必須ではありません。
- リクエストは Cloudflare Worker（`cleanyourmail-feedback`）に送られ、検証されたうえで非公開の Discord チャンネルに転送されます。Discord の webhook は Cloudflare のシークレットであり、アプリやウェブサイトに同梱されることはありません。
- **アカウント、テレメトリー、分析、クラッシュレポートはありません。** Worker はメッセージ本文を保存せず、短時間のソルト付き IP レート制限を適用します。

<a id="provider-status"></a>

## プロバイダーの状態

| プロバイダー | アプリでの経路 | 状態 |
|---|---|---|
| Gmail | アプリパスワード + 2FA | 合格、CLI 1.2.2 で検証済み |
| Outlook / Microsoft 365 | デバイスコード | 一部対応: Microsoft 365 はテナント管理者の同意が必要。個人の Outlook.com アカウントは検証済みの発行元が必要 |
| Yahoo、iCloud、Fastmail | アプリパスワード | 文書化済み、スモークテスト未実施 |
| Proton Bridge | Bridge パスワード | 文書化済み、スモークテスト未実施 |
| カスタム IMAP | ホスト。TLS 付きの固定ポート 993 | 文書化済み、スモークテスト未実施 |

アプリはこれらの状態を正直に示します。Outlook のワンクリック対応をうたうことはありません。

## セキュリティモデル

- **オプトインのフィードバックを除き、ローカルのみ。** アカウント、クラウド、テレメトリー、本文へのアクセスはありません。アプリはバックグラウンドでネットワークリクエストを行いません。自身が行う唯一のリクエストは、送信を押して同意行に同意した後のフィードバック POST です。
- **CLI のみ。** アプリは CLI にない機能を追加できません。
- **argv にシークレットを置かない。** アプリパスワードは CLI の `password_file` に書き込まれ、コマンドライン引数として渡されることはありません。
- **アプリ設定にシークレットを保存しない。** シークレットが QSettings、ログ、エラーダイアログ、テスト出力に入ることはありません。
- **まずレビュー。** レビュー済みのプランなしに書き込みません。取り消しは常にワンクリックです。
- **完全削除なし。** 移動とアーカイブは元に戻せます。
- **0.4.0 では配信停止なし。** プランに配信停止モードが表示されることはありますが、適用はメッセージを移動するだけです。
- **英語とスペイン語を同等にサポート。** すべての文字列は `i18n/*.json` にあります。

脆弱性の報告方法は [SECURITY.md](SECURITY.md) を参照してください。

## プロジェクト構成

| パス | 内容 |
|---|---|
| `src/cleanyourmail_app/` | ネイティブアプリのパッケージ。 |
| `src/cleanyourmail_app/version.py` | アプリバージョンの唯一の情報源。 |
| `src/cleanyourmail_app/__main__.py` | `python -m cleanyourmail_app` のエントリーポイント。 |
| `src/cleanyourmail_app/app.py` | ローカルサービスを構築し、ウィザードを開きます。 |
| `src/cleanyourmail_app/ui/` | PySide6 のウィンドウ、ページ、ウィジェット、テーマ、リソース。 |
| `src/cleanyourmail_app/domain/` | プロバイダーカタログ、設定、ユーザー設定、プランモデル。 |
| `src/cleanyourmail_app/services/` | サイドカークライアント（`cli.py`）、構成（`config.py`）、シークレット（`secrets.py`）、OAuth（`oauth.py`）、設定（`settings.py`）。 |
| `src/cleanyourmail_app/i18n/` | 英語とスペイン語の文字列。 |
| `scripts/` | サイドカーとアプリのビルド、インストーラーのスモークテスト。 |
| `packaging/` | Inno Setup スクリプトとアイコン。 |
| `tests/` | ダミーの CLI フィクスチャを使う pytest と pytest-qt のスイート。 |
| `docs/superpowers/specs/` | 設計ドキュメント（アプリ 0.3.0、フィードバック 0.4.0）。 |
| `docs/superpowers/plans/` | タスクごとの実装計画。 |

## リンク

- アプリのリリース: <https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- Skill と CLI: <https://github.com/jparedesDS/cleanyourmail>
- ウェブサイト: <https://cleanyourmail.org/>
- 安全モデル: <https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。
