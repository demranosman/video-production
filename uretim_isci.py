"""Arka plan video üretim işçisi.

Streamlit oturumunu bloklamamak için `app.py` bu betiği ayrı süreç olarak
başlatır. İlerleme `seriler/<series_id>/uretim_durum.json` dosyasına yazılır.

Kullanım:
    python uretim_isci.py --series-id <id> --video-modu openmontage
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

import medya_motoru
import senaryo_modelleri as modeller
import seri_deposu as depo

BOLUM_NO = 1
BOLUM_SLUG = "video"


def _zaman() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def durum_yaz(proje_dizini: str, **alanlar) -> None:
    os.makedirs(proje_dizini, exist_ok=True)
    yol = os.path.join(proje_dizini, "uretim_durum.json")
    gecici = yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as file:
        json.dump({"guncellendi": _zaman(), **alanlar}, file, ensure_ascii=False, indent=2)
    os.replace(gecici, yol)


def durum_oku(proje_dizini: str) -> dict:
    yol = os.path.join(proje_dizini, "uretim_durum.json")
    if not os.path.exists(yol):
        return {}
    try:
        with open(yol, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


def _argumanlar() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Video üretim işçisi")
    parser.add_argument("--series-id", required=True)
    parser.add_argument("--video-modu", default="openmontage", choices=list(medya_motoru.VIDEO_MODLARI))
    parser.add_argument("--seslendirme", default="auto", choices=["auto", "1", "0"])
    parser.add_argument("--dil", default="tr", choices=["tr", "en"])
    parser.add_argument("--cinsiyet", default="kadin", choices=["kadin", "erkek"])
    parser.add_argument("--intro-outro", default="1", choices=["1", "0"])
    parser.add_argument("--altyazi", default="1", choices=["1", "0"])
    return parser.parse_args()


def main() -> int:
    args = _argumanlar()
    sure_bas = time.time()
    basladi = _zaman()
    proje_dizini = str(depo.seri_kok(args.series_id))
    try:
        seri = depo.seri_yukle(args.series_id)
        karakterler = depo.karakterleri_yukle(args.series_id).characters
        mekanlar = depo.mekanlari_yukle(args.series_id).locations
        senaryo_yolu = depo.senaryo_yolu(args.series_id, BOLUM_NO, BOLUM_SLUG)
        if not senaryo_yolu.exists():
            raise ValueError("Senaryo bulunamadı. Önce 1. sekmede senaryoyu oluşturun.")
        senaryo = modeller.Senaryo.model_validate(
            json.loads(senaryo_yolu.read_text(encoding="utf-8"))
        )
        if args.seslendirme == "auto":
            seslendirme = args.video_modu != "openmontage"
        else:
            seslendirme = args.seslendirme == "1"

        durum_yaz(
            proje_dizini,
            durum="calisiyor",
            oran=0.0,
            mesaj="Başlatılıyor...",
            pid=os.getpid(),
            video_modu=args.video_modu,
            basladi=basladi,
        )

        def ilerleme(mesaj: str, oran: float) -> None:
            durum_yaz(
                proje_dizini,
                durum="calisiyor",
                oran=round(float(oran), 4),
                mesaj=mesaj,
                pid=os.getpid(),
                video_modu=args.video_modu,
                basladi=basladi,
            )

        sonuc = medya_motoru.uret(
            senaryo,
            seri,
            karakterler,
            mekanlar,
            proje_dizini,
            video_modu=args.video_modu,
            seslendirme=seslendirme,
            tts_dili=args.dil,
            tts_cinsiyeti=args.cinsiyet,
            intro_outro=args.intro_outro == "1",
            altyazi=args.altyazi == "1",
            ilerleme=ilerleme,
        )
        durum_yaz(
            proje_dizini,
            durum="bitti",
            oran=1.0,
            mesaj="Video hazır.",
            final=sonuc["final"],
            altyazi=sonuc.get("altyazi", False),
            video_modu=args.video_modu,
            sure_sn=round(time.time() - sure_bas, 1),
            pid=os.getpid(),
        )
        return 0
    except Exception as hata:  # noqa: BLE001 - işçi hatayı durum dosyasına yazar
        durum_yaz(
            proje_dizini,
            durum="hata",
            oran=0.0,
            mesaj="Üretim başarısız.",
            hata=str(hata),
            pid=os.getpid(),
            video_modu=args.video_modu,
            sure_sn=round(time.time() - sure_bas, 1),
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
