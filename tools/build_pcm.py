# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the KiCad Plugin and Content Manager package.

    python3 tools/build_pcm.py

Reads pcm/metadata.json (one version, no download fields) and writes to dist/:

* <identifier>_<version>.zip   - the package: plugins/, resources/icon.png,
                                 metadata.json (as read)
* metadata.json                - the copy for gitlab.com/kicad/addons/metadata
                                 (packages/<identifier>/), with download_url,
                                 download_sha256, download_size, install_size
* icon.png                     - goes beside it in the metadata repository

The zip is meant for a GitHub release tagged v<version>; download_url points
there.
"""

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "fab_drc_rules"
TEMPLATE = ROOT / "pcm" / "metadata.json"
DIST = ROOT / "dist"
ICON = PLUGIN / "resources" / "icon.png"
RELEASE_URL = "https://github.com/JYPochez/Fab-DRC-Rules-for-KiCad/releases/download/v{version}/{name}"
# Not shipped: caches, per-user settings, icon sources.
SKIP_NAMES = {"__pycache__", "settings.json", ".DS_Store", "resources"}
# Zip entries get a fixed date so the same sources give the same SHA-256.
FIXED_DATE = (2020, 1, 1, 0, 0, 0)


def plugin_files():
    for path in sorted(PLUGIN.rglob("*")):
        relative = path.relative_to(PLUGIN)
        if path.is_file() and not SKIP_NAMES.intersection(relative.parts):
            yield path, "plugins/" + relative.as_posix()


def add(archive, name, data):
    info = zipfile.ZipInfo(name, FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)
    return len(data)


def main():
    metadata = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    if len(metadata["versions"]) != 1:
        sys.exit("pcm/metadata.json must hold exactly one version")
    version = metadata["versions"][0]
    if any(key.startswith("download_") or key == "install_size" for key in version):
        sys.exit("pcm/metadata.json must not hold download fields")

    DIST.mkdir(exist_ok=True)
    name = "{}_{}.zip".format(metadata["identifier"], version["version"])
    package = DIST / name
    install_size = 0
    with zipfile.ZipFile(package, "w") as archive:
        for path, arcname in plugin_files():
            install_size += add(archive, arcname, path.read_bytes())
        install_size += add(archive, "resources/icon.png", ICON.read_bytes())
        install_size += add(archive, "metadata.json",
                            (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))

    data = package.read_bytes()
    version.update(
        download_url=RELEASE_URL.format(version=version["version"], name=name),
        download_sha256=hashlib.sha256(data).hexdigest(),
        download_size=len(data),
        install_size=install_size,
    )
    (DIST / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    shutil.copy2(str(ICON), str(DIST / "icon.png"))
    print("package  ", package)
    print("sha256   ", version["download_sha256"])
    print("size     ", version["download_size"], "download /", install_size, "installed")
    print("metadata ", DIST / "metadata.json")


if __name__ == "__main__":
    main()
