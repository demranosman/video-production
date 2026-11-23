# Senaryo & Video Stüdyosu

Fikir veya hikâyeden senaryo üretip **kısa (Shorts/Reels), orta ve uzun metraj** video üreten tek Python/Streamlit uygulaması.

Ana hat: **fikir/hikâye → Mistral senaryo → Gemini görsel → Runway/Veo 3.1 hareket + native ses → FFmpeg master**

## Ne yapar

- Fikri hikâyeye genişletir, hikâyeden karakter/mekân çıkarır, sahnelere böler (Mistral; istenirse Claude).
- Format ve türe göre sahne sayısı/süresi hedefli senaryo üretir.
- Her karakter için bir kez referans portre üretir (Gemini); sahneleri bu referanslarla üretir.
- Sahneleri Runway/Veo 3.1 ile hareketli videoya çevirir; native sesi korur.
- Ekonomik modda FFmpeg Ken Burns veya fal.ai + ElevenLabs kullanır.
- Intro/outro kartı, altyazı yakma, gerçek medya kolajı ve FFmpeg birleştirme yapar.
- Üretim arka planda çalışır; Streamlit kilitlenmez, kaldığı yerden devam eder.

## Hızlı başlangıç

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env         # anahtarları doldurun
streamlit run app.py
```

FFmpeg ve ffprobe PATH'te olmalı. OpenMontage `D:\OpenMontage` altında beklenir; farklıysa `.env` içinde `OPENMONTAGE_PATH` ayarlayın.

## Tek akış

1. **Proje oluştur** — ad, tür, format, görsel tarz, hedef kitle.
2. **Senaryo** — “Fikir” veya “Hazır hikâye”; *Senaryoyu oluştur*.
3. **Düzenle** — hikâye, logline, sahne anlatımı, görsel komut, kamera hareketi, süre, gerçek medya.
4. **Üret** — video modu, intro/outro, altyazı; *Videoyu üret*.
5. **Video** — önizle, MP4 indir, klipleri yeniden birleştir.

## Formatlar

| Format | Sahne | Hedef süre | En-boy | Kullanım |
|---|---|---|---|---|
| Kısa | 4-8 | 30-90 sn | 9:16 | Shorts, Reels, TikTok |
| Orta | 8-15 | 2-5 dk | 16:9 | YouTube, tanıtım |
| Uzun | 15-40 | 6-20 dk | 16:9 | Belgesel, eğitim, uzun hikâye |

## Üretim modları

| Mod | Görsel | Hareket | Ses | Not |
|---|---|---|---|---|
| **OpenMontage + native (varsayılan)** | Gemini | Veo 3.1 → Runway | Veo/Runway native audio | Sahne 4-8 sn; kısa video |
| OpenMontage + ElevenLabs | Gemini | Veo 3.1 → Runway (sessiz) | ElevenLabs anlatım | Uzun metraj, kontrollü ses |
| Resim | Gemini | FFmpeg Ken Burns | ElevenLabs (opsiyonel) | En ekonomik |
| Hareketli | Gemini | fal.ai Kling | ElevenLabs | fal.ai anahtarı gerekir |

OpenMontage sağlayıcı sırası `video_provider_policy.json` içindedir (`veo → runway → gemini_omni → openai`); Veo erişimi yoksa Runway otomatik devreye girer. Native ses modunda sahneler `NATIVE_MAX_SN` (varsayılan 8 sn) ile sınırlanır; uzun videolarda ElevenLabs modu önerilir.

## Gerekli anahtarlar

- `MISTRAL_API_KEY` — senaryo (varsayılan). Alternatif: `ANTHROPIC_API_KEY`, `LLM_PROVIDER=claude`.
- `GEMINI_API_KEY` — görseller ve (varsa) Veo.
- `RUNWAY_API_KEY` veya `RUNWAYML_API_SECRET` — Runway video sağlayıcısı.
- `ELEVENLABS_API_KEY` — yalnızca resim/hareketli modda seslendirme.
- `FAL_API_KEY` — yalnızca hareketli mod.
- `OPENMONTAGE_PATH` — varsayılan `D:\OpenMontage`.

## Maliyet (video başına)

Liste fiyatları (2026-11 itibarıyla, sağlayıcı değiştirebilir — kendi hesabınızdan doğrulayın):

| Kalem | Birim | Kaynak |
|---|---|---|
| Gemini 3 Pro Image (sahne görseli + karakter referansı) | ~$0.134 / görsel (2K), ~$0.24 (4K) | ai.google.dev/gemini-api/docs/pricing |
| Veo 3.1 / Runway i2v | ~$0.05–0.40 / saniye (modele göre) | dev.runway.com/pricing · ai.google.dev/gemini-api/docs/pricing |
| ElevenLabs (turbo v2.5) | ~$0.04 / 1.000 karakter | elevenlabs.io/pricing/api |
| Mistral / Claude (senaryo) | token başına; video maliyeti yanında ihmal edilebilir | — |

Kaba formül: `görsel_sayısı × $0.134  +  klip_saniyesi × sn_fiyatı  +  (karakter/1000) × $0.04`

Çağrı sayısını kod hesaplıyor: `medya_motoru.tahmini_cagri_sayilari(senaryo, video_modu, seslendirme)`.
Örnek — 6 sahne, 8 sn klip (native ses), 600 karakter anlatım:

- **OpenMontage (Veo/Runway)** — 6 × $0.134 = $0.80 görsel + 48 sn klip. Klip $0.05/sn ise **~$3.2**, $0.40/sn ise **~$19.9**. En pahalı mod.
- **Resim modu (FFmpeg Ken Burns) + ElevenLabs** — $0.80 + $0.024 ≈ **$0.83**. Uzun metrajda tek pratik seçenek.
- **Hareketli (fal.ai Kling)** — $0.80 + sahne başına 5 sn'lik klip sayısı kadar fal ücreti.

Uzun metraj = klip saniyesi = maliyet. 20 dk'lık video native modda 1.200 sn klip ister; bu yüzden uzun formatta
`openmontage` yerine `resim` + ElevenLabs önerilir.

> Risk: Veo 3.1 **preview** modelleri Gemini API'de 22 Ekim 2026'da kapatıldı; bu proje Veo'yu Runway üzerinden
> (`RUNWAY_VIDEO_MODEL=veo3.1_fast`) çağırıyor. Model adı Runway tarafında değişirse `video_provider_policy.json`
> sırası `runway`'e düşer — üretim öncesi bir test klibiyle doğrulayın.

## Proje yapısı

```text
app.py                    # tek akışlı Streamlit uygulaması (ana giriş)
uretim_isci.py            # arka plan üretim işçisi + durum JSON'u
senaryo_motoru.py         # Mistral/Claude: fikir, varlık çıkarımı, sahne üretimi
senaryo_modelleri.py      # Pydantic sözleşmeleri
seri_deposu.py            # seri/katalog/senaryo disk deposu
medya_motoru.py           # Gemini + Runway/Veo + FFmpeg + ElevenLabs/fal.ai
formatlar.py              # kısa/orta/uzun format ve tür tanımları
video_provider_router.py  # OpenMontage sağlayıcı fallback'i
video_provider_policy.json
senaryo_studyo.py         # gelişmiş/legacy seri-bölüm arayüzü
test_*.py                 # çevrimdışı testler

