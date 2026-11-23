"""Senaryodan video üretir: Gemini görsel + ElevenLabs ses + FFmpeg/fal.ai + birleştirme.

SenaryoAI projesindeki çalışan medya hattının sadeleştirilmiş uyarlamasıdır;
girdi olarak bu projenin Pydantic `Senaryo` modelini kullanır.

Maliyet notu: Görsel (Gemini), ses (ElevenLabs) ve hareket (fal.ai) ücretlidir.
`resim` + `sessiz` modu yalnızca Gemini görseli harcar; test/önizleme için uygundur.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

import requests
from dotenv import load_dotenv
from PIL import Image

import senaryo_modelleri as modeller

load_dotenv()

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
FAL_QUEUE_BASE_URL = "https://queue.fal.run"

# ElevenLabs varsayılan sesleri. Ücretsiz planda "library voice" kısıtı olursa
# .env üzerinden ELEVENLABS_VOICE_<DIL>_<CINSIYET> ile kendi voice_id'nizi verin.
DEFAULT_ELEVENLABS_VOICES = {
    ("tr", "kadin"): {"voice_id": "21m00Tcm4TlvDq8ikWAM", "label": "Rachel (Kadın)"},
    ("tr", "erkek"): {"voice_id": "pNInz6obpgDQGcFmaJgB", "label": "Adam (Erkek)"},
    ("en", "kadin"): {"voice_id": "21m00Tcm4TlvDq8ikWAM", "label": "Rachel (Kadın)"},
    ("en", "erkek"): {"voice_id": "pNInz6obpgDQGcFmaJgB", "label": "Adam (Erkek)"},
}

VIDEO_MODLARI = {
    "resim": "Resim + Ken Burns (ücretsiz FFmpeg)",
    "hareketli": "Hareketli video (fal.ai, ücretli)",
    "openmontage": "OpenMontage (Runway/Veo..., sağlayıcı fallback, ücretli)",
}

_DIMENSIONS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "4:3": (1440, 1080),
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _binary(name: str) -> str:
    bin_dir = _env("FFMPEG_BIN_DIR")
    if bin_dir:
        aday = os.path.join(bin_dir, name + (".exe" if os.name == "nt" else ""))
        if os.path.exists(aday):
            return aday
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} bulunamadı. FFmpeg kurulu ve PATH'te olmalı.")
    return path


def boyutlar(en_boy: str) -> tuple[int, int]:
    return _DIMENSIONS.get((en_boy or "").strip(), (1920, 1080))


def ses_preset(dil: str, cinsiyet: str) -> dict:
    anahtar = (dil.lower(), cinsiyet.lower())
    if anahtar not in DEFAULT_ELEVENLABS_VOICES:
        raise ValueError(f"Geçersiz dil/cinsiyet: {dil}/{cinsiyet}")
    override = _env(f"ELEVENLABS_VOICE_{dil.upper()}_{cinsiyet.upper()}")
    if override:
        return {"voice_id": override, "label": f"Özel ses ({dil.upper()})"}
    return DEFAULT_ELEVENLABS_VOICES[anahtar]


# ---------------------------------------------------------------
# Gemini görsel
# ---------------------------------------------------------------
def _image_b64(path: str) -> str:
    with open(path, "rb") as file:
        return base64.b64encode(file.read()).decode("utf-8")


def _extract_gemini_image(result: dict):
    interaction = result.get("interaction") or result
    out = interaction.get("output_image") or {}
    if out.get("data"):
        return out["data"]
    for step in interaction.get("steps", []):
        if not isinstance(step, dict):
            continue
        for part in step.get("content", []):
            if isinstance(part, dict) and part.get("type") == "image" and part.get("data"):
                return part["data"]
    return None


def gemini_gorsel(prompt: str, reference_paths: list[str], output_path: str, en_boy: str) -> None:
    api_key = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY ortam değişkeni ayarlanmalı.")

    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for ref in reference_paths:
        parts.append({"type": "image", "mime_type": "image/jpeg", "data": _image_b64(ref)})

    body: dict[str, Any] = {
        "model": _env("GEMINI_IMAGE_MODEL", "gemini-3-pro-image"),
        "input": parts,
        "response_format": {
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": en_boy,
            "image_size": _env("GEMINI_IMAGE_SIZE", "2K"),
        },
    }
    response = requests.post(
        GEMINI_BASE_URL,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=300,
    )
    if response.status_code != 200:
        raise ValueError(f"Gemini görsel hatası (HTTP {response.status_code}): {response.text[:500]}")
    data = _extract_gemini_image(response.json())
    if not data:
        raise ValueError("Gemini görüntü üretmedi (içerik reddi veya boş yanıt).")
    with Image.open(io.BytesIO(base64.b64decode(data))) as image:
        image.convert("RGB").save(output_path, format="PNG")


def _kimlik_metni(deger: Any) -> str:
    """visual_identity gibi iç içe sözlükleri okunabilir tek satıra çevirir."""
    if isinstance(deger, dict):
        return ", ".join(f"{k}: {_kimlik_metni(v)}" for k, v in deger.items() if v)
    if isinstance(deger, (list, tuple)):
        return ", ".join(_kimlik_metni(v) for v in deger if v)
    return str(deger).strip()


def karakter_referans_promptu(seri: modeller.Seri, karakter: modeller.Karakter) -> str:
    stil = seri.visual_style or "cinematic"
    tip = f" ({karakter.type})" if karakter.type else ""
    kimlik = _kimlik_metni(karakter.visual_identity)
    kiyafet = f" wearing {karakter.default_clothing}" if karakter.default_clothing else ""
    return (
        f"{stil}. Full-body character reference portrait of {karakter.name}{tip}{kiyafet}. "
        f"{kimlik}. Facing camera, neutral plain background, soft even lighting, "
        "single character only, clear face and anatomy, no text, no watermark."
    )


def karakter_referanslari(
    seri: modeller.Seri,
    karakterler: list[modeller.Karakter],
    aktif_ids: set[str],
    proje_dizini: str,
) -> dict[str, str]:
    """Her aktif karakter için bir kez referans portre üretir (idempotent)."""
    klasor = os.path.join(proje_dizini, "referanslar")
    os.makedirs(klasor, exist_ok=True)
    yollar: dict[str, str] = {}
    for karakter in karakterler:
        if karakter.character_id not in aktif_ids:
            continue
        yol = os.path.join(klasor, f"{karakter.character_id}.png")
        yollar[karakter.character_id] = yol
        if _gecerli_gorsel(yol):
            continue
        gemini_gorsel(karakter_referans_promptu(seri, karakter), [], yol, "1:1")
    return yollar


def sahne_promptu(
    sahne: modeller.Sahne,
    seri: modeller.Seri,
    karakterler: dict[str, modeller.Karakter],
    mekanlar: dict[str, modeller.Mekan],
) -> str:
    parcalar = [seri.visual_style or "cinematic film still"]
    parcalar.append(sahne.image_prompt or sahne.visual_description or sahne.story_event)

    for cid in sahne.character_ids:
        karakter = karakterler.get(cid)
        if karakter:
            kiyafet = f", wearing {karakter.default_clothing}" if karakter.default_clothing else ""
            parcalar.append(
                f"{karakter.name} ({karakter.type}): {_kimlik_metni(karakter.visual_identity)}{kiyafet}"
            )

    mekan = mekanlar.get(sahne.location_id)
    if mekan:
        parcalar.append(f"Location {mekan.name}: {_kimlik_metni(mekan.visual_identity)}")

    for cid, durum in sahne.character_states.items():
        if not durum:
            continue
        ad = karakterler[cid].name if cid in karakterler else cid
        parcalar.append(f"{ad} state: {_kimlik_metni(durum)}")

    if sahne.location_state:
        parcalar.append(f"Scene state: {_kimlik_metni(sahne.location_state)}")

    parcalar.append("Cinematic composition, consistent identity, no text, no letters, no watermark.")
    return " ".join(p.strip() for p in parcalar if p and p.strip())


def sahne_metni(sahne: modeller.Sahne) -> str:
    """Seslendirilecek metin. narration diyalogları da içerecek şekilde üretilir."""
    metin = sahne.narration.strip()
    if metin:
        return metin
    # ponytail: diyalog yalnızca narration boşsa okunur; çok sesli TTS eklenirse buraya taşınır.
    return " ".join(str(d.get("line", "")).strip() for d in sahne.dialogue if d.get("line"))


# ---------------------------------------------------------------
# Ses
# ---------------------------------------------------------------
def _tts_istek(
    metin: str,
    dil: str,
    cinsiyet: str,
    voice_settings: dict | None = None,
    voice_id: str | None = None,
    zamanli: bool = False,
):
    """ElevenLabs çağrısı. zamanli=True ise (ses, alignment) sözlüğü döner."""
    api_key = _env("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY ortam değişkeni ayarlanmalı.")
    secili = voice_id or ses_preset(dil, cinsiyet)["voice_id"]
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{secili}"
    if zamanli:
        url += "/with-timestamps"
    ayarlar = voice_settings or {"stability": 0.5, "similarity_boost": 0.75, "style": 0.3}
    response = requests.post(
        url,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={
            "text": metin,
            "model_id": _env("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5"),
            "voice_settings": ayarlar,
        },
        timeout=300,
    )
    if response.status_code != 200:
        raise ValueError(f"ElevenLabs hatası (HTTP {response.status_code}): {response.text[:500]}")
    return response.json() if zamanli else response.content


def tts_elevenlabs(
    metin: str,
    output_path: str,
    dil: str = "tr",
    cinsiyet: str = "kadin",
    voice_settings: dict | None = None,
    voice_id: str | None = None,
) -> None:
    if not metin.strip():
        raise ValueError("Seslendirilecek metin boş.")
    with open(output_path, "wb") as file:
        file.write(_tts_istek(metin, dil, cinsiyet, voice_settings, voice_id))


def tts_zamanli(
    metin: str,
    output_path: str,
    dil: str = "tr",
    cinsiyet: str = "kadin",
    voice_settings: dict | None = None,
    voice_id: str | None = None,
) -> dict:
    """Sesi zaman damgalarıyla üretir; altyazı için alignment döndürür."""
    if not metin.strip():
        raise ValueError("Seslendirilecek metin boş.")
    data = _tts_istek(metin, dil, cinsiyet, voice_settings, voice_id, zamanli=True)
    ses = base64.b64decode(data.get("audio_base64") or "")
    if not ses:
        raise ValueError("ElevenLabs zamanlı yanıtında ses verisi yok.")
    with open(output_path, "wb") as file:
        file.write(ses)
    return data.get("alignment") or data.get("normalized_alignment") or {}


def sahne_ses_parcalari(
    sahne: modeller.Sahne, karakterler: dict[str, modeller.Karakter] | None = None
) -> list[tuple[str, str]]:
    """(metin, voice_id) listesi. Anlatıcı önce, replikler karakter sesiyle."""
    karakterler = karakterler or {}
    parcalar: list[tuple[str, str]] = []
    if sahne.narration.strip():
        parcalar.append((sahne.narration.strip(), ""))
    for replik in sahne.dialogue:
        metin = str(replik.get("line", "")).strip()
        if not metin:
            continue
        cid = str(replik.get("character_id", ""))
        karakter = karakterler.get(cid)
        parcalar.append((metin, karakter.voice_id if karakter and karakter.voice_id else ""))
    return parcalar


def _sessiz_ses(output_path: str, duration: float) -> None:
    cmd = [
        _binary("ffmpeg"), "-y", "-f", "lavfi",
        "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
        "-t", f"{duration:.2f}", "-q:a", "9", output_path,
    ]
    _run_ffmpeg(cmd, "sessiz ses")


def _zaman_parcalari(metin: str, max_chars: int = 46) -> list[tuple[int, int, str]]:
    """Metni cümle/kelime sınırlarında altyazı parçalarına böler."""
    kelimeler = [(m.start(), m.end()) for m in re.finditer(r"\S+", metin)]
    parcalar: list[tuple[int, int, str]] = []
    mevcut: list[tuple[int, int]] = []
    uzunluk = 0
    for bas, son in kelimeler:
        kelime = metin[bas:son]
        onceki_nokta = bool(mevcut) and metin[mevcut[-1][0]:mevcut[-1][1]].endswith((".", "!", "?", "…"))
        if mevcut and (onceki_nokta or uzunluk + 1 + len(kelime) > max_chars):
            parcalar.append((mevcut[0][0], mevcut[-1][1], metin[mevcut[0][0]:mevcut[-1][1]]))
            mevcut, uzunluk = [], 0
        mevcut.append((bas, son))
        uzunluk += len(kelime) + 1
    if mevcut:
        parcalar.append((mevcut[0][0], mevcut[-1][1], metin[mevcut[0][0]:mevcut[-1][1]]))
    return parcalar


def _cues(metin: str, alignment: dict, offset: float, sure: float) -> list[dict]:
    """Metni altyazı cue'larına çevirir; alignment yoksa süreyi oransal böler."""
    if not metin.strip() or sure <= 0:
        return []
    chars: list = list(alignment.get("characters") or []) if alignment else []
    starts: list = list(alignment.get("character_start_times_seconds") or []) if alignment else []
    ends: list = list(alignment.get("character_end_times_seconds") or []) if alignment else []
    hizalama_var = bool(chars and starts and ends and len(chars) == len(metin))

    cues: list[dict] = []
    for bas, son, parca in _zaman_parcalari(metin):
        if hizalama_var and bas < len(starts) and son - 1 < len(ends):
            baslangic = float(starts[bas])
            bitis = float(ends[son - 1])
        else:
            baslangic = sure * bas / max(1, len(metin))
            bitis = sure * son / max(1, len(metin))
        cues.append({
            "start": max(0.0, offset + baslangic),
            "end": max(0.0, offset + bitis),
            "text": parca.strip(),
        })
    return cues


