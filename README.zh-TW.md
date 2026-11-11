<p align="center">
  <img src="docs/banner.png" alt="CleanYourMail — 你的收件匣，減去雜訊" width="100%">
</p>

<p align="center">
  <a href="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml"><img src="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml/badge.svg" alt="測試"></a>
  <img src="https://img.shields.io/badge/license-MIT-b9f36a?labelColor=08110d" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12%2B-b9f36a?labelColor=08110d" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/windows-10%2F11%20x64-b9f36a?labelColor=08110d" alt="Windows 10/11 x64">
  <img src="https://img.shields.io/badge/local--by--default-opt%20in%20feedback-b9f36a?labelColor=08110d" alt="預設本機，選用意見回饋">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português (BR)</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <b>繁體中文</b> ·
  <a href="README.ko.md">한국어</a>
</p>

# CleanYourMail 應用程式

**你的收件匣，減去雜訊——一款原生 Windows 應用程式。** CleanYourMail 應用程式是 CleanYourMail CLI 的 PySide6 前端。它會引導你連接信箱、選擇要清理的內容、檢視可復原的計畫，並在之後復原。

沒有瀏覽器、本機伺服器、帳戶、遙測，不讀取郵件本文，也不會永久刪除。應用程式本身只會連線至公開的 GitHub 發行來源（用於更新）與意見回饋 Worker（僅在你按下傳送並同意後）。

