<p align="center">
  <img src="docs/banner.png" alt="CleanYourMail — la tua casella di posta, senza il rumore" width="100%">
</p>

<p align="center">
  <a href="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml"><img src="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/license-MIT-b9f36a?labelColor=08110d" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12%2B-b9f36a?labelColor=08110d" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/windows-10%2F11%20x64-b9f36a?labelColor=08110d" alt="Windows 10/11 x64">
  <img src="https://img.shields.io/badge/local--by--default-opt%20in%20feedback-b9f36a?labelColor=08110d" alt="Locale per impostazione predefinita; feedback facoltativo">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português (BR)</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <b>Italiano</b> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ko.md">한국어</a>
</p>

# App CleanYourMail

**La tua casella di posta, senza il rumore — come app nativa per Windows.** L'app CleanYourMail è un
front end PySide6 per la CLI [CleanYourMail](https://github.com/jparedesDS/cleanyourmail). Ti guida
nella connessione di una casella, nella scelta di cosa pulire, nella revisione di un piano reversibile
e nell'annullamento.

Niente browser, niente server locale, niente account, niente telemetria, nessun accesso al corpo dei
messaggi, nessuna eliminazione definitiva. L'unica richiesta di rete che l'app effettua da sola è il
POST di feedback che invii esplicitamente.

> **Stato:** `0.4.0` è l'attuale release Early MVP per Windows. Aggiunge il feedback facoltativo
> dall'intestazione dell'app e dal sito web. L'installer include la CLI CleanYourMail `1.2.2`
> congelata come sidecar. Gmail è validato; Outlook dipende dal modello di consenso di Microsoft.
> Vedi [Stato dei provider](#provider-status).

## Download

[CleanYourMail app 0.4.0 per Windows 10/11 x64](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)
è un installer per utente che include la CLI CleanYourMail `1.2.2` fissata come sidecar e non
richiede privilegi di amministratore.

L'installer 0.4.0 non è firmato. Al primo avvio Windows SmartScreen potrebbe mostrare un avviso di
editore sconosciuto: scegli **Ulteriori informazioni**, poi **Esegui comunque**, e confronta lo
SHA-256 pubblicato con la release con `CleanYourMail-Setup-0.4.0.exe`:

```powershell
Get-FileHash .\CleanYourMail-Setup-0.4.0.exe -Algorithm SHA256
```

La release pubblica anche un file `.sha256` nel formato `HASH  filename`.

Gmail funziona con una password per le app e la verifica in due passaggi. Outlook / Microsoft 365 non
funziona con un clic: Microsoft 365 richiede il consenso dell'amministratore del tenant, mentre gli
account personali Outlook.com richiedono un editore verificato. macOS e Linux sono fuori ambito per
la 0.4.0.

## Perché questa app

La CLI CleanYourMail è il motore e la fonte di verità. Gestisce già l'accesso IMAP, la
classificazione, i piani, gli spostamenti reversibili e il journal di annullamento. Quello che non
offre è un percorso breve per chi non vuole usare un terminale o modificare un file TOML.

Questa app aggiunge quel percorso senza duplicare il motore:

- Scegli un provider e connettiti senza scrivere una configurazione a mano.
- Scegli categorie e modalità con caselle di controllo e pulsanti di opzione.
- Esegui la scansione, leggi il report e controlla il piano prima che qualcosa cambi.
- Applica solo dopo una revisione esplicita, poi annulla dalla stessa finestra.
- Leggi ogni schermata in inglese o spagnolo.

L'app non implementa mai IMAP, pianificazione, spostamenti, annullamento o disiscrizione. Chiama il
sidecar congelato della CLI CleanYourMail e mostra il risultato, così esiste un solo modello di
sicurezza e un solo insieme di regole.

## Screenshot

<p align="center">
  <img src="docs/images/app-provider.png" alt="Scegli un provider e inserisci l'indirizzo della casella" width="49%">
  <img src="docs/images/app-review.png" alt="Rivedi il piano prima di applicarlo" width="49%">
</p>

<p align="center"><em>Dati demo sintetici. Scegli un provider e controlla il piano prima di applicare qualsiasi cosa.</em></p>

## Requisiti

- Windows 10/11 x64 per l'installer.
- Python **3.12+** solo per l'esecuzione dal codice sorgente.
- Il sidecar della CLI CleanYourMail `1.2.2`. L'installer lo include; per lo sviluppo, imposta
  `CYM_CLI` su un `cym-cli.exe` compilato con lo stesso contratto JSON. L'app non esegue `mail.py`
  direttamente.

## Sviluppo

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` stampa `CleanYourMail app 0.4.0`.

Esegui i test:

```bash
python -m pytest -q
```

La suite usa fixture CLI simulate. Non richiede mai una casella reale, credenziali o accesso alla rete.

## Cosa fa l'app

1. **Benvenuto / provider.** Gmail, Outlook / Microsoft 365, Yahoo, iCloud, Fastmail, Proton Bridge
   o IMAP personalizzato, più l'indirizzo email.
2. **Connessione.** Per Gmail un flusso guidato con password per le app, per Outlook un flusso con
   codice dispositivo e, per gli altri provider, assistenza dedicata sulle password per le app. La
   password normale non viene mai richiesta.
3. **Preferenze.** Categorie da pulire, cartelle o archivio, protezioni, limiti e lingua.
4. **Revisione e pulizia.** Scansione, report, piano, revisione obbligatoria, applicazione con un
   limite e journal di annullamento. La colonna delle disiscrizioni del piano è solo informativa:
   questa build non invia mai richieste di disiscrizione e Applica viene sempre eseguito con
   `--action move`.

## Feedback

Il feedback è **facoltativo e manuale**. Aprilo con il pulsante **Feedback** nell'intestazione
dell'app oppure usa il [modulo sul sito](https://cleanyourmail.org/#feedback).
Nulla viene raccolto in background e l'app non invia niente finché non premi **Invia** e accetti la
riga di consenso.

- L'app precompila una **checklist modificabile** con le versioni dell'app e del sidecar, la versione
  di Windows, il nome del provider, la modalità cartelle/archivio, le categorie selezionate e la
  lingua.
- Modifica o elimina tutto ciò che non vuoi condividere. **Non** inserire password, token, indirizzi
  email, oggetti delle email, ID dei messaggi o percorsi di file nel messaggio o nella checklist.
- Il campo di contatto facoltativo è l'unico posto in cui lasciare un handle Discord, un nome utente
  GitHub o un indirizzo email. Non è mai obbligatorio.
- La richiesta va a un Cloudflare Worker (`cleanyourmail-feedback`), che la valida e la inoltra a un
  canale Discord privato. Il webhook di Discord è un segreto Cloudflare e non viene mai distribuito
  con l'app o il sito.
- Non ci sono **account, telemetria, analisi o segnalazione di crash**. Il Worker non memorizza il
  corpo dei messaggi e applica un rate limit breve basato su hash IP con salt.

<a id="provider-status"></a>

## Stato dei provider

| Provider | Percorso nell'app | Stato |
|---|---|---|
| Gmail | Password per le app + 2FA | superato, validato con CLI 1.2.2 |
| Outlook / Microsoft 365 | Codice dispositivo | parziale: Microsoft 365 richiede il consenso dell'amministratore del tenant; gli account personali Outlook.com richiedono un editore verificato |
| Yahoo, iCloud, Fastmail | Password per le app | documentato, non testato con smoke test |
| Proton Bridge | Password Bridge | documentato, non testato con smoke test |
| IMAP personalizzato | Host; porta fissa 993 con TLS | documentato, non testato con smoke test |

L'app riporta questi stati con onestà. Non promette un supporto Outlook con un solo clic.

## Modello di sicurezza

- **Solo locale, tranne il feedback facoltativo.** Nessun account, cloud, telemetria o accesso ai
  corpi dei messaggi. L'app non effettua richieste di rete in background; l'unica richiesta che fa da
  sola è il POST di feedback dopo che premi Invia e accetti la riga di consenso.
- **Solo CLI.** L'app non può aggiungere capacità che la CLI non ha.
- **Nessun segreto in argv.** Le password per le app vengono scritte nel `password_file` della CLI;
  l'app non le passa mai come argomenti della riga di comando.
- **Nessun segreto a riposo nelle impostazioni dell'app.** I segreti non entrano mai in QSettings,
  nei log, nei dialoghi di errore o nell'output dei test.
- **Prima la revisione.** Nessuna scrittura senza un piano rivisto; l'annullamento resta a un clic.
- **Nessuna eliminazione definitiva.** Spostamenti e archiviazioni sono reversibili.
- **Nessuna disiscrizione nella 0.4.0.** Il piano può mostrare modalità di disiscrizione, ma Applica
  sposta solo i messaggi.
- **Inglese e spagnolo di pari livello.** Ogni stringa vive in `i18n/*.json`.

Vedi [SECURITY.md](SECURITY.md) per come segnalare una vulnerabilità.

## Struttura del progetto

| Percorso | Cos'è |
|---|---|
| `src/cleanyourmail_app/` | Pacchetto dell'app nativa. |
| `src/cleanyourmail_app/version.py` | Unica fonte della versione dell'app. |
| `src/cleanyourmail_app/__main__.py` | Punto di ingresso per `python -m cleanyourmail_app`. |
| `src/cleanyourmail_app/app.py` | Costruisce i servizi locali e apre la procedura guidata. |
| `src/cleanyourmail_app/ui/` | Finestra, pagine, widget, tema e risorse PySide6. |
| `src/cleanyourmail_app/domain/` | Catalogo provider, impostazioni, preferenze e modelli di piano. |
| `src/cleanyourmail_app/services/` | Client sidecar (`cli.py`), configurazione (`config.py`), segreti (`secrets.py`), OAuth (`oauth.py`) e impostazioni (`settings.py`). |
| `src/cleanyourmail_app/i18n/` | Stringhe in inglese e spagnolo. |
| `scripts/` | Build di sidecar e app e smoke test dell'installer. |
| `packaging/` | Script Inno Setup e icone. |
| `tests/` | Suite pytest e pytest-qt con fixture CLI simulate. |
| `docs/superpowers/specs/` | Documenti di design (app 0.3.0, feedback 0.4.0). |
| `docs/superpowers/plans/` | Piano di implementazione attività per attività. |

## Link

- Release dell'app: <https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- Skill e CLI: <https://github.com/jparedesDS/cleanyourmail>
- Sito web: <https://cleanyourmail.org/>
- Modello di sicurezza: <https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## Licenza

MIT. Vedi [LICENSE](LICENSE).
