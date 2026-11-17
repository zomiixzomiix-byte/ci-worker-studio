"""Export active AI Studio keys safely into an encrypted-secret-ready bundle without printing raw secrets."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

DEFAULT_VAULT = Path(os.environ.get("AEGIS_KEYS_VAULT", str(Path.home() / ".gemini" / "antigravity" / "scratch" / "agypool" / "data" / "aistudio_keys.json")))
DEFAULT_OUT = Path(__file__).resolve().parent.parent / ".secrets" / "AISTUDIO_KEYS_JSON.txt"


def export_keys_bundle(vault_path: Path = DEFAULT_VAULT, out_path: Path = DEFAULT_OUT, copy_clipboard: bool = False) -> dict[str, int | str | bool]:
    """Extract only enabled, valid apiKey strings cleanly into minimal JSON array."""
    raw = json.loads(vault_path.read_text(encoding="utf-8"))
    keys = [
        str(k["apiKey"]).strip()
        for k in raw
        if k.get("apiKey") and k.get("enabled", True) and k.get("status") != "invalid"
    ]
    compact = json.dumps(keys, separators=(",", ":"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(compact, encoding="utf-8")

    copied = False
    if copy_clipboard:
        try:
            subprocess.run(["clip.exe"], input=compact.encode("utf-8"), check=True)
            copied = True
        except Exception:
            copied = False

    return {
        "exported_count": len(keys),
        "bundle_file": str(out_path),
        "copied_to_clipboard": copied,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely package AI Studio keys for Kaggle/GitHub Secrets")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--clip", action="store_true", help="Copy minified JSON to Windows clipboard without printing secrets")
    args = parser.parse_args()

    info = export_keys_bundle(args.vault, args.out, copy_clipboard=args.clip)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
