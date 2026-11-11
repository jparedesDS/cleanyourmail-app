<p align="center">
  <img src="docs/banner.png" alt="CleanYourMail — 소음은 덜어낸 받은편지함" width="100%">
</p>

<p align="center">
  <a href="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml"><img src="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml/badge.svg" alt="테스트"></a>
  <img src="https://img.shields.io/badge/license-MIT-b9f36a?labelColor=08110d" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12%2B-b9f36a?labelColor=08110d" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/windows-10%2F11%20x64-b9f36a?labelColor=08110d" alt="Windows 10/11 x64">
  <img src="https://img.shields.io/badge/local--by--default-opt%20in%20feedback-b9f36a?labelColor=08110d" alt="기본은 로컬, 선택형 피드백">
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
  <a href="README.zh-TW.md">繁體中文</a> ·
  <b>한국어</b>
</p>

# CleanYourMail 앱

**소음은 덜어낸 받은편지함, 이제 네이티브 Windows 앱으로.** CleanYourMail 앱은
CleanYourMail CLI를 위한 PySide6 프런트엔드입니다. 사서함 연결부터 정리할 항목 선택,
되돌릴 수 있는 계획 검토, 실행 취소까지 차근차근 안내합니다.

브라우저도, 로컬 서버도, 계정도, 텔레메트리도, 본문 접근도, 영구 삭제도 없습니다. 앱 자체가 연결하는 곳은 공개 GitHub 릴리스 피드(업데이트용)와 피드백 Worker(보내기를 누르고 동의한 경우에만)뿐입니다.

