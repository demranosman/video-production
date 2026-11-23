"""video_provider_router.py için çevrimdışı testler (OpenMontage mock'lanır)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import video_provider_router as router


class TmpTestTemeli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class PolitikaTestleri(TmpTestTemeli):
    def test_varsayilan_politika_yuklenir(self):
        policy = router._load_policy()
        self.assertTrue(policy["preferred_order"])

    def test_explicit_yol_ve_ortam_degiskeni(self):
        dosya = self.tmp / "p.json"
        dosya.write_text(json.dumps({"preferred_order": ["a"]}), encoding="utf-8")
        self.assertEqual(router._load_policy(str(dosya))["preferred_order"], ["a"])
        with mock.patch.dict(os.environ, {"VIDEO_PROVIDER_POLICY": str(dosya)}):
            self.assertEqual(router._load_policy()["preferred_order"], ["a"])


class SiniflandirmaTestleri(unittest.TestCase):
    def test_kota_hata_mesajlari(self):
        self.assertTrue(router._is_quota_error("429 Too Many Requests"))
        self.assertTrue(router._is_quota_error("insufficient credits"))
        self.assertFalse(router._is_quota_error("unknown provider"))

    def test_kimlik_hata_mesajlari(self):
        self.assertTrue(router._is_auth_error("401 unauthorized"))
        self.assertTrue(router._is_auth_error("API key not set"))
        self.assertFalse(router._is_auth_error("timeout"))

    def test_gecici_hata_mesajlari(self):
        self.assertTrue(router._is_transient_error("connection timeout"))
        self.assertTrue(router._is_transient_error("503 server error"))
        self.assertFalse(router._is_transient_error("invalid prompt"))

    def test_error_text_alanlari_sirayla_dener(self):
        self.assertEqual(router._error_text(mock.Mock(error="e", data="d")), "e")
        self.assertEqual(router._error_text(mock.Mock(error=None, data="d")), "d")
        self.assertEqual(router._error_text("metin"), "metin")


class CiktiYoluTestleri(TmpTestTemeli):
    def test_data_output_path_kullanilir(self):
        dosya = self.tmp / "v.mp4"
        dosya.write_bytes(b"v")
        result = mock.Mock(data={"output_path": str(dosya)})
        self.assertEqual(router._result_output_path(result, str(self.tmp / "yok.mp4")), str(dosya.resolve()))

    def test_istenen_yol_yoksa_bos_doner(self):
        result = mock.Mock(data={})
        self.assertEqual(router._result_output_path(result, str(self.tmp / "yok.mp4")), "")


class SaglayiciDenemesiTestleri(TmpTestTemeli):
    def test_eksik_gorsel_hata_verir(self):
        with self.assertRaises(FileNotFoundError):
            router._provider_attempt(
                selector=mock.Mock(), provider="a", prompt="p",
                image_path=str(self.tmp / "yok.png"), output_path="o.mp4",
                duration=8, generate_audio=True,
            )

    def test_girdiler_selector_sozlesmesine_uyar(self):
        gorsel = self.tmp / "i.png"
        gorsel.write_bytes(b"i")
        selector = mock.Mock()
        router._provider_attempt(
            selector=selector, provider="runway", prompt="p",
            image_path=str(gorsel), output_path="o.mp4",
            duration=8, generate_audio=True, negative_prompt="kötü",
            aspect_ratio="9:16",
        )
        girdi = selector.execute.call_args.args[0]
        self.assertEqual(girdi["preferred_provider"], "runway")
        self.assertEqual(girdi["allowed_providers"], ["runway"])
        self.assertTrue(girdi["generate_audio"])
        self.assertEqual(girdi["negative_prompt"], "kötü")
        self.assertEqual(girdi["aspect_ratio"], "9:16")
        self.assertEqual(girdi["ratio"], "9:16")
        self.assertEqual(girdi["duration"], 8)
        self.assertIsInstance(girdi["duration"], int)

    def test_veo_sure_bicimi(self):
        gorsel = self.tmp / "i.png"
        gorsel.write_bytes(b"i")
        for istenen, beklenen in ((4, "4s"), (6, "6s"), (9, "8s")):
            selector = mock.Mock()
            router._provider_attempt(
                selector=selector, provider="veo", prompt="p",
                image_path=str(gorsel), output_path="o.mp4",
                duration=istenen, generate_audio=True, aspect_ratio="9:16",
            )
            girdi = selector.execute.call_args.args[0]
            self.assertEqual(girdi["duration"], beklenen)
            self.assertEqual(girdi["aspect_ratio"], "9:16")


class SelectorTestleri(TmpTestTemeli):
    def _sahte_openmontage(self) -> Path:
        modul = self.tmp / "tools" / "video" / "video_selector.py"
        modul.parent.mkdir(parents=True)
        (self.tmp / "tools" / "__init__.py").write_text("", encoding="utf-8")
        (self.tmp / "tools" / "video" / "__init__.py").write_text("", encoding="utf-8")
        modul.write_text("class VideoSelector:\n    pass\n", encoding="utf-8")
        return self.tmp

    def test_dizin_yoksa_hata_verir(self):
        with mock.patch.dict(os.environ, {"OPENMONTAGE_PATH": str(self.tmp / "yok")}), self.assertRaises(RuntimeError):
            router._openmontage_yolu()

    def test_acik_yol_gecersizse_hata_verir(self):
        with mock.patch.dict(os.environ, {"OPENMONTAGE_PATH": str(self.tmp / "yok")}), self.assertRaises(RuntimeError):
            router._openmontage_selector()

    @unittest.skipUnless(Path("D:/OpenMontage").is_dir(), "D:/OpenMontage yok")
    def test_gercek_openmontage_yolu_bulunur(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(router._openmontage_yolu().is_dir())

    @unittest.skipUnless(Path("D:/OpenMontage").is_dir(), "D:/OpenMontage yok")
    def test_runway_saglayici_listede(self):
        selector = router._openmontage_selector()
        self.assertIn("runway", {p.provider for p in selector._providers()})

    def test_selector_yuklenir(self):
        yol = self._sahte_openmontage()
        eklenen = []
        with (
            mock.patch.dict(os.environ, {"OPENMONTAGE_PATH": str(yol)}),
            mock.patch.object(sys, "path", eklenen.copy()),
        ):
            try:
                selector = router._openmontage_selector()
                self.assertEqual(type(selector).__name__, "VideoSelector")
            finally:
                sys.modules.pop("tools", None)
                sys.modules.pop("tools.video", None)
                sys.modules.pop("tools.video.video_selector", None)


class YonlendirmeTestleri(TmpTestTemeli):
    def _politika(self, **ek) -> str:
        dosya = self.tmp / "politika.json"
        veri = {"preferred_order": ["a"], "max_retries_per_provider": 0}
        veri.update(ek)
        dosya.write_text(json.dumps(veri), encoding="utf-8")
        return str(dosya)

    def test_bos_saglayici_listesi_hata_verir(self):
        dosya = self.tmp / "bos.json"
        dosya.write_text(json.dumps({"preferred_order": []}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            router.generate_video_via_openmontage(
                prompt="p", image_path="i.png", output_path="o.mp4",
                duration=8, policy_path=str(dosya),
            )

    def test_basarili_uretim_cikti_yolunu_doner(self):
        cikti = self.tmp / "o.mp4"
        cikti.write_bytes(b"v")
        result = mock.Mock(success=True, data={"output_path": str(cikti)})
        with (
            mock.patch.object(router, "_openmontage_selector", return_value=mock.Mock()),
            mock.patch.object(router, "_provider_attempt", return_value=result),
        ):
            sonuc = router.generate_video_via_openmontage(
                prompt="p", image_path="i.png", output_path=str(cikti),
                duration=8, policy_path=self._politika(),
            )
        self.assertTrue(sonuc["success"])
        self.assertEqual(sonuc["provider"], "a")
        self.assertEqual(sonuc["output_path"], str(cikti.resolve()))

    def test_gecersiz_cikti_tum_saglayicilar_bitince_hata_verir(self):
        result = mock.Mock(success=True, data={})
        with (
            mock.patch.object(router, "_openmontage_selector", return_value=mock.Mock()),
            mock.patch.object(router, "_provider_attempt", return_value=result),
            self.assertRaises(RuntimeError),
        ):
            router.generate_video_via_openmontage(
                prompt="p", image_path="i.png", output_path=str(self.tmp / "yok.mp4"),
                duration=8, policy_path=self._politika(),
            )

    def test_gecici_hata_sonraki_saglayiciya_gecer(self):
        basarisiz = mock.Mock(success=False, error="timeout", data=None)
        cikti = self.tmp / "o.mp4"
        cikti.write_bytes(b"v")
        basarili = mock.Mock(success=True, data={"output_path": str(cikti)})
        with (
            mock.patch.object(router, "_openmontage_selector", return_value=mock.Mock()),
            mock.patch.object(router, "_provider_attempt", side_effect=[basarisiz, basarili]),
        ):
            sonuc = router.generate_video_via_openmontage(
                prompt="p", image_path="i.png", output_path=str(cikti),
                duration=8, policy_path=self._politika(preferred_order=["a", "b"]),
            )
        self.assertEqual(sonuc["provider"], "b")
        self.assertEqual(sonuc["attempts"][0]["error_class"], "transient")

    def test_beklenmeyen_istisna_yakalanir(self):
        with (
            mock.patch.object(router, "_openmontage_selector", return_value=mock.Mock()),
            mock.patch.object(router, "_provider_attempt", side_effect=ValueError("patladı")),
            self.assertRaises(RuntimeError),
        ):
            router.generate_video_via_openmontage(
                prompt="p", image_path="i.png", output_path=str(self.tmp / "o.mp4"),
                duration=8, policy_path=self._politika(),
            )

    def test_kota_hatasi_sonraki_saglayiciya_gecer(self):
        kota = mock.Mock(success=False, error="429 quota exceeded", data=None)
        cikti = self.tmp / "o.mp4"
        cikti.write_bytes(b"v")
        basarili = mock.Mock(success=True, data={"output_path": str(cikti)})
        with (
            mock.patch.object(router, "_openmontage_selector", return_value=mock.Mock()),
            mock.patch.object(router, "_provider_attempt", side_effect=[kota, basarili]),
        ):
            sonuc = router.generate_video_via_openmontage(
                prompt="p", image_path="i.png", output_path=str(cikti),
                duration=8, policy_path=self._politika(preferred_order=["a", "b"]),
            )
        self.assertEqual(sonuc["provider"], "b")
        self.assertEqual(sonuc["attempts"][0]["error_class"], "quota")


if __name__ == "__main__":
    unittest.main()
