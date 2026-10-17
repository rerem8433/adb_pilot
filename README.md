# ADB Pilot

**Gestionnaire d'appareils Android via ADB pour Linux, natif — sans Wine.**

ADB Pilot permet de gérer un téléphone ou une box Android TV depuis Ubuntu / Linux Mint : lister les applications avec leurs noms, icônes et versions, désactiver ou désinstaller le bloatware, installer des APK / XAPK / APKS / APKM, sauvegarder des applications, suivre les processus, piloter l'écran avec scrcpy et ouvrir une console adb / fastboot.

Développé par **ParadoxXx Squad** — [github.com/rerem8433/adb_pilot](https://github.com/rerem8433/adb_pilot)

🇫🇷 [Français](#adb-pilot) · 🇬🇧 [English](#adb-pilot--english)

> Langue de l'interface : **français** uniquement pour le moment.

---

## Pourquoi ce projet ?

J'utilisais depuis longtemps **[ADB AppControl](https://adbappcontrol.com)** (de *Cyber.Cat*) sous Windows pour gérer mes box Android TV. En passant sous Linux, la seule option était de le faire tourner via Wine, avec des résultats aléatoires.

ADB Pilot est donc une **réécriture complète pour Linux**, qui reprend l'ergonomie d'ADB AppControl. Aucun code, logo ou ressource d'ADB AppControl n'a été réutilisé : l'application est écrite de zéro en Python + Qt 6. Elle a été conçue avec l'aide de **Claude**, l'assistant IA d'Anthropic, puis testée et ajustée sur mon propre parc de box.

> ADB Pilot est un projet indépendant, **sans lien** avec ADB AppControl ni avec son auteur.

## Fonctionnalités

**Applications**
- Liste des applications avec **nom réel, icône et version**, sans rien installer sur l'appareil. Les infos sont lues directement dans les APK (manifeste, `resources.arsc`), alors qu'ADB AppControl passe par une appli compagnon.
- Filtres Toutes / Système / Utilisateur / Désactivées / Supprimées, recherche, tri par colonne.
- Actions groupées : désactiver, désinstaller (utilisateur 0), effacer les données, effacer le cache, sauvegarder le fichier d'installation. Au clic droit : activer, restaurer, forcer l'arrêt, permissions, infos détaillées.
- **Assistant debloat** à 4 niveaux (Basique, Sûr, Moyen, Maximal), basé sur des listes texte modifiables.
- Presets (listes d'applis cochées) à enregistrer et recharger.

**Installation**
- Bibliothèque d'APK favoris (`~/ADB_Pilot/install`) et dossier par appareil.
- APK, split APK, **XAPK** (avec OBB), **APKS**, **APKM**, par glisser-déposer.
- Pour chaque fichier, l'état sur l'appareil : non installée, identique, mise à jour disponible, version plus récente déjà installée.

**Outils**
- Infos de l'appareil : processeur (marque et modèle), RAM, stockage, et **vraie version d'Android**. Celle-ci est lue dans `framework-res.apk`, ce qui permet de repérer un `build.prop` falsifié.
- Captures d'écran, enregistrement vidéo, touches (volume, power, accueil…), redémarrage (recovery, bootloader…).
- **scrcpy** intégré : choix de la résolution et enregistrement vidéo de la session.
- Connexion Wi-Fi (IP + port, historique), passage USB → Wi-Fi, appairage Android 11+.

**Processus** : applications en cours, RAM en %, application au premier plan, forcer l'arrêt.

**Console** : commandes `adb` / `fastboot`, shell interactif, logcat, commandes rapides. Taper `shell` ouvre un terminal.

## Compatibilité

Le paquet `.deb` est prévu pour les distributions **64 bits (amd64)** qui ont au minimum **glibc 2.34** et **Python 3.10**.

| Distribution | Statut |
|---|---|
| Ubuntu 22.04 LTS, 24.04 LTS et suivantes | ✅ Compatible |
| Linux Mint 21.x et 22.x (Cinnamon, MATE, Xfce) | ✅ Compatible (testé sous Cinnamon) |
| Kubuntu, Xubuntu, Lubuntu, Ubuntu MATE 22.04+ | ✅ Compatible |
| Zorin OS 17+, Pop!_OS 22.04+, elementary OS 7+, KDE neon 22.04+ | ✅ Devrait fonctionner (base Ubuntu 22.04+) |
| Debian 12 (Bookworm) et suivantes | ⚠️ Devrait fonctionner (non testé) |
| Ubuntu 20.04, Linux Mint 20.x et plus anciennes | ❌ Non compatible (glibc et Python trop anciens) |
| Architectures ARM (Raspberry Pi…) | ❌ Non compatible (paquet amd64 uniquement) |

Fonctionne sous X11 et Wayland.

## Installation

1. Télécharge le dernier `adbpilot_X.Y.Z_amd64.deb` dans les [Releases](https://github.com/rerem8433/adb_pilot/releases).
2. Installe-le **avec `apt`**, qui récupère automatiquement les dépendances :

```bash
sudo apt install ./adbpilot_1.2.1_amd64.deb
```

Le double-clic sur le fichier (Gestionnaire de paquets / GDebi) fonctionne aussi. Si tu utilises `dpkg -i`, lance ensuite `sudo apt -f install` pour compléter les dépendances.

ADB Pilot apparaît ensuite dans le menu des applications (catégorie Utilitaires), ou se lance avec la commande `adbpilot`.

### Dépendances

Rien à installer à la main. Tout est installé automatiquement par `apt` lors de l'installation du `.deb`.

**Obligatoires** (déjà présentes sur la plupart des bureaux Ubuntu/Mint) :

| Paquet | Rôle |
|---|---|
| `python3` (≥ 3.10) | Exécution de l'application |
| `libxcb-cursor0`, `libxcb-icccm4`, `libxcb-keysyms1`, `libxcb-image0`, `libxcb-render-util0`, `libxcb-shape0`, `libxcb-xkb1`, `libxcb-randr0`, `libxcb-util1`, `libxkbcommon0`, `libxkbcommon-x11-0` | Affichage Qt 6 sous X11 |
| `libwayland-client0`, `libwayland-cursor0`, `libwayland-egl1` | Affichage sous Wayland |
| `libegl1`, `libgl1`, `libfontconfig1`, `libfreetype6`, `libdbus-1-3`, `libglib2.0-0` | Rendu, polices, intégration au bureau |

**Recommandées** (installées par défaut avec `apt`) :

| Paquet | Rôle |
|---|---|
| `adb` | Communication avec les appareils Android |
| `scrcpy` | Affichage et contrôle de l'écran |
| `android-sdk-platform-tools-common` | Règles udev : accès aux appareils USB sans `sudo` |

**Suggérée** : `fastboot`, pour les commandes fastboot de la console.

Qt 6 / PySide6 est **embarqué dans le paquet**. Il n'y a rien à installer via `pip`.

> Une version plus récente d'adb ou de scrcpy que celle des dépôts peut être téléchargée depuis **Paramètres → Télécharger adb / scrcpy**.

### Désinstallation

```bash
sudo apt remove adbpilot
```

Tes fichiers dans `~/ADB_Pilot` sont conservés.

## Premiers pas

- **USB** : active le *Débogage USB* dans les Options développeur de l'appareil, branche-le et accepte la demande d'autorisation. Si l'appareil apparaît en *no permissions*, vérifie que `android-sdk-platform-tools-common` est installé, puis débranche et rebranche.
- **Wi-Fi** : active le *Débogage ADB réseau* sur la box, saisis son IP en haut à droite (port `Auto` = 5555), puis **GO !**. Le bouton historique permet de se reconnecter en un clic.
- **Android 11+ sans fil** : Outils → *Appairer*.

## Compiler depuis les sources

```bash
python3 -m venv venv && . venv/bin/activate
pip install PySide6-Essentials
python -m adbpilot                                   # lancer sans installer
python packaging/build.py venv/lib/python3.*/site-packages out   # construire le .deb
```

## Dossiers

Tout est centralisé dans `~/ADB_Pilot/` (sans espace, pratique en ligne de commande) :

| Dossier | Contenu |
|---|---|
| `~/ADB_Pilot/images/` | Captures d'écran |
| `~/ADB_Pilot/videos/` | Enregistrements d'écran et sessions scrcpy |
| `~/ADB_Pilot/install/` | Ta bibliothèque d'APK à installer (+ un sous-dossier par appareil) |
| `~/ADB_Pilot/apps/<appareil>/` | Sauvegardes : `nomappli_(paquet)_version.apk` (`.apks` pour les applis en plusieurs fichiers) |
| `~/ADB_Pilot/debloat/` | Listes de debloat `debloat0.db` à `debloat3.db` |

La configuration est dans `~/.config/adbpilot/` et le cache des icônes dans `~/.cache/adbpilot/`.

## Listes de debloat

Les fichiers `~/ADB_Pilot/debloat/debloat0.db` à `debloat3.db` sont de simples fichiers texte : un nom de paquet par ligne, `#` pour les commentaires. Ils sont relus automatiquement après modification.

Les niveaux sont **cumulatifs** :

| Niveau | Fichiers utilisés |
|---|---|
| Basique | `debloat0.db` |
| Sûr | `debloat0.db` + `debloat1.db` |
| Moyen | `debloat0.db` à `debloat2.db` |
| Maximal | `debloat0.db` à `debloat3.db` |

L'assistant ne fait que **cocher** les applications concernées. Rien n'est désactivé avant que tu cliques sur *Appliquer*.

## ⚠️ Avertissement

Désactiver ou désinstaller des applications système peut provoquer des dysfonctionnements : perte du clavier de la télécommande, de la mise à jour OTA, du Play Store… Vérifie toujours la liste avant d'appliquer. Une application supprimée pour l'utilisateur 0 peut être restaurée depuis le filtre *Supprimées* → clic droit → *Restaurer*. Tu utilises ce logiciel à tes propres risques.

## Mentions et crédits

- **Inspiration** : [ADB AppControl](https://adbappcontrol.com) par *Cyber.Cat*, pour l'ergonomie et le principe. Aucun code ni ressource repris. ADB AppControl est un logiciel propriétaire distinct.
- **Développement** : ParadoxXx Squad, avec l'aide de **Claude** (Anthropic).
- **Qt 6 / PySide6** — The Qt Company, licence **LGPL-3.0**. Embarqué dans le paquet et lié dynamiquement.
- **[Universal Android Debloater Next Generation (UAD-ng)](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation)** — licence **GPL-3.0**. Descriptions de paquets affichées dans les infos-bulles.
- **[scrcpy](https://github.com/Genymobile/scrcpy)** — Genymobile, licence **Apache-2.0**. Non embarqué : installé depuis les dépôts ou téléchargé à la demande.
- **adb / fastboot** (Android SDK Platform-Tools) — Android Open Source Project, licence **Apache-2.0**. Non embarqués.
- **libxcb-cursor** — licence MIT/X11. Copie de secours incluse uniquement dans l'archive portable.
- *Android* est une marque de Google LLC. Les autres noms cités appartiennent à leurs propriétaires respectifs.

## Licence

ADB Pilot est distribué sous licence **GNU General Public License v3.0**. Voir le fichier [LICENSE](LICENSE).

Copyright © 2026 ParadoxXx Squad

---
---

# ADB Pilot — English

**Native Linux Android device manager over ADB — no Wine needed.**

ADB Pilot lets you manage an Android phone or Android TV box from Ubuntu / Linux Mint. You can:
- list apps with their real names, icons and versions;
- disable or uninstall bloatware;
- install APK / XAPK / APKS / APKM files;
- back up apps;
- monitor running processes;
- mirror and control the screen with scrcpy;
- use an adb / fastboot console.

Developed by **ParadoxXx Squad** — [github.com/rerem8433/adb_pilot](https://github.com/rerem8433/adb_pilot)

> User interface language: **French** only for now.

## Why this project?

For a long time I used **[ADB AppControl](https://adbappcontrol.com)** (by *Cyber.Cat*) on Windows to manage my Android TV boxes. After moving to Linux, the only option left was running it through Wine, with hit-and-miss results.

ADB Pilot is a **complete rewrite for Linux** that follows the workflow of ADB AppControl. No code, logo or asset from ADB AppControl was reused: the app is written from scratch in Python + Qt 6. It was designed with the help of **Claude**, Anthropic's AI assistant, then tested and refined on my own fleet of boxes.

> ADB Pilot is an independent project, **not affiliated** with ADB AppControl or its author.

## Features

**Applications**
- App list with **real name, icon and version**, without installing anything on the device. Data is read directly from the APKs (manifest, `resources.arsc`). ADB AppControl relies on a companion app for this.
- Filters (All / System / User / Disabled / Uninstalled), search, sortable columns.
- Batch actions: disable, uninstall (user 0), clear data, clear cache, back up the installation file.
- Right-click actions: enable, restore, force stop, permissions, detailed info.
- 4-level **debloat wizard** (Basic, Safe, Medium, Maximum) based on editable text lists.
- Presets: save and reload sets of checked apps.

**Installation**
- Favourite APK library (`~/ADB_Pilot/install`), plus a folder per device.
- APK, split APK, **XAPK** (with OBB), **APKS**, **APKM**, with drag & drop.
- Each file shows its status on the device: not installed, identical, update available, or newer version already installed.

**Tools**
- Device info: CPU (brand and model), RAM, storage and the **real Android version**. The version is read from `framework-res.apk`, so a tampered `build.prop` is detected.
- Screenshots, screen recording, hardware keys (volume, power, home…), reboot to recovery / bootloader…
- Built-in **scrcpy** launcher with resolution choice and session recording.
- Wi-Fi connection (IP + port, history), USB → Wi-Fi switch, Android 11+ pairing.

**Processes**: running apps, RAM usage in %, foreground app, force stop.

**Console**: `adb` / `fastboot` commands, interactive shell, logcat, quick commands. Typing `shell` opens a terminal.

## Compatibility

The `.deb` package targets **64-bit (amd64)** distributions with at least **glibc 2.34** and **Python 3.10**.

| Distribution | Status |
|---|---|
| Ubuntu 22.04 LTS, 24.04 LTS and newer | ✅ Compatible |
| Linux Mint 21.x and 22.x (Cinnamon, MATE, Xfce) | ✅ Compatible (tested on Cinnamon) |
| Kubuntu, Xubuntu, Lubuntu, Ubuntu MATE 22.04+ | ✅ Compatible |
| Zorin OS 17+, Pop!_OS 22.04+, elementary OS 7+, KDE neon 22.04+ | ✅ Should work (Ubuntu 22.04+ base) |
| Debian 12 (Bookworm) and newer | ⚠️ Should work (untested) |
| Ubuntu 20.04, Linux Mint 20.x and older | ❌ Not compatible (glibc and Python too old) |
| ARM architectures (Raspberry Pi…) | ❌ Not compatible (amd64 package only) |

Works on both X11 and Wayland.

## Installation

1. Download the latest `adbpilot_X.Y.Z_amd64.deb` from the [Releases](https://github.com/rerem8433/adb_pilot/releases) page.
2. Install it **with `apt`**, which pulls in the dependencies automatically:

```bash
sudo apt install ./adbpilot_1.2.1_amd64.deb
```

Double-clicking the file (Package Installer / GDebi) also works. If you use `dpkg -i`, run `sudo apt -f install` afterwards to complete the dependencies.

ADB Pilot then appears in the application menu (Utilities), or can be started with the `adbpilot` command.

### Dependencies

Nothing to install by hand. Everything is installed automatically by `apt` when installing the `.deb`.

**Required** (already present on most Ubuntu/Mint desktops):

| Package | Purpose |
|---|---|
| `python3` (≥ 3.10) | Runs the application |
| `libxcb-cursor0`, `libxcb-icccm4`, `libxcb-keysyms1`, `libxcb-image0`, `libxcb-render-util0`, `libxcb-shape0`, `libxcb-xkb1`, `libxcb-randr0`, `libxcb-util1`, `libxkbcommon0`, `libxkbcommon-x11-0` | Qt 6 display on X11 |
| `libwayland-client0`, `libwayland-cursor0`, `libwayland-egl1` | Display on Wayland |
| `libegl1`, `libgl1`, `libfontconfig1`, `libfreetype6`, `libdbus-1-3`, `libglib2.0-0` | Rendering, fonts, desktop integration |

**Recommended** (installed by default with `apt`):

| Package | Purpose |
|---|---|
| `adb` | Communication with Android devices |
| `scrcpy` | Screen mirroring and control |
| `android-sdk-platform-tools-common` | udev rules: USB device access without `sudo` |

**Suggested**: `fastboot`, for fastboot commands in the console.

Qt 6 / PySide6 is **bundled in the package**. Nothing needs to be installed with `pip`.

> A newer adb or scrcpy than the one in the repositories can be downloaded from **Paramètres → Télécharger adb / scrcpy** (Settings → Download).

### Uninstall

```bash
sudo apt remove adbpilot
```

Your files in `~/ADB_Pilot` are kept.

## Getting started

- **USB**: enable *USB debugging* in the device's Developer options, plug it in and accept the authorization prompt. If the device shows up as *no permissions*, make sure `android-sdk-platform-tools-common` is installed, then unplug and replug it.
- **Wi-Fi**: enable *ADB over network* on the box, type its IP in the top-right field (port `Auto` = 5555), then click **GO !**. The history button reconnects in one click.
- **Android 11+ wireless debugging**: Outils (Tools) → *Appairer* (Pair).

## Build from source

```bash
python3 -m venv venv && . venv/bin/activate
pip install PySide6-Essentials
python -m adbpilot                                   # run without installing
python packaging/build.py venv/lib/python3.*/site-packages out   # build the .deb
```

## Folders

Everything lives in `~/ADB_Pilot/` (no spaces, easy to use from a terminal):

| Folder | Content |
|---|---|
| `~/ADB_Pilot/images/` | Screenshots |
| `~/ADB_Pilot/videos/` | Screen recordings and scrcpy sessions |
| `~/ADB_Pilot/install/` | Your APK library (+ one sub-folder per device) |
| `~/ADB_Pilot/apps/<device>/` | Backups: `appname_(package)_version.apk` (`.apks` for split apps) |
| `~/ADB_Pilot/debloat/` | Debloat lists `debloat0.db` to `debloat3.db` |

Settings are stored in `~/.config/adbpilot/` and the icon cache in `~/.cache/adbpilot/`.

## Debloat lists

`~/ADB_Pilot/debloat/debloat0.db` to `debloat3.db` are plain text files: one package name per line, `#` for comments. They are reloaded automatically after you edit them.

Levels are **cumulative**:

| Level | Files used |
|---|---|
| Basic | `debloat0.db` |
| Safe | `debloat0.db` + `debloat1.db` |
| Medium | `debloat0.db` to `debloat2.db` |
| Maximum | `debloat0.db` to `debloat3.db` |

The wizard only **checks** the matching apps. Nothing is disabled until you click *Appliquer* (Apply).

## ⚠️ Disclaimer

Disabling or uninstalling system apps can break things: remote-control keyboard, OTA updates, Play Store… Always review the list before applying. An app uninstalled for user 0 can be restored from the *Supprimées* (Uninstalled) filter → right-click → *Restaurer* (Restore). Use this software at your own risk.

## Credits and notices

- **Inspiration**: [ADB AppControl](https://adbappcontrol.com) by *Cyber.Cat*, for its workflow and concept. No code or assets reused. ADB AppControl is a separate proprietary program.
- **Development**: ParadoxXx Squad, with the help of **Claude** (Anthropic).
- **Qt 6 / PySide6** — The Qt Company, **LGPL-3.0** license. Bundled and dynamically linked.
- **[Universal Android Debloater Next Generation (UAD-ng)](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation)** — **GPL-3.0** license. Package descriptions shown in tooltips.
- **[scrcpy](https://github.com/Genymobile/scrcpy)** — Genymobile, **Apache-2.0** license. Not bundled: installed from the repositories or downloaded on demand.
- **adb / fastboot** (Android SDK Platform-Tools) — Android Open Source Project, **Apache-2.0** license. Not bundled.
- **libxcb-cursor** — MIT/X11 license. Fallback copy included only in the portable archive.
- *Android* is a trademark of Google LLC. Other names mentioned belong to their respective owners.

## License

ADB Pilot is released under the **GNU General Public License v3.0**. See [LICENSE](LICENSE).

Copyright © 2026 ParadoxXx Squad
