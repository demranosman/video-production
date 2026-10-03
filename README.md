# Hikâyeden Senaryo ve Video Üretim Stüdyosu

Bir hikâye metnini alıp karakter ve mekân kataloğunu çıkaran, seri boyunca tutarlılığı sağlayan, sahneleme yapıp senaryo üreten ve **OpenMontage** entegrasyonu ile otomatik sahne görseli, seslendirme ve video montajı gerçekleştiren uçtan uca üretim stüdyosu.

---

## 🎯 Amaç

1. **Görsel & Karakter Tutarlılığı:** Bir serinin tüm bölümlerinde karakterlerin ve mekânların görsel kimliğini (`visual_identity`, `default_clothing`, `consistency_rules`) korumak.
2. **Akıllı Senaryo Bölümleme:** Hikâyenin kaynak metnini bozmadan sahneler, anlatıcı/diyalog metinleri ve görsel/video promptları üretmek.
3. **OpenMontage ile Çoklu Video Sağlayıcı & Akıllı Fallback:**
   - Runway Gen-3 / Gen-4
   - Google Veo 2 / Veo 3
   - Gemini Omni
   - OpenAI Sora 2
   - Kling, Minimax, Seedance ve diğer OpenMontage sağlayıcıları
   - Bir sağlayıcıda kota tükenmesi (`quota_exhausted`), yetkilendirme veya geçici hata meydana geldiğinde sahne görselini yeniden üretmeye gerek kalmadan bir sonraki sağlayıcıya otomatik geçiş (graceful fallback).
4. **Uçtan Uca Medya Hattı (Pipeline):**
   - **Görsel:** Gemini / Imagen referans destekli sahne görseli üretimi (`_sahne.png`).
   - **Video:** OpenMontage `VideoSelector` aracılığıyla image-to-video üretimi.
   - **Ses:** Google Cloud Text-to-Speech (TTS) ile karakter ve anlatıcı seslendirmesi.
   - **Montaj:** `ffmpeg` ile video ve sesin senkron birleştirilmesi ve bölümlerin nihai film haline getirilmesi.

---

## 📁 Proje Mimarisi ve Dosya Düzeni

```text
senaryo-video-uretim/
├── senaryo_modelleri.py        # Pydantic veri modelleri ve doğrulama
├── senaryo_motoru.py           # Claude / LLM çağrıları, varlık eşleme ve prompt paketleri
├── senaryo_studyo.py           # Streamlit web stüdyo arayüzü
├── seri_deposu.py              # Dizin yönetimi, seriler ve katalog saklama
├── test_senaryo_studyo.py      # Senaryo ve stüdyo testleri
│
├── video_motoru_openmontage.py # Ana video üretim motoru (Görsel + TTS + Video + Montaj)
├── video_motoru.py             # Alternatif / doğrudan video motoru
├── video_provider_router.py    # OpenMontage video_selector adaptörü ve fallback yöneticisi
├── video_provider_policy.json  # Video sağlayıcı öncelik ve fallback politikası
├── video_uretim.py             # Video üretim boru hattı komut satırı tetikleyicisi
├── test_video_router.py        # OpenMontage sağlayıcı ve politika doğrulama testi
│
├── .vscode/settings.json       # Editör arama yolları (OpenMontage extraPaths)
├── pyrightconfig.json          # Pyright / Pylance statik analiz yapılandırması
├── requirements.txt            # Python bağımlılıkları
│
└── seriler/<series_id>/
    ├── seri.json               # Seri temel bilgileri ve hedef kitle
    ├── karakterler.json        # Seri geneli kalıcı karakter kimlikleri
    ├── mekanlar.json           # Seri geneli kalıcı mekân kimlikleri
    ├── intro/intro.json        # Seri intro tanımı
    ├── outro/outro.json        # Seri outro tanımı
    ├── referanslar/            # Karakter ve stil referans görselleri
    ├── gorsel_promptlar/       # Üretilen prompt paketleri (TR/EN)
    └── bolumler/<NNN>_<slug>/
        ├── hikaye.txt          # Kaynak hikâye metni
        ├── senaryo.json        # Sahne listesi ve diyaloglar
        └── final_video.mp4     # Birleştirilmiş nihai bölüm videosu
```

---

## ⚙️ Kurulum

### 1. Python Sanal Ortamı ve Paketler

Python 3.10 veya üzeri önerilir:

```bash
# Sanal ortam oluşturun ve aktif edin
python -m venv venv
.\venv\Scripts\activate   # Windows

# Bağımlılıkları yükleyin
pip install -r requirements.txt
```

### 2. Harici Sistem Gereksinimi: FFmpeg

Video ve ses birleştirme işlemleri için sisteminizde `ffmpeg` kurulu ve sistem ortam değişkenlerine (`PATH`) eklenmiş olmalıdır:
```bash
ffmpeg -version
```

### 3. OpenMontage Reposu ve Entegrasyonu

Video üretiminde çoklu sağlayıcı (Runway, Veo, Gemini Omni, Sora vb.) desteği için **OpenMontage** reposu kullanılır.

1. **Repo Konumu:**
   OpenMontage reposunu proje dizininin yanına veya masaüstüne yerleştirin:
   - Varsayılan konum: `C:\Users\fikret\Desktop\OpenMontage` (veya `../OpenMontage`)
