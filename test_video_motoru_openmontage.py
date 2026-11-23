"""video_motoru_openmontage.py saf yardımcıları için çevrimdışı testler.

Ağ, FFmpeg ve harici servis çağrıları mock'lanır; burada yalnızca veri dönüşümü,
prompt kurulumu ve hata yolları doğrulanır.
"""
import base64
import io
import json
import os
import runpy
import shutil
import subprocess  # nosec B404 - testte yalnızca CalledProcessError kullanılır
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import video_motoru_openmontage as vm


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class TmpTestTemeli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class BinaryTestleri(TmpTestTemeli):
    def test_bulunan_binarynin_tam_yolu_doner(self):
        ad = Path(sys.executable).name
        self.assertTrue(os.path.isabs(vm._binary(ad)))

    def test_bulunmayan_binary_hata_verir(self):
        with self.assertRaises(RuntimeError):
            vm._binary("kesinlikle-olmayan-arac-12345")


class GoruntuTestleri(TmpTestTemeli):
    def test_image_to_b64_dosyayi_kodlar(self):
        p = self.tmp / "a.bin"
        p.write_bytes(b"merhaba")
        self.assertEqual(vm._image_to_b64(str(p)), base64.b64encode(b"merhaba").decode())

    def test_extract_gemini_image_output_image_alanini_okur(self):
        data, mime = vm._extract_gemini_image({"output_image": {"data": "x", "mime_type": "image/png"}})
        self.assertEqual((data, mime), ("x", "image/png"))

    def test_extract_gemini_image_step_blogunu_okur(self):
        sonuc = {"interaction": {"steps": [{"content": [{"type": "image", "data": "y"}]}]}}
        self.assertEqual(vm._extract_gemini_image(sonuc), ("y", "image/jpeg"))

    def test_extract_gemini_image_yoksa_none_doner(self):
        self.assertEqual(vm._extract_gemini_image({"interaction": {}}), (None, None))

    def test_gemini_generate_image_png_kaydeder(self):
        cikti = self.tmp / "out.png"
        yanit = mock.Mock(status_code=200)
        yanit.json.return_value = {
            "output_image": {"data": base64.b64encode(_png_bytes()).decode(), "mime_type": "image/jpeg"}
        }
        with mock.patch.object(vm.requests, "post", return_value=yanit) as post:
            vm._gemini_generate_image("prompt", [], str(cikti))
        self.assertEqual(post.call_args.kwargs["json"]["model"], vm.GEMINI_IMAGE_MODEL)
        with Image.open(cikti) as img:
            self.assertEqual(img.format, "PNG")

    def test_gemini_generate_image_http_hatasi(self):
        yanit = mock.Mock(status_code=500, text="boom")
        with mock.patch.object(vm.requests, "post", return_value=yanit), self.assertRaises(ValueError):
            vm._gemini_generate_image("prompt", [], str(self.tmp / "out.png"))

    def test_gemini_generate_image_gorsiz_yanit_hata_verir(self):
        yanit = mock.Mock(status_code=200)
        yanit.json.return_value = {"interaction": {"status": "failed"}}
        with mock.patch.object(vm.requests, "post", return_value=yanit), self.assertRaises(ValueError):
            vm._gemini_generate_image("prompt", [], str(self.tmp / "out.png"))


class KarakterMetniTestleri(unittest.TestCase):
    def test_character_ref_prompt_kiyafet_ve_ozellikleri_icerir(self):
        prompt = vm._character_ref_prompt({
            "name": "Pamuk", "type": "tavşan", "default_clothing": "mavi yelek",
            "visual_identity": {"fur_or_skin": "beyaz kürk", "eyes": "siyah"},
        })
        self.assertIn("Pamuk", prompt)
        self.assertIn("wearing mavi yelek", prompt)
        self.assertIn("beyaz kürk", prompt)

    def test_character_ref_prompt_dogal_kurk_kelimesini_korur(self):
        prompt = vm._character_ref_prompt({
            "name": "Pamuk", "type": "tavşan", "default_clothing": "doğal tüy",
            "visual_identity": {},
        })
        self.assertIn("with doğal tüy", prompt)

    def test_character_text_ve_location_text(self):
        self.assertIn("mavi yelek giyer", vm._character_text({
            "name": "Pamuk", "type": "Tavşan", "default_clothing": "mavi yelek",
            "visual_identity": {"fur_or_skin": "beyaz"},
        }))
        metin = vm._location_text({"name": "Orman", "visual_identity": {
            "environment": "ağaçlar", "landmarks": ["göl"], "atmosphere": "sakin",
        }})
        self.assertIn("ağaçlar", metin)
        self.assertIn("göl bulunur", metin)
        self.assertIn("atmosfer sakin", metin)


