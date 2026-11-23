"""Üretim işçisinin durum dosyası testleri (ağ/LLM çağrısı yok)."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import uretim_isci


class DurumTestleri(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.klasor, ignore_errors=True)

    def test_yaz_oku(self):
        uretim_isci.durum_yaz(self.klasor, durum="calisiyor", oran=0.5, mesaj="Sahne 1")
        durum = uretim_isci.durum_oku(self.klasor)
        self.assertEqual(durum["durum"], "calisiyor")
        self.assertEqual(durum["oran"], 0.5)
        self.assertEqual(durum["mesaj"], "Sahne 1")
        self.assertTrue(durum["guncellendi"])

    def test_yoksa_bos_doner(self):
        self.assertEqual(uretim_isci.durum_oku(self.klasor), {})

    def test_bozuk_json_bos_doner(self):
        with open(os.path.join(self.klasor, "uretim_durum.json"), "w", encoding="utf-8") as file:
            file.write("{bozuk")
        self.assertEqual(uretim_isci.durum_oku(self.klasor), {})

    def test_atomik_yazim_gecici_dosya_birakmaz(self):
        uretim_isci.durum_yaz(self.klasor, durum="bitti", oran=1.0)
        dosyalar = os.listdir(self.klasor)
        self.assertIn("uretim_durum.json", dosyalar)
        self.assertNotIn("uretim_durum.json.tmp", dosyalar)


if __name__ == "__main__":
    unittest.main()
