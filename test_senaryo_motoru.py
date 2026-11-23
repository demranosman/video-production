"""senaryo_motoru.py çevrimdışı testleri (LLM çağrıları mock'lanır)."""
import os
import unittest
from unittest import mock

import senaryo_modelleri as modeller
import senaryo_motoru as motor


def _karakter(**ek):
    alanlar = {
        "character_id": "pamuk", "name": "Pamuk", "type": "Tavşan",
        "visual_identity": {"fur_or_skin": "beyaz kürk", "eyes": "siyah"},
        "default_clothing": "mavi yelek", "aliases": ["Pamukçuğum"],
    }
    alanlar.update(ek)
    return modeller.Karakter(**alanlar)


def _mekan():
    return modeller.Mekan(
        location_id="buyulu_orman", name="Büyülü Orman",
        visual_identity={"environment": "ağaçlar", "atmosphere": "sakin"},
    )


class LlmTestleri(unittest.TestCase):
    def test_client_anahtar_yoksa_hata_verir(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            motor._client()

    def test_client_anahtar_varsa_istemci_doner(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            self.assertIsNotNone(motor._client())

    def test_temiz_json_markdown_bloklarini_soyar(self):
        self.assertEqual(motor._temiz_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(motor._temiz_json('```\n{"a": 2}\n```'), {"a": 2})
        self.assertEqual(motor._temiz_json('{"a": 3}'), {"a": 3})

    def test_llm_metin_akis_metnini_doner(self):
        client = mock.MagicMock()
        akis = client.messages.stream.return_value.__enter__.return_value
        akis.get_final_text.return_value = "cevap"
        with mock.patch.object(motor, "llm_saglayici", return_value="claude"),              mock.patch.object(motor, "_client", return_value=client):
            self.assertEqual(motor._llm_metin("sistem", "kullanıcı"), "cevap")

    def test_llm_saglayici_secimi(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "mistral", "MISTRAL_API_KEY": "x"}, clear=True):
            self.assertEqual(motor.llm_saglayici(), "mistral")
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "x"}, clear=True):
            self.assertEqual(motor.llm_saglayici(), "mistral")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}, clear=True):
            self.assertEqual(motor.llm_saglayici(), "claude")
        # Seçilen sağlayıcının anahtarı yoksa diğerine düşer.
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "mistral", "ANTHROPIC_API_KEY": "x"}, clear=True):
            self.assertEqual(motor.llm_saglayici(), "claude")
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "claude", "MISTRAL_API_KEY": "x"}, clear=True):
            self.assertEqual(motor.llm_saglayici(), "mistral")
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            motor.llm_saglayici()

    def test_mistral_istegi_json_modu(self):
        cevap = mock.Mock(status_code=200)
        cevap.json.return_value = {"choices": [{"message": {"content": '{"a": 1}'}}]}
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "k", "MISTRAL_MODEL": "m"}, clear=True),              mock.patch.object(motor.requests, "post", return_value=cevap) as post:
            self.assertEqual(motor._mistral_metin("s", "u", json_modu=True), '{"a": 1}')
            govde = post.call_args.kwargs["json"]
            self.assertEqual(govde["model"], "m")
            self.assertEqual(govde["response_format"], {"type": "json_object"})

    def test_llm_json_gecersiz_yaniti_yeniden_dener(self):
        with mock.patch.object(motor, "_llm_metin", side_effect=["bozuk", '{"ok": 1}']):
            self.assertEqual(motor._llm_json("s", "u"), {"ok": 1})

    def test_llm_json_bos_yaniti_yeniden_dener(self):
        with mock.patch.object(motor, "_llm_metin", side_effect=["", '{"ok": 2}']):
            self.assertEqual(motor._llm_json("s", "u"), {"ok": 2})

    def test_llm_json_hep_gecersizse_hata_verir(self):
        with mock.patch.object(motor, "_llm_metin", side_effect=["bozuk", "bozuk"]), self.assertRaises(ValueError):
            motor._llm_json("s", "u")

    def test_varlik_cikar_bos_metinde_hata_verir(self):
        with self.assertRaises(ValueError):
            motor.varlik_cikar("   ")

    def test_varlik_cikar_llm_sonucunu_doner(self):
        with mock.patch.object(motor, "_llm_json", return_value={"characters": []}):
            self.assertEqual(motor.varlik_cikar("hikâye"), {"characters": []})


class AdayTestleri(unittest.TestCase):
    def test_adaydan_karakter_bos_adda_hata_verir(self):
        with self.assertRaises(ValueError):
            motor.adaydan_karakter({"name": "  "}, "s", 1)

    def test_adaydan_karakter_alanlari_doldurur(self):
        k = motor.adaydan_karakter(
            {"name": "Pamuk", "type": "Tavşan", "aliases": ["Pamukçuğum", " "],
             "personality": ["cesur", ""], "consistency_rules": ["hep mavi yelek"]},
            "s", 3,
        )
        self.assertEqual(k.character_id, "pamuk")
        self.assertEqual(k.first_seen_episode, 3)
        self.assertEqual(k.aliases, ["Pamukçuğum"])
        self.assertEqual(k.visual_identity, {"description": "Tavşan"})

    def test_adaydan_mekan_bos_adda_hata_verir(self):
        with self.assertRaises(ValueError):
            motor.adaydan_mekan({"name": ""}, "s", 1)

    def test_adaydan_mekan_alanlari_doldurur(self):
        m = motor.adaydan_mekan({"name": "Büyülü Orman"}, "s", 2)
        self.assertEqual(m.location_id, "buyulu_orman")
        self.assertEqual(m.visual_identity, {"description": "Büyülü Orman"})


