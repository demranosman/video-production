import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from video_provider_router import _load_policy, _openmontage_selector


def main():
    policy = _load_policy()
    om = Path(os.environ.get("OPENMONTAGE_PATH", r"C:\Users\fikret\Desktop\OpenMontage"))
    print(f"[CHECK] OpenMontage: {om}")
    if not om.is_dir():
        print("[FAIL] OPENMONTAGE_PATH bulunamadı.")
        return 2

    selector = _openmontage_selector()
    providers = selector._providers()
    available = [p.provider for p in providers if str(p.get_status()).lower().endswith("available")]
    print(f"[CHECK] Registry video provider sayısı: {len(providers)}")
    print(f"[CHECK] Kullanılabilir providerlar: {sorted(set(available))}")

    configured = policy.get("preferred_order", [])
    print(f"[CHECK] Policy sırası: {' -> '.join(configured)}")
    missing = [p for p in configured if p not in available]
    if missing:
        print(f"[WARN] Şu providerlar şu anda kullanılabilir değil: {', '.join(missing)}")
    else:
        print("[PASS] Policy'deki tüm providerlar kullanılabilir.")

    print("[PASS] Router import + OpenMontage registry kontrolü tamamlandı.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
