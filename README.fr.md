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
pas de suppression définitive. L’app ne contacte elle-même que le flux public des versions GitHub
(pour les mises à jour) et le Worker de retour (uniquement après **Envoyer** et le consentement).

> **État :** `0.6.1` est la version early-MVP Windows actuelle. Elle ajoute les mises à jour
> automatiques : l’app installée consulte la version publique GitHub, vérifie le SHA-256 de
> l’installateur et installe après une confirmation. L’installateur embarque le sidecar figé de la CLI
> CleanYourMail `1.3.0`. Gmail est validé ; Outlook dépend du modèle de consentement de Microsoft.
> Voir la section [État des fournisseurs](#provider-status).

## Téléchargement

[CleanYourMail app 0.6.1 pour Windows 10/11 x64](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)
est un installateur par utilisateur qui embarque le sidecar figé de la CLI CleanYourMail `1.3.0` et
ne nécessite aucun droit administrateur.

L’installateur 0.6.1 n’est pas signé. Windows SmartScreen peut afficher un avertissement « Éditeur
inconnu » au premier lancement : choisissez **Informations complémentaires**, puis **Exécuter quand
même**, et comparez le SHA-256 publié avec la version à celui de `CleanYourMail-Setup-0.6.1.exe` :

```powershell
Get-FileHash .\CleanYourMail-Setup-0.6.1.exe -Algorithm SHA256
```

La version publie également un fichier `.sha256` au format `HASH  filename`.

## Mises à jour automatiques

L’app installée consulte la [version publique GitHub](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)
au plus toutes les six heures, et le bouton **Updates** de l’en-tête vérifie à la demande. La requête
indique la version de l’app et votre IP à GitHub ; elle n’envoie ni données de compte, ni données de
boîte mail, ni jetons.

Quand une version plus récente existe, une bannière propose **Install update** et **Later**.
**Install update** demande une confirmation. L’app télécharge ensuite l’exécutable exact
`CleanYourMail-Setup-<version>.exe` et son `.sha256` en HTTPS, vérifie le SHA-256 avant d’exécuter
quoi que ce soit, se ferme, exécute l’installateur silencieusement pour l’utilisateur courant et
rouvre la nouvelle version.

Une mise à jour échouée ne boucle jamais et ne s’installe jamais pendant que l’app tourne.
Un contrôle automatique qui échoue reste silencieux ;
cliquez sur **Updates** pour réessayer à la main. Un contrôle manuel en échec affiche un message
localisé avec **Open GitHub**. Si la release n’a pas d’installateur ou de checksum valide, la
bannière propose **Open GitHub** au lieu de **Install update**. Un échec de téléchargement, de
vérification ou de hachage affiche une erreur localisée avec **Install update** pour réessayer et
**Open GitHub** pour la page de la release. Si l’assistant de mise à jour ne peut pas démarrer,
l’app reste ouverte et la bannière propose **Open GitHub**. Si l’installateur démarre mais échoue,
l’assistant rouvre l’ancienne app ; aucune bannière d’échec n’est enregistrée, donc utilisez
**Updates** pour réessayer ou ouvrez la page de la release à la main.

L’installateur 0.6.1 n’est pas signé, donc SmartScreen peut avertir pendant la mise à jour comme lors
d’une exécution manuelle : choisissez **Informations complémentaires**, puis **Exécuter quand même**.
Le SHA-256 prouve que le téléchargement est intact, pas qui l’a publié ; la signature de code est la
prochaine étape de sécurité. Si l’installation automatique n’est pas disponible (par exemple depuis
le code source), le même parcours propose la page de la version pour installer à la main.

Gmail fonctionne avec un mot de passe d’application et la validation en deux étapes. Outlook /
Microsoft 365 ne fonctionne pas en un clic : Microsoft 365 exige le consentement de l’administrateur
du locataire, et les comptes personnels Outlook.com exigent un éditeur vérifié. macOS et Linux sont
hors périmètre pour 0.6.1.

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

<p align="center"><em>Données de démonstration synthétiques. Choisissez un fournisseur, puis vérifiez le plan avant d'appliquer quoi que ce soit.</em></p>

## Prérequis

- Windows 10/11 x64 pour l’installateur.
- Python **3.12+** uniquement pour lancer depuis les sources.
- Le sidecar de la CLI CleanYourMail `1.3.0`. L’installateur l’embarque ; pour le développement,
  pointez `CYM_CLI` vers un `cym-cli.exe` compilé avec le même contrat JSON. L’app n’exécute pas
  `mail.py` directement.

## Développement

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` affiche `CleanYourMail app 0.6.1`.

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
l’app ou utilisez le [formulaire du site](https://cleanyourmail.org/#feedback). Aucune donnée de
retour n’est collectée en arrière-plan, et le formulaire n’envoie rien tant que vous n’avez pas
cliqué sur **Envoyer** et accepté la ligne de consentement. La seule requête réseau automatique est
la vérification des mises à jour décrite plus haut.

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
| Gmail | Mot de passe d’application + 2FA | OK, validé avec la CLI 1.3.0 |
| Outlook / Microsoft 365 | Code d’appareil | partiel : Microsoft 365 exige le consentement de l’administrateur du locataire ; Outlook.com personnel exige un éditeur vérifié |
| Yahoo, iCloud, Fastmail | Mot de passe d’application | documenté, sans smoke test |
| Proton Bridge | Mot de passe Bridge | documenté, sans smoke test |
| IMAP personnalisé | Hôte ; port fixe 993 avec TLS | documenté, sans smoke test |

L’app rapporte ces états honnêtement. Elle ne prétend pas offrir un support Outlook en un clic.

## Modèle de sécurité

- **Local par défaut, sauf retours facultatifs.** Aucun compte, cloud, télémétrie ni accès au corps
  des messages. L’app fait deux requêtes elle-même : la consultation publique des versions GitHub
  (version et IP seulement ; au plus toutes les six heures ou via **Updates**) et le POST de retour
  après Envoyer et consentement. L’accès réseau au mail appartient au sidecar.
- **Mises à jour vérifiées.** L’installateur est téléchargé en HTTPS depuis la version GitHub, vérifié
  avec le SHA-256 publié et exécuté seulement après une confirmation. L’installateur 0.6.1 n’est pas
  signé, donc SmartScreen peut avertir ; le SHA-256 prouve l’intégrité, pas l’auteur.
- **CLI uniquement.** L’app ne peut pas ajouter des capacités que la CLI n’a pas.
- **Aucun secret dans argv.** Les mots de passe d’application sont écrits dans le `password_file` de
  la CLI ; l’app ne les passe jamais en arguments de ligne de commande.
- **Aucun secret au repos dans les réglages de l’app.** Les secrets n’entrent jamais dans QSettings,
  les logs, les boîtes d’erreur ni la sortie des tests.
- **Relire d’abord.** Aucune écriture sans un plan relu ; l’annulation reste à un clic.
- **Aucune suppression définitive.** Les déplacements et archivages sont réversibles.
- **Aucun désabonnement en 0.6.1.** Le plan peut afficher des modes de désabonnement, mais Appliquer
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
- Site : <https://cleanyourmail.org/>
- Modèle de sécurité : <https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## Licence

MIT. Voir [LICENSE](LICENSE).
