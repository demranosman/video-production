# DURUM

## Proje amacı
Fikir veya hikâyeden senaryo üretip kısa/orta/uzun metraj video üreten tek Python/Streamlit uygulaması.

## Nihai hat
```text
Fikir / Hikâye
  → Mistral (varsayılan) veya Claude: senaryo + karakter/mekân + sahneler
  → Gemini 3 Pro Image (Nano Banana Pro): sahne görselleri + karakter referansları
  → OpenMontage: Veo 3.1 → Runway → diğer sağlayıcılar (fallback)
       native mod: Veo/Runway native audio
       ElevenLabs mod: sessiz hareket + ElevenLabs anlatım
  → FFmpeg: intro/outro, altyazı yakma, kolaj, final birleştirme
```

## Model / sağlayıcı kararları
- **Senaryo:** Mistral (`mistral-large-latest`) varsayılan. `LLM_PROVIDER=claude` veya Mistral anahtarı yoksa Claude'a düşer.
- **Görsel:** `gemini-3-pro-image` (Nano Banana Pro) — kalite/karakter tutarlılığı için. `GEMINI_IMAGE_MODEL` ile değiştirilebilir.
- **Video:** OpenMontage varsayılan; policy sırası `veo → runway → gemini_omni → openai`. Veo erişimi yoksa Runway otomatik devreye girer.
- **Ses:** Native modda Veo/Runway. Uzun metraj/kontrollü anlatımda ElevenLabs. Ekonomik modlarda ElevenLabs.
- **Birleştirme:** FFmpeg.

## Tamamlananlar
- `app.py`: tek akışlı sihirbaz (Proje → Senaryo → Üretim → Video).
- `formatlar.py`: kısa/orta/uzun format + 5 tür.
- `senaryo_motoru.py`: Mistral/Claude sağlayıcı seçimi ve fallback; fikir genişletme; tür/format hedefli sahne üretimi; narration/dialogue ayrımı.
- `senaryo_modelleri.py`: `Seri.genre/format/target_duration_sec`, `Sahne.image_prompt/motion/media`, `Karakter.voice_id`.
- `medya_motoru.py`:
  - Gemini görsel + karakter referansı
  - Çok sesli ElevenLabs TTS + zaman damgaları
  - FFmpeg Ken Burns, fal.ai segment zincirleme
  - OpenMontage (Veo/Runway) + native audio + sağlayıcı fallback
  - OpenMontage + ElevenLabs (sessiz hareket + anlatım)
  - Intro/outro drawtext kartları
  - SRT üretimi ve FFmpeg ile altyazı yakma
  - Gerçek fotoğraf/video kolajı
  - Kaldığı yerden devam (geçerli klipler atlanır)
- `uretim_isci.py`: arka plan üretim işçisi + `uretim_durum.json`; Streamlit kilitlenmez.
- `video_provider_router.py`: `D:\OpenMontage` otomatik bulma, aspect ratio, sağlayıcıya özgü süre biçimi (Runway int / Veo "8s"), fallback.
- `.env.example`, `README.md`, `DURUM.md` güncellendi.
- Eski `senaryo_studyo.py` gelişmiş arayüz olarak korundu.

## Test kanıtı
```text
$ venv/Scripts/python.exe -m unittest discover
Ran 146 tests in 4.888s
OK

$ ruff check .
All checks passed!

$ mypy --ignore-missing-imports app.py medya_motoru.py senaryo_motoru.py \
       senaryo_modelleri.py seri_deposu.py uretim_isci.py \
       video_provider_router.py formatlar.py
(çıktı yok — hata yok)
```

Gerçek FFmpeg uçtan uca testi (OpenMontage mock, native ses, intro/outro, altyazı):
```text
Sahne 1: Runway/Veo üretiyor...
Intro kartı hazırlanıyor...
Final video birleştiriliyor... Video hazır.
final: final_video.mp4 sure: 9.08
altyazi: True
srt: 00:00:02,500 --> 00:00:06,500
```

Arka plan işçisi testi:
```text
rc 0
durum: {'durum': 'bitti', 'oran': 1.0, 'mesaj': 'Video hazır.'}
final var: True
```

Streamlit `AppTest`: proje oluşturma, fikir→senaryo, sahne düzenleyici, medya yükleme, üretim sekmesi ve `openmontage` varsayılanı hatasız render edildi.

