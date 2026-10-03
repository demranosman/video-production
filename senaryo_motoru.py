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


# --- LLM: görsel üretim prompt paketi ---
def _gorsel_prompt_sistem(
    seri: modeller.Seri,
    karakterler: list[modeller.Karakter],
    mekanlar: list[modeller.Mekan],
    intro: modeller.Intro | None,
    outro: modeller.Outro | None,
    senaryolar: list[modeller.Senaryo],
    dil: str,
    hedef: str,
) -> str:
    """Serinin tüm görsel varlıklarını tek üretim brief'inde toplar."""
    veri = {
        "series": seri.model_dump(),
        "characters": [karakter.model_dump() for karakter in karakterler],
        "locations": [mekan.model_dump() for mekan in mekanlar],
        "intro": intro.model_dump() if intro else None,
        "outro": outro.model_dump() if outro else None,
        "episodes": [senaryo.model_dump() for senaryo in senaryolar],
    }
    dil_adi = {"tr": "Türkçe", "en": "English"}.get(dil)
    if not dil_adi:
        raise ValueError("Çıktı dili yalnızca 'tr' veya 'en' olabilir.")

    return f"""
Sen deneyimli bir yapay zekâ görsel üretim prompt tasarımcısısın. Aşağıdaki seri
verisinden {hedef} için doğrudan kullanılabilir, tutarlı bir görsel üretim prompt
paketi yaz.

ÇIKTI DİLİ: {dil_adi}. Kaynak veride başka bir dil kullanılsa bile başlıklar,
açıklamalar, pozitif promptlar ve negatif promptlar tamamen {dil_adi} olmalı.

ZORUNLU ÇIKTI SIRASI:
1. `GLOBAL STYLE BIBLE`: seri tarzı, hedef kitle, en-boy oranı, renk/ışık,
   görsel devamlılık ve tüm karelerde korunacak kurallar.
2. Her karakter için `CHARACTER REFERENCE — <ad>`: önce nötr tam-boy karakter
   referansı için tek güçlü pozitif prompt, ardından `Negative prompt:` satırı.
   Kalıcı fiziksel kimlik, kıyafet ve consistency_rules dışına çıkma.
3. Her mekân için `LOCATION REFERENCE — <ad>`: karakter olmadan mekân
   establishing-shot promptu ve negatif promptu.
4. Intro varsa `INTRO — <seri adı>`; outro varsa `OUTRO — <seri adı>`:
   süre, seçili karakter/mekân, görsel-hareket-ses tanımları ve sabit metinleri
   temel alan birer görsel/video ana kare promptu ile negatif promptu.
5. Her kayıtlı bölümün her sahnesi için `EPISODE <no> / SCENE <no> — <başlık>`:
   tek karede ana olayı anlatan ayrıntılı pozitif prompt ve `Negative prompt:`.
   Sahnedeki yalnızca tanımlı karakterleri/mekânı kullan; geçici duygu, eylem,
   zaman ve hava bilgisini ekle. Anlatı/diyalog metnini ekrana yazı olarak
   üretme; yalnızca fixed_text veya call_to_action açıkça varsa ekranda okunur
   metin olmasına izin ver.

KURALLAR:
- Promptlar yapıştırılabilir düz metin olsun; açıklama, gerekçe, kamera ayarı
  öğreticisi veya JSON yazma.
- Her pozitif prompt; konu, kalıcı görünüm, eylem, çevre, kompozisyon, kadraj,
  ışık, atmosfer, seri görsel tarzı ve en-boy oranını somut biçimde içersin.
- Aynı karakterin fiziksel özelliğini/kıyafetini her promptta aynen koru;
  kaynakta olmayan karakter, aksesuar, olay, yazı veya marka uydurma.
- Negatif promptlarda en az: karakter tasarımının değişmesi, ekstra uzuv/parmak,
  deforme anatomi, bulanıklık, düşük çözünürlük, filigran, logo, istenmeyen
  metin/altyazı ve kaynakla çelişen kıyafet/renk yer alsın.
- Eksik intro/outro veya hiç kayıtlı bölüm yoksa bunu bir satırla belirt; veri
  uydurma.

SERİ VERİSİ:
{json.dumps(veri, ensure_ascii=False, indent=2)}
"""


def _prompt_metni(deger: object) -> str:
    """İç içe katalog verisini promptta okunabilir, kayıpsız metne çevirir."""
    if isinstance(deger, dict):
        return ", ".join(f"{anahtar}: {_prompt_metni(deger)}" for anahtar, deger in deger.items())
    if isinstance(deger, list):
        return ", ".join(_prompt_metni(oge) for oge in deger)
    return str(deger).strip()


def _deger_metni(deger: object) -> str:
    """Liste ise virgülle birleştirir, aksi halde düz metin döner."""
    if isinstance(deger, list):
        return ", ".join(str(x) for x in deger)
    return str(deger).strip()


