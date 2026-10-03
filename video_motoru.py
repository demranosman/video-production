import os
from pathlib import Path
import subprocess
import json
import shutil
import base64
import time
import urllib.request
import requests
import io
from PIL import Image

# -------------------------------------------------------------
# AYARLAR
# -------------------------------------------------------------
RUNWAY_API_KEY = (
    os.environ.get("RUNWAY_API_KEY", "").strip()
    or os.environ.get("RUNWAYML_API_SECRET", "").strip()
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Runway üzerinde kullanılacak video modeli.
# Varsayılan: Google Veo 3.1 Fast + native audio
RUNWAY_VIDEO_MODEL = os.environ.get("RUNWAY_VIDEO_MODEL", "veo3.1_fast").strip()
RUNWAY_VIDEO_RATIO = os.environ.get("RUNWAY_VIDEO_RATIO", "1280:720").strip()
RUNWAY_MAX_WAIT = int(os.environ.get("RUNWAY_MAX_WAIT", "900"))

# "RESIM" veya "VIDEO" olarak seçin.
# RESIM: Gemini Flash image generation
# VIDEO: Runway üzerinden Veo 3.1 Fast + native audio ile hareketli video üretimi
URETIM_MODU = os.environ.get("URETIM_MODU", "VIDEO").upper()
# -------------------------------------------------------------

# GÖRSEL ÜRETİMİ — GEMINI 3 PRO IMAGE (Nano Banana Pro) + karakter referansları
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3-pro-image")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_ASPECT_RATIO = os.environ.get("GEMINI_ASPECT_RATIO", "16:9")
GEMINI_IMAGE_SIZE = os.environ.get("GEMINI_IMAGE_SIZE", "2K")
STYLE_PREFIX = (
    "Cinematic 3D animation style, children's fairy tale, soft warm lighting, "
    "vibrant colors, cute cartoon characters, 16:9 aspect ratio."
)


def _image_to_b64(image_path: str) -> str:
    """Görüntü dosyasını saf base64 dizesine çevirir (data URI prefix'siz)."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _extract_gemini_image(result: dict):
    """Interactions API yanıtından üretilen görüntüyü (base64) çıkarır."""
    interaction = result.get("interaction") or result
    out_img = interaction.get("output_image") or {}
    if out_img.get("data"):
        return out_img["data"], out_img.get("mime_type") or out_img.get("mimeType") or "image/jpeg"
    for step in interaction.get("steps", []):
        if not isinstance(step, dict):
            continue
        for part in step.get("content", []):
            if isinstance(part, dict) and part.get("type") == "image" and part.get("data"):
                return part["data"], part.get("mime_type") or part.get("mimeType") or "image/jpeg"
    return None, None


def _gemini_generate_image(prompt: str, reference_paths: list, output_path: str):
    """Gemini 3 Pro Image ile görsel üretir (referanslı = image-to-image)."""
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    input_parts = [{"type": "text", "text": prompt}]
    for ref_path in reference_paths:
        input_parts.append({"type": "image", "mime_type": "image/png", "data": _image_to_b64(ref_path)})
    body = {
        "model": GEMINI_IMAGE_MODEL,
        "input": input_parts,
        "response_format": {
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": GEMINI_ASPECT_RATIO,
            "image_size": GEMINI_IMAGE_SIZE,
        },
    }
    resp = requests.post(GEMINI_BASE_URL, headers=headers, json=body, timeout=300)
    if resp.status_code != 200:
        raise ValueError(f"Gemini görsel üretim hatası (HTTP {resp.status_code}): {resp.text[:500]}")
    result = resp.json()
    image_b64, _mime = _extract_gemini_image(result)
    if not image_b64:
        interaction = result.get("interaction") or result
        status = interaction.get("status", "bilinmiyor")
        error = result.get("error")
        raise ValueError(f"Gemini görüntü üretmedi (status={status}): {error or 'görüntü bloğu bulunamadı'}")
    # Gemini bu endpointte JPEG döndürür. Dosya içeriğini gerçek PNG olarak
    # kaydet; böylece sonraki image-reference çağrılarında .png uzantısı ile
    # gerçek MIME tipi birbiriyle uyumlu kalır.
    raw_image = base64.b64decode(image_b64)
    with Image.open(io.BytesIO(raw_image)) as img:
        img.convert("RGB").save(output_path, format="PNG")
    print(f"[+] Görsel kaydedildi: {output_path}")


def _character_ref_prompt(k: dict) -> str:
    """Karakter referans portresi için text-to-image promptu."""
    vid = k.get("visual_identity", {})
    tip = k.get("type", "")
    core = f"{k.get('name', '')} the {tip}" if tip else k.get("name", "")
    features = [vid[key] for key in ("fur_or_skin", "body", "face", "eyes", "distinctive_features") if vid.get(key)]
    clothing = k.get("default_clothing", "")
    natural_kw = ("kürk", "fur", "tüy", "feather", "doğal", "natural", "post", "pul")
    if clothing and not any(kw in clothing.lower() for kw in natural_kw):
        clothing_phrase = f"wearing {clothing}"
    elif clothing:
        clothing_phrase = f"with {clothing}"
    else:
        clothing_phrase = "with natural soft fluffy fur"
    return (
        f"{STYLE_PREFIX} Portrait of {core}, {clothing_phrase}, "
        f"{', '.join(features)}, facing camera, neutral plain studio background, "
        "soft even lighting, clear face and full anatomy, "
        "single character only, no other creatures blended in."
    )


def ensure_character_references(karakterler: dict, active_ids: set, seri_klasoru: str) -> dict:
    """Her aktif karakter için bir kez referans portre üretir (idempotent)."""
    referans_dir = os.path.join(seri_klasoru, "referanslar")
    os.makedirs(referans_dir, exist_ok=True)
    ref_paths = {}
    for cid, k in karakterler.items():
        if cid not in active_ids:
            continue
        ref_path = os.path.join(referans_dir, f"{cid}.png")
        ref_paths[cid] = ref_path
        if os.path.exists(ref_path) and os.path.getsize(ref_path) > 0:
            print(f"[REFERANS] '{cid}' zaten mevcut, atlanıyor...")
            continue
        print(f"[REFERANS] '{cid}' için referans portre üretiliyor...")
        _gemini_generate_image(_character_ref_prompt(k), [], ref_path)
    return ref_paths


def _scene_image(prompt: str, reference_paths: list, image_path: str):
    """Sahne görselini referanslarla üretir; kimlik görselden kilitlenir."""
    full = f"{STYLE_PREFIX} Scene: {prompt}"
    if reference_paths:
        note = " ".join(
            f"Character {i+1} must look exactly like reference image {i+1} (same face, body and clothing)."
            for i in range(len(reference_paths))
        )
        full += f" {note}"
    full += " No text, no writing, no letters, no words, no watermarks."
    _gemini_generate_image(full, reference_paths, image_path)


def _character_text(k: dict) -> str:
    """Karakteri düz yazı prompt cümlesine çevirir."""
    vid = k.get("visual_identity", {})
    tip = k.get("type", "")
    parts = [f"{k.get('name', '')} bir {tip.lower()}" if tip else k.get('name', '')]
    for key in ("fur_or_skin", "body", "face", "eyes", "distinctive_features"):
        if vid.get(key):
            parts.append(vid[key])
    text = ". ".join(parts) + "."
    if k.get("default_clothing"):
        text += f" {k['default_clothing']} giyer."
    return text


def _location_text(m: dict) -> str:
    """Mekânı düz yazı prompt cümlesine çevirir."""
    vid = m.get("visual_identity", {})
    parts = [f"Mekân: {m.get('name', '')}"]
    if vid.get("environment"):
        parts.append(vid["environment"])
    if vid.get("ground"):
        parts.append(vid["ground"])
    lm = vid.get("landmarks") or []
    if lm:
        parts.append(", ".join(lm) + " bulunur")
    if vid.get("default_lighting"):
        parts.append(vid["default_lighting"])
    if vid.get("atmosphere"):
        parts.append("atmosfer " + vid["atmosphere"])
    return ". ".join(parts) + "."



def _scene_duration(scene: dict, default: int = 5) -> int:
    """Veo 3.1 Fast için desteklenen 4/6/8 saniyeye normalize eder."""
    try:
        value = int(scene.get("duration", default))
    except (TypeError, ValueError):
        value = default
    # Veo 3.1 Fast için desteklenen seçenekler: 4, 6, 8 sn.
    # İçeriği erken kesmemek için istenen süreyi bir üst desteklenen değere yuvarlarız.
    for allowed in (4, 6, 8):
        if value <= allowed:
            return allowed
    return 8


def _motion_spec(scene: dict) -> dict:
    """Sahnenin hareketini yapılandırılmış alanlardan okur; eski formatı da destekler."""
    motion = scene.get("motion") or {}
    if isinstance(motion, str):
        motion = {"action": motion}

    return {
        "action": str(
            motion.get("action")
            or scene.get("motion_description")
            or scene.get("movement")
            or scene.get("action")
            or ""
        ).strip(),
        "camera": str(
            motion.get("camera")
            or scene.get("camera")
            or "subtle cinematic camera movement"
        ).strip(),
        "intensity": str(
            motion.get("intensity")
            or scene.get("motion_intensity")
            or "subtle"
        ).strip(),
        "preserve": str(
            motion.get("preserve")
            or "Keep character identity, clothing, proportions and environment consistent. "
               "No new characters, no morphing, no scene transformation, no text."
        ).strip(),
    }


def _dialogue_lines(scene: dict) -> list:
    """Sahnedeki tüm diyalogları Veo'nun native speech üretimine hazırlar."""
    lines = []
    dialogues = scene.get("dialogue") or []
    if isinstance(dialogues, dict):
        dialogues = [dialogues]

    for item in dialogues:
        if not isinstance(item, dict):
            continue
        text = str(item.get("line") or item.get("text") or "").strip()
        if not text:
            continue
        character = str(
            item.get("character_id")
            or item.get("character")
            or "narrator"
        ).strip()
        lines.append((character, text))

    fixed_text = str(scene.get("fixed_text") or "").strip()
    narration = str(scene.get("narration") or "").strip()

    if not lines and fixed_text:
        lines.append((str(scene.get("speaker") or "narrator"), fixed_text))
    if not lines and narration:
        lines.append(("narrator", narration))

    return lines


def _audio_spec(scene: dict) -> dict:
    """Sahne için Veo native audio talimatlarını toplar."""
    audio = scene.get("audio") or {}
    if isinstance(audio, str):
        audio = {"ambient": audio}

    return {
        "ambient": str(
            audio.get("ambient")
            or scene.get("ambient_sound")
            or scene.get("sfx")
            or "natural environment ambience"
        ).strip(),
        "sfx": str(audio.get("sfx") or scene.get("sound_effects") or "").strip(),
        "music": str(audio.get("music") or scene.get("music") or "").strip(),
    }


def _build_video_prompt(scene: dict) -> str:
    """Veo'ya hareket + kamera + konuşma + ortam sesi talimatlarını verir."""
    spec = _motion_spec(scene)
    audio = _audio_spec(scene)
    lines = _dialogue_lines(scene)

    parts = [
        "Animate the existing image; do not redesign the scene.",
        f"Primary action: {spec['action']}" if spec["action"] else "Natural subtle character movement.",
        f"Camera: {spec['camera']}.",
        f"Motion intensity: {spec['intensity']}.",
        "Use smooth, physically plausible movement.",
        spec["preserve"],
        "Generate synchronized native audio for this shot.",
        f"Ambient sound: {audio['ambient']}.",
    ]

    if audio["sfx"]:
        parts.append(f"Sound effects: {audio['sfx']}.")
    if audio["music"]:
        parts.append(f"Background music: {audio['music']}.")

    if lines:
        parts.append("Spoken dialogue/narration must be in Turkish and synchronized to the visible speaker.")
        for character, text in lines:
            parts.append(f'{character} says in Turkish: "{text}"')
    else:
        parts.append("Do not add dialogue or narration unless explicitly requested by the scene.")

    return " ".join(parts)


def _negative_prompt(scene: dict) -> str:
    """Veo negative promptunu sahne JSON'undan alır."""
    value = scene.get("negative_prompt") or scene.get("negativePrompt")
    if value:
        return str(value).strip()[:1000]
    return (
        "character morphing, identity change, clothing change, extra characters, "
        "duplicate limbs, deformed hands, distorted faces, scene transformation, "
        "text, subtitles, captions, logos, watermark"
    )


def _render_static_motion(image_path: str, output_path: str, duration: int, zoom_out: bool = False):
    """AI video yerine düşük maliyetli FFmpeg kamera hareketi."""
    if zoom_out:
        z = "max(1,1.12-0.12*on/(max(1,FRAME_RATE*DURATION)))"
    else:
        z = "min(1.12,1+0.12*on/(max(1,FRAME_RATE*DURATION)))"

    vf = (
        "scale=1920:1080:force_original_aspect_ratio=increase,"
        "crop=1920:1080,"
        f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={duration*30}:s=1280x720:fps=30,"
        "format=yuv420p"
    )

    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", image_path,
        "-t", str(duration), "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", output_path
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def generate_audio(text: str, character: str, output_path: str):
    """Uyumluluk katmanı: sahne sesleri artık Veo 3.1 native audio ile üretiliyor."""
    raise RuntimeError(
        "Ayrı Google Cloud TTS devre dışı. Sahne sesi Veo 3.1 native audio ile üretilir."
    )


def merge_media(video_path: str, audio_path: str, output_path: str):
    """Uyumluluk katmanı: Veo videosu sesi zaten içerir; harici TTS birleştirilmez."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)
    shutil.copyfile(video_path, output_path)
    print(f"[+] Native audio zaten videoda: {output_path}")


def generate_image_and_convert_to_video(
    prompt: str, output_path: str, sahne_id_name: str,
    reference_paths: list = None, duration: int = 5, scene: dict = None
):
    """Gemini sahne görseli + FFmpeg kontrollü hafif hareket."""
    scene = scene or {}
    duration = _scene_duration(scene, duration)

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ortam değişkeni ayarlanmamış.")

    image_path = output_path.replace(".mp4", "_sahne.png")
    print(f"[1/2] {sahne_id_name}: Gemini sahne görseli")
    _scene_image(prompt, reference_paths or [], image_path)

    camera = _motion_spec(scene)["camera"].lower()
    zoom_out = "zoom out" in camera or "zoom-out" in camera or "uzaklaş" in camera

    print(f"[2/2] {sahne_id_name}: FFmpeg motion ({duration}s)")
    _render_static_motion(image_path, output_path, duration, zoom_out)
    print(f"[+] {sahne_id_name}: video hazır")


def generate_video(
    prompt: str, output_path: str, sahne_id_name: str = "Video",
    reference_paths: list = None, duration: int = 8, scene: dict = None
):
    """Gemini/Nano Banana Pro görseli + Runway Veo 3.1 Fast image-to-video.

    Veo native audio üretir; bu nedenle ayrı Google Cloud TTS kullanılmaz.
    """
    scene = scene or {}
    duration = _scene_duration(scene, duration)

    if not RUNWAY_API_KEY:
        raise RuntimeError("RUNWAY_API_KEY veya RUNWAYML_API_SECRET ortam değişkeni ayarlanmamış.")
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ortam değişkeni ayarlanmamış.")

    image_path = output_path.replace(".mp4", "_sahne.png")

    print(f"[1/2] {sahne_id_name}: Gemini sahne görseli")
    _scene_image(prompt, reference_paths or [], image_path)

    # Runway SDK bağlantısı.
    # Güncel Runway SDK'da yerel dosya için doğru yöntem:
    # client.uploads.create_ephemeral(file=Path(...))
    try:
        from runwayml import RunwayML
    except ImportError as exc:
        raise RuntimeError(
            "Runway SDK bulunamadı. Windows terminalinde şu komutu çalıştırın: "
            "python -m pip install -U runwayml"
        ) from exc

    runway_client = RunwayML(api_key=RUNWAY_API_KEY)

    # Data-URI yerine Runway ephemeral upload kullanıyoruz.
    # Böylece görselin 5 MB data-URI sınırına takılma riski ortadan kalkar.
    # Runway dokümantasyonuna göre ephemeral URI 24 saat geçerlidir.
    try:
        upload = runway_client.uploads.create_ephemeral(file=Path(image_path))
    except AttributeError as exc:
        raise RuntimeError(
            "Kurulu runwayml SDK sürümü eski ve create_ephemeral desteklemiyor. "
            "Şunu çalıştırın: python -m pip install -U runwayml"
        ) from exc

    image_uri = upload.uri
    if not image_uri:
        raise RuntimeError("Runway görsel yüklemesi başarılı görünmesine rağmen URI dönmedi.")

    video_prompt = _build_video_prompt(scene)
    negative_prompt = _negative_prompt(scene)

    print(f"[2/2] {sahne_id_name}: Runway {RUNWAY_VIDEO_MODEL} + native audio ({duration}s)")
    print(f"      {video_prompt}")

    request = {
        "model": RUNWAY_VIDEO_MODEL,
        "prompt_image": image_uri,
        "prompt_text": video_prompt,
        "ratio": RUNWAY_VIDEO_RATIO,
        "duration": duration,
        "audio": True,
    }

    # Veo 3.1 / 3.1 Fast Runway API'sinde negativePrompt destekleniyor.
    if negative_prompt:
        request["negative_prompt"] = negative_prompt

    # Runway Python SDK, REST API'deki camelCase alanları snake_case olarak bekler:
    # promptImage -> prompt_image, promptText -> prompt_text, negativePrompt -> negative_prompt.
    try:
        task = runway_client.image_to_video.create(**request)
    except Exception as exc:
        # SDK'nin döndürdüğü HTTP hata gövdesini kaybetmeden kullanıcıya aktar.
        detail = getattr(exc, "body", None) or getattr(exc, "response", None) or str(exc)
        raise RuntimeError(f"Runway image-to-video isteği başarısız: {detail}") from exc

    print(f"      [RUNWAY] Görev oluşturuldu: {task.id}")

    start_time = time.time()
    while True:
        task_status = runway_client.tasks.retrieve(task.id)
        status = getattr(task_status, "status", "")

        if status == "SUCCEEDED":
            outputs = getattr(task_status, "output", None) or []
            if not outputs:
                raise RuntimeError("Runway görevi başarılı görünüyor ancak video çıktısı bulunamadı.")
            urllib.request.urlretrieve(outputs[0], output_path)
            print(f"[+] Video + native audio kaydedildi: {output_path}")
            return

        if status in ["FAILED", "CANCELLED", "CANCELED"]:
            failure = getattr(task_status, "failure", "") or getattr(task_status, "failure_code", "")
            raise RuntimeError(f"Runway görevi başarısız: {status} - {failure}")

        if time.time() - start_time > RUNWAY_MAX_WAIT:
            raise TimeoutError(f"Video {RUNWAY_MAX_WAIT} saniye içinde tamamlanamadı.")

        time.sleep(10)


def concat_videos(video_list, output_path):
    """Tüm sahneleri tek bir videoda uç uca ekler (Windows path uyumlu)."""
    list_file = "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for video in video_list:
            safe_path = os.path.abspath(video).replace("\\", "/")
            f.write(f"file '{safe_path}'\n")
            
    command = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", output_path
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[+] Tüm sahneler başarıyla birleştirildi: {output_path}")
    except subprocess.CalledProcessError:
        # Stream copy birleştiremezse re-encode concat uygula
        fallback_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", output_path
        ]
        try:
            subprocess.run(fallback_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[+] Tüm sahneler yeniden kodlanarak birleştirildi: {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"[-] FFmpeg concat hatası: {e}")
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)


def run_pipeline(senaryo_path: str = None):
    """Senaryoyu okur ve tüm video üretim pipeline'ını çalıştırır."""
    if not senaryo_path:
        senaryo_path = os.path.join(
            "seriler", "pamuk_tiltu_ve_kiko_orman_dostlari", "bolumler",
            "001_pamuk_un_kaybolan_havuclari", "senaryo.json"
        )
        print(f"[!] Belirli bir senaryo belirtilmedi. Varsayılan senaryo işleniyor: {senaryo_path}")
    
    if not os.path.exists(senaryo_path):
        print(f"[-] Senaryo dosyası bulunamadı: {senaryo_path}")
        return False
        
    bolum_klasoru = os.path.dirname(senaryo_path) or "."
    seri_klasoru = os.path.dirname(os.path.dirname(bolum_klasoru))
    
    # Karakterler ve Mekanları yükle
    karakterler = {}
    karakterler_path = os.path.join(seri_klasoru, "karakterler.json")
    if os.path.exists(karakterler_path):
        with open(karakterler_path, "r", encoding="utf-8") as f:
            for k in json.load(f).get("characters", []):
                karakterler[k["character_id"]] = k

    mekanlar = {}
    mekanlar_path = os.path.join(seri_klasoru, "mekanlar.json")
    if os.path.exists(mekanlar_path):
        with open(mekanlar_path, "r", encoding="utf-8") as f:
            for m in json.load(f).get("locations", []):
                mekanlar[m["location_id"]] = m

    with open(senaryo_path, "r", encoding="utf-8") as f:
        scenes = json.load(f).get("scenes", [])
    
    intro_path = os.path.join(seri_klasoru, "intro", "intro.json")
    outro_path = os.path.join(seri_klasoru, "outro", "outro.json")

    active_ids = set()
    for scene in scenes:
        active_ids.update(scene.get("character_ids", []))
    for p in (intro_path, outro_path):
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                active_ids.update(json.load(f).get("character_ids", []))
    ref_paths = ensure_character_references(karakterler, active_ids, seri_klasoru)

    def process_scene_data(scene, sahne_id_name):
        print(f"\n--- {sahne_id_name.upper()} İşleniyor ---")
        raw_video = os.path.join(bolum_klasoru, f"temp_{sahne_id_name}.mp4")

        # ---------------------------------------------------------
        # 1) GÖRSEL PROMPTU
        # Karakter/mekan/sahne bilgisi burada kalır.
        # ---------------------------------------------------------
        prompt_parts = [scene.get("visual_description", "")]

        loc_id = scene.get("location_id")
        if loc_id and loc_id in mekanlar:
            prompt_parts.append(_location_text(mekanlar[loc_id]))

        for cid in scene.get("character_ids", []):
            if cid in karakterler:
                prompt_parts.append(_character_text(karakterler[cid]))

        prompt = " ".join(p for p in prompt_parts if p)

        refs = [
            ref_paths[cid]
            for cid in scene.get("character_ids", [])
            if cid in ref_paths and os.path.exists(ref_paths[cid])
        ]

        # ---------------------------------------------------------
        # 2) VIDEO ROUTER
        # ai_video      = Gemini/Nano Banana Pro + Runway Veo 3.1 Fast
        # static_motion = Gemini + FFmpeg (sessiz fallback)
        # image_only    = Gemini + FFmpeg (sessiz fallback)
        # ---------------------------------------------------------
        duration = _scene_duration(scene, 8)
        motion_mode = (
            scene.get("motion_mode")
            or scene.get("generation_mode")
            or ("image_only" if URETIM_MODU == "RESIM_ONLY" else "ai_video")
        )

        print(
            f"[ROUTER] {sahne_id_name}: mode={motion_mode}, "
            f"duration={duration}s, model={RUNWAY_VIDEO_MODEL}, "
            f"native_audio={'yes' if motion_mode == 'ai_video' else 'no'}, "
            f"characters={scene.get('character_ids', [])}"
        )

        if motion_mode == "static_motion":
            generate_image_and_convert_to_video(
                prompt, raw_video, sahne_id_name.upper(), refs,
                duration=duration, scene=scene
            )
        elif motion_mode == "image_only":
            image_path = raw_video.replace(".mp4", "_sahne.png")
            _scene_image(prompt, refs, image_path)
            _render_static_motion(image_path, raw_video, duration)
        else:
            generate_video(
                prompt, raw_video, sahne_id_name.upper(), refs,
                duration=duration, scene=scene
            )

        if os.path.exists(raw_video):
            return raw_video
        return None

    final_scenes = []
    
    if os.path.exists(intro_path):
        with open(intro_path, "r", encoding="utf-8") as f:
            if vid := process_scene_data(json.load(f), "intro"):
                final_scenes.append(vid)
            
    for i, scene in enumerate(scenes):
        if vid := process_scene_data(scene, f"sahne{scene.get('order', i+1)}"):
            final_scenes.append(vid)
        
    if os.path.exists(outro_path):
        with open(outro_path, "r", encoding="utf-8") as f:
            if vid := process_scene_data(json.load(f), "outro"):
                final_scenes.append(vid)

    if final_scenes:
        print("\n--- Tüm Sahneler Birleştiriliyor ---")
        final_output_path = os.path.join(bolum_klasoru, "final_video.mp4")
        concat_videos(final_scenes, final_output_path)
        print(f"\n[+] İşlem tamamlandı! Sonuç dosyası: {final_output_path}")
        return True
    return False


if __name__ == "__main__":
    import sys
    sen_path = sys.argv[1] if len(sys.argv) > 1 else None
    run_pipeline(sen_path)
