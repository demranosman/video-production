"""Seri/bölüm/katalog dosyaları için tek doğruluk kaynağı.

Veriler bu modülün bulunduğu dizinin altındaki `seriler/` klasöründe saklanır.
Yollar CWD'den bağımsızdır; her zaman modülün gerçek konumuna göre üretilir.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from senaryo_modelleri import (
    Intro,
    KarakterKatalogu,
    Mekan,
    MekanKatalogu,
    Outro,
    Senaryo,
    Seri,
)

KOK = Path(__file__).resolve().parent / "seriler"

_TURKCE = str.maketrans({
    "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
    "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
})


def slugify(name: str) -> str:
    """Türkçe karakterleri güvenli ASCII kimliğe çevirir."""
    s = name.translate(_TURKCE).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "seri"


def seri_kok(series_id: str) -> Path:
    return KOK / series_id


def _yol(series_id: str, *parcalar: str) -> Path:
    return seri_kok(series_id).joinpath(*parcalar)


def seri_yolu(series_id: str) -> Path:
    return _yol(series_id, "seri.json")


def karakterler_yolu(series_id: str) -> Path:
    return _yol(series_id, "karakterler.json")


def mekanlar_yolu(series_id: str) -> Path:
    return _yol(series_id, "mekanlar.json")


def intro_dizini(series_id: str) -> Path:
    return _yol(series_id, "intro")


def outro_dizini(series_id: str) -> Path:
    return _yol(series_id, "outro")


def bolum_dizini(series_id: str, episode_no: int, bolum_slug: str) -> Path:
    return _yol(series_id, "bolumler", f"{episode_no:03d}_{bolum_slug}")


def senaryo_yolu(series_id: str, episode_no: int, bolum_slug: str) -> Path:
    return bolum_dizini(series_id, episode_no, bolum_slug) / "senaryo.json"


def hikaye_yolu(series_id: str, episode_no: int, bolum_slug: str) -> Path:
    return bolum_dizini(series_id, episode_no, bolum_slug) / "hikaye.txt"


def gorsel_prompt_yolu(series_id: str, dil: str) -> Path:
    if dil not in {"tr", "en"}:
        raise ValueError("Prompt dili yalnızca 'tr' veya 'en' olabilir.")
    return _yol(series_id, "gorsel_promptlar", f"prompt_{dil}.txt")


# --- Medya hedef yolları (bu aşamada yalnızca sonraki üretim için) ---
def intro_medya_yolu(series_id: str, tur: str) -> Path:
    return intro_dizini(series_id) / tur  # tur: "reference.png" | "intro.mp4" | "audio.wav"


def outro_medya_yolu(series_id: str, tur: str) -> Path:
    return outro_dizini(series_id) / tur  # tur: "reference.png" | "outro.mp4" | "audio.wav"


# --- Düşük seviye JSON işlemleri ---
def _atomik_json_yaz(path: Path, data) -> None:
    """Yarım yazma bırakmamak için geçici dosya + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def _json_oku(path: Path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


# --- Seri ---
def serileri_listele() -> list[str]:
    if not KOK.is_dir():
        return []
    return sorted(
        p.name for p in KOK.iterdir()
        if p.is_dir() and (p / "seri.json").is_file()
    )


def seri_olustur(
    name: str,
    description: str = "",
    target_audience: str = "",
    language: str = "tr",
    visual_style: str = "",
    default_aspect_ratio: str = "16:9",
    created_at: str = "",
) -> Seri:
    if not name.strip():
        raise ValueError("Seri adı boş olamaz.")
    series_id = slugify(name)
    if seri_yolu(series_id).exists():
        raise ValueError(f"'{series_id}' kimlikli seri zaten mevcut.")
    seri = Seri(
        series_id=series_id,
        name=name.strip(),
        description=description.strip(),
        target_audience=target_audience.strip(),
        language=language.strip() or "tr",
        visual_style=visual_style.strip(),
        default_aspect_ratio=default_aspect_ratio.strip() or "16:9",
        created_at=created_at,
    )
    seri_kaydet(seri)
    return seri


def seri_yukle(series_id: str) -> Seri:
    return Seri.model_validate(_json_oku(seri_yolu(series_id)))


def seri_kaydet(seri: Seri) -> None:
    _atomik_json_yaz(seri_yolu(seri.series_id), seri.model_dump())


# --- Karakterler ---
def karakterleri_yukle(series_id: str) -> KarakterKatalogu:
    path = karakterler_yolu(series_id)
    if not path.exists():
        return KarakterKatalogu(series_id=series_id)
    return KarakterKatalogu.model_validate(_json_oku(path))


def karakterleri_kaydet(katalog: KarakterKatalogu) -> None:
    _atomik_json_yaz(karakterler_yolu(katalog.series_id), katalog.model_dump())


# --- Mekânlar ---
def mekanlari_yukle(series_id: str) -> MekanKatalogu:
    path = mekanlar_yolu(series_id)
    if not path.exists():
        return MekanKatalogu(series_id=series_id)
    return MekanKatalogu.model_validate(_json_oku(path))


def mekanlari_kaydet(katalog: MekanKatalogu) -> None:
    _atomik_json_yaz(mekanlar_yolu(katalog.series_id), katalog.model_dump())


# --- Referans doğrulama ---
def senaryo_referanslarini_dogrula(
    senaryo: Senaryo,
    karakterler: KarakterKatalogu,
    mekanlar: MekanKatalogu,
) -> None:
    """Senaryodaki her karakter/mekân kimliği katalogda bulunmalı."""
    karakter_ids = {k.character_id for k in karakterler.characters}
    mekan_ids = {m.location_id for m in mekanlar.locations}
    for sahne in senaryo.scenes:
        eksik_karakter = [c for c in sahne.character_ids if c not in karakter_ids]
        if eksik_karakter:
            raise ValueError(
                f"{sahne.scene_id}: katalogda bulunmayan karakter: {', '.join(eksik_karakter)}"
            )
        if sahne.location_id not in mekan_ids:
            raise ValueError(
                f"{sahne.scene_id}: katalogda bulunmayan mekân: {sahne.location_id}"
            )


def _intro_outro_referanslarini_dogrula(
    karakterler: KarakterKatalogu,
    mekanlar: MekanKatalogu,
    *,
    karakter_ids: list[str],
    location_id: str,
    etiket: str,
) -> None:
    katalog_ids = {k.character_id for k in karakterler.characters}
    mekan_ids = {m.location_id for m in mekanlar.locations}
    eksik = [c for c in karakter_ids if c not in katalog_ids]
    if eksik:
        raise ValueError(f"{etiket}: katalogda bulunmayan karakter: {', '.join(eksik)}")
    if location_id and location_id not in mekan_ids:
        raise ValueError(f"{etiket}: katalogda bulunmayan mekân: {location_id}")


# --- Senaryo ---
def senaryo_kaydet(
    senaryo: Senaryo,
    karakterler: KarakterKatalogu,
    mekanlar: MekanKatalogu,
    bolum_slug: str,
) -> Path:
    senaryo_referanslarini_dogrula(senaryo, karakterler, mekanlar)
    if senaryo.series_id != karakterler.series_id or senaryo.series_id != mekanlar.series_id:
        raise ValueError("Senaryo, karakter ve mekân katalogları aynı seriye ait olmalı.")
    path = senaryo_yolu(senaryo.series_id, senaryo.episode.episode_no, bolum_slug)
    _atomik_json_yaz(path, senaryo.model_dump())
    return path


def hikaye_kaydet(series_id: str, episode_no: int, bolum_slug: str, metin: str) -> Path:
    path = hikaye_yolu(series_id, episode_no, bolum_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as file:
        file.write(metin)
    os.replace(temp, path)
    return path


def gorsel_prompt_kaydet(series_id: str, dil: str, metin: str) -> Path:
    path = gorsel_prompt_yolu(series_id, dil)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as file:
        file.write(metin)
    os.replace(temp, path)
    return path


def gorsel_prompt_yukle(series_id: str, dil: str) -> str | None:
    path = gorsel_prompt_yolu(series_id, dil)
    return path.read_text(encoding="utf-8") if path.exists() else None


def senaryo_yukle(series_id: str, episode_no: int, bolum_slug: str) -> Senaryo:
    return Senaryo.model_validate(_json_oku(senaryo_yolu(series_id, episode_no, bolum_slug)))


def bolumler(series_id: str) -> list[dict]:
    """Serinin kayıtlı bölümlerini (episode_no, slug, senaryo var mı) döner."""
    bolum_kok = _yol(series_id, "bolumler")
    if not bolum_kok.is_dir():
        return []
    sonuc = []
    for dir_path in sorted(bolum_kok.iterdir()):
        if not dir_path.is_dir():
            continue
        eslesme = re.match(r"^(\d{3})_(.+)$", dir_path.name)
        if not eslesme:
            continue
        episode_no = int(eslesme.group(1))
        slug = eslesme.group(2)
        sonuc.append({
            "episode_no": episode_no,
            "slug": slug,
            "senaryo_var": (dir_path / "senaryo.json").is_file(),
            "hikaye_var": (dir_path / "hikaye.txt").is_file(),
        })
    return sonuc


# --- Intro/outro ---
def intro_yukle(series_id: str) -> Intro | None:
    path = intro_dizini(series_id) / "intro.json"
    if not path.exists():
        return None
    return Intro.model_validate(_json_oku(path))


def intro_kaydet(intro: Intro, karakterler: KarakterKatalogu, mekanlar: MekanKatalogu) -> Path:
    _intro_outro_referanslarini_dogrula(
        karakterler, mekanlar,
        karakter_ids=intro.character_ids, location_id=intro.location_id, etiket="intro",
    )
    path = intro_dizini(intro.series_id) / "intro.json"
    _atomik_json_yaz(path, intro.model_dump())
    return path


def outro_yukle(series_id: str) -> Outro | None:
    path = outro_dizini(series_id) / "outro.json"
    if not path.exists():
        return None
    return Outro.model_validate(_json_oku(path))


def outro_kaydet(outro: Outro, karakterler: KarakterKatalogu, mekanlar: MekanKatalogu) -> Path:
    _intro_outro_referanslarini_dogrula(
        karakterler, mekanlar,
        karakter_ids=outro.character_ids, location_id=outro.location_id, etiket="outro",
    )
    path = outro_dizini(outro.series_id) / "outro.json"
    _atomik_json_yaz(path, outro.model_dump())
    return path