seriler/<proje>/
  seri.json, karakterler.json, mekanlar.json
  referanslar/            # karakter referans portreleri
  gorseller/, sesler/, klipler/, medya/
  bolumler/001_video/     # hikaye.txt + senaryo.json
  final_video.mp4, final.srt, uretim_durum.json
```

## Testler

Tek komut (ruff + mypy + unittest):

```bash
pip install -r requirements-dev.txt
venv\Scripts\python.exe check.py     # OK: ruff + mypy + unittest geçti.
```

Ayrı ayrı:

```bash
venv\Scripts\python.exe -m unittest discover -v
venv\Scripts\python.exe -m ruff check .
venv\Scripts\python.exe -m mypy          # dosya listesi pyproject.toml'da
```

Testler LLM ve ücretli API çağrılarını mock'lar; FFmpeg testleri gerçek ffmpeg kullanır, yoksa atlanır. Gerçek Runway/Veo çağrısı testlerde yapılmaz (maliyet).

## Birleştirme notu

- **senaryo-video-uretim** → çekirdek modeller, depo, senaryo motoru, OpenMontage router.
- **SenaryoAI** → Gemini görsel, ElevenLabs TTS, fal.ai hareket, FFmpeg kolaj/altyazı yaklaşımı.
- **ai-storyboard** → storyboard/kare UX referansı; TypeScript kodu taşınmadı.

## Gelişmiş

Seri/bölüm bazlı çoklu bölüm yönetimi ve görsel prompt paketleri için:

```bash
streamlit run senaryo_studyo.py
```
