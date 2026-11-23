"""Tek akışlı stüdyo: fikir/hikâye → senaryo → görsel + ses + video.

Çalıştırma:
    streamlit run app.py

Gelişmiş (seri/bölüm bazlı) arayüz için eski `senaryo_studyo.py` korunmuştur.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

import formatlar
import medya_motoru
import senaryo_modelleri as modeller
import senaryo_motoru as motor
import seri_deposu as depo

load_dotenv()

st.set_page_config(page_title="Senaryo & Video Stüdyosu", page_icon="🎬", layout="wide")

# Proje değişiminde/üretim sonrasında metin alanlarını widget oluşmadan güncelle.
for _anahtar in ("kaynak_metni", "hikaye_metni", "logline_metni"):
    _bekleyen = f"{_anahtar}_bekleyen"
    if _bekleyen in st.session_state:
        st.session_state[_anahtar] = st.session_state.pop(_bekleyen)

BOLUM_NO = 1
BOLUM_SLUG = "video"

TARZLAR = [
    "Sinematik 3D animasyon, yumuşak ışık, canlı renkler",
    "Fotorealistik sinematik film karesi, doğal ışık",
    "Koyu tonlu çizgi roman, dramatik gölgeler",
    "Klasik yağlı boya tablo, belirgin fırça darbeleri",
    "El çizimi anime estetiği, ayrıntılı arka planlar",
    "Minimalist vektör illüstrasyon, düz renkler",
]
OZEL_TARZ = "Özel tarz (kendin yaz)"
KAMERA_HAREKETLERI = ["zoom in", "zoom out", "pan left", "pan right", "none"]


def _anahtar_var(*adlar: str) -> bool:
    return any(os.environ.get(ad, "").strip() for ad in adlar)


def _proje_dizini(series_id: str) -> str:
    return str(depo.seri_kok(series_id))


def _final_yolu(series_id: str) -> str:
    return os.path.join(_proje_dizini(series_id), "final_video.mp4")


def _durum_yolu(series_id: str) -> str:
    return os.path.join(_proje_dizini(series_id), "uretim_durum.json")


def _durum_oku(series_id: str) -> dict:
    yol = _durum_yolu(series_id)
    if not os.path.exists(yol):
        return {}
    try:
        with open(yol, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


def _durum_yaz(series_id: str, **alanlar) -> None:
    yol = _durum_yolu(series_id)
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    gecici = yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as file:
        json.dump(
            {"guncellendi": datetime.now().astimezone().isoformat(timespec="seconds"), **alanlar},
            file, ensure_ascii=False, indent=2,
        )
    os.replace(gecici, yol)


def _senaryo_yukle(series_id: str) -> modeller.Senaryo | None:
    yol = depo.senaryo_yolu(series_id, BOLUM_NO, BOLUM_SLUG)
    if not yol.exists():
        return None
    try:
        return depo.senaryo_yukle(series_id, BOLUM_NO, BOLUM_SLUG)
    except Exception:  # noqa: BLE001 - bozuk kayıt uygulamayı kilitlemesin
        return None


def _projeyi_yukle(series_id: str) -> None:
    st.session_state.series_id = series_id
    st.session_state.hikaye = ""
    st.session_state.senaryo = None
    st.session_state.logline = ""
    st.session_state.girdi_turu = "Hazır hikâye"
    st.session_state.kaynak_metni = ""
    st.session_state.hikaye_metni = ""
    st.session_state.logline_metni = ""

    hikaye_yolu = depo.hikaye_yolu(series_id, BOLUM_NO, BOLUM_SLUG)
    if hikaye_yolu.exists():
        st.session_state.hikaye = hikaye_yolu.read_text(encoding="utf-8")
    st.session_state.kaynak_metni = st.session_state.hikaye
    st.session_state.hikaye_metni = st.session_state.hikaye
    senaryo = _senaryo_yukle(series_id)
    if senaryo:
        st.session_state.senaryo = senaryo.model_dump()
        st.session_state.logline = senaryo.episode.summary
        st.session_state.logline_metni = senaryo.episode.summary


def _kataloglari_guncelle(series_id: str, cikarilan: dict) -> tuple[modeller.KarakterKatalogu, modeller.MekanKatalogu]:
    """Çıkarılan yeni varlıkları kataloglara ekler; mevcutları yeniden üretmez."""
    karakter_katalogu = depo.karakterleri_yukle(series_id)
    mevcut_k = {k.character_id for k in karakter_katalogu.characters}
    for ham in cikarilan.get("characters", []):
        if not str(ham.get("name", "")).strip():
            continue
        if motor.karakter_esle(str(ham["name"]), karakter_katalogu.characters):
            continue
        yeni = motor.adaydan_karakter(ham, series_id, BOLUM_NO)
        taban, i = yeni.character_id, 2
        while yeni.character_id in mevcut_k:
            yeni = yeni.model_copy(update={"character_id": f"{taban}_{i}"})
            i += 1
        karakter_katalogu.characters.append(yeni)
        mevcut_k.add(yeni.character_id)
    depo.karakterleri_kaydet(karakter_katalogu)

    mekan_katalogu = depo.mekanlari_yukle(series_id)
    mevcut_m = {m.location_id for m in mekan_katalogu.locations}
    for ham in cikarilan.get("locations", []):
        if not str(ham.get("name", "")).strip():
            continue
        if motor.mekan_esle(str(ham["name"]), mekan_katalogu.locations):
            continue
        yeni_mekan = motor.adaydan_mekan(ham, series_id, BOLUM_NO)
        taban, i = yeni_mekan.location_id, 2
        while yeni_mekan.location_id in mevcut_m:
            yeni_mekan = yeni_mekan.model_copy(update={"location_id": f"{taban}_{i}"})
            i += 1
        mekan_katalogu.locations.append(yeni_mekan)
        mevcut_m.add(yeni_mekan.location_id)
    if not mekan_katalogu.locations:
        mekan_katalogu.locations.append(
            modeller.Mekan(
                location_id="genel_mekan",
                name="Genel mekân",
                visual_identity={"description": "Sahnenin atmosferine uygun genel mekân"},
            )
        )
    depo.mekanlari_kaydet(mekan_katalogu)
    return karakter_katalogu, mekan_katalogu


def _senaryoyu_kaydet(series_id: str, senaryo: modeller.Senaryo, hikaye: str) -> None:
    karakter_katalogu = depo.karakterleri_yukle(series_id)
    mekan_katalogu = depo.mekanlari_yukle(series_id)
    depo.senaryo_kaydet(senaryo, karakter_katalogu, mekan_katalogu, BOLUM_SLUG)
    depo.hikaye_kaydet(series_id, BOLUM_NO, BOLUM_SLUG, hikaye)


# ---------------------------------------------------------------
# Kenar çubuğu
# ---------------------------------------------------------------
with st.sidebar:
    st.header("Proje")

    projeler = depo.serileri_listele()
    if projeler:
        isimler = {}
        for pid in projeler:
            try:
                isimler[pid] = depo.seri_yukle(pid).name
            except Exception:  # noqa: BLE001
                isimler[pid] = pid
        secili = st.selectbox(
            "Mevcut projeler",
            projeler,
            format_func=lambda pid: isimler.get(pid, pid),
            index=projeler.index(st.session_state.series_id) if st.session_state.get("series_id") in projeler else 0,
        )
        if st.button("Projeyi aç", icon=":material/folder_open:", width="stretch"):
            _projeyi_yukle(secili)
            st.rerun()

    st.divider()
    st.subheader("Yeni proje")
    with st.form("yeni_proje"):
        ad = st.text_input("Proje adı")
        tur = st.selectbox(
            "İçerik türü", list(formatlar.TURLER),
            format_func=lambda k: formatlar.TURLER[k]["ad"],
        )
        fmt = st.selectbox(
            "Format", list(formatlar.FORMATLAR),
            format_func=lambda k: formatlar.FORMATLAR[k]["ad"],
            index=1,
        )
        stil_secim = st.selectbox("Görsel tarz", [*TARZLAR, OZEL_TARZ])
        stil = (
            st.text_input("Özel tarz açıklaması")
            if stil_secim == OZEL_TARZ
            else stil_secim
        )
        kitle = st.text_input("Hedef kitle", placeholder="örn. 5-7 yaş / genel izleyici")
        olustur = st.form_submit_button("Projeyi oluştur", type="primary", icon=":material/add:")

    if olustur:
        try:
            ayar = formatlar.format_ayari(fmt)
            seri = depo.seri_olustur(
                ad,
                description="",
                target_audience=kitle,
                visual_style=stil,
                default_aspect_ratio=ayar["en_boy"],
                genre=tur,
                format=fmt,
                target_duration_sec=ayar["sure_sn"][0],
            )
            _projeyi_yukle(seri.series_id)
            st.rerun()
        except Exception as hata:  # noqa: BLE001
            st.error(f"Proje oluşturulamadı: {hata}")

    st.divider()
    st.caption("API durumu")
    st.write(("✅" if _anahtar_var("MISTRAL_API_KEY") else "❌") + " Mistral (senaryo)")
    st.write(("✅" if _anahtar_var("ANTHROPIC_API_KEY") else "❌") + " Claude (yedek senaryo)")
    st.write(("✅" if _anahtar_var("GEMINI_API_KEY", "GOOGLE_API_KEY") else "❌") + " Gemini (görsel/Veo)")
    st.write(("✅" if _anahtar_var("RUNWAY_API_KEY", "RUNWAYML_API_SECRET") else "❌") + " Runway (video)")
    st.write(("✅" if _anahtar_var("ELEVENLABS_API_KEY") else "❌") + " ElevenLabs (ekonomik ses)")
    st.write(("✅" if _anahtar_var("FAL_API_KEY") else "❌") + " fal.ai (ekonomik hareket)")
    try:
        st.caption(f"Senaryo sağlayıcısı: **{motor.llm_saglayici()}**")
    except ValueError:
        st.caption("Senaryo sağlayıcısı: anahtar yok")
    st.caption("Anahtarlar `.env` dosyasından okunur; sağlayıcı `LLM_PROVIDER` ile seçilir.")


# ---------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------
if not st.session_state.get("series_id"):
    st.title("🎬 Senaryo & Video Stüdyosu")
    st.info("Başlamak için soldan yeni bir proje oluşturun veya mevcut bir projeyi açın.")
    st.stop()

series_id = st.session_state.series_id
seri = depo.seri_yukle(series_id)
format_ayari = formatlar.format_ayari(seri.format)
tur_ayari = formatlar.tur_ayari(seri.genre) if seri.genre in formatlar.TURLER else formatlar.tur_ayari("genel")

st.title(f"🎬 {seri.name}")
st.caption(
    f"{tur_ayari['ad']} · {format_ayari['ad']} · {seri.default_aspect_ratio} · "
    f"hedef ~{seri.target_duration_sec} sn"
)

senaryo_tab, uretim_tab, video_tab = st.tabs(["1 · Senaryo", "2 · Üretim", "3 · Video"])


# ===============================================================
# 1) Senaryo
# ===============================================================
with senaryo_tab:
    st.subheader("Kaynak")
    st.session_state.setdefault("girdi_turu", "Hazır hikâye")
    girdi_turu = st.radio(
        "Girdi türü",
        ["Fikir", "Hazır hikâye"],
        horizontal=True,
        key="girdi_turu",
        help="Fikir seçilirse model önce hikâyeyi yazar; hazır hikâyede metin doğrudan sahnelenir.",
    )
    kaynak = st.text_area(
        "Fikir veya hikâye metni",
        height=220,
        key="kaynak_metni",
        placeholder="Tek cümlelik bir fikir ya da tam hikâye yazın.",
    )

    if st.button("Senaryoyu oluştur", type="primary", icon=":material/auto_awesome:"):
        try:
            if not kaynak.strip():
                raise ValueError("Fikir veya hikâye metni boş olamaz.")
            with st.status("Senaryo hazırlanıyor...", expanded=True) as durum:
                hikaye = kaynak.strip()
                baslik = seri.name
                logline = ""
                if girdi_turu == "Fikir":
                    st.write("Fikir hikâyeye genişletiliyor...")
                    genisletilmis = motor.fikir_genislet(
                        hikaye, seri.genre, seri.format, seri.visual_style, seri.target_audience
                    )
                    hikaye = genisletilmis["story"]
                    baslik = genisletilmis["title"]
                    logline = genisletilmis["logline"]

                st.write("Karakter ve mekânlar çıkarılıyor...")
                cikarilan = motor.varlik_cikar(hikaye, seri.genre)
                karakter_katalogu, mekan_katalogu = _kataloglari_guncelle(series_id, cikarilan)

                st.write("Sahneler üretiliyor...")
                episode = modeller.Episode(
                    episode_no=BOLUM_NO,
                    title=baslik,
                    summary=logline,
                )
                senaryo = motor.sahne_uret(
                    hikaye, seri,
                    karakter_katalogu.characters,
                    mekan_katalogu.locations,
                    episode,
                )
                _senaryoyu_kaydet(series_id, senaryo, hikaye)
                st.session_state.hikaye = hikaye
                st.session_state.senaryo = senaryo.model_dump()
                st.session_state.logline = logline
                st.session_state.kaynak_metni_bekleyen = hikaye
                st.session_state.hikaye_metni_bekleyen = hikaye
                st.session_state.logline_metni_bekleyen = logline
                durum.update(label="Senaryo hazır.", state="complete")
            st.rerun()
        except Exception as hata:  # noqa: BLE001
            st.error(f"Senaryo oluşturulamadı: {hata}")

    if st.session_state.get("senaryo"):
        st.divider()
        senaryo = modeller.Senaryo.model_validate(st.session_state.senaryo)

        st.subheader("Hikâye ve künye")
        hikaye = st.text_area("Hikâye", height=180, key="hikaye_metni")
        logline = st.text_input("Logline / özet", key="logline_metni")
        if st.button("Hikâyeyi kaydet", icon=":material/save:"):
            depo.hikaye_kaydet(series_id, BOLUM_NO, BOLUM_SLUG, hikaye)
            st.session_state.hikaye = hikaye
            senaryo = senaryo.model_copy(update={"episode": senaryo.episode.model_copy(update={"summary": logline})})
            _senaryoyu_kaydet(series_id, senaryo, hikaye)
            st.session_state.senaryo = senaryo.model_dump()
            st.session_state.hikaye_metni_bekleyen = hikaye
            st.session_state.logline_metni_bekleyen = logline
            st.success("Kaydedildi.")

        st.subheader(f"Sahneler ({len(senaryo.scenes)})")
        tahmini = sum(s.estimated_duration_sec for s in senaryo.scenes)
        st.caption(f"Tahmini süre: ~{tahmini} sn · hedef ~{seri.target_duration_sec} sn")

        for i, sahne in enumerate(senaryo.scenes):
            baslik = f"{sahne.order:02d} · {sahne.title or sahne.story_event[:60] or 'Sahne'}"
            with st.expander(baslik):
                sahne.title = st.text_input("Başlık", sahne.title, key=f"t_{series_id}_{i}")
                sahne.narration = st.text_area(
                    "Anlatım (seslendirilecek metin)", sahne.narration, height=120, key=f"n_{series_id}_{i}"
                )
                sahne.visual_description = st.text_area(
                    "Görsel açıklama", sahne.visual_description, height=100, key=f"v_{series_id}_{i}"
                )
                sahne.image_prompt = st.text_area(
                    "Görsel komut (İngilizce, opsiyonel)", sahne.image_prompt, height=80, key=f"p_{series_id}_{i}"
                )
                sahne.motion = st.selectbox(
                    "Kamera hareketi",
                    KAMERA_HAREKETLERI,
                    index=KAMERA_HAREKETLERI.index(sahne.motion) if sahne.motion in KAMERA_HAREKETLERI else 0,
                    key=f"m_{series_id}_{i}",
                )
                sahne.estimated_duration_sec = int(st.number_input(
                    "Süre (sn)", min_value=2, max_value=60,
                    value=max(2, sahne.estimated_duration_sec), key=f"d_{series_id}_{i}",
                ))

                st.markdown("**Gerçek medya (opsiyonel)**")
                st.caption("Fotoğraf/video eklerseniz bu sahnede Gemini görseli üretilmez; kolaj kullanılır.")
                medya_dizini = os.path.join(_proje_dizini(series_id), "medya")
                os.makedirs(medya_dizini, exist_ok=True)
                for j, oge in enumerate(list(sahne.media)):
                    st.caption(f"• {oge.get('path', oge)}")
                    if st.button("Kaldır", key=f"medya_kaldir_{series_id}_{i}_{j}"):
                        sahne.media.pop(j)
                        _senaryoyu_kaydet(
                            series_id,
                            modeller.Senaryo.model_validate(senaryo.model_dump()),
                            st.session_state.get("hikaye", ""),
                        )
                        st.session_state.senaryo = senaryo.model_dump()
                        st.rerun()
                yeni_medya = st.file_uploader(
                    "Fotoğraf/video ekle",
                    type=["jpg", "jpeg", "png", "webp", "mp4", "mov"],
                    accept_multiple_files=True,
                    key=f"medya_yukle_{series_id}_{i}",
                )
                if yeni_medya:
                    for dosya in yeni_medya:
                        uzanti = os.path.splitext(dosya.name)[1].lower()
                        guvenli = depo.slugify(os.path.splitext(dosya.name)[0])
                        hedef_ad = f"s{sahne.order:03d}_{guvenli}{uzanti}"
                        with open(os.path.join(medya_dizini, hedef_ad), "wb") as file:
                            file.write(dosya.getbuffer())
                        tur = "image" if (dosya.type or "").startswith("image") else "video"
                        sahne.media.append({"path": f"medya/{hedef_ad}", "type": tur})
                    _senaryoyu_kaydet(
                        series_id,
                        modeller.Senaryo.model_validate(senaryo.model_dump()),
                        st.session_state.get("hikaye", ""),
                    )
                    st.session_state.senaryo = senaryo.model_dump()
                    st.rerun()

        if st.button("Sahne değişikliklerini kaydet", type="primary", icon=":material/save:"):
            try:
                guncel = modeller.Senaryo.model_validate(senaryo.model_dump())
                _senaryoyu_kaydet(series_id, guncel, st.session_state.get("hikaye", ""))
                st.session_state.senaryo = guncel.model_dump()
                st.success("Senaryo kaydedildi.")
            except Exception as hata:  # noqa: BLE001
                st.error(f"Kaydedilemedi: {hata}")

        with st.expander("Karakterler ve mekânlar (JSON)"):
            k_katalog = depo.karakterleri_yukle(series_id)
            m_katalog = depo.mekanlari_yukle(series_id)
            k_json = st.text_area(
                "Karakterler", json.dumps(k_katalog.model_dump(), ensure_ascii=False, indent=2), height=260
            )
            m_json = st.text_area(
                "Mekânlar", json.dumps(m_katalog.model_dump(), ensure_ascii=False, indent=2), height=220
            )
            if st.button("Katalogları kaydet", icon=":material/save:"):
                try:
                    depo.karakterleri_kaydet(modeller.KarakterKatalogu.model_validate(json.loads(k_json)))
                    depo.mekanlari_kaydet(modeller.MekanKatalogu.model_validate(json.loads(m_json)))
                    st.success("Kataloglar kaydedildi.")
                except Exception as hata:  # noqa: BLE001
                    st.error(f"Kaydedilemedi: {hata}")


# ===============================================================
# 2) Üretim
# ===============================================================
with uretim_tab:
    if not st.session_state.get("senaryo"):
        st.info("Önce 1. sekmede senaryoyu oluşturun.")
    else:
        senaryo = modeller.Senaryo.model_validate(st.session_state.senaryo)
        st.subheader("Üretim ayarları")

        modlar = list(medya_motoru.VIDEO_MODLARI)
        c1, c2 = st.columns(2)
        with c1:
            video_modu = st.selectbox(
                "Video modu",
                modlar,
                index=modlar.index("openmontage"),
                format_func=lambda k: medya_motoru.VIDEO_MODLARI[k],
            )
        with c2:
            intro_outro = st.checkbox("Intro/outro kartı", value=True)
            altyazi = st.checkbox("Altyazı (SRT yak)", value=True)

        native = video_modu == "openmontage"
        dil, cinsiyet = "tr", "kadin"
        if native:
            ses_kaynagi = st.radio(
                "Ses kaynağı",
                ["native", "elevenlabs"],
                horizontal=True,
                format_func=lambda k: "Veo/Runway native audio" if k == "native" else "ElevenLabs anlatım",
                help="Native: sahne başına 4-8 sn, kısa videolar için. ElevenLabs: uzun metraj ve kontrollü anlatım.",
            )
            seslendirme = ses_kaynagi == "elevenlabs"
            if seslendirme:
                dil = st.selectbox("Dil", ["tr", "en"], format_func=lambda k: "Türkçe" if k == "tr" else "English")
                cinsiyet = st.selectbox("Ses", ["kadin", "erkek"], format_func=lambda k: "Kadın" if k == "kadin" else "Erkek")
            else:
                st.info("Native audio: sahneler 4-8 sn. Uzun metraj için ElevenLabs seçin.")
        else:
            seslendirme = st.checkbox("Seslendirme (ElevenLabs)", value=True)
            dil = st.selectbox("Dil", ["tr", "en"], format_func=lambda k: "Türkçe" if k == "tr" else "English")
            cinsiyet = st.selectbox("Ses", ["kadin", "erkek"], format_func=lambda k: "Kadın" if k == "kadin" else "Erkek")

        cagri = medya_motoru.tahmini_cagri_sayilari(senaryo, video_modu, seslendirme)
        st.caption(
            f"Tahmini çağrı: {cagri['referans_gorsel']} referans portre + "
            f"{cagri['sahne_gorsel']} sahne görseli"
            + (f" + {cagri['tts']} ElevenLabs" if cagri["tts"] else "")
            + (f" + {cagri['fal_klip']} fal.ai klip" if cagri["fal_klip"] else "")
            + (f" + {cagri['openmontage']} Runway/Veo klip" if cagri["openmontage"] else "")
        )

        eksik: list[str] = []
        if not _anahtar_var("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            eksik.append("GEMINI_API_KEY (görseller)")
        if seslendirme and not _anahtar_var("ELEVENLABS_API_KEY"):
            eksik.append("ELEVENLABS_API_KEY (seslendirme)")
        if video_modu == "hareketli" and not _anahtar_var("FAL_API_KEY"):
            st.warning("FAL_API_KEY yok; hareketli modda statik videoya düşülecek.")
        if native:
            try:
                from video_provider_router import _openmontage_yolu

                st.caption(f"OpenMontage: `{_openmontage_yolu()}`")
            except Exception as hata:  # noqa: BLE001
                eksik.append(f"OpenMontage ({hata})")
            if not _anahtar_var(
                "RUNWAY_API_KEY", "RUNWAYML_API_SECRET", "GEMINI_API_KEY",
                "GOOGLE_API_KEY", "OPENAI_API_KEY", "FAL_KEY", "FAL_AI_API_KEY",
            ):
                eksik.append("Runway/Veo sağlayıcı anahtarı")
        if eksik:
            st.error("Eksik: " + ", ".join(eksik))

        mevcut_klipler = [
            s.order for s in senaryo.scenes
            if os.path.exists(os.path.join(_proje_dizini(series_id), "klipler", f"sahne_{s.order:03d}.mp4"))
        ]
        yeniden: list[int] = []
        if mevcut_klipler:
            yeniden = st.multiselect(
                "Yeniden üretilecek sahneler",
                mevcut_klipler,
                format_func=lambda o: next(
                    (f"{s.order:02d} · {s.title or s.story_event[:50]}" for s in senaryo.scenes if s.order == o),
                    str(o),
                ),
                help="Seçilen sahnelerin klibi, görseli, sesi ve altyazı önbelleği silinir.",
            )

        is_durumu = _durum_oku(series_id)
        proc = st.session_state.get("uretim_proc")
        calisiyor = proc is not None and proc.poll() is None

        if calisiyor and proc is not None:
            st.progress(
                min(1.0, max(0.0, float(is_durumu.get("oran", 0.0)))),
                text=str(is_durumu.get("mesaj", "Çalışıyor...")),
            )
            if st.button("Durdur", icon=":material/stop:"):
                proc.terminate()
                st.session_state.uretim_proc = None
                _durum_yaz(series_id, durum="durdu", mesaj="Kullanıcı durdurdu.", oran=0.0)
                st.rerun()
            time.sleep(2)
            st.rerun()
        elif is_durumu.get("durum") == "bitti":
            st.success(f"Video hazır: {is_durumu.get('final', '')}")
        elif is_durumu.get("durum") == "hata":
            st.error(f"Üretim hatası: {is_durumu.get('hata', 'bilinmiyor')}")
        elif is_durumu.get("durum") == "calisiyor":
            st.warning(
                "Önceki üretim yarıda kalmış görünüyor. 'Videoyu üret' kaldığı yerden devam eder."
            )

        if st.button(
            "Videoyu üret",
            type="primary",
            icon=":material/movie:",
            disabled=bool(eksik) or calisiyor,
        ):
            for order in yeniden:
                ad = f"{order:03d}"
                kok = _proje_dizini(series_id)
                ses_yolu = os.path.join(kok, "sesler", f"sahne_{ad}.mp3")
                for yol in (
                    os.path.join(kok, "klipler", f"sahne_{ad}.mp4"),
                    os.path.join(kok, "klipler", f"sahne_{ad}.mp4.ham.mp4"),
                    os.path.join(kok, "gorseller", f"sahne_{ad}.png"),
                    ses_yolu,
                    os.path.join(kok, "sesler", f"sahne_{ad}.cues.json"),
                ):
                    if os.path.exists(yol):
                        os.remove(yol)
                for klasor in (
                    f"{ses_yolu}_parcalar",
                    os.path.join(kok, "klipler", f"sahne_{ad}.mp4_segmentler"),
                    os.path.join(kok, "klipler", f"sahne_{ad}.mp4_medya_segmentler"),
                ):
                    if os.path.isdir(klasor):
                        shutil.rmtree(klasor, ignore_errors=True)

            isci = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uretim_isci.py")
            komut = [
                sys.executable, isci,
                "--series-id", series_id,
                "--video-modu", video_modu,
                "--seslendirme", "1" if seslendirme else "0",
                "--dil", dil,
                "--cinsiyet", cinsiyet,
                "--intro-outro", "1" if intro_outro else "0",
                "--altyazi", "1" if altyazi else "0",
            ]
            st.session_state.uretim_proc = subprocess.Popen(
                komut,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=os.environ.copy(),
            )
            st.rerun()

        st.caption(
            "Üretim arka planda çalışır; Streamlit kilitlenmez. Geçerli sahneler atlanır. "
            "OpenMontage modunda klipler Runway/Veo sağlayıcı sırasına göre üretilir."
        )

# ===============================================================
# 3) Video
# ===============================================================
with video_tab:
    final = _final_yolu(series_id)
    if os.path.exists(final) and os.path.getsize(final) > 0:
        st.subheader("Final video")
        st.video(final)
        with open(final, "rb") as video_dosyasi:
            st.download_button(
                "MP4 indir", video_dosyasi, f"{depo.slugify(seri.name)}.mp4", "video/mp4",
                icon=":material/download:",
            )
        if st.button("Kliplerden finali yeniden birleştir", icon=":material/call_merge:"):
            try:
                klipler_klasoru = os.path.join(_proje_dizini(series_id), "klipler")
                klipler = sorted(
                    os.path.join(klipler_klasoru, ad)
                    for ad in os.listdir(klipler_klasoru)
                    if ad.startswith("sahne_") and ad.endswith(".mp4")
                ) if os.path.isdir(klipler_klasoru) else []
                medya_motoru.birlestir(klipler, final)
                st.success("Final yeniden oluşturuldu.")
                st.rerun()
            except Exception as hata:  # noqa: BLE001
                st.error(f"Birleştirme hatası: {hata}")
    else:
        st.info("Henüz final video yok. 2. sekmede üretimi başlatın.")

    if st.session_state.get("senaryo"):
        senaryo = modeller.Senaryo.model_validate(st.session_state.senaryo)
        st.subheader("Sahne klipleri")
        satirlar = []
        for sahne in senaryo.scenes:
            yol = os.path.join(_proje_dizini(series_id), "klipler", f"sahne_{sahne.order:03d}.mp4")
            satirlar.append({
                "Sahne": sahne.order,
                "Başlık": sahne.title,
                "Süre (sn)": round(medya_motoru.medya_suresi(yol), 1) if os.path.exists(yol) else 0,
                "Durum": "hazır" if os.path.exists(yol) and os.path.getsize(yol) > 0 else "yok",
            })
        st.dataframe(satirlar, width="stretch", hide_index=True)

    st.divider()
    st.caption(
        "Gelişmiş seri/bölüm yönetimi ve görsel prompt paketleri için "
        "`streamlit run senaryo_studyo.py` kullanılabilir."
    )
