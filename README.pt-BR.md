<p align="center">
  <img src="docs/banner.png" alt="CleanYourMail — sua caixa de entrada, sem o ruído" width="100%">
</p>

<p align="center">
  <a href="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml"><img src="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/license-MIT-b9f36a?labelColor=08110d" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12%2B-b9f36a?labelColor=08110d" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/windows-10%2F11%20x64-b9f36a?labelColor=08110d" alt="Windows 10/11 x64">
  <img src="https://img.shields.io/badge/local--by--default-opt%20in%20feedback-b9f36a?labelColor=08110d" alt="Local por padrão; feedback opcional">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.es.md">Español</a> ·
  <b>Português (BR)</b> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ko.md">한국어</a>
</p>

# CleanYourMail app

**Sua caixa de entrada, sem o ruído — como um app nativo para Windows.** O CleanYourMail app é uma
interface PySide6 para a CLI do [CleanYourMail](https://github.com/jparedesDS/cleanyourmail). Ele
guia você para conectar uma caixa de correio, escolher o que limpar, revisar um plano reversível e
desfazê-lo.

Sem navegador, sem servidor local, sem conta, sem telemetria, sem corpos de mensagem e sem exclusão
permanente. A única requisição de rede que o app faz por conta própria é o POST de feedback que você
envia explicitamente.

> **Status:** `0.4.0` é a versão early-MVP atual para Windows. Ela adiciona feedback opcional no
> cabeçalho do app e no site. O instalador inclui o sidecar congelado da CLI do CleanYourMail
> `1.2.2`. O Gmail está validado; o Outlook depende do modelo de consentimento da Microsoft. Veja o
> [status dos provedores](#provider-status).

## Download

[CleanYourMail app 0.4.0 para Windows 10/11 x64](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)
é um instalador por usuário que inclui o sidecar fixado da CLI do CleanYourMail `1.2.2` e não exige
direitos de administrador.

O instalador 0.4.0 não tem assinatura de código. O Windows SmartScreen pode mostrar um aviso de
"Editor desconhecido" na primeira execução: escolha **Mais informações** e depois **Executar mesmo
assim**, e compare o SHA-256 publicado na release com o de `CleanYourMail-Setup-0.4.0.exe`:

```powershell
Get-FileHash .\CleanYourMail-Setup-0.4.0.exe -Algorithm SHA256
```

A release também publica um arquivo `.sha256` no formato `HASH  filename`.

O Gmail funciona com uma senha de app e verificação em duas etapas. O Outlook / Microsoft 365 não
funciona em um clique: o Microsoft 365 precisa de consentimento do administrador do locatário, e
contas pessoais do Outlook.com precisam de um editor verificado. macOS e Linux estão fora do escopo
da 0.4.0.

## Por que este app

A CLI do CleanYourMail é o motor e a fonte da verdade. Ela já cuida do acesso IMAP, da classificação,
dos planos, dos movimentos reversíveis e do diário de desfazer. O que ela não oferece é um caminho
curto para quem não quer usar um terminal nem editar um arquivo TOML.

Este app adiciona esse caminho sem duplicar o motor:

- Escolha um provedor e conecte-se sem escrever uma configuração à mão.
- Escolha categorias e modo com caixas de seleção e botões de rádio.
- Escaneie, leia o relatório e inspecione o plano antes de qualquer mudança.
- Aplique só depois de uma revisão explícita e desfaça na mesma janela.
- Leia todas as telas em inglês ou espanhol.

O app nunca implementa IMAP, planejamento, movimentos, desfazer ou cancelamento de inscrição por
conta própria. Ele chama o sidecar congelado da CLI do CleanYourMail e renderiza o resultado, então
há um único modelo de segurança e um único conjunto de regras.

## Capturas de tela

<p align="center">
  <img src="docs/images/app-provider.png" alt="Escolha um provedor e informe o endereço da caixa de correio" width="49%">
  <img src="docs/images/app-review.png" alt="Revise o plano antes de aplicá-lo" width="49%">
</p>

## Requisitos

- Windows 10/11 x64 para o instalador.
- Python **3.12+** apenas para rodar a partir do código-fonte.
- O sidecar da CLI do CleanYourMail `1.2.2`. O instalador o inclui; para desenvolvimento, aponte
  `CYM_CLI` para um `cym-cli.exe` compilado com o mesmo contrato JSON. O app não executa `mail.py`
  diretamente.

## Desenvolvimento

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` imprime `CleanYourMail app 0.4.0`.

Rode os testes:

```bash
python -m pytest -q
```

A suíte usa fixtures de CLI falsa. Ela nunca precisa de uma caixa de correio real, credenciais ou
acesso à rede.

## O que o app faz

1. **Boas-vindas / provedor.** Gmail, Outlook / Microsoft 365, Yahoo, iCloud, Fastmail, Proton Bridge
   ou IMAP personalizado, além do endereço de e-mail.
2. **Conectar.** Um fluxo guiado de senha de app para o Gmail, um fluxo de código de dispositivo para
   o Outlook e ajuda com a senha de app específica de cada provedor para os demais. A senha normal
   nunca é solicitada.
3. **Preferências.** Categorias a limpar, pastas ou arquivamento, proteções, limites e idioma.
4. **Revisar e limpar.** Escaneamento, relatório, plano, etapa de revisão, aplicação com um limite e
   o diário de desfazer. A coluna de cancelamento de inscrição do plano é apenas informativa: esta
   build nunca envia solicitações de cancelamento, e Aplicar sempre roda com `--action move`.

## Feedback

O feedback é **opcional e manual**. Abra-o com o botão **Feedback** no cabeçalho do app ou use o
[formulário do site](https://cleanyourmail.org/#feedback). Nada é coletado em
segundo plano, e o app não envia nada até você apertar **Enviar** e aceitar a linha de consentimento.

- O app preenche um **checklist editável** com as versões do app e do sidecar, a versão do Windows,
  o nome do provedor, o modo pasta/arquivamento, as categorias selecionadas e o idioma.
- Edite ou apague o que não quiser compartilhar. **Não** inclua senhas, tokens, endereços de e-mail,
  assuntos, IDs de mensagem ou caminhos de arquivo na mensagem nem no checklist.
- O campo de contato opcional é o único lugar para deixar um usuário do Discord, um nome de usuário
  do GitHub ou um endereço de e-mail. Ele nunca é obrigatório.
- A requisição vai para um Worker da Cloudflare (`cleanyourmail-feedback`), que a valida e a
  encaminha para um canal privado do Discord. O webhook do Discord é um segredo da Cloudflare e
  nunca é distribuído com o app nem com o site.
- **Não há conta, telemetria, analytics nem relatórios de falhas.** O Worker não armazena o corpo da
  mensagem e aplica um limite de frequência de curto prazo baseado no IP com sal.

<a id="provider-status"></a>

## Status dos provedores

| Provedor | Caminho no app | Status |
|---|---|---|
| Gmail | Senha de app + 2FA | aprovado, validado com a CLI 1.2.2 |
| Outlook / Microsoft 365 | Código de dispositivo | parcial: o Microsoft 365 precisa de consentimento do administrador do locatário; o Outlook.com pessoal precisa de um editor verificado |
| Yahoo, iCloud, Fastmail | Senha de app | documentado, sem smoke test |
| Proton Bridge | Senha do Bridge | documentado, sem smoke test |
| IMAP personalizado | Host; porta fixa 993 com TLS | documentado, sem smoke test |

O app relata esses estados com honestidade. Ele não afirma oferecer suporte a Outlook em um clique.

## Modelo de segurança

- **Só local, exceto o feedback opcional.** Sem conta, nuvem, telemetria ou acesso ao corpo das
  mensagens. O app não faz nenhuma requisição de rede em segundo plano; a única que ele faz por conta
  própria é o POST de feedback depois que você aperta Enviar e aceita a linha de consentimento.
- **Só a CLI.** O app não pode adicionar capacidades que a CLI não tem.
- **Nenhum segredo em argv.** As senhas de app são gravadas no `password_file` da CLI; o app nunca
  as passa como argumentos de linha de comando.
- **Nenhum segredo em repouso nas configurações do app.** Segredos nunca entram no QSettings, nos
  logs, nas caixas de erro nem na saída dos testes.
- **Revisar primeiro.** Nenhuma escrita sem um plano revisado; desfazer fica a um clique.
- **Sem exclusão permanente.** Movimentos e arquivamentos são reversíveis.
- **Sem cancelamento de inscrição na 0.4.0.** O plano pode mostrar modos de cancelamento, mas
  Aplicar só move mensagens.
- **Inglês e espanhol de primeira classe.** Cada string fica em `i18n/*.json`.

Veja [SECURITY.md](SECURITY.md) para saber como relatar uma vulnerabilidade.

## Estrutura do projeto

| Caminho | O que é |
|---|---|
| `src/cleanyourmail_app/` | Pacote do app nativo. |
| `src/cleanyourmail_app/version.py` | Fonte única da versão do app. |
| `src/cleanyourmail_app/__main__.py` | Ponto de entrada de `python -m cleanyourmail_app`. |
| `src/cleanyourmail_app/app.py` | Monta os serviços locais e abre o assistente. |
| `src/cleanyourmail_app/ui/` | Janela, páginas, widgets, tema e recursos em PySide6. |
| `src/cleanyourmail_app/domain/` | Catálogo de provedores, configurações, preferências e modelos de plano. |
| `src/cleanyourmail_app/services/` | Cliente do sidecar (`cli.py`), configuração (`config.py`), segredos (`secrets.py`), OAuth (`oauth.py`) e configurações (`settings.py`). |
| `src/cleanyourmail_app/i18n/` | Strings em inglês e espanhol. |
| `scripts/` | Builds do sidecar e do app, e o smoke test do instalador. |
| `packaging/` | Script do Inno Setup e ícones. |
| `tests/` | Suíte de pytest e pytest-qt com fixtures de CLI falsa. |
| `docs/superpowers/specs/` | Documentos de design (app 0.3.0, feedback 0.4.0). |
| `docs/superpowers/plans/` | Plano de implementação tarefa a tarefa. |

## Links

- Versões publicadas do app: <https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- Skill e CLI: <https://github.com/jparedesDS/cleanyourmail>
- Site: <https://cleanyourmail.org/>
- Modelo de segurança: <https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## Licença

MIT. Veja [LICENSE](LICENSE).
