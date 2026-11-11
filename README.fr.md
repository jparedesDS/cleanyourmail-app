<p align="center">
  <img src="docs/banner.png" alt="CleanYourMail — votre boîte de réception, sans le bruit" width="100%">
</p>

<p align="center">
  <a href="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml"><img src="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/license-MIT-b9f36a?labelColor=08110d" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12%2B-b9f36a?labelColor=08110d" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/windows-10%2F11%20x64-b9f36a?labelColor=08110d" alt="Windows 10/11 x64">
  <img src="https://img.shields.io/badge/local--by--default-opt%20in%20feedback-b9f36a?labelColor=08110d" alt="Local par défaut ; retours facultatifs">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português (BR)</a> ·
  <b>Français</b> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ko.md">한국어</a>
</p>

# Application CleanYourMail

**Votre boîte de réception, sans le bruit — en app native Windows.** CleanYourMail app est une
interface PySide6 pour la CLI [CleanYourMail](https://github.com/jparedesDS/cleanyourmail). Elle vous
guide pour connecter une boîte mail, choisir quoi nettoyer, relire un plan réversible et l’annuler.

Pas de navigateur, pas de serveur local, pas de compte, pas de télémétrie, pas de corps de message,
pas de suppression définitive. La seule requête réseau que l’app fait elle-même est le POST de retour
que vous envoyez explicitement.

> **État :** `0.4.0` est la version early-MVP Windows actuelle. Elle ajoute des retours facultatifs
> depuis l’en-tête de l’app et le site. L’installateur embarque le sidecar figé de la CLI
> CleanYourMail `1.2.2`. Gmail est validé ; Outlook dépend du modèle de consentement de Microsoft.
> Voir la section [État des fournisseurs](#provider-status).

## Téléchargement

[CleanYourMail app 0.4.0 pour Windows 10/11 x64](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)
est un installateur par utilisateur qui embarque le sidecar figé de la CLI CleanYourMail `1.2.2` et
ne nécessite aucun droit administrateur.

L’installateur 0.4.0 n’est pas signé. Windows SmartScreen peut afficher un avertissement « Éditeur
inconnu » au premier lancement : choisissez **Informations complémentaires**, puis **Exécuter quand
même**, et comparez le SHA-256 publié avec la version à celui de `CleanYourMail-Setup-0.4.0.exe` :

```powershell
Get-FileHash .\CleanYourMail-Setup-0.4.0.exe -Algorithm SHA256
```

La version publie également un fichier `.sha256` au format `HASH  filename`.

Gmail fonctionne avec un mot de passe d’application et la validation en deux étapes. Outlook /
Microsoft 365 ne fonctionne pas en un clic : Microsoft 365 exige le consentement de l’administrateur
du locataire, et les comptes personnels Outlook.com exigent un éditeur vérifié. macOS et Linux sont
hors périmètre pour 0.4.0.

## Pourquoi cette app

La CLI CleanYourMail est le moteur et la source de vérité. Elle gère déjà l’accès IMAP, la
classification, les plans, les déplacements réversibles et le journal d’annulation. Ce qu’elle
n’offre pas, c’est un chemin court pour qui ne veut pas passer par un terminal ni modifier un fichier
TOML.

Cette app ajoute ce chemin sans dupliquer le moteur :

- Choisir un fournisseur et se connecter sans écrire de configuration à la main.
- Choisir les catégories et le mode avec des cases à cocher et des boutons radio.
- Scanner, lire le rapport et inspecter le plan avant que quoi que ce soit ne change.
- Appliquer seulement après une relecture explicite, puis annuler depuis la même fenêtre.
- Lire chaque écran en anglais ou en espagnol.

L’app n’implémente jamais IMAP, la planification, les déplacements, l’annulation ni le désabonnement
elle-même. Elle appelle le sidecar figé de la CLI CleanYourMail et affiche le résultat : un seul
modèle de sécurité et un seul ensemble de règles.

## Captures d’écran

<p align="center">
  <img src="docs/images/app-provider.png" alt="Choisir un fournisseur et saisir l’adresse de la boîte mail" width="49%">
  <img src="docs/images/app-review.png" alt="Relire le plan avant de l’appliquer" width="49%">
</p>

## Prérequis

- Windows 10/11 x64 pour l’installateur.
- Python **3.12+** uniquement pour lancer depuis les sources.
- Le sidecar de la CLI CleanYourMail `1.2.2`. L’installateur l’embarque ; pour le développement,
  pointez `CYM_CLI` vers un `cym-cli.exe` compilé avec le même contrat JSON. L’app n’exécute pas
  `mail.py` directement.

## Développement

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` affiche `CleanYourMail app 0.4.0`.

Lancez les tests :

```bash
python -m pytest -q
```

La suite utilise des fixtures de CLI factice. Elle n’a jamais besoin d’une vraie boîte mail,
d’identifiants ni d’accès réseau.

## Ce que fait l’app

1. **Accueil / fournisseur.** Gmail, Outlook / Microsoft 365, Yahoo, iCloud, Fastmail, Proton Bridge
   ou IMAP personnalisé, plus l’adresse e-mail.
2. **Connexion.** Un parcours guidé de mot de passe d’application pour Gmail, un parcours par code
   d’appareil pour Outlook, et une aide propre à chaque fournisseur pour les autres. Le mot de passe
   habituel n’est jamais demandé.
3. **Préférences.** Catégories à nettoyer, dossiers ou archivage, protections, limites et langue.
4. **Relire et nettoyer.** Scan, rapport, plan, étape de relecture, application avec une limite et
   journal d’annulation. La colonne de désabonnement du plan est purement informative : cette build
   n’envoie jamais de demandes de désabonnement, et Appliquer s’exécute toujours avec
   `--action move`.

## Feedback

Les retours sont **facultatifs et manuels**. Ouvrez-les avec le bouton **Feedback** dans l’en-tête de
l’app ou utilisez le [formulaire du site](https://jparedesds.github.io/cleanyourmail-web/#feedback).
Rien n’est collecté en arrière-plan, et l’app n’envoie rien tant que vous n’avez pas cliqué sur
**Envoyer** et accepté la ligne de consentement.

- L’app préremplit une **liste de vérification modifiable** avec les versions de l’app et du
  sidecar, la version de Windows, le nom du fournisseur, le mode dossier/archivage, les catégories
  sélectionnées et la langue.
- Modifiez ou supprimez ce que vous ne voulez pas partager. **N’incluez pas** de mots de passe,
  jetons, adresses e-mail, objets d’e-mail, ID de message ni chemins de fichier dans le message ou la
  liste.
- Le champ de contact facultatif est le seul endroit où laisser un pseudo Discord, un nom
  d’utilisateur GitHub ou une adresse e-mail. Il n’est jamais obligatoire.
- La requête part vers un Worker Cloudflare (`cleanyourmail-feedback`), qui la valide et la transmet
  à un canal Discord privé. Le webhook Discord est un secret Cloudflare et n’est jamais livré avec
  l’app ni le site.
- **Aucun compte, aucune télémétrie, aucune analytique ni rapport de plantage.** Le Worker ne stocke
  aucun corps de message et applique une limite de débit à court terme basée sur une IP salée.

<a id="provider-status"></a>

## État des fournisseurs

| Fournisseur | Parcours dans l’app | État |
|---|---|---|
| Gmail | Mot de passe d’application + 2FA | OK, validé avec la CLI 1.2.2 |
| Outlook / Microsoft 365 | Code d’appareil | partiel : Microsoft 365 exige le consentement de l’administrateur du locataire ; Outlook.com personnel exige un éditeur vérifié |
| Yahoo, iCloud, Fastmail | Mot de passe d’application | documenté, sans smoke test |
| Proton Bridge | Mot de passe Bridge | documenté, sans smoke test |
| IMAP personnalisé | Hôte ; port fixe 993 avec TLS | documenté, sans smoke test |

L’app rapporte ces états honnêtement. Elle ne prétend pas offrir un support Outlook en un clic.

## Modèle de sécurité

- **Local uniquement, sauf les retours facultatifs.** Aucun compte, cloud, télémétrie ni accès au
  corps des messages. L’app ne fait aucune requête réseau en arrière-plan ; la seule qu’elle fait
  elle-même est le POST de retour après un clic sur Envoyer et l’acceptation de la ligne de
  consentement.
- **CLI uniquement.** L’app ne peut pas ajouter des capacités que la CLI n’a pas.
- **Aucun secret dans argv.** Les mots de passe d’application sont écrits dans le `password_file` de
  la CLI ; l’app ne les passe jamais en arguments de ligne de commande.
- **Aucun secret au repos dans les réglages de l’app.** Les secrets n’entrent jamais dans QSettings,
  les logs, les boîtes d’erreur ni la sortie des tests.
- **Relire d’abord.** Aucune écriture sans un plan relu ; l’annulation reste à un clic.
- **Aucune suppression définitive.** Les déplacements et archivages sont réversibles.
- **Aucun désabonnement en 0.4.0.** Le plan peut afficher des modes de désabonnement, mais Appliquer
  ne fait que déplacer les messages.
- **Anglais et espagnol de premier ordre.** Chaque chaîne vit dans `i18n/*.json`.

Voir [SECURITY.md](SECURITY.md) pour savoir comment signaler une vulnérabilité.

## Structure du projet

| Chemin | Ce que c’est |
|---|---|
| `src/cleanyourmail_app/` | Paquet de l’app native. |
| `src/cleanyourmail_app/version.py` | Source unique de la version de l’app. |
| `src/cleanyourmail_app/__main__.py` | Point d’entrée de `python -m cleanyourmail_app`. |
| `src/cleanyourmail_app/app.py` | Construit les services locaux et ouvre l’assistant. |
| `src/cleanyourmail_app/ui/` | Fenêtre, pages, widgets, thème et ressources PySide6. |
| `src/cleanyourmail_app/domain/` | Catalogue de fournisseurs, réglages, préférences et modèles de plan. |
| `src/cleanyourmail_app/services/` | Client sidecar (`cli.py`), configuration (`config.py`), secrets (`secrets.py`), OAuth (`oauth.py`) et réglages (`settings.py`). |
| `src/cleanyourmail_app/i18n/` | Chaînes en anglais et en espagnol. |
| `scripts/` | Builds du sidecar et de l’app, et smoke test de l’installateur. |
| `packaging/` | Script Inno Setup et icônes. |
| `tests/` | Suite pytest et pytest-qt avec fixtures de CLI factice. |
| `docs/superpowers/specs/` | Docs de conception (app 0.3.0, retours 0.4.0). |
| `docs/superpowers/plans/` | Plan d’implémentation tâche par tâche. |

## Liens

- Versions publiées de l’app : <https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- Skill et CLI : <https://github.com/jparedesDS/cleanyourmail>
- Site : <https://jparedesds.github.io/cleanyourmail-web/>
- Modèle de sécurité : <https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## Licence

MIT. Voir [LICENSE](LICENSE).
