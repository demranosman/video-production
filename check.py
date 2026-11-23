"""Tek komutla kalite kapısı: ruff + mypy + unittest.

Kullanım: venv\\Scripts\\python.exe check.py  (Windows)  /  python check.py
Bağımlılıklar: pip install -r requirements-dev.txt
"""

from __future__ import annotations

import subprocess
import sys

KOMUTLAR = [
    ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
    ("mypy", [sys.executable, "-m", "mypy"]),  # dosya listesi pyproject.toml'da
    ("unittest", [sys.executable, "-m", "unittest", "discover", "-q"]),
]


def main() -> int:
    for ad, komut in KOMUTLAR:
        print(f"\n=== {ad} ===", flush=True)
        sonuc = subprocess.run(komut)
        if sonuc.returncode != 0:
            print(f"\nFAIL: {ad} (çıkış kodu {sonuc.returncode})")
            return sonuc.returncode
    print("\nOK: ruff + mypy + unittest geçti.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