> **상태:** `0.6.0`은 현재 Windows용 초기 MVP 릴리스입니다. 자동 업데이트가 추가되었습니다.
> 설치된 앱이 공개 GitHub 릴리스를 확인하고 설치 프로그램의 SHA-256을 검증한 뒤 한 번의 확인으로
> 설치합니다. 설치 프로그램에는 동결된 CleanYourMail CLI `1.3.0` 사이드카가 포함됩니다. Gmail은
> 검증되었고, Outlook은 Microsoft의 동의 모델에 따라 달라집니다. [제공자 상태](#provider-status)를
> 참고하세요.

## 다운로드

[Windows 10/11 x64용 CleanYourMail 앱 0.6.0](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)은
사용자 단위 설치 프로그램으로, 고정된 CleanYourMail CLI `1.3.0` 사이드카를 포함하며 관리자
권한이 필요하지 않습니다.

0.6.0 설치 프로그램은 코드 서명이 되어 있지 않습니다. 처음 실행할 때 Windows SmartScreen에
"알 수 없는 게시자" 경고가 표시될 수 있습니다. **추가 정보**를 선택한 다음 **실행**을 누르고,
릴리스와 함께 게시된 SHA-256을 `CleanYourMail-Setup-0.6.0.exe`와 비교하세요.

```powershell
Get-FileHash .\CleanYourMail-Setup-0.6.0.exe -Algorithm SHA256
```

릴리스에는 `HASH  filename` 형식의 `.sha256` 파일도 함께 게시됩니다.

## 자동 업데이트

설치된 앱은 [공개 GitHub 릴리스](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)를 최대 6시간마다 확인하며, 헤더의 **Updates** 버튼으로 언제든 확인할 수 있습니다. 이 요청은 앱 버전과 IP를 GitHub에 알리지만 계정, 사서함, 토큰 데이터는 보내지 않습니다.

새 버전이 있으면 배너에 **Install update**와 **Later**가 표시됩니다. **Install update**를 누르면 한 번 확인합니다. 그다음 앱이 정확한 `CleanYourMail-Setup-<version>.exe`와 공개된 `.sha256`을 HTTPS로 내려받고, 무엇이든 실행하기 전에 SHA-256을 검증한 뒤 종료하며, 설치 프로그램을 현재 사용자용으로 조용히 실행하고 새 버전을 다시 엽니다.

실패해도 앱은 계속 사용할 수 있습니다. 자동 확인이 실패하면 아무것도 표시되지 않으며 **Updates**를 눌러 직접 확인할 수 있습니다. 수동 확인이 실패하면 현지화된 메시지와 **Open GitHub**가 표시됩니다. 릴리스에 유효한 설치 프로그램이나 체크섬이 없으면 배너가 **Install update** 대신 **Open GitHub**를 제공합니다. 다운로드나 해시가 실패하면 현지화된 오류가 표시되고 배너가 유지되어 **Install update**로 다시 시도할 수 있습니다. 설치 프로그램이 완료되지 않으면 이전 앱이 다시 열리고 배너에 **Open GitHub**가 표시됩니다.

0.6.0 설치 프로그램은 코드 서명이 되어 있지 않아 업데이트 중에도 수동 실행 때와 같이 SmartScreen 경고가 표시될 수 있습니다. **추가 정보**를 선택한 다음 **실행**을 누르세요. SHA-256은 다운로드의 무결성을 증명할 뿐 게시자를 증명하지 않습니다. 코드 서명이 다음 보안 단계입니다. 자동 설치를 사용할 수 없으면(예: 소스에서 실행) 같은 흐름에서 릴리스 페이지를 안내하여 수동으로 설치할 수 있습니다.

Gmail은 앱 비밀번호와 2단계 인증으로 작동합니다. Outlook / Microsoft 365는 클릭 한 번으로
연결되지 않습니다. Microsoft 365는 테넌트 관리자 동의가 필요하고, 개인 Outlook.com 계정은
확인된 게시자가 필요합니다. 0.6.0에서는 macOS와 Linux를 지원하지 않습니다.

## 이 앱이 필요한 이유

CleanYourMail CLI는 엔진이자 최종 기준입니다. IMAP 접속, 분류, 계획, 되돌릴 수 있는 이동,
실행 취소 저널을 이미 담당합니다. 다만 터미널을 쓰거나 TOML 파일을 직접 편집하고 싶지 않은
사람을 위한 짧은 경로는 제공하지 않습니다.

이 앱은 엔진을 중복 구현하지 않으면서 그러한 경로를 제공합니다.

- 설정 파일을 직접 작성하지 않고도 제공자를 선택해 연결할 수 있습니다.
- 체크박스와 라디오 버튼으로 카테고리와 모드를 고릅니다.
- 아무것도 바뀌기 전에 스캔하고, 보고서를 읽고, 계획을 검토합니다.
- 명시적으로 검토한 뒤에만 적용하고, 같은 창에서 실행 취소할 수 있습니다.
- 모든 화면을 영어 또는 스페인어로 볼 수 있습니다.

앱은 IMAP, 계획 수립, 이동, 실행 취소, 수신 거부를 자체적으로 구현하지 않습니다. 동결된
CleanYourMail CLI 사이드카를 호출해 결과를 표시하므로, 안전 모델과 규칙이 하나로 유지됩니다.

## 스크린샷

<p align="center">
  <img src="docs/images/app-provider.png" alt="제공자를 선택하고 사서함 주소를 입력하는 화면" width="49%">
  <img src="docs/images/app-review.png" alt="적용 전에 계획을 검토하는 화면" width="49%">
</p>

<p align="center"><em>합성 데모 데이터입니다. 제공자를 선택하고 적용하기 전에 계획을 검토하세요.</em></p>

## 요구 사항

- 설치 프로그램은 Windows 10/11 x64에서 실행됩니다.
- 소스에서 실행하려면 Python **3.12+**가 필요합니다.
- CleanYourMail CLI `1.3.0` 사이드카. 설치 프로그램에 포함되어 있습니다. 개발 시에는 동일한
  JSON 계약을 따르는 빌드된 `cym-cli.exe`를 `CYM_CLI`로 지정하세요. 앱은 `mail.py`를 직접
  실행하지 않습니다.

## 개발

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version`을 실행하면 `CleanYourMail app 0.6.0`이 출력됩니다.

테스트를 실행하세요.

```bash
python -m pytest -q
```

테스트 모음은 모의 CLI 픽스처를 사용합니다. 실제 사서함, 자격 증명, 네트워크 접근은 전혀
필요하지 않습니다.

## 앱의 기능

1. **환영 / 제공자.** Gmail, Outlook / Microsoft 365, Yahoo, iCloud, Fastmail, Proton Bridge
   또는 사용자 지정 IMAP을 선택하고 이메일 주소를 입력합니다.
2. **연결.** Gmail은 앱 비밀번호 설정을 단계별로 안내하고, Outlook은 장치 코드 흐름을
   사용하며, 나머지 제공자는 각자의 앱 비밀번호 도움말을 제공합니다. 일반 비밀번호는 절대
   요구하지 않습니다.
3. **환경 설정.** 정리할 카테고리, 폴더 또는 보관 방식, 보호 항목, 제한, 언어를 설정합니다.
4. **검토 및 정리.** 스캔, 보고서, 계획, 검토 게이트, 제한을 둔 적용, 실행 취소 저널까지
   진행합니다. 계획의 수신 거부 열은 참고용일 뿐입니다. 이 빌드는 수신 거부 요청을 보내지
   않으며, 적용은 항상 `--action move`로 실행됩니다.

## 피드백

피드백은 **선택 사항이며 직접 보내는 방식**입니다. 앱 헤더의 **피드백** 버튼을 누르거나
[웹사이트 양식](https://cleanyourmail.org/#feedback)을 이용하세요.
백그라운드에서 피드백 데이터를 수집하지 않으며, **보내기**를 누르고 동의 문구를 확인하기 전까지
양식은 아무것도 전송하지 않습니다. 자동으로 이루어지는 네트워크 요청은 위에서 설명한 업데이트
확인뿐입니다.

- 앱은 자체 버전과 사이드카 버전, Windows 버전, 제공자 이름, 폴더/보관 모드, 선택한 카테고리,
  언어를 담은 **편집 가능한 체크리스트**를 미리 채웁니다.
- 공유하고 싶지 않은 항목은 수정하거나 삭제하세요. 메시지나 체크리스트에 비밀번호, 토큰,
  이메일 주소, 이메일 제목, 메시지 ID, 파일 경로를 **넣지 마세요**.
- 선택 사항인 연락처 필드는 Discord 핸들, GitHub 사용자 이름, 이메일 주소를 남길 수 있는
  유일한 곳입니다. 필수는 아닙니다.
- 요청은 Cloudflare Worker(`cleanyourmail-feedback`)로 전송되며, Worker가 이를 검증해 비공개
  Discord 채널로 전달합니다. Discord 웹훅은 Cloudflare 비밀로 보관되며 앱이나 웹사이트에
  포함되지 않습니다.
- **계정도 텔레메트리도 분석도 충돌 보고도 없습니다.** Worker는 메시지 본문을 저장하지 않고,
  솔트 처리된 IP를 기준으로 짧은 속도 제한을 적용합니다.

<a id="provider-status"></a>

## 제공자 상태

| 제공자 | 앱 내 방식 | 상태 |
|---|---|---|
| Gmail | 앱 비밀번호 + 2단계 인증 | 통과, CLI 1.3.0로 검증 |
| Outlook / Microsoft 365 | 장치 코드 | 부분 지원: Microsoft 365는 테넌트 관리자 동의 필요, Outlook.com 개인 계정은 확인된 게시자 필요 |
| Yahoo, iCloud, Fastmail | 앱 비밀번호 | 문서화됨, 스모크 테스트 미실시 |
| Proton Bridge | Bridge 비밀번호 | 문서화됨, 스모크 테스트 미실시 |
| 사용자 지정 IMAP | 호스트, TLS가 적용된 고정 포트 993 | 문서화됨, 스모크 테스트 미실시 |

앱은 이 상태를 있는 그대로 알립니다. Outlook 원클릭 지원을 내세우지 않습니다.

## 보안 모델

- **선택형 피드백을 제외하면 기본은 로컬입니다.** 계정, 클라우드, 텔레메트리, 본문 접근이 없습니다.
  앱 자체 요청은 두 가지뿐입니다. 공개 GitHub 릴리스 확인(버전과 IP만, 최대 6시간마다 또는
  **Updates**를 누를 때)과 보내기를 누르고 동의한 뒤의 피드백 POST입니다. 메일 네트워크 접근은
  사이드카가 담당합니다.
- **업데이트는 검증됩니다.** 설치 프로그램은 GitHub 릴리스에서 HTTPS로 내려받고, 공개된 SHA-256으로
  검증하며, 한 번의 확인 후에만 실행합니다. 0.6.0 설치 프로그램은 코드 서명이 되어 있지 않아
  SmartScreen 경고가 표시될 수 있습니다. SHA-256은 무결성을 증명할 뿐 게시자를 증명하지 않습니다.
- **CLI만 사용합니다.** 앱은 CLI에 없는 기능을 추가할 수 없습니다.
- **명령줄 인수에 비밀 정보가 없습니다.** 앱 비밀번호는 CLI의 `password_file`에 기록되며,
  앱은 이를 명령줄 인수로 전달하지 않습니다.
- **앱 설정에 비밀 정보를 저장하지 않습니다.** 비밀 정보는 QSettings, 로그, 오류 대화상자,
  테스트 출력에 들어가지 않습니다.
- **검토 먼저.** 검토된 계획 없이는 아무것도 변경하지 않으며, 실행 취소는 언제나 한 번의
  클릭으로 가능합니다.
- **영구 삭제가 없습니다.** 이동과 보관은 되돌릴 수 있습니다.
- **0.6.0에는 수신 거부가 없습니다.** 계획에 수신 거부 모드가 표시될 수 있지만, 적용은
  메시지를 이동할 뿐입니다.
- **영어와 스페인어를 정식 지원합니다.** 모든 문자열은 `i18n/*.json`에 있습니다.

취약점 신고 방법은 [SECURITY.md](SECURITY.md)를 참고하세요.

## 프로젝트 구조

| 경로 | 설명 |
|---|---|
| `src/cleanyourmail_app/` | 네이티브 앱 패키지. |
| `src/cleanyourmail_app/version.py` | 앱 버전의 단일 소스. |
| `src/cleanyourmail_app/__main__.py` | `python -m cleanyourmail_app` 진입점. |
| `src/cleanyourmail_app/app.py` | 로컬 서비스를 구성하고 마법사를 엽니다. |
| `src/cleanyourmail_app/ui/` | PySide6 창, 페이지, 위젯, 테마, 리소스. |
| `src/cleanyourmail_app/domain/` | 제공자 카탈로그, 설정, 환경 설정, 계획 모델. |
| `src/cleanyourmail_app/services/` | 사이드카 클라이언트(`cli.py`), 구성(`config.py`), 비밀 정보(`secrets.py`), OAuth(`oauth.py`), 설정(`settings.py`). |
| `src/cleanyourmail_app/i18n/` | 영어 및 스페인어 문자열. |
| `scripts/` | 사이드카/앱 빌드와 설치 프로그램 스모크 테스트. |
| `packaging/` | Inno Setup 스크립트와 아이콘. |
| `tests/` | 모의 CLI 픽스처를 사용하는 pytest 및 pytest-qt 모음. |
| `docs/superpowers/specs/` | 설계 문서(0.3.0 앱, 0.4.0 피드백). |
| `docs/superpowers/plans/` | 작업별 구현 계획. |

## 링크

- 앱 릴리스: <https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- 스킬과 CLI: <https://github.com/jparedesDS/cleanyourmail>
- 웹사이트: <https://cleanyourmail.org/>
- 안전 모델: <https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## 라이선스

MIT. [LICENSE](LICENSE)를 참고하세요.