def _karakter_gorunum_duzyazi(vid: dict) -> str:
    """Karakter görünümünü etiketsiz düz yazıya çevirir."""
    return "; ".join(
        _deger_metni(vid[anahtar])
        for anahtar in ("fur_or_skin", "body", "face", "eyes", "distinctive_features")
        if vid.get(anahtar)
    )


def _mekan_gorunum_duzyazi(vid: dict) -> str:
    """Mekân görünümünü etiketsiz düz yazıya çevirir."""
    return "; ".join(
        _deger_metni(vid[anahtar])
        for anahtar in ("environment", "ground", "landmarks", "color_palette", "default_lighting", "atmosphere")
        if vid.get(anahtar)
    )


def _karakter_durum_duzyazi(states: dict, karakter_adlari: dict) -> str:
    """Karakter durumlarını 'Ad duygu ve eylem' biçiminde düz yazıya çevirir."""
    parcalar = []
    for kimlik, durum in states.items():
        ad = karakter_adlari.get(kimlik, kimlik)
        emotion = str(durum.get("emotion") or "").strip()
        action = str(durum.get("action") or "").strip()
        birlesik = " ve ".join(b for b in (emotion, action) if b)
        if birlesik:
            parcalar.append(f"{ad} {birlesik}")
    return "; ".join(parcalar)


def _mekan_durum_duzyazi(state: dict) -> str:
    """Mekân durumunu düz yazıya çevirir."""
    parcalar = []
    tod = str(state.get("time_of_day") or "").strip()
    weather = str(state.get("weather") or "").strip()
    if tod:
        parcalar.append(tod)
    if weather:
        parcalar.append(weather)
    details = state.get("temporary_details") or []
    if details:
        parcalar.append(_deger_metni(details))
    return "; ".join(parcalar)


def _sahne_karakter_metni(kimlik: str, karakter_sozluk: dict, en: bool) -> str:
    """Sahne promptuna karakterin TAM tanımını (tür, görünüm, kıyafet) ekler."""
    k = karakter_sozluk.get(kimlik)
    if not k:
        return kimlik
    gorunum = _karakter_gorunum_duzyazi(k.visual_identity)
    if en:
        return f"{k.name} ({k.type}): {gorunum}; clothing: {k.default_clothing}"
    return f"{k.name} ({k.type}): {gorunum}; kıyafet: {k.default_clothing}"


def _sahne_mekan_metni(location_id: str, mekan_sozluk: dict, en: bool) -> str:
    """Sahne promptuna mekânın TAM tanımını ekler."""
    m = mekan_sozluk.get(location_id)
    if not m:
        return location_id
    return f"{m.name}: {_mekan_gorunum_duzyazi(m.visual_identity)}"