## Bilinen sınırlar
- Gerçek ücretli Runway/Veo/Gemini/ElevenLabs çağrıları testlerde çalıştırılmadı; yalnızca FFmpeg + mock ile uçtan uca doğrulandı. İlk gerçek üretimde sağlayıcı kotaları/anahtarları kontrol edilmeli.
- Native ses modunda sahneler `NATIVE_MAX_SN` (varsayılan 8 sn) ile sınırlı. Uzun videolarda native ses yerine ElevenLabs modu önerilir; aksi halde çok sayıda sahne gerekir.
- Veo klibi anlatımdan kısaysa `video_ile_ses` görüntüyü döngüler (maliyet/segment üretimi yerine bu tercih edildi).
- Mistral tek çağrıda büyük senaryolarda `MISTRAL_MAX_TOKENS` sınırına takılabilir; gerekirse `MISTRAL_MAX_TOKENS` artırılmalı veya sahne üretimi parçalanmalı.
- Gezi/belgesel için gerçek medya kolajı vardır; arşiv görseli otomatik indirme yoktur.

## Dizin bağımlılığı
Çalışma zamanı için gerekli:
- `D:\senaryo-video-uretim` (bu proje)
- `D:\OpenMontage` (video sağlayıcıları)
- FFmpeg + ffprobe (PATH veya `FFMPEG_BIN_DIR`)

Artık gerekli değil:
- `D:\SenaryoAI` — medya hattı bu projeye uyarlandı. Yalnızca `.env` anahtarları ve eski `hikaye/` varlıkları taşınmak istenirse bakılır.
- `D:\ai-storyboard` — yalnızca UX referansıydı; kodu taşınmadı.

Bu iki dizin arşivlenebilir/silinmeden önce: `.env` içindeki anahtarları bu projenin `.env` dosyasına kopyalayın; saklamak istediğiniz hikâye/görsel varlıkları varsa `seriler/` altına taşıyın.

## Tamamlananlar (ürünleştirme, 2026-11-23)
- `LICENSE` (MIT), `requirements-dev.txt`, `check.py` (tek komut: ruff + mypy + unittest).
- `pyproject.toml`: ruff (E4,E7,E9,F,I,B,UP,RET, ll=120) + mypy (ignore_missing_imports) yapılandırması.
- `ruff --fix` 6 bulguyu düzeltti; testler yeniden koşuldu: 146 OK, ruff temiz, mypy temiz.
- Kök dizindeki `gen-lang-client-*.json` (Google service account, hiçbir kodda referansı yok)
  `C:\Users\fikret\.senaryo-secrets\` altına taşındı. **Anahtar hâlâ döndürülmedi/iptal edilmedi.**
- Eski `test-raporu.json` silindi (45 lint bulgulu, başka makine yolunu gösteren bayat çıktı).
- `.gitignore`: `.coverage`, `.mypy_cache/`, `.ruff_cache/`, `.jscpd-report/`, `test-raporu.json`.
- `README.md`: "Maliyet (video başına)" bölümü (görsel/klip/TTS birim fiyatları + kaba formül + 3 örnek).

## Açık işler
1. Tüm çalışma ağacı ilk kez commit'lendi (2026-11-23). **Remote yok** — `git remote add origin <url> && git push -u origin master`.
2. Service account anahtarını Google Cloud üzerinden iptal et (dosya taşındı, anahtar geçerli).
3. Veo 3.1 preview modelleri Gemini API'de 22 Ekim 2026'da kapatıldı; bu hat Veo'yu Runway
   üzerinden (`RUNWAY_VIDEO_MODEL=veo3.1_fast`) çağırıyor. Gerçek üretimden önce tek kliplik
   doğrulama yap; model adı değiştiyse `video_provider_policy.json` sırasını güncelle.
4. Gerçek Mistral + Gemini + Runway/Veo ile ilk üretim denemesi ve çıktı kalitesi ayarı.
5. Uzun metrajda native ses yerine otomatik "ElevenLabs'a geç" önerisi (format bazlı).
6. Mistral uzun senaryo için parçalı üretim.

## Test komutları
```bash
venv/Scripts/python.exe check.py          # ruff + mypy + unittest (önerilen)
venv/Scripts/python.exe -m unittest discover -v
venv/Scripts/python.exe -m ruff check .
venv/Scripts/python.exe -m mypy           # dosya listesi pyproject.toml'da
```
