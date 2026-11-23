"""Veri sözleşmeleri ve seri deposu için çevrimdışı testler."""
import json
import os
import shutil
import unittest

from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

import senaryo_modelleri as modeller
import senaryo_motoru as motor
import seri_deposu as depo


class EslemeTestleri(unittest.TestCase):
    def test_karakter_ad_ve_takma_adla_eslesir(self):
        pamuk = modeller.Karakter(
            character_id="pamuk", name="Pamuk", aliases=["Pamukçuğum"],
            visual_identity={"fur_or_skin": "Beyaz"},
        )
        self.assertEqual(motor.karakter_esle("Pamuk", [pamuk]), "pamuk")
        self.assertEqual(motor.karakter_esle("pamukçuğum", [pamuk]), "pamuk")
        self.assertEqual(motor.karakter_esle("pamuk", [pamuk]), "pamuk")
        self.assertIsNone(motor.karakter_esle("Mavi Kuş", [pamuk]))

    def test_mekan_ad_ve_kimlikle_eslesir(self):
        orman = modeller.Mekan(location_id="buyulu_orman", name="Büyülü Orman", aliases=["orman"], visual_identity={"x": "y"})
        self.assertEqual(motor.mekan_esle("Orman", [orman]), "buyulu_orman")
        self.assertEqual(motor.mekan_esle("Büyülü Orman", [orman]), "buyulu_orman")
        self.assertIsNone(motor.mekan_esle("Bahçe", [orman]))

    def test_cikarilanlari_esle_yeni_aday_ayirir(self):
        pamuk = modeller.Karakter(character_id="pamuk", name="Pamuk", visual_identity={"x": "y"})
        cikarilan = {
            "characters": [{"name": "Pamuk"}, {"name": "Mavi Kuş", "type": "Kuş"}],
            "locations": [{"name": "Orman"}],
        }
        sonuc = motor.cikarilanlari_esle(cikarilan, [pamuk], [])
        self.assertEqual(sonuc["characters"][0]["matched_character_id"], "pamuk")
        self.assertIsNone(sonuc["characters"][0]["candidate"])
        self.assertIsNone(sonuc["characters"][1]["matched_character_id"])
        self.assertIsNotNone(sonuc["characters"][1]["candidate"])


class ModelTestleri(unittest.TestCase):
    def test_seri_adi_bos_olamaz(self):
        with self.assertRaises(ValidationError):
            modeller.Seri(series_id="x", name="   ")

    def test_karakter_gorsel_kimligi_zorunlu(self):
        with self.assertRaises(ValidationError):
            modeller.Karakter(character_id="pamuk", name="Pamuk")

    def test_mekan_gorsel_kimligi_zorunlu(self):
        with self.assertRaises(ValidationError):
            modeller.Mekan(location_id="orman", name="Orman")

    def test_senaryo_en_az_bir_sahne_ister(self):
        with self.assertRaises(ValidationError):
            modeller.Senaryo(
                series_id="s",
                episode=modeller.Episode(episode_no=1, title="t"),
                scenes=[],
            )

    def test_sahne_siralari_artan_olamali(self):
        s1 = modeller.Sahne(scene_id="a", order=2, location_id="m", source_excerpt="x", estimated_duration_sec=5)
        s2 = modeller.Sahne(scene_id="b", order=1, location_id="m", source_excerpt="x", estimated_duration_sec=5)
        with self.assertRaises(ValidationError):
            modeller.Senaryo(
                series_id="s",
                episode=modeller.Episode(episode_no=1, title="t"),
                scenes=[s1, s2],
            )


class PromptTestleri(unittest.TestCase):
    def test_sahne_promptu_kalici_gorsel_kimligi_icerir(self):
        # Tutarlılık için çıkarılan visual_identity/consistency_rules LLM'e gitmeli.
        seri = modeller.Seri(series_id="s", name="S", visual_style="3D")
        pamuk = modeller.Karakter(
            character_id="pamuk", name="Pamuk", type="Tavşan",
            visual_identity={"fur_or_skin": "KARBEYAZ_POST", "eyes": "ZUMRUT_YESILI"},
            default_clothing="MAVI_YELEK",
            consistency_rules=["KURAL_HAVUC_TASIYAMAZ"],
        )
        orman = modeller.Mekan(
            location_id="orman", name="Orman",
            visual_identity={"color_palette": ["PEMBE_GOKKUSAGI"]},
            consistency_rules=["KURAL_ORMAN_SISLI_DEGIL"],
        )
        prompt = motor._sahne_uret_sistem(seri, [pamuk], [orman])
        for beklenen in (
            "KARBEYAZ_POST", "ZUMRUT_YESILI", "MAVI_YELEK", "KURAL_HAVUC_TASIYAMAZ",
            "PEMBE_GOKKUSAGI", "KURAL_ORMAN_SISLI_DEGIL",
        ):
            self.assertIn(beklenen, prompt)


