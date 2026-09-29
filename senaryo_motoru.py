"""Claude ile karakter/mekân çıkarımı ve sahne üretimi.

LLM yalnızca ham JSON üretir; katalogla eşleştirme ve doğrulama saf Python
fonksiyonlarında yapılır, böylece bu kısımlar API olmadan test edilebilir.
"""
from __future__ import annotations

import json
import os
import re

import anthropic
from dotenv import load_dotenv

import senaryo_modelleri as modeller
from seri_deposu import slugify

load_dotenv()

LLM_MODEL = "claude-sonnet-5"

_TURKCE_NORM = str.maketrans({
    "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
    "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
})


def _norm(metin: str) -> str:
    return metin.translate(_TURKCE_NORM).lower().strip()


def _temiz_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY ortam değişkeni ayarlanmalı.")
    return anthropic.Anthropic(api_key=api_key)


_JSON_UYARISI = (
    "\n\nÖNEMLİ: Önceki yanıtın geçerli JSON değildi. Yanıtın YALNIZCA geçerli JSON olsun; "
    "açıklama, markdown veya ``` bloğu ekleme."
)


def _llm_metin(system: str, user: str) -> str:
    client = _client()
    with client.messages.stream(
        model=LLM_MODEL,
        max_tokens=30000,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        return stream.get_final_text() or ""


def _llm_json(system: str, user: str, deneme: int = 2) -> dict:
    """JSON ayrıştırılamazsa modeli sıkı bir uyarıyla yeniden dener."""
    son_hata: Exception | None = None
    for _ in range(deneme):
        text = _llm_metin(system, user)
        if not text:
            son_hata = ValueError("Claude yanıtında JSON bulunamadı.")
        else:
            try:
                return _temiz_json(text)
            except json.JSONDecodeError as hata:
                son_hata = hata
        user = user + _JSON_UYARISI
    raise ValueError(f"Claude geçerli JSON döndürmedi: {son_hata}")


# --- Saf eşleştirme (API'siz test edilebilir) ---
def karakter_esle(ad: str, karakterler: list[modeller.Karakter]) -> str | None:
    """Adı mevcut karakter adı, takma adı veya kimliğiyle eşleştirir."""
    norm = _norm(ad)
    for k in karakterler:
        adaylar = {_norm(k.name), _norm(k.character_id), k.character_id.lower()}
        adaylar.update(_norm(a) for a in k.aliases)
        if norm in adaylar:
            return k.character_id
    return None


def mekan_esle(ad: str, mekanlar: list[modeller.Mekan]) -> str | None:
    """Adı mevcut mekân adı, takma adı veya kimliğiyle eşleştirir."""
    norm = _norm(ad)
    for m in mekanlar:
        adaylar = {_norm(m.name), _norm(m.location_id), m.location_id.lower()}
        adaylar.update(_norm(a) for a in m.aliases)
        if norm in adaylar:
            return m.location_id
    return None


# --- LLM: karakter ve mekân çıkarımı ---
_VARLIK_CKARIM_SISTEM = """
Sen bir çocuk masalı editörüsün. Kaynak hikâyedeki karakterleri ve mekânları çıkar.

YALNIZCA geçerli JSON döndür (açıklama ekleme). Şema:
{
  "characters": [
    {
      "name": "Karakterin hikâyedeki adı",
      "type": "Tavşan/Papağan/İnsan vb.",
      "role": "main|recurring|supporting|guest",
      "aliases": [],
      "visual_identity": {"body":"","fur_or_skin":"","face":"","eyes":"","distinctive_features":""},
      "default_clothing": "",
      "personality": [],
      "speech_style": "",
      "voice_description": "",
      "consistency_rules": []
    }
  ],
  "locations": [
    {
      "name": "Mekânın adı",
      "aliases": [],
      "visual_identity": {"environment":"","ground":"","landmarks":[],"color_palette":[],"default_lighting":"","atmosphere":""},
      "consistency_rules": []
    }
  ]
}

KURALLAR:
- name alanına YALNIZCA düz karakter/mekân adını yaz (sıfat/açıklama ekleme).
- Anlatıcıyı (narrator) karakter olarak EKLEME; yalnızca hikâyede fiilen
  görünen/sahne alan varlıkları listele.
- Kaynakta olmayan karakter veya mekân uydurma.
- Görsel kimlik sabit ve çekime bağlı olmayan özellikleri tarif etsin
  (renk, boyut, kalıcı fiziksel özellikler); geçici durumları yazma.
- Masal kahramanı bir HAYVAN ise (tavşan, tilki, papağan, kedi, ejderha vb.) ona
  sevimli İNSANSİ KIYAFETLER giydir: yelek, elbise, tulum, şapka, atkı, ceket vb.
  Bu kıyafeti default_clothing alanına yaz. Hayvan karakterleri çıplak/doğal tüy
  halinde bırakma. Tür+renk kimliği visual_identity'de, kıyafet default_clothing'de
  AYRI tutulur; ikisi de kalıcıdır.
- Yanıt sadece bu JSON olsun.
"""


def varlik_cikar(kaynak_metin: str) -> dict:
    if not kaynak_metin.strip():
        raise ValueError("Hikâye metni boş olamaz.")
    return _llm_json(_VARLIK_CKARIM_SISTEM, kaynak_metin)


def cikarilanlari_esle(
    cikarilan: dict,
    karakterler: list[modeller.Karakter],
    mekanlar: list[modeller.Mekan],
) -> dict:
    """Çıkarılan varlıkları mevcut katalogla eşleştirir; yeni adayları ayırır."""
    karakter_sonuc = []
    for ham in cikarilan.get("characters", []):
        ad = str(ham.get("name", "")).strip()
        if not ad:
            continue
        eslesen = karakter_esle(ad, karakterler)
        karakter_sonuc.append({
            "name": ad,
            "matched_character_id": eslesen,
            "candidate": None if eslesen else ham,
        })

    mekan_sonuc = []
    for ham in cikarilan.get("locations", []):
        ad = str(ham.get("name", "")).strip()
        if not ad:
            continue
        eslesen = mekan_esle(ad, mekanlar)
        mekan_sonuc.append({
            "name": ad,
            "matched_location_id": eslesen,
            "candidate": None if eslesen else ham,
        })

    return {"characters": karakter_sonuc, "locations": mekan_sonuc}


def adaydan_karakter(ham: dict, series_id: str, first_seen_episode: int) -> modeller.Karakter:
    ad = str(ham.get("name", "")).strip()
    if not ad:
        raise ValueError("Aday karakter adı boş olamaz.")
    kimlik = ham.get("visual_identity") or {}
    if not kimlik:
        kimlik = {"description": str(ham.get("type") or ad)}
    return modeller.Karakter(
        character_id=slugify(ad),
        name=ad,
        aliases=[str(a) for a in (ham.get("aliases") or []) if str(a).strip()],
        type=str(ham.get("type") or "").strip(),
        role=(ham.get("role") or "supporting"),
        first_seen_episode=first_seen_episode,
        visual_identity=kimlik,
        default_clothing=str(ham.get("default_clothing") or "").strip(),
        personality=[str(p) for p in (ham.get("personality") or []) if str(p).strip()],
        speech_style=str(ham.get("speech_style") or "").strip(),
        voice_description=str(ham.get("voice_description") or "").strip(),
        consistency_rules=[str(r) for r in (ham.get("consistency_rules") or []) if str(r).strip()],
    )


def adaydan_mekan(ham: dict, series_id: str, first_seen_episode: int) -> modeller.Mekan:
    ad = str(ham.get("name", "")).strip()
    if not ad:
        raise ValueError("Aday mekân adı boş olamaz.")
    kimlik = ham.get("visual_identity") or {}
    if not kimlik:
        kimlik = {"description": ad}
    return modeller.Mekan(
        location_id=slugify(ad),
        name=ad,
        aliases=[str(a) for a in (ham.get("aliases") or []) if str(a).strip()],
        first_seen_episode=first_seen_episode,
        visual_identity=kimlik,
        consistency_rules=[str(r) for r in (ham.get("consistency_rules") or []) if str(r).strip()],
    )


# --- LLM: sahne üretimi ---
def _sahne_uret_sistem(seri: modeller.Seri, karakterler: list[modeller.Karakter], mekanlar: list[modeller.Mekan]) -> str:
    karakter_blok = json.dumps(
        [
            {
                "character_id": k.character_id,
                "name": k.name,
                "type": k.type,
                "visual_identity": k.visual_identity,
                "default_clothing": k.default_clothing,
                "consistency_rules": k.consistency_rules,
            }
            for k in karakterler
        ],
        ensure_ascii=False, indent=2,
    )
    mekan_blok = json.dumps(
        [
            {
                "location_id": m.location_id,
                "name": m.name,
                "visual_identity": m.visual_identity,
                "consistency_rules": m.consistency_rules,
            }
            for m in mekanlar
        ],
        ensure_ascii=False, indent=2,
    )
    return f"""
Sen çocuk masalı senaristsin. Kaynak hikâyeyi sahnelere böl.

Seri: {seri.name}
Görsel tarz: {seri.visual_style or 'Cinematic 3D animasyon'}

KULLANILABİLİR KARAKTERLER (yalnızca bu character_id değerlerini kullan):
{karakter_blok}

KULLANILABİLİR MEKÂNLAR (yalnızca bu location_id değerlerini kullan):
{mekan_blok}

YALNIZCA geçerli JSON döndür. Şema:
{{
  "scenes": [
    {{
      "scene_id": "scene_001",
      "order": 1,
      "title": "Kısa sahne başlığı",
      "source_excerpt": "Bu sahnenin kaynak hikâyedeki karşılığı (olduğu gibi)",
      "location_id": "KATALOGDAKİ location_id",
      "character_ids": ["KATALOGDAKİ character_id'ler"],
      "character_states": {{ "character_id": {{"emotion":"","action":"","temporary_clothing":null}} }},
      "location_state": {{"time_of_day":"","weather":"","temporary_details":[]}},
      "story_event": "Bu sahnede ne olur",
      "narration": "Anlatıcı metni (kaynak akışına sadık)",
      "dialogue": [ {{"character_id":"","line":""}} ],
      "visual_description": "Görsel kompozisyon tarifi",
      "estimated_duration_sec": 10
    }}
  ]
}}

KURALLAR:
- Hikâyedeki olayları SIRASIYLA sahnelere böl; kaynakta olmayan olay/diyalog uydurma.
- narration ve dialogue kaynağı başka cümlelerle özetleyip iyileştirme; olduğu gibi taşı.
- Her sahne tek ana olaya odaklansın; estimated_duration_sec 5-20 arasında olsun.
- character_ids ve location_id YALNIZCA yukarıdaki kataloglardan seçilir.
- character_states ve location_state yalnızca GEÇİCİ durumları taşır (duygu, hareket,
  hava, saat); kalıcı kimlik bilgisini buraya yazma.
- HAYVAN karakterler (type bir hayvan türüyse) sahnelerde mutlaka default_clothing'lerini
  (insansı kıyafet) giymiş olarak görünür. Kıyafetlerini değiştirme ve çıplak/doğal tüy
  halinde çizme; visual_description içinde kıyafeti de tarif et.
- visual_description yazarken karakterin visual_identity ve default_clothing değerlerini
  OLDUĞU GİBİ kullan (renk, tüy/kürk, göz, ayırt edici özellik); kendi başına renk veya
  özellik uydurma. Mekânı tarif ederken de mekânın visual_identity'sine sadık kal.
- Karakterlerin ve mekânların consistency_rules maddelerine HER sahnede uy.
- Yanıt sadece bu JSON olsun.
"""


def sahne_uret(
    kaynak_metin: str,
    seri: modeller.Seri,
    karakterler: list[modeller.Karakter],
    mekanlar: list[modeller.Mekan],
    episode: modeller.Episode,
) -> modeller.Senaryo:
    if not karakterler:
        raise ValueError("Sahne üretimi için en az bir karakter kataloğu gerekli.")
    if not mekanlar:
        raise ValueError("Sahne üretimi için en az bir mekân kataloğu gerekli.")
    sonuc = _llm_json(_sahne_uret_sistem(seri, karakterler, mekanlar), kaynak_metin)
    sahneler = [
        modeller.Sahne.model_validate(s)
        for s in sonuc.get("scenes", [])
    ]
    return modeller.Senaryo(
        series_id=seri.series_id,
        episode=episode,
        scenes=_sirali_sahneler(sahneler),
    )


def _sirali_sahneler(sahnaler: list[modeller.Sahne]) -> list[modeller.Sahne]:
    """LLM `order`/`scene_id` alanlarını atlarsa ikisini de sırayla yeniden üretir.

    `scene_id` ile `order` tutarlı kalsın diye her ikisi de konumdan türetilir;
    hiçbir dış referans `scene_id`'ye bağlı değildir.
    """
    return [
        s.model_copy(update={"order": i, "scene_id": f"scene_{i:03d}"})
        for i, s in enumerate(sahnaler, start=1)
    ]
