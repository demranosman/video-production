"""formatlar, fikir genişletme ve medya hattı için çevrimdışı testler."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image

import formatlar
import medya_motoru as medya
import senaryo_modelleri as modeller
import senaryo_motoru as motor


def _seri(genre="genel", fmt="kisa"):
    return modeller.Seri(
        series_id="s", name="Test", genre=genre, format=fmt,
        target_duration_sec=60, default_aspect_ratio="9:16",
        visual_style="cinematic",
    )


def _sahne(**ek):
    alanlar = {
        "scene_id": "scene_001", "order": 1, "location_id": "orman",
        "source_excerpt": "kaynak", "estimated_duration_sec": 5,
        "narration": "Pamuk ormanda yürüdü.",
        "visual_description": "Tavşan ormanda",
        "character_ids": ["pamuk"], "motion": "zoom in",
    }
    alanlar.update(ek)
    return modeller.Sahne(**alanlar)


class FormatTestleri(unittest.TestCase):
    def test_formatlar_tutarli(self):
        for anahtar, ayar in formatlar.FORMATLAR.items():
            self.assertLessEqual(ayar["sahne"][0], ayar["sahne"][1], anahtar)
            self.assertLessEqual(ayar["sure_sn"][0], ayar["sure_sn"][1], anahtar)
            self.assertLessEqual(ayar["sahne_sure_sn"][0], ayar["sahne_sure_sn"][1], anahtar)
            self.assertEqual(len(medya.boyutlar(ayar["en_boy"])), 2)

    def test_gecersiz_format_ve_tur(self):
        with self.assertRaises(ValueError):
            formatlar.format_ayari("yok")
        with self.assertRaises(ValueError):
            formatlar.tur_ayari("yok")


class MotorPromptTestleri(unittest.TestCase):
    def test_fikir_genislet_story_doner(self):
        with mock.patch.object(motor, "_llm_json", return_value={"title": "T", "story": "Hikâye"}):
            sonuc = motor.fikir_genislet("bir fikir", "genel", "kisa")
        self.assertEqual(sonuc["story"], "Hikâye")
        self.assertEqual(sonuc["title"], "T")

    def test_fikir_genislet_bos_girdi_hata(self):
        with self.assertRaises(ValueError):
            motor.fikir_genislet("  ")

    def test_masal_kurali_hayvan_kiyafeti_icerir(self):
        self.assertIn("insansı", motor._varlik_cikarim_sistem("masal").lower())
        self.assertNotIn("insansı", motor._varlik_cikarim_sistem("genel").lower())

    def test_sahne_promptu_format_hedefini_icerir(self):
        sistem = motor._sahne_uret_sistem(_seri("genel", "kisa"), [], [])
        self.assertIn("Hedef sahne sayısı: 4-8", sistem)
        self.assertIn("9:16", sistem)
        self.assertIn("~60 saniye", sistem)


class MedyaYardimciTestleri(unittest.TestCase):
    def test_boyutlar(self):
        self.assertEqual(medya.boyutlar("9:16"), (1080, 1920))
        self.assertEqual(medya.boyutlar("16:9"), (1920, 1080))
        self.assertEqual(medya.boyutlar("bilinmiyor"), (1920, 1080))

    def test_ses_preset_override(self):
        with mock.patch.dict(os.environ, {"ELEVENLABS_VOICE_TR_KADIN": "ozel"}, clear=False):
            self.assertEqual(medya.ses_preset("tr", "kadin")["voice_id"], "ozel")

    def test_kimlik_metni(self):
        self.assertEqual(
            medya._kimlik_metni({"fur": "beyaz", "eyes": ["siyah", "iri"]}),
            "fur: beyaz, eyes: siyah, iri",
        )

    def test_sahne_promptu_kimlik_ve_kiyafet(self):
        k = modeller.Karakter(
            character_id="pamuk", name="Pamuk", type="Tavşan",
            visual_identity={"fur_or_skin": "beyaz kürk"},
            default_clothing="mavi yelek",
        )
        m = modeller.Mekan(
            location_id="orman", name="Orman",
            visual_identity={"environment": "ağaçlar"},
        )
        prompt = medya.sahne_promptu(_sahne(), _seri(), {"pamuk": k}, {"orman": m})
        self.assertIn("Pamuk", prompt)
        self.assertIn("mavi yelek", prompt)
        self.assertIn("beyaz kürk", prompt)
        self.assertIn("Orman", prompt)
        self.assertIn("no text", prompt.lower())

    def test_sahne_metni_narration_oncelikli(self):
        self.assertEqual(medya.sahne_metni(_sahne()), "Pamuk ormanda yürüdü.")
        sahne = _sahne(narration="", dialogue=[{"line": "Merhaba"}, {"line": "Selam"}])
        self.assertEqual(medya.sahne_metni(sahne), "Merhaba Selam")

    def test_zoom_filtresi_yonleri(self):
        self.assertIn("zoom-0.0015", medya._zoom_filtresi("zoom out", 50, 1080, 1920))
        self.assertIn("on*iw*0.08", medya._zoom_filtresi("pan left", 50, 1080, 1920))
        self.assertIn("zoom+0.0015", medya._zoom_filtresi("zoom in", 50, 1080, 1920))

    def test_tahmini_cagri_sayilari(self):
        senaryo = modeller.Senaryo(
            series_id="s", episode=modeller.Episode(episode_no=1, title="B"),
            scenes=[_sahne()],
        )
        self.assertEqual(
            medya.tahmini_cagri_sayilari(senaryo, "resim", True),
            {"referans_gorsel": 1, "sahne_gorsel": 1, "tts": 1, "fal_klip": 0, "openmontage": 0},
        )
        self.assertEqual(medya.tahmini_cagri_sayilari(senaryo, "hareketli", False)["fal_klip"], 1)
        self.assertEqual(medya.tahmini_cagri_sayilari(senaryo, "openmontage", False)["openmontage"], 1)


class UretimAkisiTestleri(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.klasor, ignore_errors=True)
        self.senaryo = modeller.Senaryo(
            series_id="s", episode=modeller.Episode(episode_no=1, title="B"),
            scenes=[
                _sahne(),
                _sahne(scene_id="scene_002", order=2, estimated_duration_sec=6,
                       narration="İkinci sahne."),
            ],
        )
        self.karakter = modeller.Karakter(
            character_id="pamuk", name="Pamuk", type="Tavşan",
            visual_identity={"fur": "beyaz"}, default_clothing="mavi yelek",
        )
        self.mekan = modeller.Mekan(
            location_id="orman", name="Orman", visual_identity={"environment": "ağaçlar"},
        )

    def _sahte_dosyalar(self):
        def gorsel(prompt, refs, path, en_boy):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"png")

        def tts(metin, path, dil, cinsiyet, voice_settings=None, voice_id=None):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"mp3")

        def klip(image_path, audio_path, duration, output_path, motion="zoom in", en_boy="16:9"):
            with open(output_path, "wb") as f:
                f.write(b"mp4")

        def birlestir(klips, output_path):
            with open(output_path, "wb") as f:
                f.write(b"final")

        return gorsel, tts, klip, birlestir

    def test_sesli_uretim_ve_devam_etme(self):
        gorsel, tts, klip, birlestir = self._sahte_dosyalar()
        with mock.patch.object(medya, "karakter_referanslari", return_value={}), \
             mock.patch.object(medya, "gemini_gorsel", side_effect=gorsel), \
             mock.patch.object(medya, "tts_elevenlabs", side_effect=tts), \
             mock.patch.object(medya, "statik_klip", side_effect=klip) as statik, \
             mock.patch.object(medya, "birlestir", side_effect=birlestir), \
             mock.patch.object(medya, "medya_suresi", return_value=3.0):
            sonuc = medya.uret(
                self.senaryo, _seri(), [self.karakter], [self.mekan], self.klasor,
                seslendirme=True,
            )
            self.assertEqual(sonuc["sahne_sayisi"], 2)
            self.assertTrue(os.path.exists(sonuc["final"]))
            self.assertEqual(statik.call_count, 2)

            # İkinci çalıştırmada geçerli klipler atlanır.
            statik.reset_mock()
            medya.uret(
                self.senaryo, _seri(), [self.karakter], [self.mekan], self.klasor,
                video_modu="resim", seslendirme=True, intro_outro=False, altyazi=False,
            )
            self.assertEqual(statik.call_count, 0)

    def test_sessiz_uretim_sureyi_tahminden_alir(self):
        gorsel, _tts, klip, birlestir = self._sahte_dosyalar()
        with mock.patch.object(medya, "karakter_referanslari", return_value={}), \
             mock.patch.object(medya, "gemini_gorsel", side_effect=gorsel), \
             mock.patch.object(medya, "statik_klip", side_effect=klip) as statik, \
             mock.patch.object(medya, "birlestir", side_effect=birlestir), \
             mock.patch.object(medya, "medya_suresi", return_value=3.0):
            medya.uret(
                self.senaryo, _seri(), [self.karakter], [self.mekan], self.klasor,
                video_modu="resim", seslendirme=False, intro_outro=False, altyazi=False,
            )
        self.assertEqual(statik.call_args_list[0].args[2], 5.0)
        self.assertIsNone(statik.call_args_list[0].args[1])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg gerekli")
    def test_gercek_ffmpeg_statik_klip(self):
        image_path = os.path.join(self.klasor, "kare.png")
        Image.new("RGB", (320, 568), "navy").save(image_path)
        cikti = os.path.join(self.klasor, "klip.mp4")
        medya.statik_klip(image_path, None, 0.6, cikti, "zoom in", "9:16")
        self.assertTrue(medya._gecerli_video(cikti))


if __name__ == "__main__":
    unittest.main()