class SahneYardimcilariTestleri(TmpTestTemeli):
    def test_scene_duration_desteklenen_degerlere_yuvarlar(self):
        self.assertEqual(vm._scene_duration({"duration": 3}), 4)
        self.assertEqual(vm._scene_duration({"duration": 5}), 6)
        self.assertEqual(vm._scene_duration({"duration": 7}), 8)
        self.assertEqual(vm._scene_duration({"duration": 99}), 8)
        self.assertEqual(vm._scene_duration({"duration": "bozuk"}, 6), 6)

    def test_has_series_music_alanlari(self):
        self.assertTrue(vm._has_series_music({"audio_description": "assets/muzik.mp3 çalar"}))
        self.assertTrue(vm._has_series_music({"music_asset": "x.mp3"}))
        self.assertFalse(vm._has_series_music({"audio_description": "kuş sesi"}))

    def test_resolve_music_path_explicit_ve_fallback(self):
        bolum = self.tmp
        explicit = bolum / "ozel.mp3"
        explicit.write_bytes(b"x")
        self.assertEqual(vm._resolve_music_path({"music_asset": "ozel.mp3"}, str(bolum), str(bolum)), str(explicit.resolve()))
        self.assertIsNone(vm._resolve_music_path({}, str(bolum), str(bolum)))
        assets = bolum / "assets"
        assets.mkdir()
        (assets / "muzik.mp3").write_bytes(b"x")
        self.assertEqual(
            vm._resolve_music_path({}, str(bolum), str(bolum)),
            str((assets / "muzik.mp3").resolve()),
        )

    def test_motion_spec_eski_ve_yeni_formati_destekler(self):
        yeni = vm._motion_spec({"motion": {"action": "koşar", "intensity": "yüksek"}})
        self.assertEqual(yeni["action"], "koşar")
        self.assertEqual(yeni["intensity"], "yüksek")
        eski = vm._motion_spec({"motion": "zıplar"})
        self.assertEqual(eski["action"], "zıplar")
        self.assertIn("consistent", eski["preserve"])

    def test_dialogue_lines_liste_sozluk_ve_fallback(self):
        lines = vm._dialogue_lines({"dialogue": [{"character_id": "pamuk", "line": "Merhaba"}]})
        self.assertEqual(lines, [("pamuk", "Merhaba")])
        self.assertEqual(vm._dialogue_lines({"dialogue": {"line": "Selam"}}), [("narrator", "Selam")])
        self.assertEqual(vm._dialogue_lines({"fixed_text": "Başlık"}), [("narrator", "Başlık")])
        self.assertEqual(vm._dialogue_lines({"narration": "Anlatı"}), [("narrator", "Anlatı")])
        self.assertEqual(vm._dialogue_lines({}), [])

    def test_audio_spec_varsayilanlari(self):
        spec = vm._audio_spec({"audio": "rüzgar"})
        self.assertEqual(spec["ambient"], "rüzgar")
        self.assertEqual(spec["music"], "")
        self.assertEqual(vm._audio_spec({})["ambient"], "natural environment ambience")

    def test_build_video_prompt_diyalog_ve_muzik(self):
        prompt = vm._build_video_prompt({
            "dialogue": [{"character_id": "pamuk", "line": "Merhaba"}],
            "audio": {"music": "neşeli"},
        })
        self.assertIn("pamuk says in Turkish", prompt)
        self.assertIn("Background music: neşeli", prompt)

    def test_build_video_prompt_harici_muzikte_arka_plan_uretmez(self):
        prompt = vm._build_video_prompt({"music_asset": "x.mp3", "audio": {"music": "neşeli"}})
        self.assertIn("Do not generate background music", prompt)
        self.assertIn("No spoken dialogue", prompt)

    def test_negative_prompt_alani_ve_varsayilan(self):
        self.assertEqual(vm._negative_prompt({"negative_prompt": "kötü"}), "kötü")
        self.assertIn("morphing", vm._negative_prompt({}))