class SahneTestleri(unittest.TestCase):
    def _seri(self):
        return modeller.Seri(series_id="s", name="Seri", visual_style="3D")

    def test_sahne_uret_karaktersiz_mekanla_calisir(self):
        # Belgesel/gezi gibi görünür karakteri olmayan türlerde karakter listesi boş olabilir.
        llm = {"scenes": [
            {"scene_id": "x", "order": 1, "location_id": "buyulu_orman",
             "source_excerpt": "a", "estimated_duration_sec": 5},
        ]}
        with mock.patch.object(motor, "_llm_json", return_value=llm):
            senaryo = motor.sahne_uret(
                "hikâye", self._seri(), [], [_mekan()],
                modeller.Episode(episode_no=1, title="B"),
            )
        self.assertEqual(senaryo.scenes[0].character_ids, [])

    def test_sahne_uret_karakter_ve_mekansiz_hata_verir(self):
        with self.assertRaises(ValueError):
            motor.sahne_uret("hikâye", self._seri(), [], [], modeller.Episode(episode_no=1, title="B"))

    def test_sahne_uret_sahneleri_sirali_uretir(self):
        llm = {"scenes": [
            {"scene_id": "x", "order": 9, "location_id": "buyulu_orman",
             "source_excerpt": "a", "estimated_duration_sec": 5},
        ]}
        with mock.patch.object(motor, "_llm_json", return_value=llm):
            senaryo = motor.sahne_uret(
                "hikâye", self._seri(), [_karakter()], [_mekan()],
                modeller.Episode(episode_no=2, title="Bölüm"),
            )
        self.assertEqual(senaryo.episode.episode_no, 2)
        self.assertEqual(senaryo.scenes[0].scene_id, "scene_001")
        self.assertEqual(senaryo.scenes[0].order, 1)

    def test_sahne_uret_sistem_katalog_kimliklerini_icerir(self):
        sistem = motor._sahne_uret_sistem(self._seri(), [_karakter()], [_mekan()])
        self.assertIn("pamuk", sistem)
        self.assertIn("buyulu_orman", sistem)


class MetinDonusumTestleri(unittest.TestCase):
    def test_prompt_metni_ic_ice_veriyi_duzlestirir(self):
        self.assertEqual(motor._prompt_metni({"a": ["x", "y"]}), "a: x, y")

    def test_deger_metni_liste_ve_duz_metin(self):
        self.assertEqual(motor._deger_metni(["a", "b"]), "a, b")
        self.assertEqual(motor._deger_metni(" a "), "a")

    def test_gorunum_duzyazilari(self):
        self.assertIn("beyaz kürk", motor._karakter_gorunum_duzyazi({"fur_or_skin": "beyaz kürk"}))
        self.assertIn("ağaçlar", motor._mekan_gorunum_duzyazi({"environment": "ağaçlar"}))

    def test_durum_duzyazilari(self):
        self.assertEqual(
            motor._karakter_durum_duzyazi({"pamuk": {"emotion": "mutlu", "action": "koşar"}}, {"pamuk": "Pamuk"}),
            "Pamuk mutlu ve koşar",
        )
        self.assertEqual(
            motor._mekan_durum_duzyazi({"time_of_day": "gece", "weather": "yağmur", "temporary_details": ["sis"]}),
            "gece; yağmur; sis",
        )

    def test_sahne_karakter_ve_mekan_metni_bilinmeyeni_korur(self):
        self.assertEqual(motor._sahne_karakter_metni("yok", {}, False), "yok")
        self.assertEqual(motor._sahne_mekan_metni("yok", {}, False), "yok")
        k = _karakter()
        metin = motor._sahne_karakter_metni("pamuk", {"pamuk": k}, True)
        self.assertIn("clothing: mavi yelek", metin)


class GorselPromptTestleri(unittest.TestCase):
    def _veri(self):
        seri = modeller.Seri(series_id="s", name="Seri", visual_style="3D", target_audience="çocuk")
        k = _karakter()
        m = modeller.Mekan(location_id="buyulu_orman", name="Büyülü Orman", visual_identity={"environment": "ağaçlar"})
        intro = modeller.Intro(series_id="s", duration_sec=5, character_ids=["pamuk"], location_id="buyulu_orman")
        outro = modeller.Outro(series_id="s", duration_sec=7, character_ids=["pamuk"], location_id="buyulu_orman")
        return seri, k, m, intro, outro

    def test_paket_tr_ve_en_basliklari(self):
        seri, k, m, intro, outro = self._veri()
        tr = motor.gorsel_prompt_paketi_sablon(seri, [k], [m], intro, outro, [], "tr")
        en = motor.gorsel_prompt_paketi_sablon(seri, [k], [m], intro, outro, [], "en")
        self.assertIn("GÖRSEL PROMPT PAKETİ", tr)
        self.assertIn("KARAKTER REFERANSI", tr)
        self.assertIn("LOCATION REFERENCE", en)
        self.assertIn("clothing:", en)

    def test_paket_gecersiz_dilde_hata_verir(self):
        seri, k, m, intro, outro = self._veri()
        with self.assertRaises(ValueError):
            motor.gorsel_prompt_paketi_sablon(seri, [k], [m], intro, outro, [], "de")

    def test_gorsel_prompt_sistem_dil_dogrular(self):
        seri, k, m, intro, outro = self._veri()
        sistem = motor._gorsel_prompt_sistem(seri, [k], [m], intro, outro, [], "en", "model")
        self.assertIn("English", sistem)
        with self.assertRaises(ValueError):
            motor._gorsel_prompt_sistem(seri, [k], [m], intro, outro, [], "de", "model")


if __name__ == "__main__":
    unittest.main()
