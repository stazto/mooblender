# Installation

## Requirements

- Blender 4.5 LTS or Blender 5.2 LTS.
- A Mooblender extension ZIP built by the project or downloaded from a trusted
  project release.
- Blender **Online Access** enabled if you want to synchronize or download from
  [Mooble](https://www.mooble.com/br/). Local file imports do not require
  network access unless a PContent package references remote child resources.

## Install from a ZIP

1. Download `mooblender-<version>.zip`. Do not extract it.
2. In Blender, open **Edit → Preferences**.
3. Select **Extensions**.
4. Open the Extensions menu in the top-right corner and select
   **Install from Disk**.
5. Choose the Mooblender ZIP and confirm the installation.
6. Search for **Mooblender** and make sure it is enabled.

<!-- SCREENSHOT: Add _static/screenshots/install-from-disk.png here. Capture
Blender 4.5 LTS Preferences > Extensions with the top-right menu open and
"Install from Disk" highlighted. Crop out usernames and filesystem paths. -->

The extension appears as a **Mooble** tab in the 3D View sidebar and adds
**[Promob](https://promob.com/) Model** to Blender's File → Import menu.

## Enable online access

1. Open **Edit → Preferences → System**.
2. Find the **Network** section.
3. Enable **Allow Online Access**.

<!-- SCREENSHOT: Add _static/screenshots/allow-online-access.png here. Capture
Preferences > System with the Network section and Allow Online Access visible.
Do not include unrelated system or account information. -->

When online access is disabled, Mooblender keeps the cached catalog available
but disables catalog synchronization and remote model downloads.

## Upgrade

Install the newer ZIP with **Install from Disk**. Blender replaces the extension
code while keeping its Blender-managed user data. If the catalog schema changed,
the Mooble panel asks you to run **Sync Catalog** once before browsing.

## Uninstall

Open **Edit → Preferences → Extensions**, find Mooblender, open its menu, and
select **Uninstall**. Blender may retain extension data separately from the
installed code. Use **Clear Downloads** before uninstalling if you want to remove
cached models and thumbnails from within Mooblender.