> **狀態：** `0.6.0` 是目前的 Windows 早期 MVP 版本。它新增了自動更新：已安裝的應用程式會檢查公開的 GitHub 發行頁、驗證安裝程式的 SHA-256，並在一次確認後安裝。安裝程式會捆綁凍結的 CleanYourMail CLI `1.3.0` sidecar。Gmail 已驗證；Outlook 取決於 Microsoft 的同意模式。請見[提供者狀態](#provider-status)。

## 下載

[適用於 Windows 10/11 x64 的 CleanYourMail 應用程式 0.6.0](https://github.com/jparedesDS/cleanyourmail-app/releases/latest) 是以每位使用者為範圍的安裝程式，會捆綁固定版本的 CleanYourMail CLI `1.3.0` sidecar，且不需要系統管理員權限。

0.6.0 安裝程式未經程式碼簽章。首次啟動時，Windows SmartScreen 可能會顯示「未知的發行者」警告：請選擇**更多資訊**，再選擇**仍要執行**，並將隨版本發行的 SHA-256 與 `CleanYourMail-Setup-0.6.0.exe` 比對：

```powershell
Get-FileHash .\CleanYourMail-Setup-0.6.0.exe -Algorithm SHA256
```

發行頁也提供 `.sha256` 檔案，格式為 `HASH  filename`。

## 自動更新

已安裝的應用程式最多每六小時檢查一次[公開的 GitHub 發行頁](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)，頂欄的 **Updates** 按鈕可隨時手動檢查。該請求會向 GitHub 說明應用程式版本和你的 IP；不會傳送帳戶、信箱或權杖資料。

有新版本時，橫幅會提供 **Install update** 和 **Later**。**Install update** 會要求一次確認。隨後應用程式透過 HTTPS 下載完全相符的 `CleanYourMail-Setup-<version>.exe` 及其 `.sha256`，在執行任何內容前驗證 SHA-256，關閉應用程式，為目前使用者靜默安裝並重新開啟新版本。

失敗不會關閉應用程式，仍可繼續使用。自動檢查失敗時不會顯示任何內容；按下 **Updates** 可手動檢查。手動檢查失敗時會顯示本地化訊息和 **Open GitHub**。如果發行缺少有效的安裝程式或校驗和，橫幅會顯示 **Open GitHub** 而不是 **Install update**。下載、驗證或雜湊失敗時會顯示本地化錯誤，可用 **Install update** 重試，也可用 **Open GitHub** 開啟發行頁。如果更新助手無法啟動，應用程式會保持開啟，橫幅會提供 **Open GitHub**。如果安裝程式已啟動但失敗，助手會重新開啟舊版應用程式；不會儲存失敗橫幅，因此請用 **Updates** 重試或手動開啟發行頁。

0.6.0 安裝程式未經程式碼簽章，因此更新時 SmartScreen 可能像手動執行安裝程式一樣發出警告：請選擇**更多資訊**，再選擇**仍要執行**。SHA-256 證明下載完整，不證明發行者身分；程式碼簽章是下一步安全措施。如果無法自動安裝（例如從原始碼執行），同一流程會提供發行頁，供你手動安裝。

Gmail 可搭配應用程式密碼與兩步驟驗證使用。Outlook / Microsoft 365 無法一鍵完成：Microsoft 365 需要租用戶系統管理員同意，個人 Outlook.com 帳戶則需要已驗證的發行者。macOS 與 Linux 不在 0.6.0 的範圍內。

## 為什麼需要這個應用程式

CleanYourMail CLI 是引擎，也是唯一的真實來源。它已負責 IMAP 存取、分類、計畫、可復原的移動與復原日誌。它缺少的，是為不想使用終端機或編輯 TOML 檔案的人提供一條捷徑。

這個應用程式在不重複實作引擎的前提下補上這條路：

- 選擇提供者並連線，不必手寫設定檔。
- 用核取方塊和選項按鈕選擇類別與模式。
- 在任何變更發生前掃描、閱讀報告並檢查計畫。
- 只有在明確檢視後才套用，然後從同一個視窗復原。
- 所有畫面都能以英文或西班牙文閱讀。

應用程式本身從不實作 IMAP、規劃、移動、復原或取消訂閱。它會呼叫凍結的 CleanYourMail CLI sidecar 並呈現結果，因此只有一套安全模型和一組規則。

## 螢幕擷取畫面

<p align="center">
  <img src="docs/images/app-provider.png" alt="選擇提供者並輸入信箱地址" width="49%">
  <img src="docs/images/app-review.png" alt="在套用前檢視計畫" width="49%">
</p>

<p align="center"><em>合成示範資料。選擇服務商，並在套用前檢視計畫。</em></p>

## 需求

- 安裝程式需要 Windows 10/11 x64。
- 只有從原始碼執行時才需要 Python **3.12+**。
- CleanYourMail CLI `1.3.0` sidecar。安裝程式已捆綁；開發時請將 `CYM_CLI` 指向具有相同 JSON 契約的已建置 `cym-cli.exe`。應用程式不會直接執行 `mail.py`。

## 開發

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` 會輸出 `CleanYourMail app 0.6.0`。

執行測試：

```bash
python -m pytest -q
```

測試套件使用模擬 CLI 測試資料，永遠不需要真實信箱、認證資訊或網路存取。

## 應用程式的功能

1. **歡迎 / 提供者。** 選擇 Gmail、Outlook / Microsoft 365、Yahoo、iCloud、Fastmail、Proton Bridge 或自訂 IMAP，並輸入電子郵件地址。
2. **連線。** Gmail 使用引導式應用程式密碼流程，Outlook 使用裝置代碼流程，其餘提供者則有各自的應用程式密碼說明。應用程式絕不會要求一般密碼。
3. **偏好設定。** 要清理的類別、資料夾或封存、保護項目、限制與語言。
4. **檢視與清理。** 掃描、報告、計畫、檢視關卡、依限制套用，以及復原日誌。計畫中的取消訂閱欄僅供參考：此版本從不送出取消訂閱要求，套用時一律使用 `--action move`。

## 意見回饋

意見回饋是**選用且手動**的。使用應用程式頂欄的**意見回饋**按鈕，或[網站表單](https://cleanyourmail.org/#feedback)。應用程式不會在背景收集任何意見回饋資料；在你按下**傳送**並接受同意聲明之前，表單不會送出任何內容。唯一的自動網路請求是上文所述的更新檢查。

- 應用程式會預先填入一份**可編輯的檢查清單**，包含應用程式與 sidecar 版本、Windows 版本、提供者名稱、資料夾/封存模式、已選類別與語言。
- 不想分享的內容可以修改或刪除。請**不要**在訊息或檢查清單中填入密碼、權杖、電子郵件地址、郵件主旨、訊息 ID 或檔案路徑。
- 選填的聯絡欄位是唯一可以留下 Discord 帳號、GitHub 使用者名稱或電子郵件地址的地方。它永遠不是必填欄位。
- 請求會送到 Cloudflare Worker（`cleanyourmail-feedback`），由它驗證後轉送到私人 Discord 頻道。Discord webhook 是 Cloudflare 機密，絕不會隨應用程式或網站發布。
- **沒有帳戶、沒有遙測、沒有分析，也沒有當機報告。** Worker 不儲存訊息本文，並會套用以加鹽 IP 為基礎的短期速率限制。

<a id="provider-status"></a>

## 提供者狀態

| 提供者 | 應用程式內方式 | 狀態 |
|---|---|---|
| Gmail | 應用程式密碼 + 兩步驟驗證 | 通過，已用 CLI 1.3.0 驗證 |
| Outlook / Microsoft 365 | 裝置代碼 | 部分可用：Microsoft 365 需要租用戶系統管理員同意；Outlook.com 個人帳戶需要已驗證的發行者 |
| Yahoo, iCloud, Fastmail | 應用程式密碼 | 已有文件，未做冒煙測試 |
| Proton Bridge | Bridge 密碼 | 已有文件，未做冒煙測試 |
| 自訂 IMAP | 主機；固定連接埠 993，啟用 TLS | 已有文件，未做冒煙測試 |

應用程式會如實回報這些狀態。它不會宣稱 Outlook 支援一鍵連線。

## 安全模型

- **預設本機，選用意見回饋除外。** 沒有帳戶、雲端、遙測或本文存取。應用程式本身只發出兩類請求：公開的 GitHub 發行檢查（僅版本與 IP；最多每六小時一次，或按下 **Updates** 時）以及按下傳送並同意後的意見回饋 POST。郵件網路存取由 sidecar 負責。
- **更新經過驗證。** 安裝程式透過 HTTPS 從 GitHub 發行頁下載，使用公開的 SHA-256 驗證，並且只在一次確認後執行。0.6.0 安裝程式未經程式碼簽章，因此 SmartScreen 可能發出警告；SHA-256 證明完整性，不證明發行者。
- **僅透過 CLI。** 應用程式無法增加 CLI 沒有的能力。
- **命令列引數中沒有機密。** 應用程式密碼會寫入 CLI 的 `password_file`；應用程式絕不會將它們當作命令列引數傳遞。
- **應用程式設定中不保留機密。** 機密絕不會進入 QSettings、日誌、錯誤對話方塊或測試輸出。
- **先檢視。** 沒有檢視過的計畫就不會寫入；復原永遠只差一次點擊。
- **不永久刪除。** 移動與封存都可復原。
- **0.6.0 沒有取消訂閱。** 計畫可能顯示取消訂閱模式，但套用時只會移動郵件。
- **英文與西班牙文都是完整支援的語言。** 所有字串都位於 `i18n/*.json`。

請見 [SECURITY.md](SECURITY.md) 了解如何回報漏洞。

## 專案結構

| 路徑 | 說明 |
|---|---|
| `src/cleanyourmail_app/` | 原生應用程式套件。 |
| `src/cleanyourmail_app/version.py` | 應用程式版本的唯一來源。 |
| `src/cleanyourmail_app/__main__.py` | `python -m cleanyourmail_app` 進入點。 |
| `src/cleanyourmail_app/app.py` | 建構本機服務並開啟精靈。 |
| `src/cleanyourmail_app/ui/` | PySide6 視窗、頁面、小工具、主題與資源。 |
| `src/cleanyourmail_app/domain/` | 提供者目錄、設定、偏好設定與計畫模型。 |
| `src/cleanyourmail_app/services/` | sidecar 用戶端（`cli.py`）、設定（`config.py`）、機密（`secrets.py`）、OAuth（`oauth.py`）與設定（`settings.py`）。 |
| `src/cleanyourmail_app/i18n/` | 英文與西班牙文字串。 |
| `scripts/` | sidecar/應用程式建置與安裝程式冒煙測試。 |
| `packaging/` | Inno Setup 指令碼與圖示。 |
| `tests/` | 使用模擬 CLI 測試資料的 pytest 與 pytest-qt 套件。 |
| `docs/superpowers/specs/` | 設計文件（0.3.0 應用程式、0.4.0 意見回饋）。 |
| `docs/superpowers/plans/` | 逐項工作的實作計畫。 |

## 連結

- 應用程式發行版本：<https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- Skill 與 CLI：<https://github.com/jparedesDS/cleanyourmail>
- 網站：<https://cleanyourmail.org/>
- 安全模型：<https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## 授權

MIT。請見 [LICENSE](LICENSE)。
