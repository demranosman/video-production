# Hikâyeden senaryo üretim stüdyosu

Bir hikâye metnini alıp karakter/mekân kataloğu çıkarır, onları seri boyunca
sabit tutar ve hikâyeyi sahnelere bölerek üretime hazır senaryo JSON'u üretir.

Amaç: bir serinin bütün bölümlerinde karakterlerin ve mekânların görsel olarak
aynı kalması. Kalıcı kimlik (`visual_identity`, `default_clothing`,
`consistency_rules`) seri seviyesinde saklanır ve her sahne üretiminde modele
girdi olarak verilir.

## Kurulum

```
pip install -r requirements.txt
```

`ANTHROPIC_API_KEY` ortam değişkenini ayarlayın. İsterseniz proje kökündeki
`.env` dosyasına yazın (`python-dotenv` otomatik okur); `.env` sürüm kontrolüne
girmez.

## Çalıştırma

```
streamlit run senaryo_studyo.py
```

## Testler

Ağ erişimi gerektirmez; LLM çağrıları sahte fonksiyonlarla değiştirilir.

```
python -m pytest test_senaryo_studyo.py -q
```

## Akış

1. **Seri oluştur** — ad, hedef kitle, görsel tarz.
2. **Hikâyeyi gir** — bölüm no, başlık, metin.
3. **Karakter ve mekânları çıkar** — LLM hikâyedeki varlıkları bulur; mevcut
   kataloglarla eşleşenler yeniden kullanılır, yeniler **aday** olarak listelenir.
4. **Adayları onayla** — düzenleyip kataloglara ekleyin (`karakterler.json`,
   `mekanlar.json`).
5. **Sahneleri üret** — hikâye sırasıyla sahnelere bölünür.
6. **Senaryoyu kaydet** — JSON'u düzenleyip kaydedin.
7. **Intro / Outro** — seriye özel bir kez tanımlanır, bölümlerde yeniden üretilmez.

Kaynak hikâye metni model tarafından yeniden yazılmaz; `narration` ve `dialogue`
kaynak cümleleri olduğu gibi taşır.

## Dosya düzeni

```
senaryo_modelleri.py    Pydantic veri sözleşmeleri (tek doğruluk kaynağı)
senaryo_motoru.py       Claude çağrıları + saf eşleştirme/doğrulama fonksiyonları
seri_deposu.py          Disk deposu; seri/bölüm/katalog dosya yolları
senaryo_studyo.py       Streamlit arayüzü
test_senaryo_studyo.py  Çevrimdışı testler

seriler/<series_id>/
  seri.json
  karakterler.json      seri geneli kalıcı karakter kimlikleri
  mekanlar.json         seri geneli kalıcı mekân kimlikleri
  intro/intro.json
  outro/outro.json
  assets/               seri medyası (örn. muzik.mp3)
  bolumler/<NNN>_<slug>/
    hikaye.txt          kaynak hikâye (olduğu gibi)
    senaryo.json        üretilmiş sahne listesi
```

Bölüm klasörünün `slug` kısmı her kayıtta başlıktan yeniden türetilir; başlık
değişirse yeni klasör açılır ve eski klasör otomatik silinmez.

## Doğrulama katmanları

- `senaryo_modelleri.py` yalnızca **yapısal** doğrulama yapar (zorunlu alanlar,
  sahne sırası benzersizliği, pozitif süre).
- `seri_deposu.senaryo_referanslarini_dogrula` **referans** doğrulaması yapar:
  senaryodaki her `character_id` / `location_id` katalogda bulunmalıdır.
- Aynı kontrol intro/outro için de `*_kaydet` içinde çalışır.

## Durum alanları

`intro`/`outro` üzerindeki `status` (`draft`, `approved`, `producing`, `ready`,
`locked`, `failed`) **elle** işaretlenir; hiçbir durum düzenlemeyi kısıtlamaz.
`status` ve `revision` alanları dışındaki içerik değiştiğinde artar
(`senaryo_modelleri.revizyon_artir`).

## Henüz yok

- Görsel / video / ses üretimi. `seri_deposu.intro_medya_yolu` ve
  `outro_medya_yolu` hedef yolları tanımlar, üretim kodu yoktur.
- Uzun hikâyelerde parçalama (chunking); şu an tek istek gönderilir.