class ReferansTestleri(TmpTestTemeli):
    def test_ensure_character_references_var_olani_atlar(self):
        ref_dizin = self.tmp / "referanslar"
        ref_dizin.mkdir()
        (ref_dizin / "pamuk.png").write_bytes(b"x")
        with mock.patch.object(vm, "_gemini_generate_image") as uret:
            refs = vm.ensure_character_references({"pamuk": {"name": "Pamuk"}}, {"pamuk"}, str(self.tmp))
        uret.assert_not_called()
        self.assertIn("pamuk", refs)

    def test_ensure_character_references_eksik_olan_uretir(self):
        with mock.patch.object(vm, "_gemini_generate_image") as uret:
            refs = vm.ensure_character_references(
                {"pamuk": {"name": "Pamuk"}}, {"pamuk"}, str(self.tmp)
            )
        uret.assert_called_once()
        self.assertTrue(refs["pamuk"].endswith("pamuk.png"))

    def test_scene_image_kimlik_notunu_ekler(self):
        with mock.patch.object(vm, "_gemini_generate_image") as uret:
            vm._scene_image("ormanda", [str(self.tmp / "a.png"), str(self.tmp / "b.png")], "out.png")
        prompt = uret.call_args.args[0]
        self.assertIn("Scene: ormanda", prompt)
        self.assertIn("reference image 1", prompt)
        self.assertIn("No text", prompt)


class UretimAkisiTestleri(TmpTestTemeli):
    def test_generate_image_and_convert_gemini_anahtari_ister(self):
        with mock.patch.object(vm, "GEMINI_API_KEY", ""), self.assertRaises(RuntimeError):
            vm.generate_image_and_convert_to_video("p", str(self.tmp / "v.mp4"), "S")

    def test_generate_image_and_convert_zoom_out_algilar(self):
        with (
            mock.patch.object(vm, "GEMINI_API_KEY", "x"),
            mock.patch.object(vm, "_scene_image") as sahne,
            mock.patch.object(vm, "_render_static_motion") as hareket,
        ):
            vm.generate_image_and_convert_to_video(
                "p", str(self.tmp / "v.mp4"), "S",
                scene={"motion": {"camera": "slow zoom out"}},
            )
        sahne.assert_called_once()
        self.assertTrue(hareket.call_args.args[3])

    def test_generate_video_routeri_cagirir(self):
        cikti = {
            "provider": "runway", "output_path": str(self.tmp / "v.mp4"), "success": True,
        }
        with (
            mock.patch.object(vm, "GEMINI_API_KEY", "x"),
            mock.patch.object(vm, "_scene_image"),
            mock.patch.object(vm, "_build_video_prompt", return_value="vp"),
            mock.patch("video_provider_router.generate_video_via_openmontage", return_value=cikti) as router,
        ):
            vm.generate_video("p", str(self.tmp / "v.mp4"), "S", scene={})
        self.assertEqual(router.call_args.kwargs["prompt"], "vp")
        self.assertTrue(router.call_args.kwargs["generate_audio"])

    def test_generate_audio_devre_disidir(self):
        with self.assertRaises(RuntimeError):
            vm.generate_audio("metin", "pamuk", "out.mp3")

    def test_merge_media_videoyu_kopyalar(self):
        kaynak = self.tmp / "v.mp4"
        kaynak.write_bytes(b"video")
        hedef = self.tmp / "birlesik.mp4"
        vm.merge_media(str(kaynak), str(self.tmp / "yok.mp3"), str(hedef))
        self.assertEqual(hedef.read_bytes(), b"video")

    def test_merge_media_eksik_video_hata_verir(self):
        with self.assertRaises(FileNotFoundError):
            vm.merge_media(str(self.tmp / "yok.mp4"), str(self.tmp / "yok.mp3"), str(self.tmp / "o.mp4"))

    def test_render_static_motion_tam_yol_kullanir(self):
        with mock.patch.object(vm.subprocess, "run") as calistir:
            vm._render_static_motion("a.png", "o.mp4", 4)
        self.assertEqual(calistir.call_args.args[0][0], vm._binary("ffmpeg"))

    def test_add_series_music_ffprobe_ve_ffmpeg_cagirir(self):
        with (
            mock.patch.object(vm.subprocess, "check_output", return_value="10.0\n") as cikti,
            mock.patch.object(vm.subprocess, "run") as calistir,
        ):
            vm._add_series_music("v.mp4", "m.mp3", "o.mp4")
        self.assertEqual(cikti.call_args.args[0][0], vm._binary("ffprobe"))
        self.assertEqual(calistir.call_args.args[0][0], vm._binary("ffmpeg"))

    def test_concat_videos_liste_dosyasini_temizler(self):
        eski = os.getcwd()
        os.chdir(self.tmp)
        try:
            with mock.patch.object(vm.subprocess, "run") as calistir:
                vm.concat_videos(["a.mp4", "b.mp4"], "o.mp4")
            self.assertFalse(os.path.exists("concat_list.txt"))
            self.assertEqual(calistir.call_count, 1)
        finally:
            os.chdir(eski)

    def test_concat_videos_hatada_yeniden_kodlar(self):
        eski = os.getcwd()
        os.chdir(self.tmp)
        try:
            hata = subprocess.CalledProcessError(1, "ffmpeg")
            with mock.patch.object(vm.subprocess, "run", side_effect=[hata, None]) as calistir:
                vm.concat_videos(["a.mp4"], "o.mp4")
            self.assertEqual(calistir.call_count, 2)
            self.assertIn("libx264", calistir.call_args.args[0])
        finally:
            os.chdir(eski)


