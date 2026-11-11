<p align="center">
  <img src="docs/banner.png" alt="CleanYourMail — dein Posteingang, ohne das Rauschen" width="100%">
</p>

<p align="center">
  <a href="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml"><img src="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/license-MIT-b9f36a?labelColor=08110d" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12%2B-b9f36a?labelColor=08110d" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/windows-10%2F11%20x64-b9f36a?labelColor=08110d" alt="Windows 10/11 x64">
  <img src="https://img.shields.io/badge/local--by--default-opt%20in%20feedback-b9f36a?labelColor=08110d" alt="Standardmäßig lokal; Feedback auf Wunsch">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português (BR)</a> ·
  <a href="README.fr.md">Français</a> ·
  <b>Deutsch</b> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ko.md">한국어</a>
</p>

# CleanYourMail-App

**Dein Posteingang, ohne das Rauschen — als native Windows-App.** Die CleanYourMail-App ist eine
PySide6-Oberfläche für die [CleanYourMail](https://github.com/jparedesDS/cleanyourmail)-CLI. Sie
führt dich durch das Verbinden eines Postfachs, die Auswahl dessen, was aufgeräumt werden soll, die
Prüfung eines umkehrbaren Plans und das Rückgängigmachen.

Kein Browser, kein lokaler Server, kein Konto, keine Telemetrie, kein Zugriff auf Nachrichteninhalte,
keine endgültige Löschung. Die App kontaktiert selbst nur den öffentlichen GitHub-Release-Feed (für
Updates) und den Feedback-Worker (erst nach **Senden** und Zustimmung).

> **Status:** `0.6.1` ist die aktuelle Early-MVP-Version für Windows. Sie ergänzt automatische
> Updates: Die installierte App prüft den öffentlichen GitHub-Release, verifiziert den SHA-256 des
> Installers und installiert nach einer Bestätigung. Der Installer bündelt die eingefrorene
> CleanYourMail-CLI `1.3.0` als Sidecar. Gmail ist validiert; Outlook hängt vom Zustimmungsmodell von
> Microsoft ab. Siehe [Provider-Status](#provider-status).

## Download

[CleanYourMail app 0.6.1 für Windows 10/11 x64](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)
ist ein Installer pro Benutzer, der die festgeschriebene CleanYourMail-CLI `1.3.0` als Sidecar
bündelt und keine Administratorrechte benötigt.

Der Installer 0.6.1 ist nicht code-signiert. Windows SmartScreen zeigt beim ersten Start
möglicherweise eine Warnung wegen eines unbekannten Herausgebers: Wähle **Weitere Informationen** und
dann **Trotzdem ausführen**, und vergleiche die mit dem Release veröffentlichte SHA-256 mit
`CleanYourMail-Setup-0.6.1.exe`:

```powershell
Get-FileHash .\CleanYourMail-Setup-0.6.1.exe -Algorithm SHA256
```

Das Release veröffentlicht außerdem eine `.sha256`-Datei im Format `HASH  filename`.

## Automatische Updates

Die installierte App prüft den [öffentlichen GitHub-Release-Feed](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)
höchstens alle sechs Stunden; die Schaltfläche **Updates** in der Kopfzeile prüft auf Wunsch. Die
Anfrage übermittelt die App-Version und deine IP an GitHub, aber keine Konto-, Postfach- oder
Token-Daten.

Gibt es eine neuere Version, bietet ein Banner **Install update** und **Later** an. **Install update**
fragt einmal nach. Danach lädt die App genau die Datei `CleanYourMail-Setup-<version>.exe` und die
zugehörige `.sha256` über HTTPS, prüft den SHA-256, bevor irgendetwas ausgeführt wird, schließt sich,
führt den Installer still für den aktuellen Benutzer aus und öffnet die neue Version wieder.

Ein fehlgeschlagenes Update läuft nie in einer Schleife und installiert nie, während die App noch läuft.
Eine fehlgeschlagene automatische Prüfung bleibt
still; drücke **Updates**, um es manuell zu versuchen. Eine fehlgeschlagene manuelle Prüfung zeigt
eine lokalisierte Meldung mit **Open GitHub**. Fehlt dem Release ein gültiger Installer oder
Checksum, bietet das Banner **Open GitHub** statt **Install update** an. Bei einem Download-,
Prüf- oder Hash-Fehler erscheint eine lokalisierte Fehlermeldung mit **Install update** zum erneuten
Versuch und **Open GitHub** für die Release-Seite. Kann der Update-Helfer nicht starten, bleibt die
App geöffnet und das Banner bietet **Open GitHub** an. Startet der Installer, schlägt aber fehl,
öffnet der Helfer die alte App wieder; es gibt kein gespeichertes Fehlerbanner, daher kannst du über
**Updates** erneut versuchen oder die Release-Seite manuell öffnen.

Der Installer 0.6.1 ist nicht code-signiert, daher kann SmartScreen während des Updates warnen, genau
wie beim manuellen Start: Wähle **Weitere Informationen** und dann **Trotzdem ausführen**. Der
SHA-256 belegt die Unversehrtheit des Downloads, nicht den Herausgeber; Code-Signierung ist der
nächste Sicherheitsschritt. Ist die automatische Installation nicht verfügbar (z. B. beim Start aus
dem Quellcode), bietet derselbe Ablauf die Release-Seite für eine manuelle Installation an.

Gmail funktioniert mit einem App-Passwort und der Bestätigung in zwei Schritten. Outlook /
Microsoft 365 funktioniert nicht per Klick: Microsoft 365 benötigt die Zustimmung des
Tenant-Administrators, und persönliche Outlook.com-Konten benötigen einen verifizierten Herausgeber.
macOS und Linux sind für 0.6.1 nicht vorgesehen.

## Warum diese App

Die CleanYourMail-CLI ist die Engine und die maßgebliche Quelle. Sie übernimmt bereits den
IMAP-Zugriff, die Klassifizierung, die Pläne, die umkehrbaren Verschiebungen und das Undo-Journal.
Was sie nicht bietet, ist ein kurzer Weg für alle, die kein Terminal verwenden oder keine TOML-Datei
bearbeiten möchten.

Diese App schafft diesen Weg, ohne die Engine zu duplizieren:

- Wähle einen Anbieter und verbinde dich, ohne eine Konfiguration von Hand zu schreiben.
- Wähle Kategorien und Modus über Kontrollkästchen und Optionsfelder.
- Scanne, lies den Bericht und prüfe den Plan, bevor sich etwas ändert.
- Wende Änderungen erst nach einer ausdrücklichen Prüfung an und mache sie im selben Fenster
  rückgängig.
- Lies jeden Bildschirm auf Englisch oder Spanisch.

Die App implementiert IMAP, Planung, Verschiebungen, Rückgängigmachen und Abmeldung nie selbst.
Sie ruft das eingefrorene CleanYourMail-CLI-Sidecar auf und stellt das Ergebnis dar, sodass es ein
Sicherheitsmodell und einen Satz von Regeln gibt.

## Screenshots

<p align="center">
  <img src="docs/images/app-provider.png" alt="Anbieter auswählen und die Postfachadresse eingeben" width="49%">
  <img src="docs/images/app-review.png" alt="Den Plan vor dem Anwenden prüfen" width="49%">
</p>

<p align="center"><em>Synthetische Demodaten. Anbieter wählen und den Plan prüfen, bevor du etwas anwendest.</em></p>

## Voraussetzungen

- Windows 10/11 x64 für den Installer.
- Python **3.12+** nur zum Ausführen aus dem Quellcode.
- Das CleanYourMail-CLI-Sidecar `1.3.0`. Der Installer bündelt es; für die Entwicklung setzt du
  `CYM_CLI` auf eine gebaute `cym-cli.exe` mit demselben JSON-Vertrag. Die App führt `mail.py` nicht
  direkt aus.

## Entwicklung

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` gibt `CleanYourMail app 0.6.1` aus.

Führe die Tests aus:

```bash
python -m pytest -q
```

Die Testsuite verwendet simulierte CLI-Fixtures. Sie benötigt niemals ein echtes Postfach,
Zugangsdaten oder Netzwerkzugriff.

## Was die App macht

1. **Willkommen / Anbieter.** Gmail, Outlook / Microsoft 365, Yahoo, iCloud, Fastmail, Proton Bridge
   oder benutzerdefiniertes IMAP, dazu die E-Mail-Adresse.
2. **Verbinden.** Ein geführter App-Passwort-Ablauf für Gmail, ein Gerätecode-Ablauf für Outlook und
   anbieterspezifische Hilfe zum App-Passwort für die übrigen. Das normale Passwort wird nie
   abgefragt.
3. **Einstellungen.** Kategorien zum Aufräumen, Ordner oder Archiv, Schutzoptionen, Limits und
   Sprache.
4. **Prüfen und aufräumen.** Scan, Bericht, Plan, verbindliche Prüfung, Anwenden mit Limit und das
   Undo-Journal. Die Abmelde-Spalte des Plans dient nur zur Information: Dieser Build sendet nie
   Abmeldeanfragen, und Anwenden wird immer mit `--action move` ausgeführt.

## Feedback

Feedback ist **optional und manuell**. Öffne es über die Schaltfläche **Feedback** in der
App-Kopfzeile oder nutze das
[Formular auf der Website](https://cleanyourmail.org/#feedback). Es werden keine Feedback-Daten im
Hintergrund erfasst, und das Formular sendet nichts, bis du **Senden** drückst und der
Einwilligungszeile zustimmst. Die einzige automatische Netzwerkanfrage ist die oben beschriebene
Update-Prüfung.

- Die App füllt eine **editierbare Checkliste** vor: Versionen von App und Sidecar, Windows-Version,
  Anbietername, Ordner-/Archivmodus, ausgewählte Kategorien und Sprache.
- Bearbeite oder lösche alles, was du nicht teilen möchtest. Füge **keine** Passwörter, Tokens,
  E-Mail-Adressen, Betreffzeilen, Nachrichten-IDs oder Dateipfade in die Nachricht oder die
  Checkliste ein.
- Das optionale Kontaktfeld ist die einzige Stelle für einen Discord-Handle, einen GitHub-Benutzernamen
  oder eine E-Mail-Adresse. Es ist nie erforderlich.
- Die Anfrage geht an einen Cloudflare Worker (`cleanyourmail-feedback`), der sie validiert und an
  einen privaten Discord-Kanal weiterleitet. Der Discord-Webhook ist ein Cloudflare-Secret und wird
  nie mit der App oder der Website ausgeliefert.
- Es gibt **kein Konto, keine Telemetrie, keine Analyse und keine Absturzberichte**. Der Worker
  speichert keinen Nachrichtentext und wendet ein kurzes Rate-Limit auf Basis gesalzener IP-Hashes
  an.

<a id="provider-status"></a>

## Provider-Status

| Anbieter | Weg in der App | Status |
|---|---|---|
| Gmail | App-Passwort + 2FA | bestanden, mit CLI 1.3.0 validiert |
| Outlook / Microsoft 365 | Gerätecode | teilweise: Microsoft 365 benötigt die Zustimmung des Tenant-Administrators; persönliche Outlook.com-Konten benötigen einen verifizierten Herausgeber |
| Yahoo, iCloud, Fastmail | App-Passwort | dokumentiert, nicht per Smoke-Test geprüft |
| Proton Bridge | Bridge-Passwort | dokumentiert, nicht per Smoke-Test geprüft |
| Benutzerdefiniertes IMAP | Host; fester Port 993 mit TLS | dokumentiert, nicht per Smoke-Test geprüft |

Die App meldet diese Zustände ehrlich. Sie behauptet nicht, Outlook funktioniere per Klick.

## Sicherheitsmodell

- **Standardmäßig lokal, außer optionalem Feedback.** Kein Konto, keine Cloud, keine Telemetrie und
  kein Zugriff auf Nachrichteninhalte. Die App stellt zwei eigene Anfragen: die öffentliche
  GitHub-Release-Abfrage (nur Version und IP; höchstens alle sechs Stunden oder über **Updates**) und
  den Feedback-POST nach Senden und Zustimmung. Der Mail-Netzzugriff gehört zum Sidecar.
- **Verifizierte Updates.** Der Installer wird per HTTPS aus dem GitHub-Release geladen, gegen den
  veröffentlichten SHA-256 geprüft und erst nach einer Bestätigung ausgeführt. Der Installer 0.6.1
  ist nicht code-signiert, daher kann SmartScreen warnen; der SHA-256 belegt Integrität, nicht den
  Herausgeber.
- **Nur CLI.** Die App kann keine Fähigkeiten hinzufügen, die die CLI nicht hat.
- **Kein Secret in argv.** App-Passwörter werden in die `password_file` der CLI geschrieben; die App
  übergibt sie nie als Kommandozeilenargumente.
- **Keine Secrets im Ruhezustand in den App-Einstellungen.** Secrets gelangen nie in QSettings, Logs,
  Fehlerdialoge oder Testausgaben.
- **Prüfung zuerst.** Keine Schreibaktion ohne geprüften Plan; Rückgängig bleibt einen Klick entfernt.
- **Keine endgültige Löschung.** Verschiebungen und Archivierungen sind umkehrbar.
- **Keine Abmeldung in 0.6.1.** Der Plan kann Abmeldemodi anzeigen, aber Anwenden verschiebt nur
  Nachrichten.
- **Englisch und Spanisch gleichberechtigt.** Jeder Text liegt in `i18n/*.json`.

Wie du eine Sicherheitslücke meldest, steht in [SECURITY.md](SECURITY.md).

## Projektstruktur

| Pfad | Inhalt |
|---|---|
| `src/cleanyourmail_app/` | Natives App-Paket. |
| `src/cleanyourmail_app/version.py` | Einzige Quelle der App-Version. |
| `src/cleanyourmail_app/__main__.py` | Einstiegspunkt für `python -m cleanyourmail_app`. |
| `src/cleanyourmail_app/app.py` | Baut die lokalen Dienste auf und öffnet den Assistenten. |
| `src/cleanyourmail_app/ui/` | PySide6-Fenster, Seiten, Widgets, Theme und Ressourcen. |
| `src/cleanyourmail_app/domain/` | Anbieterkatalog, Einstellungen, Präferenzen und Planmodelle. |
| `src/cleanyourmail_app/services/` | Sidecar-Client (`cli.py`), Konfiguration (`config.py`), Secrets (`secrets.py`), OAuth (`oauth.py`) und Einstellungen (`settings.py`). |
| `src/cleanyourmail_app/i18n/` | Englische und spanische Texte. |
| `scripts/` | Sidecar-/App-Builds und der Smoke-Test des Installers. |
| `packaging/` | Inno-Setup-Skript und Icons. |
| `tests/` | pytest- und pytest-qt-Suite mit simulierten CLI-Fixtures. |
| `docs/superpowers/specs/` | Design-Dokumente (App 0.3.0, Feedback 0.4.0). |
| `docs/superpowers/plans/` | Umsetzungsplan Aufgabe für Aufgabe. |

## Links

- App-Releases: <https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- Skill und CLI: <https://github.com/jparedesDS/cleanyourmail>
- Website: <https://cleanyourmail.org/>
- Sicherheitsmodell: <https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## Lizenz

MIT. Siehe [LICENSE](LICENSE).