class GorselPromptTestleri(unittest.TestCase):
    def test_yerel_sablon_api_olmadan_sahne_ve_negatif_prompt_uretir(self):
        seri = modeller.Seri(series_id="s", name="Masal", visual_style="3D")
        karakter = modeller.Karakter(character_id="pamuk", name="Pamuk", visual_identity={"fur": "Beyaz"})
        mekan = modeller.Mekan(location_id="orman", name="Orman", visual_identity={"light": "Gün doğumu"})
        sahne = modeller.Sahne(
            scene_id="scene_001", order=1, title="Yolculuk", location_id="orman",
            character_ids=["pamuk"], source_excerpt="x", story_event="Pamuk yürür.",
            visual_description="Ağaçların arasında.", estimated_duration_sec=5,
        )
        senaryo = modeller.Senaryo(
            series_id="s", episode=modeller.Episode(episode_no=1, title="Bölüm"), scenes=[sahne]
        )
        sonuc = motor.gorsel_prompt_paketi_sablon(
            seri, [karakter], [mekan], None, None, [senaryo], "en"
        )
        for beklenen in ("VISUAL PROMPT PACK", "CHARACTER REFERENCE", "Pamuk", "Orman", "Main story frame", "Negative prompt"):
            self.assertIn(beklenen, sonuc)

    def test_gecersiz_gorsel_prompt_dili_hata_verir(self):
        seri = modeller.Seri(series_id="s", name="Masal")
        with self.assertRaises(ValueError):
            motor.gorsel_prompt_paketi_sablon(seri, [], [], None, None, [], "de", "Genel")


class LlmJsonTestleri(unittest.TestCase):
    def test_bozuk_yanitta_yeniden_dener(self):
        yanitlar = ["```json\n{bozuk}\n```", '{"scenes": []}']
        cagrilar = []

        def sahte_llm_metin(system, user, json_modu=False):
            cagrilar.append(user)
            return yanitlar[len(cagrilar) - 1]

        orijinal = motor._llm_metin
        motor._llm_metin = sahte_llm_metin
        try:
            sonuc = motor._llm_json("sistem", "kullanici")
        finally:
            motor._llm_metin = orijinal

        self.assertEqual(sonuc, {"scenes": []})
        self.assertEqual(len(cagrilar), 2)
        self.assertNotIn("ÖNEMLİ", cagrilar[0])
        self.assertIn("ÖNEMLİ", cagrilar[1])  # ikinci deneme JSON uyarısı taşımalı

    def test_hep_bozuksa_hata_verir(self):
        orijinal = motor._llm_metin
        motor._llm_metin = lambda system, user, json_modu=False: "JSON değil"
        try:
            with self.assertRaises(ValueError):
                motor._llm_json("sistem", "kullanici", deneme=3)
        finally:
            motor._llm_metin = orijinal


class SahneSiralamaTestleri(unittest.TestCase):
    def test_scene_id_order_ile_tutarli_yeniden_numaralanir(self):
        # LLM'in verdiği scene_id sırayla çelişse bile ikisi birlikte düzeltilmeli.
        sahneler = [
            modeller.Sahne(scene_id="scene_003", order=3, location_id="m", source_excerpt="a", estimated_duration_sec=5),
            modeller.Sahne(scene_id="scene_001", order=1, location_id="m", source_excerpt="b", estimated_duration_sec=5),
        ]
        sonuc = motor._sirali_sahneler(sahneler)
        self.assertEqual([(s.order, s.scene_id) for s in sonuc], [(1, "scene_001"), (2, "scene_002")])
        self.assertEqual([s.source_excerpt for s in sonuc], ["a", "b"])  # içerik korunur


