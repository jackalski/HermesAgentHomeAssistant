#!/usr/bin/env python3
"""Patch Hermes PyPI wheels missing hermes_cli subpackages (upstream #34701 on older releases)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

SUBPACKAGES = ("dashboard_auth", "proxy")
DEFAULT_TAG = "v2026.6.5"
FALLBACK_ARCHIVE = "https://github.com/NousResearch/hermes-agent/archive/45b00bb49.tar.gz"


def _hermes_cli_site_packages() -> str:
    import hermes_cli

    return os.path.dirname(hermes_cli.__file__)


def _missing_subpackages(site: str) -> list[str]:
    return [
        sub
        for sub in SUBPACKAGES
        if not os.path.isfile(os.path.join(site, sub, "__init__.py"))
    ]


def _resolve_source_tag() -> str:
    try:
        proc = subprocess.run(
            ["hermes", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
        line = (proc.stdout or proc.stderr or "").splitlines()[0]
    except (FileNotFoundError, IndexError):
        return DEFAULT_TAG

    match = re.search(r"\((20[0-9]{2}\.[0-9]+\.[0-9]+\.[0-9]+)\)", line)
    if match:
        return f"v{match.group(1)}"
    return DEFAULT_TAG


def _download_archive(url: str, dest: str) -> None:
    with urllib.request.urlopen(url, timeout=120) as response:
        with open(dest, "wb") as handle:
            shutil.copyfileobj(response, handle)


def _extract_top_dir(extract_root: str) -> str:
    for name in os.listdir(extract_root):
        path = os.path.join(extract_root, name)
        if name.startswith("hermes-agent-") and os.path.isdir(path):
            return path
    raise RuntimeError("hermes-agent source archive missing top-level directory")


def _patch_from_archive(site: str, missing: list[str], archive_url: str) -> None:
    with tempfile.TemporaryDirectory(prefix="hermes-src-") as tmp:
        archive = os.path.join(tmp, "src.tgz")
        extract_root = os.path.join(tmp, "extract")
        os.makedirs(extract_root, exist_ok=True)
        _download_archive(archive_url, archive)
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(extract_root)
        top = _extract_top_dir(extract_root)
        for sub in missing:
            src = os.path.join(top, "hermes_cli", sub)
            dst = os.path.join(site, sub)
            if not os.path.isdir(src):
                continue
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"patched hermes_cli/{sub}")


def main() -> int:
    try:
        site = _hermes_cli_site_packages()
    except ImportError:
        print("WARN: hermes_cli not installed; skipping wheel repair.", file=sys.stderr)
        return 0

    missing = _missing_subpackages(site)
    if not missing:
        return 0

    tag = _resolve_source_tag()
    archive_url = f"https://github.com/NousResearch/hermes-agent/archive/refs/tags/{tag}.tar.gz"
    try:
        _patch_from_archive(site, missing, archive_url)
    except Exception as first_error:
        print(
            f"WARN: Could not patch from tag {tag} ({first_error}); trying packaging-fix commit.",
            file=sys.stderr,
        )
        try:
            _patch_from_archive(site, missing, FALLBACK_ARCHIVE)
        except Exception as second_error:
            print(f"ERROR: Hermes wheel repair failed: {second_error}", file=sys.stderr)
            return 1

    if _missing_subpackages(site):
        print("ERROR: hermes_cli subpackage repair incomplete.", file=sys.stderr)
        return 1

    print("INFO: hermes_cli subpackages repair complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