2. **Sanal Ortama Bağlama (.pth):**
   IDE ve Python'un OpenMontage araçlarını doğrudan bulabilmesi için `venv\Lib\site-packages\openmontage.pth` dosyasına OpenMontage klasör yolu yazılmıştır:
   ```text
   C:\Users\fikret\Desktop\OpenMontage
   ```
3. **Alternatif Ortam Değişkeni:**
   Farklı bir dizinde çalışıyorsanız `.env` dosyasına veya sisteminize tanımlayabilirsiniz:
   ```bash
   OPENMONTAGE_PATH="D:\Projeler\OpenMontage"
   ```

### 4. Ortam Değişkenleri (`.env`)

Proje kök dizininde bir `.env` dosyası oluşturun (`.gitignore` korumalıdır):

```env
# Senaryo ve Varlık Çıkarımı (Claude)
ANTHROPIC_API_KEY="sk-ant-..."

# Sahne Görselleri ve Gemini Video Modelleri
GEMINI_API_KEY="AIzaSy..."

# Google Cloud Text-to-Speech (Seslendirme)
GOOGLE_APPLICATION_CREDENTIALS="C:\yol\to\gen-lang-client-credentials.json"

# Video Sağlayıcıları (İhtiyaca ve policy'e göre)
RUNWAYML_API_SECRET="key_..."
OPENAI_API_KEY="sk-proj-..."

# OpenMontage Yolu (Gerekirse)
OPENMONTAGE_PATH="C:\Users\fikret\Desktop\OpenMontage"
VIDEO_PROVIDER_POLICY="video_provider_policy.json"
```

---

## 🚀 Kullanım

### 1. Senaryo Stüdyosu (Web UI)

Hikâyeyi girmek, karakterleri/mekânları onaylamak ve senaryo üretmek için Streamlit arayüzünü başlatın:

```bash
streamlit run senaryo_studyo.py
```

**Adımlar:**
1. **Seri Oluştur:** Ad, hedef kitle ve görsel stil belirleyin.
2. **Karakter ve Mekânları Tanımla:** Varlıkları oluşturun ve referans görsellerini yükleyin.
3. **Hikâyeyi Sahneleştir:** Kaynak metni girin; LLM sahneleri, diyalogları ve promptları üretsin.
4. **Görsel Prompt Paketi:** Tüm sahneler için Türkçe veya İngilizce prompt paketini dışa aktarın.

### 2. Video Üretim Hattı (Pipeline)

Hazırlanan senaryodan tam video (sahne görselleri + seslendirme + video üretimi + montaj) oluşturmak için:

```bash
# Belirli bir senaryo dosyası üzerinden üretim:
python video_uretim.py seriler/pamuk_tiltu_ve_kiko_orman_dostlari/bolumler/001_pamuk_un_kaybolan_havuclari/senaryo.json

# Veya varsayılan senaryo ile:
python video_motoru_openmontage.py
```

**Üretim Aşamaları:**
1. **Seslendirme (TTS):** Her sahnenin anlatıcı ve diyalog sesleri Google Cloud TTS ile oluşturulur.
2. **Sahne Görseli:** Gemini / Imagen ile karakter referansları dikkate alınarak yüksek çözünürlüklü sahne karesi oluşturulur (`_sahne.png`).
3. **OpenMontage Router:** Sahne görseli ve video promptu `video_provider_router.py` aracılığıyla sıradaki video modeline iletilir.
4. **Montaj:** Sahne videosu ve ses dosyaları `ffmpeg` ile birleştirilir; bölümün tüm sahneleri sırayla nihai videoda toplanır.

### 3. OpenMontage Sağlayıcı ve Politika Testi

Kayıtlı video sağlayıcılarının durumunu ve fallback politikasını test etmek için:

```bash
python test_video_router.py
```

Örnek çıktı:
```text
[CHECK] OpenMontage: C:\Users\fikret\Desktop\OpenMontage
[CHECK] Registry video provider sayısı: 26
[CHECK] Kullanılabilir providerlar: ['ark', 'cogvideo', 'gemini_omni', 'kling', 'openai', 'runway', 'veo', 'wan', ...]
[CHECK] Policy sırası: runway -> veo -> gemini_omni -> openai
[PASS] Policy'deki tüm providerlar kullanılabilir.
```

### 4. Senaryo Doğrulama Testleri

Çevrimdışı Pydantic ve mantıksal doğrulama testlerini çalıştırmak için:

```bash
python -m pytest test_senaryo_studyo.py -v
```

---

## 🔄 Video Sağlayıcı Fallback Politikası (`video_provider_policy.json`)

Pipeline, tek bir video sağlayıcısına bağımlı kalmaz. `video_provider_policy.json` dosyası üzerinden öncelik sırası ve hata toleransı yönetilir:

- **Öncelik Sırası (`preferred_order`):**
  1. `runway` (Runway Gen-3 / Gen-4)
  2. `veo` (Google Veo)
  3. `gemini_omni` (Gemini Omni video)
  4. `openai` (Sora 2)
- **Hata Yönetimi:**
  - Kota dolduğunda (`429`, `insufficient credits`, `quota_exhausted`), yetkilendirme hatasında veya servis kapalı olduğunda otomatik olarak bir sonraki sağlayıcıya geçer (`next_provider`).
  - Geçici ağ hatalarında 1 kez yeniden dener (`retry_then_next`).
  - Sahne görseli (`_sahne.png`) korunur; fallback sırasında görsel yeniden üretilmez, böylece hem bütçe hem de görsel süreklilik korunur.