class RevizyonTestleri(unittest.TestCase):
    def _intro(self, **degisiklik) -> modeller.Intro:
        temel: dict[str, object] = {
            "series_id": "s", "duration_sec": 5,
            "character_ids": ["pamuk"], "location_id": "orman",
        }
        temel.update(degisiklik)
        return modeller.Intro.model_validate(temel)

    def test_ilk_kayit_revizyon_1(self):
        self.assertEqual(modeller.revizyon_artir(None, self._intro()), 1)

    def test_icerik_degisince_revizyon_artar(self):
        mevcut = self._intro(revision=3)
        self.assertEqual(modeller.revizyon_artir(mevcut, self._intro(revision=3, duration_sec=9)), 4)

    def test_icerik_ayniysa_revizyon_sabit(self):
        mevcut = self._intro(revision=3)
        self.assertEqual(modeller.revizyon_artir(mevcut, self._intro(revision=3)), 3)

    def test_tek_basina_durum_degisimi_revizyonu_artirmaz(self):
        mevcut = self._intro(revision=3, status="draft")
        yeni = self._intro(revision=999, status="locked")  # revision karşılaştırmaya girmemeli
        self.assertEqual(modeller.revizyon_artir(mevcut, yeni), 3)


class ArayuzTestleri(unittest.TestCase):
    def test_seri_seciliyken_acilir(self):
        depo.seri_olustur("Arayuz Test Serisi")
        sid = depo.slugify("Arayuz Test Serisi")
        try:
            at = AppTest.from_file(
                os.path.join(os.path.dirname(__file__), "senaryo_studyo.py")
            )
            at.session_state["series_id"] = sid
            at.run(timeout=20)
            self.assertFalse(at.exception)
            self.assertEqual(at.title[0].value, "Arayuz Test Serisi")
            secenekler = at.selectbox(key="yeni_seri_stil_secim").options
            self.assertIn("Sinematik 3D animasyon, yumuşak ışık, canlı renkler", secenekler)
            self.assertIn("Özel tarz (kendin yaz)", secenekler)
        finally:
            shutil.rmtree(depo.seri_kok(sid), ignore_errors=True)

    def test_gorsel_prompt_sekmesi_acilir(self):
        depo.seri_olustur("Görsel Prompt Testi")
        sid = depo.slugify("Görsel Prompt Testi")
        try:
            at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "senaryo_studyo.py"))
            at.session_state["series_id"] = sid
            at.run(timeout=20)
            self.assertFalse(at.exception)
            self.assertEqual(at.segmented_control(key="gorsel_prompt_dili").value, "tr")
            self.assertTrue(any(b.label == "Görsel prompt paketini oluştur ve kaydet" for b in at.button))
        finally:
            shutil.rmtree(depo.seri_kok(sid), ignore_errors=True)

    def test_mekan_zorunlu_degil(self):
        # Mekân seçilmediğinde "— mekân yok —" varsayılan olmalı ve kayıt boş location_id üretmeli.
        depo.seri_olustur("Mekan Opsiyonel Serisi")
        sid = depo.slugify("Mekan Opsiyonel Serisi")
        depo.mekanlari_kaydet(modeller.MekanKatalogu(
            series_id=sid,
            locations=[modeller.Mekan(location_id="orman", name="Orman", visual_identity={"x": "y"})],
        ))
        try:
            at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "senaryo_studyo.py"))
            at.session_state["series_id"] = sid
            at.run(timeout=20)
            self.assertFalse(at.exception)
            mekan_kutusu = at.selectbox(key="intro_mekan")
            self.assertEqual(mekan_kutusu.options[0], "— mekân yok —")
            self.assertEqual(mekan_kutusu.value, "— mekân yok —")
            durum_kutusu = at.selectbox(key="intro_durum")
            self.assertEqual(durum_kutusu.value, "draft")
        finally:
            shutil.rmtree(depo.seri_kok(sid), ignore_errors=True)

    def test_seri_degisince_onceki_bolum_state_temizlenir(self):
        depo.seri_olustur("Birinci Seri")
        depo.seri_olustur("Ikinci Seri")
        birinci, ikinci = depo.slugify("Birinci Seri"), depo.slugify("Ikinci Seri")
        try:
            at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "senaryo_studyo.py"))
            at.session_state["series_id"] = birinci
            at.run(timeout=20)
            # Birinci seride bir hikâye çıkarılmış gibi davran.
            at.session_state["cikarilan"] = {"characters": [], "locations": []}
            at.session_state["hikaye_metni"] = "Birinci serinin hikâyesi"
            at.session_state["senaryo"] = {"eski": True}
            at.run(timeout=20)

            # Kenar çubuğundan ikinci seriye geç.
            at.selectbox(key="seri_secim").select(ikinci)
            at.run(timeout=20)
            next(b for b in at.button if b.label == "Seriyi seç").click().run(timeout=20)
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state["series_id"], ikinci)
            self.assertIsNone(at.session_state["cikarilan"])
            self.assertIsNone(at.session_state["senaryo"])
            self.assertEqual(at.session_state["hikaye_metni"], "")
        finally:
            shutil.rmtree(depo.seri_kok(birinci), ignore_errors=True)
            shutil.rmtree(depo.seri_kok(ikinci), ignore_errors=True)

    def test_baslik_degisirse_klasor_basliktan_yeniden_turetilir(self):
        # Bayat slug ile yanlış klasöre yazılmasını engelleyen senaryo.
        depo.seri_olustur("Slug Testi")
        sid = depo.slugify("Slug Testi")
        depo.karakterleri_kaydet(modeller.KarakterKatalogu(
            series_id=sid,
            characters=[modeller.Karakter(character_id="pamuk", name="Pamuk", visual_identity={"x": "y"})],
        ))
        depo.mekanlari_kaydet(modeller.MekanKatalogu(
            series_id=sid,
            locations=[modeller.Mekan(location_id="orman", name="Orman", visual_identity={"x": "y"})],
        ))

        def senaryo_json(baslik: str) -> str:
            return json.dumps({
                "series_id": sid,
                "episode": {"episode_no": 1, "title": baslik},
                "scenes": [{
                    "scene_id": "scene_001", "order": 1, "location_id": "orman",
                    "character_ids": ["pamuk"], "source_excerpt": "x",
                    "estimated_duration_sec": 5,
                }],
            }, ensure_ascii=False)

        try:
            at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "senaryo_studyo.py"))
            at.session_state["series_id"] = sid
            at.session_state["senaryo"] = json.loads(senaryo_json("Eski Baslik"))
            at.run(timeout=20)
            self.assertFalse(at.exception)

            # Kullanıcı düzenlenebilir JSON'da başlığı değiştiriyor.
            editor = next(t for t in at.text_area if t.label == "Senaryo JSON (düzenlenebilir)")
            editor.set_value(senaryo_json("Yeni Baslik"))
            next(b for b in at.button if b.label == "Senaryoyu kaydet").click().run(timeout=20)
            self.assertFalse(at.exception)

            self.assertEqual([b["slug"] for b in depo.bolumler(sid)], ["yeni_baslik"])
            self.assertTrue((depo.bolum_dizini(sid, 1, "yeni_baslik") / "senaryo.json").is_file())
            self.assertFalse(depo.bolum_dizini(sid, 1, "eski_baslik").exists())
        finally:
            shutil.rmtree(depo.seri_kok(sid), ignore_errors=True)

    def test_karakter_editoru_disk_gercegini_yansitir(self):
        # Kayıt sonrası editör eski (boş) değeri göstermemeli; diski okumalı.
        depo.seri_olustur("Editor Testi")
        sid = depo.slugify("Editor Testi")
        depo.karakterleri_kaydet(modeller.KarakterKatalogu(
            series_id=sid,
            characters=[modeller.Karakter(character_id="pamuk", name="Pamuk", visual_identity={"fur_or_skin": "Beyaz"})],
        ))
        try:
            at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "senaryo_studyo.py"))
            at.session_state["series_id"] = sid
            at.run(timeout=20)
            self.assertFalse(at.exception)
            editor = next(t for t in at.text_area if t.label == "Karakterler JSON")
            self.assertIn("Pamuk", editor.value)
        finally:
            shutil.rmtree(depo.seri_kok(sid), ignore_errors=True)


