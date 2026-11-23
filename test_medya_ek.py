"""Altyazı, kart, kolaj ve OpenMontage entegrasyon testleri."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image

import medya_motoru as medya
import senaryo_modelleri as modeller

FFMPEG_VAR = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _seri():
    return modeller.Seri(
        series_id="s", name="Test", genre="genel", format="kisa",
        default_aspect_ratio="9:16", target_duration_sec=60, visual_style="cinematic",
    )


def _karakter():
    return modeller.Karakter(
        character_id="pamuk", name="Pamuk", type="Tavşan",
        visual_identity={"fur": "beyaz"}, default_clothing="mavi yelek",
    )


def _mekan():
    return modeller.Mekan(
        location_id="orman", name="Orman", visual_identity={"environment": "ağaçlar"},
    )


def _sahne(**ek):
    alanlar = {
        "scene_id": "scene_001", "order": 1, "location_id": "orman",
        "source_excerpt": "kaynak", "estimated_duration_sec": 5,
        "narration": "Pamuk ormanda yürüdü.", "character_ids": ["pamuk"],
    }
    alanlar.update(ek)
    return modeller.Sahne(**alanlar)


class AltyaziTestleri(unittest.TestCase):
    def test_zaman_parcalari_cumle_sinirinda_boler(self):
        parcalar = medya._zaman_parcalari("Birinci cümle. İkinci cümle burada.")
        self.assertEqual(parcalar[0][2], "Birinci cümle.")
        self.assertEqual(parcalar[1][2], "İkinci cümle burada.")

    def test_cues_alignment_yoksa_oransal_boler(self):
        cues = medya._cues("abcdefghij", {}, offset=2.0, sure=4.0)
        self.assertEqual(len(cues), 1)
        self.assertAlmostEqual(cues[0]["start"], 2.0, places=2)
        self.assertAlmostEqual(cues[0]["end"], 6.0, places=2)

    def test_cues_alignment_kullanir(self):
        metin = "Merhaba dünya."
        alignment = {
            "characters": list(metin),
            "character_start_times_seconds": [i * 0.1 for i in range(len(metin))],
            "character_end_times_seconds": [(i + 1) * 0.1 for i in range(len(metin))],
        }
        cues = medya._cues(metin, alignment, offset=0.0, sure=2.0)
        self.assertAlmostEqual(cues[0]["start"], 0.0, places=2)
        self.assertAlmostEqual(cues[0]["end"], 1.4, places=2)

    def test_srt_yaz_bicim(self):
        with tempfile.TemporaryDirectory() as klasor:
            yol = os.path.join(klasor, "a.srt")
            medya.srt_yaz([{"start": 1.0, "end": 2.5, "text": "Merhaba"}], yol)
            with open(yol, encoding="utf-8") as file:
                icerik = file.read()
        self.assertIn("00:00:01,000 --> 00:00:02,500", icerik)
        self.assertIn("Merhaba", icerik)


class KartVeKolajTestleri(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.klasor, ignore_errors=True)

    def _gorsel(self, ad="kare.png", renk="navy"):
        yol = os.path.join(self.klasor, ad)
        Image.new("RGB", (320, 568), renk).save(yol)
        return yol

    @unittest.skipUnless(FFMPEG_VAR, "ffmpeg gerekli")
    def test_baslik_karti(self):
        cikti = os.path.join(self.klasor, "intro.mp4")
        medya.baslik_karti("Başlık", "Alt metin", 1.0, cikti, "9:16", arka_plan=self._gorsel())
        self.assertTrue(medya._gecerli_video(cikti))
        self.assertAlmostEqual(medya.medya_suresi(cikti), 1.0, delta=0.3)

    @unittest.skipUnless(FFMPEG_VAR, "ffmpeg gerekli")
    def test_medya_kolaj(self):
        cikti = os.path.join(self.klasor, "kolaj.mp4")
        medya.medya_kolaj(
            [self._gorsel("a.png", "navy"), self._gorsel("b.png", "maroon")],
            None, 1.2, cikti, "9:16",
        )
        self.assertTrue(medya._gecerli_video(cikti))
        self.assertAlmostEqual(medya.medya_suresi(cikti), 1.2, delta=0.4)

    @unittest.skipUnless(FFMPEG_VAR, "ffmpeg gerekli")
    def test_altyazi_yak(self):
        klip = os.path.join(self.klasor, "klip.mp4")
        medya.statik_klip(self._gorsel(), None, 1.0, klip, "zoom in", "9:16")
        srt = os.path.join(self.klasor, "a.srt")
        medya.srt_yaz([{"start": 0.1, "end": 0.8, "text": "Merhaba"}], srt)
        cikti = os.path.join(self.klasor, "altyazili.mp4")
        self.assertTrue(medya.altyazi_yak(klip, srt, cikti, "9:16"))
        self.assertTrue(medya._gecerli_video(cikti))


class OpenMontageTestleri(unittest.TestCase):
    def test_openmontage_klip_parametreleri(self):
        with tempfile.TemporaryDirectory() as klasor:
            cikti = os.path.join(klasor, "v.mp4")

            def sahte(**kwargs):
                with open(kwargs["output_path"], "wb") as file:
                    file.write(b"v")
                return {"output_path": kwargs["output_path"], "provider": "runway"}

            with mock.patch(
                "video_provider_router.generate_video_via_openmontage", side_effect=sahte
            ) as cagri:
                saglayici = medya.openmontage_klip("i.png", "p", cikti, 2.0, "9:16")
            parametre = cagri.call_args.kwargs
        self.assertEqual(saglayici, "runway")
        self.assertEqual(parametre["duration"], 4)
        self.assertEqual(parametre["aspect_ratio"], "9:16")
        self.assertTrue(parametre["generate_audio"])

    def test_openmontage_modu_klip_uretir(self):
        klasor = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, klasor, ignore_errors=True)
        senaryo = modeller.Senaryo(
            series_id="s", episode=modeller.Episode(episode_no=1, title="B"),
            scenes=[_sahne()],
        )

        def gorsel(prompt, refs, path, en_boy):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            Image.new("RGB", (320, 568), "navy").save(path)

        def klip(image_path, prompt, output_path, duration, en_boy="16:9", generate_audio=True):
            with open(output_path, "wb") as file:
                file.write(b"v")
            return "runway"

        def normalize(video_path, duration, output_path, en_boy, native_audio):
            with open(output_path, "wb") as file:
                file.write(b"v")

        def birlestir(klips, output_path):
            with open(output_path, "wb") as file:
                file.write(b"final")

        with mock.patch.object(medya, "karakter_referanslari", return_value={}), \
             mock.patch.object(medya, "gemini_gorsel", side_effect=gorsel), \
             mock.patch.object(medya, "openmontage_klip", side_effect=klip) as om, \
             mock.patch.object(medya, "_videoyu_normalize", side_effect=normalize), \
             mock.patch.object(medya, "statik_klip") as statik, \
             mock.patch.object(medya, "birlestir", side_effect=birlestir), \
             mock.patch.object(medya, "medya_suresi", return_value=3.0):
            sonuc = medya.uret(
                senaryo, _seri(), [_karakter()], [_mekan()], klasor,
                video_modu="openmontage", seslendirme=False,
                intro_outro=False, altyazi=False,
            )
        self.assertEqual(om.call_count, 1)
        self.assertEqual(statik.call_count, 0)
        self.assertTrue(os.path.exists(sonuc["final"]))


if __name__ == "__main__":
    unittest.main()
