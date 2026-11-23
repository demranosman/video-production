"""Video formatı ve içerik türü tanımları.

Format, senaryo motoruna sahne sayısı/süre hedefi verir; medya motoru da
en-boy oranını buradan alır. Tek doğruluk kaynağı burasıdır.
"""
from __future__ import annotations

FORMATLAR: dict[str, dict] = {
    "kisa": {
        "ad": "Kısa (Shorts/Reels, 30-90 sn)",
        "sahne": (4, 8),
        "sure_sn": (30, 90),
        "sahne_sure_sn": (4, 12),
        "en_boy": "9:16",
        "ritim": "İlk 2 saniyede kanca; hızlı kesme; tek fikir.",
    },
    "orta": {
        "ad": "Orta (2-5 dk)",
        "sahne": (8, 15),
        "sure_sn": (120, 300),
        "sahne_sure_sn": (10, 25),
        "en_boy": "16:9",
        "ritim": "Giriş-gelişme-sonuç; sahne başına tek olay.",
    },
    "uzun": {
        "ad": "Uzun (6-20 dk)",
        "sahne": (15, 40),
        "sure_sn": (360, 1200),
        "sahne_sure_sn": (12, 40),
        "en_boy": "16:9",
        "ritim": "Bölümler halinde akış; her 3-5 sahnede küçük bir doruk.",
    },
}

TURLER: dict[str, dict] = {
    "genel": {
        "ad": "Genel / Hikâye",
        "kural": (
            "Akıcı bir anlatı kur. Olayları nedensellik zinciriyle sırala; "
            "karakter motivasyonu ve duygu değişimi görünür olsun."
        ),
    },
    "masal": {
        "ad": "Çocuk masalı",
        "kural": (
            "Hedef yaşa uygun kısa, olumlu cümleler kullan. Tek bir moral ver. "
            "Korkutucu görüntü, şiddet veya üzücü son yok. Hayvan karakterler "
            "sevimli insansı kıyafetler giyer (yelek, elbise, şapka, atkı); "
            "kıyafet default_clothing alanına yazılır."
        ),
    },
    "belgesel": {
        "ad": "Belgesel",
        "kural": (
            "Tarih, isim ve sayı uydurma; kaynakta olmayan olguyu yazma. "
            "Gerçek kişilerin yüzünü tanınır biçimde üretme; silüet, geniş çekim "
            "veya arkadan görünüm kullan. Dönem/mekân detaylarında anakronizm yok."
        ),
    },
    "gezi": {
        "ad": "Gezi",
        "kural": (
            "Mekânı ve atmosferi öne çıkar; rota sırasını koru. Pratik bilgi "
            "(ulaşım, süre, ipucu) ver ama kaynakta olmayan fiyat/saat uydurma."
        ),
    },
    "egitici": {
        "ad": "Eğitici / Nasıl yapılır",
        "kural": (
            "Adımları sırayla ve eksiksiz anlat. Her adım tek sahnede netleşsin; "
            "güvenlik uyarılarını atlama. Kaynakta olmayan adım ekleme."
        ),
    },
}


def format_ayari(ad: str) -> dict:
    if ad not in FORMATLAR:
        raise ValueError(f"Geçersiz format: {ad}. Seçenekler: {', '.join(FORMATLAR)}")
    return FORMATLAR[ad]


def tur_ayari(ad: str) -> dict:
    if ad not in TURLER:
        raise ValueError(f"Geçersiz tür: {ad}. Seçenekler: {', '.join(TURLER)}")
    return TURLER[ad]