def _cues_tahmini(metin: str, sure: float, offset: float = 0.0) -> list[dict]:
    return _cues(metin, {}, offset, sure)


def _cues_yaz(cues: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(cues, file, ensure_ascii=False, indent=2)


def _cues_oku(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return []


def sahne_seslendir(
    sahne: modeller.Sahne,
    output_path: str,
    karakterler: dict[str, modeller.Karakter] | None = None,
    dil: str = "tr",
    cinsiyet: str = "kadin",
    zamanli: bool = True,
) -> list[dict]:
    """Sahne sesini üretir (çok sesli) ve altyazı cue'larını döndürür."""
    parcalar = sahne_ses_parcalari(sahne, karakterler)
    if not parcalar:
        raise ValueError(f"Sahne {sahne.order}: seslendirilecek metin boş.")

    klasor = output_path + "_parcalar"
    os.makedirs(klasor, exist_ok=True)
    dosyalar: list[str] = []
    cues: list[dict] = []
    offset = 0.0
    gap = 0.25

    for index, (metin, voice_id) in enumerate(parcalar):
        yol = os.path.join(klasor, f"parca_{index:03d}.mp3")
        alignment: dict = {}
        if zamanli:
            try:
                alignment = tts_zamanli(metin, yol, dil, cinsiyet, voice_id=voice_id)
            except Exception:  # noqa: BLE001 - zaman damgası desteklenmezse düz TTS
                tts_elevenlabs(metin, yol, dil, cinsiyet, voice_id=voice_id)
        else:
            tts_elevenlabs(metin, yol, dil, cinsiyet, voice_id=voice_id)
        sure = medya_suresi(yol)
        cues.extend(_cues(metin, alignment, offset, sure))
        dosyalar.append(yol)
        offset += sure + gap

    if len(dosyalar) == 1:
        shutil.copyfile(dosyalar[0], output_path)
    else:
        sessiz = os.path.join(klasor, "ara.mp3")
        _sessiz_ses(sessiz, gap)
        liste = os.path.join(klasor, "liste.txt")
        with open(liste, "w", encoding="utf-8") as file:
            for i, dosya in enumerate(dosyalar):
                file.writelines(f"file '{os.path.abspath(dosya).replace(chr(92), '/')}'\n")
                if i < len(dosyalar) - 1:
                    file.writelines(f"file '{os.path.abspath(sessiz).replace(chr(92), '/')}'\n")
        _run_ffmpeg(
            [
                _binary("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", liste,
                "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-q:a", "2", output_path,
            ],
            "çok sesli sahne sesi",
        )
    return cues


def _srt_zamani(saniye: float) -> str:
    ms = max(0, round(saniye * 1000))
    saat, kalan = divmod(ms, 3_600_000)
    dakika, kalan = divmod(kalan, 60_000)
    saniye, ms = divmod(kalan, 1000)
    return f"{saat:02d}:{dakika:02d}:{saniye:02d},{ms:03d}"


def srt_yaz(cues: list[dict], output_path: str) -> None:
    satirlar: list[str] = []
    onceki_bitis = 0.0
    for index, cue in enumerate(sorted(cues, key=lambda c: c["start"]), start=1):
        baslangic = max(onceki_bitis, float(cue["start"]))
        bitis = max(baslangic + 0.4, float(cue["end"]))
        if not str(cue.get("text", "")).strip():
            continue
        satirlar.append(
            f"{index}\n{_srt_zamani(baslangic)} --> {_srt_zamani(bitis)}\n{cue['text'].strip()}\n"
        )
        onceki_bitis = bitis
    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(satirlar))


def altyazi_yak(video_path: str, srt_path: str, output_path: str, en_boy: str = "16:9") -> bool:
    """SRT'yi videoya gömer. libass yoksa videoyu olduğu gibi kopyalar."""
    klasor = os.path.dirname(os.path.abspath(srt_path))
    ad = os.path.basename(srt_path)
    boyut = 20 if (en_boy or "16:9") == "9:16" else 17
    style = (
        f"FontName=Arial,FontSize={boyut},PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=36"
    )
    try:
        _run_ffmpeg(
            [
                _binary("ffmpeg"), "-y", "-i", os.path.abspath(video_path),
                "-vf", f"subtitles={ad}:force_style='{style}'",
                "-c:a", "copy", os.path.abspath(output_path),
            ],
            "altyazı yakma",
            cwd=klasor,
        )
    except ValueError:
        shutil.copyfile(video_path, output_path)
        return False
    if not _gecerli_video(output_path):
        shutil.copyfile(video_path, output_path)
        return False
    return True


def medya_suresi(path: str) -> float:
    cmd = [
        _binary("ffprobe"), "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


# ---------------------------------------------------------------
# FFmpeg
# ---------------------------------------------------------------
def _run_ffmpeg(cmd: list[str], aciklama: str, cwd: str | None = None) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)
    if result.returncode != 0:
        raise ValueError(f"FFmpeg hatası ({aciklama}): {(result.stderr or '').strip()[-800:]}")


def _gecerli_dosya(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0


def _gecerli_gorsel(path: str) -> bool:
    if not _gecerli_dosya(path):
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:  # noqa: BLE001 - bozuk/yarım görsel
        return False


def _gecerli_video(path: str) -> bool:
    return _gecerli_dosya(path) and medya_suresi(path) > 0


def _zoom_filtresi(motion: str, frames: int, w: int, h: int) -> str:
    metin = (motion or "zoom in").lower()
    if "zoom-out" in metin or "zoom out" in metin or "uzaklaş" in metin:
        zoom = "if(eq(on,0),1.15,max(zoom-0.0015,1.0))"
        x = "iw/2-(iw/zoom/2)"
    elif "pan left" in metin or "sola" in metin:
        zoom = "1.08"
        x = f"min(on*iw*0.08/{frames},iw-iw/zoom)"
    elif "pan right" in metin or "sağa" in metin:
        zoom = "1.08"
        x = f"max(iw-iw/zoom-on*iw*0.08/{frames},0)"
    else:
        zoom = "min(zoom+0.0015,1.15)"
        x = "iw/2-(iw/zoom/2)"
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"zoompan=z='{zoom}':d={frames}:x='{x}':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=25,"
        "format=yuv420p"
    )


def statik_klip(
    image_path: str,
    audio_path: str | None,
    duration: float,
    output_path: str,
    motion: str = "zoom in",
    en_boy: str = "16:9",
) -> None:
    """Görseli Ken Burns hareketiyle verilen süreye gerer; ses varsa ekler."""
    w, h = boyutlar(en_boy)
    vf = _zoom_filtresi(motion, int(duration * 25), w, h)
    cmd = [_binary("ffmpeg"), "-y", "-loop", "1", "-i", image_path]
    if audio_path:
        cmd += ["-i", audio_path, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
    else:
        # Her klibin ses kanalı olsun ki final concat tutarlı kalsın.
        cmd += [
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest",
        ]
    cmd += ["-vf", vf, "-t", f"{duration:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path]
    _run_ffmpeg(cmd, "statik sahne")
    if not _gecerli_video(output_path):
        raise ValueError(f"Statik klip geçersiz: {output_path}")


def _data_uri(image_path: str) -> str:
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    return f"data:{mime};base64,{_image_b64(image_path)}"


def fal_klip(image_path: str, prompt: str, output_path: str, clip_duration: int = 5) -> None:
    api_key = _env("FAL_API_KEY")
    if not api_key:
        raise ValueError("FAL_API_KEY ortam değişkeni ayarlanmalı.")

    model = _env("FAL_VIDEO_MODEL", "fal-ai/kling-video/v2.6/pro/image-to-video")
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    guvenli_prompt = prompt.strip().rstrip(".") + ". Subtle cinematic motion, no text, no watermark."
    response = requests.post(
        f"{FAL_QUEUE_BASE_URL}/{model}",
        headers=headers,
        json={
            "prompt": guvenli_prompt,
            "image_url": _data_uri(image_path),
            "duration": str(clip_duration),
        },
        timeout=120,
    )
    if response.status_code != 200:
        raise ValueError(f"fal.ai hatası (HTTP {response.status_code}): {response.text[:500]}")

    gorev = response.json()
    status_url, response_url = gorev.get("status_url"), gorev.get("response_url")
    if not status_url or not response_url:
        raise ValueError(f"fal.ai beklenmeyen yanıt: {gorev}")

    for _ in range(120):
        durum = requests.get(status_url, headers=headers, timeout=60).json().get("status")
        if durum == "COMPLETED":
            break
        if durum in ("FAILED", "CANCELED"):
            raise ValueError(f"fal.ai video başarısız: {durum}")
        time.sleep(5)
    else:
        raise ValueError("fal.ai zaman aşımı.")

    sonuc = requests.get(response_url, headers=headers, timeout=120).json()
    video_url = (sonuc.get("video") or {}).get("url")
    if not video_url:
        raise ValueError(f"fal.ai sonucunda video yok: {sonuc}")
    with open(output_path, "wb") as file:
        file.write(requests.get(video_url, timeout=300).content)


def _son_kare(video_path: str, output_path: str) -> None:
    cmd = [
        _binary("ffmpeg"), "-y", "-sseof", "-0.1", "-i", video_path,
        "-frames:v", "1", "-q:v", "2", output_path,
    ]
    _run_ffmpeg(cmd, "son kare")


def hareketli_klip(
    image_path: str,
    prompt: str,
    audio_path: str,
    duration: float,
    output_path: str,
    en_boy: str = "16:9",
) -> None:
    """fal.ai ile anlatım süresi boyunca tekrar etmeyen hareket üretir."""
    clip_duration = int(_env("FAL_CLIP_DURATION", "5"))
    klasor = output_path + "_segmentler"
    os.makedirs(klasor, exist_ok=True)
    segmentler: list[str] = []
    toplam = 0.0

    while toplam < duration:
        index = len(segmentler)
        segment = os.path.join(klasor, f"seg_{index:03d}.mp4")
        if index == 0:
            kaynak, segment_prompt = image_path, prompt
        else:
            son_kare = os.path.join(klasor, f"son_{index:03d}.jpg")
            _son_kare(segmentler[-1], son_kare)
            kaynak = son_kare
            segment_prompt = (
                "Continue the exact scene from this frame. Keep characters, clothing, "
                "lighting and camera style identical; natural continuous motion, no cut."
            )
        fal_klip(kaynak, segment_prompt, segment, clip_duration)
        sure = medya_suresi(segment)
        if sure <= 0:
            raise ValueError(f"Hareketli segment süresi geçersiz: {segment}")
        segmentler.append(segment)
        toplam += sure
        if index >= 40:
            raise ValueError("Segment limiti aşıldı; FAL_CLIP_DURATION değerini artırın.")

    _segment_birlestir(segmentler, audio_path, duration, output_path, en_boy)


def _segment_birlestir(
    segmentler: list[str], audio_path: str | None, duration: float, output_path: str, en_boy: str
) -> None:
    w, h = boyutlar(en_boy)
    n = len(segmentler)
    parcalar = [
        f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"setsar=1,fps=25[v{i}]"
        for i in range(n)
    ]
    parcalar.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]")
    cmd = [_binary("ffmpeg"), "-y"]
    for segment in segmentler:
        cmd += ["-i", segment]
    if audio_path:
        cmd += ["-i", audio_path]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += [
        "-filter_complex", ";".join(parcalar),
        "-map", "[v]", "-map", f"{n}:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration:.2f}", output_path,
    ]
    _run_ffmpeg(cmd, "segment birleştirme")


def _medya_turu(path: str) -> str:
    return "image" if os.path.splitext(path)[1].lower() in (".jpg", ".jpeg", ".png", ".webp") else "video"


def _still_segment(image_path: str, duration: float, output_path: str, en_boy: str) -> None:
    w, h = boyutlar(en_boy)
    vf = _zoom_filtresi("zoom in", max(1, int(duration * 25)), w, h)
    cmd = [
        _binary("ffmpeg"), "-y", "-loop", "1", "-i", image_path,
        "-vf", vf, "-t", f"{duration:.2f}", "-r", "25",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path,
    ]
    _run_ffmpeg(cmd, "medya görsel segmenti")


def _video_segment(video_path: str, duration: float, output_path: str, en_boy: str) -> None:
    w, h = boyutlar(en_boy)
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        "setsar=1,fps=25"
    )
    cmd = [
        _binary("ffmpeg"), "-y", "-stream_loop", "-1", "-i", video_path,
        "-vf", vf, "-t", f"{duration:.2f}",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path,
    ]
    _run_ffmpeg(cmd, "medya video segmenti")


def medya_kolaj(
    media_paths: list[str],
    audio_path: str | None,
    duration: float,
    output_path: str,
    en_boy: str = "16:9",
) -> None:
    """Gerçek fotoğraf/videoları sahne süresine eşit parçalarla kolaj yapar."""
    mevcut = [p for p in media_paths if p and os.path.exists(p)]
    if not mevcut:
        raise ValueError("Sahnede kullanılabilir medya dosyası bulunamadı.")
    n = len(mevcut)
    parca_sure = duration / n
    klasor = output_path + "_medya_segmentler"
    os.makedirs(klasor, exist_ok=True)
    segmentler: list[str] = []
    for index, path in enumerate(mevcut):
        segment = os.path.join(klasor, f"medya_{index:03d}.mp4")
        if _medya_turu(path) == "image":
            _still_segment(path, parca_sure, segment, en_boy)
        else:
            _video_segment(path, parca_sure, segment, en_boy)
        segmentler.append(segment)
    _segment_birlestir(segmentler, audio_path, duration, output_path, en_boy)


def _has_audio(path: str) -> bool:
    cmd = [
        _binary("ffprobe"), "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return "audio" in (result.stdout or "")


def video_ile_ses(
    video_path: str, audio_path: str | None, duration: float, output_path: str, en_boy: str = "16:9"
) -> None:
    """Videoyu hedef süreye döngüleyip harici sesi (veya sessizliği) ekler.

    ponytail: OpenMontage klibi anlatımdan kısaysa döngülenir; sahne başına
    yeni segment üretimi maliyeti artırdığı için önce bu yol kullanılır.
    """
    w, h = boyutlar(en_boy)
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        "setsar=1,fps=25"
    )
    cmd = [_binary("ffmpeg"), "-y", "-stream_loop", "-1", "-i", video_path]
    if audio_path:
        cmd += ["-i", audio_path]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += [
        "-vf", vf, "-map", "0:v", "-map", "1:a", "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]
    _run_ffmpeg(cmd, "video + ses")


def _videoyu_normalize(
    video_path: str, duration: float, output_path: str, en_boy: str, native_audio: bool
) -> None:
    """OpenMontage klip sesini koruyarak (veya sessizleştirerek) hedef boyuta getirir."""
    w, h = boyutlar(en_boy)
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        "setsar=1,fps=25"
    )
    cmd = [_binary("ffmpeg"), "-y", "-stream_loop", "-1", "-i", video_path]
    if native_audio and _has_audio(video_path):
        cmd += ["-map", "0:v", "-map", "0:a"]
    else:
        cmd += [
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map", "0:v", "-map", "1:a",
        ]
    cmd += [
        "-vf", vf, "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]
    _run_ffmpeg(cmd, "video normalizasyon")


def openmontage_klip(
    image_path: str,
    prompt: str,
    output_path: str,
    duration: float,
    en_boy: str = "16:9",
    generate_audio: bool = True,
) -> str:
    """OpenMontage sağlayıcı zincirini kullanarak görselden video üretir."""
    from video_provider_router import generate_video_via_openmontage

    hedef_sure = int(max(4, min(30, round(duration))))
    sonuc = generate_video_via_openmontage(
        prompt=prompt,
        image_path=image_path,
        output_path=output_path,
        duration=hedef_sure,
        generate_audio=generate_audio,
        aspect_ratio=en_boy,
    )
    gercek = str(sonuc.get("output_path") or output_path)
    if os.path.abspath(gercek) != os.path.abspath(output_path):
        shutil.copyfile(gercek, output_path)
    return str(sonuc.get("provider", ""))


def video_promptu(
    sahne: modeller.Sahne,
    seri: modeller.Seri,
    karakterler: dict[str, modeller.Karakter],
    mekanlar: dict[str, modeller.Mekan],
) -> str:
    """OpenMontage/Veo için görsel + native ses talimatı."""
    parcalar = [sahne_promptu(sahne, seri, karakterler, mekanlar)]
    if sahne.motion:
        parcalar.append(f"Camera motion: {sahne.motion}.")
    if sahne.narration.strip():
        parcalar.append(f'Narrator voice in Turkish says: "{sahne.narration.strip()}"')
    for replik in sahne.dialogue:
        metin = str(replik.get("line", "")).strip()
        if not metin:
            continue
        cid = str(replik.get("character_id", ""))
        ad = karakterler[cid].name if cid in karakterler else "Character"
        parcalar.append(f'{ad} says: "{metin}"')
    parcalar.append(
        "Include natural ambient sound and clear dialogue audio; no subtitles, no text overlays."
    )
    return " ".join(parcalar)


def _font_kopyala(klasor: str) -> str:
    adaylar = [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    hedef = os.path.join(klasor, "_font.ttf")
    if not os.path.exists(hedef):
        for aday in adaylar:
            if os.path.exists(aday):
                shutil.copyfile(aday, hedef)
                break
    if not os.path.exists(hedef):
        raise RuntimeError("drawtext için TrueType font bulunamadı.")
    return "_font.ttf"


def baslik_karti(
    baslik: str,
    alt_metin: str,
    sure: float,
    output_path: str,
    en_boy: str = "16:9",
    arka_plan: str | None = None,
) -> None:
    """FFmpeg drawtext ile intro/outro kartı üretir (sessiz ses kanalıyla)."""
    klasor = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(klasor, exist_ok=True)
    font = _font_kopyala(klasor)
    bas_dosya = "_baslik.txt"
    alt_dosya = "_alt.txt"
    with open(os.path.join(klasor, bas_dosya), "w", encoding="utf-8") as file:
        file.write(baslik)
    with open(os.path.join(klasor, alt_dosya), "w", encoding="utf-8") as file:
        file.write(alt_metin)

    w, h = boyutlar(en_boy)
    bas_font = max(24, h // 13)
    alt_font = max(16, h // 30)
    cizim = (
        f"drawtext=fontfile={font}:textfile={bas_dosya}:expansion=none:"
        f"fontcolor=white:fontsize={bas_font}:x=(w-text_w)/2:y=(h-text_h)*0.40,"
        f"drawtext=fontfile={font}:textfile={alt_dosya}:expansion=none:"
        f"fontcolor=0xDDDDDD:fontsize={alt_font}:x=(w-text_w)/2:y=(h-text_h)*0.54,"
        f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(0.0, sure - 0.35):.2f}:d=0.35"
    )

    if arka_plan and _gecerli_gorsel(arka_plan):
        cmd = [
            _binary("ffmpeg"), "-y", "-loop", "1", "-i", arka_plan,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            (
                f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.55:t=fill,{cizim}"
            ),
        ]
    else:
        cmd = [
            _binary("ffmpeg"), "-y",
            "-f", "lavfi", "-i", f"color=c=0x0E141B:s={w}x{h}:d={sure:.2f}",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", cizim,
        ]
    cmd += [
        "-t", f"{sure:.2f}", "-r", "25",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        os.path.abspath(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=klasor)
    if result.returncode != 0 or not _gecerli_video(output_path):
        raise ValueError(f"Başlık kartı üretilemedi: {(result.stderr or '')[-600:]}")


def _medya_yolu(proje_dizini: str, oge: Any) -> str:
    ham = str(oge.get("path", "")) if isinstance(oge, dict) else str(oge)
    return ham if os.path.isabs(ham) else os.path.join(proje_dizini, ham)


def birlestir(klips: list[str], output_path: str) -> None:
    if not klips:
        raise ValueError("Birleştirilecek klip yok.")
    list_file = output_path + ".concat.txt"
    with open(list_file, "w", encoding="utf-8") as file:
        file.writelines(
            f"file '{os.path.abspath(klip).replace(chr(92), '/')}'\n" for klip in klips
        )

    cmd = [
        _binary("ffmpeg"), "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", output_path,
    ]
    try:
        _run_ffmpeg(cmd, "final birleştirme")
    except ValueError:
        # Farklı kodlayıcı/örnekleme hızlarında stream copy başarısız olabilir.
        _run_ffmpeg(
            [
                _binary("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", list_file,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                output_path,
            ],
            "final birleştirme (yeniden kodlama)",
        )
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)
    if not _gecerli_video(output_path):
        raise ValueError(f"Final video geçersiz: {output_path}")


# ---------------------------------------------------------------
# Uçtan uca üretim
# ---------------------------------------------------------------
def _ilerleme_yaz(ilerleme: Callable[[str, float], None] | None, mesaj: str, oran: float) -> None:
    print(mesaj)
    if ilerleme:
        ilerleme(mesaj, oran)


def tahmini_cagri_sayilari(
    senaryo: modeller.Senaryo,
    video_modu: str = "resim",
    seslendirme: bool = True,
) -> dict[str, int]:
    gorsel_sahneler = [s for s in senaryo.scenes if not s.media]
    karakterler = {cid for s in gorsel_sahneler for cid in s.character_ids}
    hareket = 0
    if video_modu == "hareketli":
        hareket = sum(
            max(1, math.ceil(sahne.estimated_duration_sec / max(1, int(_env("FAL_CLIP_DURATION", "5")))))
            for sahne in senaryo.scenes
        )
    native = video_modu == "openmontage"
    return {
        "referans_gorsel": len(karakterler),
        "sahne_gorsel": len(gorsel_sahneler),
        "tts": len(senaryo.scenes) if seslendirme else 0,
        "fal_klip": hareket,
        "openmontage": len(senaryo.scenes) if native else 0,
    }


def uret(
    senaryo: modeller.Senaryo,
    seri: modeller.Seri,
    karakterler: list[modeller.Karakter],
    mekanlar: list[modeller.Mekan],
    proje_dizini: str,
    video_modu: str = "openmontage",
    seslendirme: bool | None = None,
    tts_dili: str = "tr",
    tts_cinsiyeti: str = "kadin",
    intro_outro: bool = True,
    altyazi: bool = True,
    ilerleme: Callable[[str, float], None] | None = None,
) -> dict:
    """Sahneleri üretir ve final videoyu döndürür. Var olan geçerli klipler atlanır."""
    if video_modu not in VIDEO_MODLARI:
        raise ValueError(f"Geçersiz video modu: {video_modu}")
    native_ses = video_modu == "openmontage"
    if seslendirme is None:
        seslendirme = not native_ses

    os.makedirs(proje_dizini, exist_ok=True)
    for alt in ("gorseller", "sesler", "klipler"):
        os.makedirs(os.path.join(proje_dizini, alt), exist_ok=True)

    k_sozluk = {k.character_id: k for k in karakterler}
    m_sozluk = {m.location_id: m for m in mekanlar}
    en_boy = seri.default_aspect_ratio or "16:9"
    gorsel_sahneler = [s for s in senaryo.scenes if not s.media]
    aktif_ids = {cid for s in gorsel_sahneler for cid in s.character_ids}

    if aktif_ids:
        _ilerleme_yaz(ilerleme, "Karakter referansları hazırlanıyor...", 0.02)
    refs = karakter_referanslari(seri, karakterler, aktif_ids, proje_dizini) if aktif_ids else {}

    intro_sure = 2.5 if intro_outro else 0.0
    kaydirma = intro_sure
    klipler: list[str] = []
    tum_cues: list[dict] = []
    toplam = len(senaryo.scenes)
    ilk_gorsel: str | None = None

    for index, sahne in enumerate(senaryo.scenes, start=1):
        oran = index / max(1, toplam)
        ad = f"{sahne.order:03d}"
        klip = os.path.join(proje_dizini, "klipler", f"sahne_{ad}.mp4")
        klipler.append(klip)
        cues_yolu = os.path.join(proje_dizini, "sesler", f"sahne_{ad}.cues.json")

        if _gecerli_video(klip):
            sure = medya_suresi(klip)
            yerel = _cues_oku(cues_yolu)
            for cue in yerel:
                tum_cues.append({
                    "start": float(cue["start"]) + kaydirma,
                    "end": float(cue["end"]) + kaydirma,
                    "text": cue["text"],
                })
            kaydirma += sure
            _ilerleme_yaz(ilerleme, f"Sahne {sahne.order}: mevcut, atlanıyor.", oran)
            continue

        gorsel = os.path.join(proje_dizini, "gorseller", f"sahne_{ad}.png")
        ses: str | None = None
        yerel_cues: list[dict] = []

        if sahne.media:
            _ilerleme_yaz(ilerleme, f"Sahne {sahne.order}: medya kolajı hazırlanıyor...", oran)
            medya = [_medya_yolu(proje_dizini, m) for m in sahne.media]
            if seslendirme:
                ses = os.path.join(proje_dizini, "sesler", f"sahne_{ad}.mp3")
                if not _gecerli_dosya(ses):
                    yerel_cues = sahne_seslendir(sahne, ses, k_sozluk, tts_dili, tts_cinsiyeti, zamanli=altyazi)
                    _cues_yaz(yerel_cues, cues_yolu)
                else:
                    yerel_cues = _cues_oku(cues_yolu) or _cues_tahmini(
                        sahne_metni(sahne), medya_suresi(ses)
                    )
                duration = max(2.0, medya_suresi(ses) + 0.35)
            else:
                duration = float(max(3, min(40, sahne.estimated_duration_sec)))
            medya_kolaj(medya, ses, duration, klip, en_boy)
        else:
            if not _gecerli_gorsel(gorsel):
                _ilerleme_yaz(ilerleme, f"Sahne {sahne.order}: görsel üretiliyor...", oran)
                sahne_refs = [refs[cid] for cid in sahne.character_ids if cid in refs]
                not_ = ""
                if sahne_refs:
                    not_ = " ".join(
                        f"Character {i} must match reference image {i} exactly."
                        for i in range(1, len(sahne_refs) + 1)
                    )
                gemini_gorsel(
                    f"{sahne_promptu(sahne, seri, k_sozluk, m_sozluk)} {not_}".strip(),
                    sahne_refs,
                    gorsel,
                    en_boy,
                )
            if ilk_gorsel is None:
                ilk_gorsel = gorsel

            if seslendirme:
                ses = os.path.join(proje_dizini, "sesler", f"sahne_{ad}.mp3")
                if not _gecerli_dosya(ses):
                    _ilerleme_yaz(ilerleme, f"Sahne {sahne.order}: seslendiriliyor...", oran)
                    yerel_cues = sahne_seslendir(
                        sahne, ses, k_sozluk, tts_dili, tts_cinsiyeti, zamanli=altyazi
                    )
                    _cues_yaz(yerel_cues, cues_yolu)
                else:
                    yerel_cues = _cues_oku(cues_yolu) or _cues_tahmini(
                        sahne_metni(sahne), medya_suresi(ses)
                    )
                duration = max(2.0, medya_suresi(ses) + 0.35)

            elif native_ses:
                # Native audio: Veo 4/6/8 sn üretir. Uzun sahnelerde ses tekrar
                # etmesin diye üst sınır NATIVE_MAX_SN (varsayılan 8) ile sınırlanır.
                native_max = int(_env("NATIVE_MAX_SN", "8"))
                duration = float(max(4, min(native_max, sahne.estimated_duration_sec)))
                if altyazi:
                    yerel_cues = _cues_tahmini(sahne_metni(sahne), duration)
                    _cues_yaz(yerel_cues, cues_yolu)
            else:
                duration = float(max(3, min(40, sahne.estimated_duration_sec)))

            motion = sahne.motion or "zoom in"
            if video_modu == "openmontage":
                try:
                    _ilerleme_yaz(ilerleme, f"Sahne {sahne.order}: Runway/Veo üretiyor...", oran)
                    ham = klip + ".ham.mp4"
                    openmontage_klip(
                        gorsel,
                        video_promptu(sahne, seri, k_sozluk, m_sozluk),
                        ham,
                        duration,
                        en_boy,
                        generate_audio=not seslendirme,
                    )
                    if seslendirme and ses:
                        video_ile_ses(ham, ses, duration, klip, en_boy)
                    else:
                        _videoyu_normalize(ham, duration, klip, en_boy, native_audio=True)
                    if os.path.exists(ham):
                        os.remove(ham)
                except Exception as hata:  # noqa: BLE001 - sağlayıcı düşerse ekonomik moda geç
                    _ilerleme_yaz(ilerleme, f"Sahne {sahne.order}: OpenMontage başarısız ({hata}); yedek mod.", oran)
                    if video_modu != "hareketli" and ses and _env("FAL_API_KEY"):
                        try:
                            hareketli_klip(
                                gorsel, sahne_promptu(sahne, seri, k_sozluk, m_sozluk),
                                ses, duration, klip, en_boy,
                            )
                        except Exception:  # noqa: BLE001
                            statik_klip(gorsel, ses, duration, klip, motion, en_boy)
                    else:
                        statik_klip(gorsel, ses, duration, klip, motion, en_boy)
            elif video_modu == "hareketli" and ses and _env("FAL_API_KEY"):
                try:
                    _ilerleme_yaz(ilerleme, f"Sahne {sahne.order}: hareketli video...", oran)
                    hareketli_klip(
                        gorsel, sahne_promptu(sahne, seri, k_sozluk, m_sozluk),
                        ses, duration, klip, en_boy,
                    )
                except Exception as hata:  # noqa: BLE001 - ücretli sağlayıcı düşerse statik devam
                    _ilerleme_yaz(ilerleme, f"Sahne {sahne.order}: fal.ai başarısız ({hata}); statik devam.", oran)
                    statik_klip(gorsel, ses, duration, klip, motion, en_boy)
            else:
                _ilerleme_yaz(ilerleme, f"Sahne {sahne.order}: video oluşturuluyor...", oran)
                statik_klip(gorsel, ses, duration, klip, motion, en_boy)

        if not _gecerli_video(klip):
            raise ValueError(f"Sahne {sahne.order}: klip üretilemedi.")
        if not medya_suresi(klip):
            raise ValueError(f"Sahne {sahne.order}: klip süresi geçersiz.")
        for cue in yerel_cues:
            tum_cues.append({
                "start": float(cue["start"]) + kaydirma,
                "end": float(cue["end"]) + kaydirma,
                "text": cue["text"],
            })
        kaydirma += duration

    parcalar: list[str] = []
    if intro_outro:
        intro = os.path.join(proje_dizini, "klipler", "intro.mp4")
        outro = os.path.join(proje_dizini, "klipler", "outro.mp4")
        if not _gecerli_video(intro):
            _ilerleme_yaz(ilerleme, "Intro kartı hazırlanıyor...", 0.96)
            baslik_karti(
                seri.name,
                senaryo.episode.title,
                intro_sure,
                intro,
                en_boy,
                arka_plan=ilk_gorsel,
            )
        if not _gecerli_video(outro):
            baslik_karti(
                "Teşekkürler",
                f"{seri.name} · Abone olmayı unutmayın",
                intro_sure,
                outro,
                en_boy,
                arka_plan=ilk_gorsel,
            )
        parcalar.extend([intro, *klipler, outro])
    else:
        parcalar = list(klipler)

    _ilerleme_yaz(ilerleme, "Final video birleştiriliyor...", 0.98)
    final = os.path.join(proje_dizini, "final_video.mp4")
    ham_final = os.path.join(proje_dizini, "final_video_ham.mp4")
    birlestir(parcalar, ham_final)

    srt = os.path.join(proje_dizini, "final.srt")
    altyazi_ok = False
    if altyazi and tum_cues:
        srt_yaz(tum_cues, srt)
        altyazi_ok = altyazi_yak(ham_final, srt, final, en_boy)
    if not altyazi_ok:
        shutil.move(ham_final, final)
    elif os.path.exists(ham_final):
        os.remove(ham_final)

    _ilerleme_yaz(ilerleme, "Video hazır.", 1.0)
    return {
        "final": final,
        "klipler": klipler,
        "sahne_sayisi": toplam,
        "altyazi": altyazi_ok,
        "srt": srt if os.path.exists(srt) else "",
        "video_modu": video_modu,
    }
