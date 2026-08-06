#!/usr/bin/env python3
"""Optional Hermes command-TTS adapter that speaks via Home Assistant TTS.

Configure Hermes (when using a command TTS provider) to invoke this script.
It calls HA /api/tts_get_url, downloads the audio, and writes it to --output
(or stdout path printed for Hermes to pick up).

Environment (synced by the add-on when HA is configured):
  HASS_URL / HOMEASSISTANT_URL
  HASS_TOKEN / HOMEASSISTANT_TOKEN

Optional:
  HA_TTS_PLATFORM   default: tts.piper (entity_id without domain is accepted)
  HA_TTS_LANGUAGE   e.g. en

Usage (example):
  python3 ha-tts-command.py --text "Hello from Hermes" --output /tmp/out.mp3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _env(*names: str) -> str:
    for name in names:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Speak text via Home Assistant TTS")
    parser.add_argument("--text", required=True, help="Text to synthesize")
    parser.add_argument("--output", required=True, help="Output audio file path")
    parser.add_argument(
        "--platform",
        default=_env("HA_TTS_PLATFORM") or "tts.piper",
        help="TTS entity_id (default tts.piper or HA_TTS_PLATFORM)",
    )
    parser.add_argument(
        "--language",
        default=_env("HA_TTS_LANGUAGE") or "",
        help="Optional language code",
    )
    args = parser.parse_args()

    base = _env("HASS_URL", "HOMEASSISTANT_URL").rstrip("/")
    token = _env("HASS_TOKEN", "HOMEASSISTANT_TOKEN")
    if not base or not token:
        print("ERROR: HASS_URL and HASS_TOKEN are required", file=sys.stderr)
        return 2

    platform = args.platform.strip()
    if "." not in platform:
        platform = f"tts.{platform}"

    body: dict = {
        "platform": platform.split(".", 1)[-1] if platform.startswith("tts.") else platform,
        "message": args.text,
    }
    # Prefer entity_id form when HA version supports it.
    body["entity_id"] = platform
    if args.language:
        body["language"] = args.language

    req = urllib.request.Request(
        f"{base}/api/tts_get_url",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR: HA TTS HTTP {e.code}: {e.read()[:200]!r}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — surface to Hermes as command failure
        print(f"ERROR: HA TTS request failed: {e}", file=sys.stderr)
        return 1

    url = (payload.get("url") or "").strip()
    if not url:
        print(f"ERROR: No url in TTS response: {payload!r}", file=sys.stderr)
        return 1
    if url.startswith("/"):
        url = f"{base}{url}"

    audio_req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(audio_req, timeout=60) as audio_resp:
            data = audio_resp.read()
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: Failed to download TTS audio: {e}", file=sys.stderr)
        return 1

    out = args.output
    try:
        with open(out, "wb") as fh:
            fh.write(data)
    except OSError as e:
        print(f"ERROR: Cannot write {out}: {e}", file=sys.stderr)
        return 1

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