class PipelineTestleri(TmpTestTemeli):
    def _dizin_kur(self) -> Path:
        seri = self.tmp / "seriler" / "s"
        bolum = seri / "bolumler" / "001"
        bolum.mkdir(parents=True)
        (seri / "karakterler.json").write_text(
            json.dumps({"characters": [{"character_id": "pamuk"}]}), encoding="utf-8"
        )
        (seri / "mekanlar.json").write_text(
            json.dumps({"locations": [{"location_id": "orman"}]}), encoding="utf-8"
        )
        (bolum / "senaryo.json").write_text(json.dumps({
            "scenes": [{
                "order": 1, "location_id": "orman", "character_ids": ["pamuk"],
                "visual_description": "ormanda", "motion_mode": "image_only",
            }],
        }), encoding="utf-8")
        return bolum / "senaryo.json"

    def test_pipeline_sahneleri_uretir_ve_birlestirir(self):
        senaryo = self._dizin_kur()

        def sahte_hareket(_image, video, _duration, **_kw):
            Path(video).write_bytes(b"v")

        with (
            mock.patch.object(vm, "ensure_character_references", return_value={}),
            mock.patch.object(vm, "_scene_image"),
            mock.patch.object(vm, "_render_static_motion", side_effect=sahte_hareket),
            mock.patch.object(vm, "concat_videos") as birlestir,
        ):
            self.assertTrue(vm.run_pipeline(str(senaryo)))
        birlestir.assert_called_once()
        self.assertTrue(birlestir.call_args.args[1].endswith("final_video.mp4"))

    def test_pipeline_eksik_senaryoda_false_doner(self):
        with mock.patch("builtins.print"):
            self.assertFalse(vm.run_pipeline(str(self.tmp / "yok.json")))

    def test_pipeline_sahne_yoksa_false_doner(self):
        bolum = self.tmp / "seriler" / "s" / "bolumler" / "001"
        bolum.mkdir(parents=True)
        (bolum / "senaryo.json").write_text(json.dumps({"scenes": []}), encoding="utf-8")
        with (
            mock.patch.object(vm, "ensure_character_references", return_value={}),
            mock.patch.object(vm, "concat_videos"),
        ):
            self.assertFalse(vm.run_pipeline(str(bolum / "senaryo.json")))


class VideoUretimGirisTestleri(unittest.TestCase):
    def test_modul_ve_main_blok_calisir(self):
        import video_uretim

        self.assertTrue(callable(video_uretim.run_pipeline))
        with (
            mock.patch.object(sys, "argv", ["video_uretim.py", "kesinlikle-yok.json"]),
            mock.patch("builtins.print"),
        ):
            runpy.run_path("video_uretim.py", run_name="__main__")


if __name__ == "__main__":
    unittest.main()