class DepoTestleri(unittest.TestCase):
    def setUp(self):
        self.series_id = depo.slugify("Test Serisi")
        shutil.rmtree(depo.seri_kok(self.series_id), ignore_errors=True)

    def tearDown(self):
        shutil.rmtree(depo.seri_kok(self.series_id), ignore_errors=True)

    def test_seri_olustur_ve_yukle(self):
        seri = depo.seri_olustur("Test Serisi", visual_style="3D")
        yuklenen = depo.seri_yukle(self.series_id)
        self.assertEqual(yuklenen.name, "Test Serisi")
        self.assertEqual(yuklenen.visual_style, "3D")
        self.assertIn(seri.series_id, depo.serileri_listele())

    def test_ayni_seri_iki_kez_olusturulamaz(self):
        depo.seri_olustur("Test Serisi")
        with self.assertRaises(ValueError):
            depo.seri_olustur("Test Serisi")

    def test_katalog_kaydet_ve_yukle(self):
        depo.seri_olustur("Test Serisi")
        katalog = modeller.KarakterKatalogu(
            series_id=self.series_id,
            characters=[
                modeller.Karakter(
                    character_id="pamuk", name="Pamuk",
                    visual_identity={"fur_or_skin": "Beyaz post"},
                )
            ],
        )
        depo.karakterleri_kaydet(katalog)
        self.assertEqual(len(depo.karakterleri_yukle(self.series_id).characters), 1)

    def test_katalog_disi_karakter_kaydedilemez(self):
        depo.seri_olustur("Test Serisi")
        depo.karakterleri_kaydet(modeller.KarakterKatalogu(series_id=self.series_id))
        depo.mekanlari_kaydet(modeller.MekanKatalogu(
            series_id=self.series_id,
            locations=[modeller.Mekan(location_id="orman", name="Orman", visual_identity={"atmosphere": "neşeli"})],
        ))
        senaryo = modeller.Senaryo(
            series_id=self.series_id,
            episode=modeller.Episode(episode_no=1, title="t"),
            scenes=[
                modeller.Sahne(
                    scene_id="scene_1", order=1, location_id="orman",
                    character_ids=["bilinmeyen"], source_excerpt="x", estimated_duration_sec=5,
                )
            ],
        )
        with self.assertRaises(ValueError):
            depo.senaryo_kaydet(
                senaryo,
                depo.karakterleri_yukle(self.series_id),
                depo.mekanlari_yukle(self.series_id),
                "deneme",
            )

    def test_gorsel_prompt_kaydet_ve_yukle(self):
        depo.seri_olustur("Test Serisi")
        depo.gorsel_prompt_kaydet(self.series_id, "tr", "Kalıcı prompt")
        self.assertEqual(depo.gorsel_prompt_yukle(self.series_id, "tr"), "Kalıcı prompt")
        self.assertIsNone(depo.gorsel_prompt_yukle(self.series_id, "en"))

    def test_yeni_bolum_intro_outroyu_degistirmez(self):
        depo.seri_olustur("Test Serisi")
        depo.karakterleri_kaydet(modeller.KarakterKatalogu(
            series_id=self.series_id,
            characters=[modeller.Karakter(character_id="pamuk", name="Pamuk", visual_identity={"x": "y"})],
        ))
        depo.mekanlari_kaydet(modeller.MekanKatalogu(
            series_id=self.series_id,
            locations=[modeller.Mekan(location_id="orman", name="Orman", visual_identity={"x": "y"})],
        ))

        intro = modeller.Intro(
            series_id=self.series_id, duration_sec=5,
            character_ids=["pamuk"], location_id="orman", status="locked",
        )
        depo.intro_kaydet(intro, depo.karakterleri_yukle(self.series_id), depo.mekanlari_yukle(self.series_id))
        intro_yolu = depo.intro_dizini(self.series_id) / "intro.json"
        onceki = intro_yolu.read_bytes()

        # Bölüm senaryosu yaz; intro dosyasına dokunulmamalı.
        senaryo = modeller.Senaryo(
            series_id=self.series_id,
            episode=modeller.Episode(episode_no=1, title="Bölüm"),
            scenes=[
                modeller.Sahne(
                    scene_id="scene_1", order=1, location_id="orman",
                    character_ids=["pamuk"], source_excerpt="x", estimated_duration_sec=5,
                )
            ],
        )
        depo.senaryo_kaydet(senaryo, depo.karakterleri_yukle(self.series_id), depo.mekanlari_yukle(self.series_id), "bolum")

        self.assertEqual(intro_yolu.read_bytes(), onceki)
        self.assertEqual(depo.intro_yukle(self.series_id).status, "locked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