def gorsel_prompt_paketi_sablon(
    seri: modeller.Seri,
    karakterler: list[modeller.Karakter],
    mekanlar: list[modeller.Mekan],
    intro: modeller.Intro | None,
    outro: modeller.Outro | None,
    senaryolar: list[modeller.Senaryo],
    dil: str,
    hedef: str = "Nano Banana Pro",
) -> str:
    """API olmadan katalog verisinden üretim aracına yapıştırılabilir paket üretir."""
    if dil not in {"tr", "en"}:
        raise ValueError("Çıktı dili yalnızca 'tr' veya 'en' olabilir.")
    en = dil == "en"
    baslik = "VISUAL PROMPT PACK" if en else "GÖRSEL PROMPT PAKETİ"
    global_baslik = "GLOBAL STYLE BIBLE" if en else "GENEL GÖRSEL REHBER"
    karakter_baslik = "CHARACTER REFERENCE" if en else "KARAKTER REFERANSI"
    mekan_baslik = "LOCATION REFERENCE" if en else "MEKÂN REFERANSI"
    sahne_baslik = "SCENE" if en else "SAHNE"
    negatif = (
        "Negative prompt: inconsistent character design, changed clothing or colors, extra characters, extra limbs or fingers, deformed anatomy, blurry, low resolution, watermark, logo, unwanted text, subtitles"
        if en else
        "Negatif prompt: tutarsız karakter tasarımı, değişmiş kıyafet veya renkler, fazladan karakter, ekstra uzuv veya parmak, deforme anatomi, bulanıklık, düşük çözünürlük, filigran, logo, istenmeyen metin, altyazı"
    )
    stil = seri.visual_style or ("cinematic visual style" if en else "sinematik görsel tarz")
    oran = seri.default_aspect_ratio
    satirlar = [
        f"# {baslik} — {seri.name}",
        f"## {global_baslik}",
        (
            f"{hedef}; style: {stil}; target audience: {seri.target_audience}; aspect ratio: {oran}. "
            "Keep every character's physical identity, clothing and consistency rules identical in all images."
            if en else
            f"{hedef}; tarz: {stil}; hedef kitle: {seri.target_audience}; en-boy oranı: {oran}. "
            "Her görselde karakterlerin fiziksel kimliğini, kıyafetini ve tutarlılık kurallarını aynen koru."
        ),
    ]
    for karakter in karakterler:
        satirlar.extend([
            f"\n## {karakter_baslik} — {karakter.name}",
            (
                f"Full-body neutral character reference of {karakter.name}, {karakter.type}; permanent appearance: {_karakter_gorunum_duzyazi(karakter.visual_identity)}; clothing: {karakter.default_clothing}; personality: {_prompt_metni(karakter.personality)}; rules: {_prompt_metni(karakter.consistency_rules)}; {stil}; clean character sheet composition, consistent proportions, detailed lighting, {oran}."
                if en else
                f"{karakter.name} için tam boy nötr karakter referansı; tür: {karakter.type}; kalıcı görünüm: {_karakter_gorunum_duzyazi(karakter.visual_identity)}; kıyafet: {karakter.default_clothing}; kişilik: {_prompt_metni(karakter.personality)}; kurallar: {_prompt_metni(karakter.consistency_rules)}; {stil}; temiz karakter sayfası kompozisyonu, tutarlı oranlar, ayrıntılı ışık, {oran}."
            ), negatif,
        ])
    for mekan in mekanlar:
        satirlar.extend([
            f"\n## {mekan_baslik} — {mekan.name}",
            (
                f"Empty establishing shot of {mekan.name}; permanent environment: {_mekan_gorunum_duzyazi(mekan.visual_identity)}; rules: {_prompt_metni(mekan.consistency_rules)}; {stil}; cinematic composition, detailed environment, atmospheric lighting, {oran}."
                if en else
                f"{mekan.name} için karaktersiz establishing shot; kalıcı çevre: {_mekan_gorunum_duzyazi(mekan.visual_identity)}; kurallar: {_prompt_metni(mekan.consistency_rules)}; {stil}; sinematik kompozisyon, ayrıntılı çevre, atmosferik ışık, {oran}."
            ), negatif,
        ])

    karakter_adlari = {karakter.character_id: karakter.name for karakter in karakterler}
    mekan_adlari = {mekan.location_id: mekan.name for mekan in mekanlar}
    karakter_sozluk = {karakter.character_id: karakter for karakter in karakterler}
    mekan_sozluk = {mekan.location_id: mekan for mekan in mekanlar}
    for etiket, parca in (("INTRO", intro), ("OUTRO", outro)):
        if parca:
            kadro = ", ".join(karakter_adlari.get(kimlik, kimlik) for kimlik in parca.character_ids)
            mekan = mekan_adlari.get(parca.location_id, parca.location_id)
            satirlar.extend([
                f"\n## {etiket} — {seri.name}",
                (
                    f"{etiket.title()} keyframe, duration {parca.duration_sec} seconds; characters: {kadro}; location: {mekan}; visual: {parca.visual_description}; action: {parca.action_description}; audio mood: {parca.audio_description}; on-screen text only if specified: {parca.fixed_text}; {stil}; cinematic framing, {oran}."
                    if en else
                    f"{etiket.title()} ana karesi, süre: {parca.duration_sec} saniye; karakterler: {kadro}; mekân: {mekan}; görsel: {parca.visual_description}; hareket: {parca.action_description}; ses atmosferi: {parca.audio_description}; yalnızca belirtilmişse ekranda metin: {parca.fixed_text}; {stil}; sinematik kadraj, {oran}."
                ), negatif,
            ])
    for senaryo in senaryolar:
        for sahne in senaryo.scenes:
            kadro_tanim = "; ".join(_sahne_karakter_metni(kimlik, karakter_sozluk, en) for kimlik in sahne.character_ids)
            mekan_tanim = _sahne_mekan_metni(sahne.location_id, mekan_sozluk, en)
            satirlar.extend([
                f"\n## EPISODE {senaryo.episode.episode_no} / {sahne_baslik} {sahne.order} — {sahne.title}",
                (
                    f"Main story frame: {sahne.story_event}; characters: {kadro_tanim}; location: {mekan_tanim}; character states: {_karakter_durum_duzyazi(sahne.character_states, karakter_adlari)}; location state: {_mekan_durum_duzyazi(sahne.location_state)}; visual direction: {sahne.visual_description}; {stil}; cinematic composition, expressive action, detailed lighting, {oran}. Do not render narration or dialogue as on-screen text."
                    if en else
                    f"Ana hikâye karesi: {sahne.story_event}; karakterler: {kadro_tanim}; mekân: {mekan_tanim}; karakter durumları: {_karakter_durum_duzyazi(sahne.character_states, karakter_adlari)}; mekân durumu: {_mekan_durum_duzyazi(sahne.location_state)}; görsel yönlendirme: {sahne.visual_description}; {stil}; sinematik kompozisyon, ifadeli eylem, ayrıntılı ışık, {oran}. Anlatı veya diyaloğu ekranda metin olarak üretme."
                ), negatif,
            ])
    return "\n".join(satirlar)
