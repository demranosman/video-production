"""Bağımsız hikâyeden senaryo üretim stüdyosu.

Çalıştırma:
    streamlit run senaryo-uretim/senaryo_studyo.py
"""
import json

import streamlit as st
from dotenv import load_dotenv

import senaryo_modelleri as modeller
import senaryo_motoru as motor
import seri_deposu as depo

load_dotenv()

st.set_page_config(page_title="Senaryo stüdyosu", layout="wide")

GORSEL_TARZLAR = [
    "Sinematik 3D animasyon, yumuşak ışık, canlı renkler",
    "Fotorealistik sinematik film karesi, doğal ışık",
    "Koyu tonlu çizgi roman, dramatik gölgeler",
    "Klasik yağlı boya tablo, belirgin fırça darbeleri",
    "El çizimi anime estetiği, ayrıntılı arka planlar",
]
OZEL_TARZ = "Özel tarz (kendin yaz)"

st.session_state.setdefault("series_id", None)
st.session_state.setdefault("cikarilan", None)
st.session_state.setdefault("senaryo", None)
st.session_state.setdefault("gorsel_prompt_paketi", None)


def _seriyi_sec(yeni_series_id: str) -> None:
    """Seri değişirse önceki seriye ait bölüm state'ini temizler.

    Aksi halde yeni seride eski serinin hikâyesi/senaryosu kaydedilebilir.
    """
    if st.session_state.series_id == yeni_series_id:
        return
    st.session_state.series_id = yeni_series_id
    st.session_state.cikarilan = None
    st.session_state.senaryo = None
    st.session_state.gorsel_prompt_paketi = None
    st.session_state.hikaye_metni = ""
    st.session_state.pop("bolum_no", None)
    st.session_state.pop("bolum_baslik", None)
    for anahtar in list(st.session_state.keys()):
        if anahtar.startswith("aday_karakter_") or anahtar.startswith("aday_mekan_"):
            del st.session_state[anahtar]


def _karakter_katalogu() -> modeller.KarakterKatalogu:
    return depo.karakterleri_yukle(st.session_state.series_id)


def _mekan_katalogu() -> modeller.MekanKatalogu:
    return depo.mekanlari_yukle(st.session_state.series_id)


def _kayitli_senaryolar(series_id: str) -> list[modeller.Senaryo]:
    """Yalnızca diske kaydedilmiş bölümleri görsel prompt paketine ekler."""
    return [
        depo.senaryo_yukle(series_id, bolum["episode_no"], bolum["slug"])
        for bolum in depo.bolumler(series_id)
        if bolum["senaryo_var"]
    ]


MEKAN_YOK = "— mekân yok —"
DURUMLAR = ["draft", "approved", "producing", "ready", "locked", "failed"]


def _mekan_secenekleri(mekanlar: list[modeller.Mekan], mevcut_location_id: str = ""):
    """(seçenekler, varsayılan index, etiket eşlemesi) döner. Mekân zorunlu değildir."""
    etiketler = {m.location_id: m.name for m in mekanlar}
    secenekler = [MEKAN_YOK, *etiketler]
    index = secenekler.index(mevcut_location_id) if mevcut_location_id in etiketler else 0
    return secenekler, index, etiketler


# --- Kenar çubuğu: seri seçimi/oluşturma ---
with st.sidebar:
    st.header("Seri")
    mevcut = depo.serileri_listele()
    secenekler = ["— yeni seri —", *mevcut]
    secim = st.selectbox("Mevcut seriler", secenekler, key="seri_secim")
    if secim != "— yeni seri —" and st.button("Seriyi seç", icon=":material/folder_open:"):
        _seriyi_sec(secim)
        st.rerun()

    st.divider()
    with st.form("yeni_seri_form"):
        st.subheader("Yeni seri")
        seri_adi = st.text_input("Seri adı", key="yeni_seri_adi")
        hedef_yas = st.text_input("Hedef kitle", key="yeni_seri_yas")
        stil_secim = st.selectbox("Görsel tarz", [*GORSEL_TARZLAR, OZEL_TARZ], key="yeni_seri_stil_secim")
        if stil_secim == OZEL_TARZ:
            stil = st.text_input("Özel tarz açıklaması", key="yeni_seri_stil_ozel")
        else:
            stil = stil_secim
        aciklama = st.text_area("Seri açıklaması", height=80, key="yeni_seri_aciklama")
        olustur = st.form_submit_button("Seriyi oluştur", type="primary", icon=":material/add:")
    if olustur:
        try:
            seri = depo.seri_olustur(
                seri_adi, description=aciklama, target_audience=hedef_yas, visual_style=stil
            )
            _seriyi_sec(seri.series_id)
            st.rerun()
        except ValueError as hata:
            st.error(str(hata))

series_id = st.session_state.series_id
if not series_id:
    st.info("Soldan bir seri oluşturun veya mevcut bir seriyi seçin.")
    st.stop()

seri = depo.seri_yukle(series_id)
st.title(seri.name)
st.caption(seri.description or "Seri açıklaması yok")

rehber_tab, hikaye_tab, bolumler_tab, karakter_tab, mekan_tab, intro_tab, outro_tab, gorsel_tab, disa_tab = st.tabs(
    ["Rehber", "Hikâyeden senaryo", "Bölümler", "Karakterler", "Mekânlar", "Intro", "Outro", "Görsel promptlar", "Dışa aktar"]
)

# ============================================================
# Rehber
# ============================================================
with rehber_tab:
    st.subheader("Adım adım kullanım rehberi")
    st.markdown(
"""
1. **Seri oluştur** — Sol panelden seri adını, hedef kitleyi ve görsel tarzı seçip
   "Seriyi oluştur" deyin. Her hikâye bir seriye bağlıdır.
2. **Hikâyeyi gir** — "Hikâyeden senaryo" sekmesinde bölüm numarası, bölüm başlığı
   ve hikâye metnini yazın.
3. **Karakter ve mekânları çıkar** — "Karakter ve mekânları çıkar" butonuna basın.
   Yapay zekâ hikâyedeki kişileri ve mekânları bulur; mevcut olanlar eşleşir,
   yeniler aday olarak listelenir.
4. **Adayları onayla** — Yeni karakter/mekân tanımlarını düzenleyip
   "Adayları onayla ve kataloglara ekle" deyin. Onaylananlar `karakterler.json`
   ve `mekanlar.json` dosyalarına kaydedilir.
5. **Sahneleri üret** — "Sahneleri üret" butonu hikâyeyi sırasıyla sahnelere böler
   ve düzenlenebilir senaryo JSON'u üretir.
6. **Senaryoyu kaydet** — Gerekirse JSON'u düzenleyip "Senaryoyu kaydet" deyin.
   Bölüm `bolumler/<no>/senaryo.json` altına yazılır.
7. **Intro ve outro** — "Intro" ve "Outro" sekmelerinde seriye özel tanımları
   bağımsız hazırlayıp kaydedin. Bunlar bölüm başına yeniden üretilmez.
8. **Görsel promptlar** — Kaydedilen sahneler, karakterler, mekânlar, intro ve
   outro için Türkçe veya İngilizce üretim paketi oluşturun.
9. **Dışa aktar** — "Dışa aktar" sekmesinden JSON dosyalarını indirin.

> **Not:** Karakterler ve mekânlar seri seviyesinde saklanır; yeni bir hikâyede aynı
> isim bulunursa mevcut kayıt yeniden kullanılır ve üzerine yazılmaz.
"""
    )

# ============================================================
# Hikâyeden senaryo
# ============================================================
with hikaye_tab:
    mevcut_bolumler = depo.bolumler(series_id)
    sonraki_no = max((b["episode_no"] for b in mevcut_bolumler), default=0) + 1

    st.subheader("Hikâye girişi")
    with st.form("hikaye_form"):
        c1, c2 = st.columns(2)
        with c1:
            bolum_no = st.number_input("Bölüm numarası", min_value=1, value=sonraki_no, step=1)
        with c2:
            bolum_baslik = st.text_input("Bölüm başlığı")
        hikaye_metni = st.text_area(
            "Hikâye metni",
            placeholder="Hikâyeyi buraya yapıştırın.",
            height=220,
        )
        cikar = st.form_submit_button("Karakter ve mekânları çıkar", type="primary", icon=":material/search:")

    if cikar:
        try:
            if not bolum_baslik.strip():
                raise ValueError("Bölüm başlığı boş olamaz.")
            # Önceki çıkarımdan kalan aday düzenleme anahtarlarını temizle.
            for anahtar in list(st.session_state.keys()):
                if anahtar.startswith("aday_karakter_") or anahtar.startswith("aday_mekan_"):
                    del st.session_state[anahtar]
            st.session_state.cikarilan = motor.varlik_cikar(hikaye_metni)
            st.session_state.senaryo = None
            st.session_state.bolum_no = int(bolum_no)
            st.session_state.bolum_baslik = bolum_baslik.strip()
            st.session_state.hikaye_metni = hikaye_metni
            st.rerun()
        except Exception as hata:
            st.error(f"Çıkarım yapılamadı: {hata}")

    cikarilan = st.session_state.cikarilan
    if cikarilan is not None:
        karakterler = _karakter_katalogu()
        mekanlar = _mekan_katalogu()
        eslesen = motor.cikarilanlari_esle(
            cikarilan, karakterler.characters, mekanlar.locations
        )

        st.subheader("Karakterler")
        if not eslesen["characters"]:
            st.caption("Hikâyede karakter bulunamadı.")
        for i, kayit in enumerate(eslesen["characters"]):
            if kayit["matched_character_id"]:
                st.write(f"• **{kayit['name']}** → mevcut: `{kayit['matched_character_id']}`")
            else:
                st.markdown(f"• **{kayit['name']}** → :orange[yeni aday]")
                st.session_state.setdefault(f"aday_karakter_{i}", json.dumps(kayit["candidate"], ensure_ascii=False, indent=2))
                st.text_area(
                    f"Yeni karakter: {kayit['name']}",
                    key=f"aday_karakter_{i}",
                    height=200,
                    label_visibility="collapsed",
                )

        st.subheader("Mekânlar")
        if not eslesen["locations"]:
            st.caption("Hikâyede mekân bulunamadı.")
        for i, kayit in enumerate(eslesen["locations"]):
            if kayit["matched_location_id"]:
                st.write(f"• **{kayit['name']}** → mevcut: `{kayit['matched_location_id']}`")
            else:
                st.markdown(f"• **{kayit['name']}** → :orange[yeni aday]")
                st.session_state.setdefault(f"aday_mekan_{i}", json.dumps(kayit["candidate"], ensure_ascii=False, indent=2))
                st.text_area(
                    f"Yeni mekân: {kayit['name']}",
                    key=f"aday_mekan_{i}",
                    height=200,
                    label_visibility="collapsed",
                )

        if st.button("Adayları onayla ve kataloglara ekle", icon=":material/check:"):
            try:
                bolum_no = int(st.session_state.get("bolum_no", sonraki_no))
                karakter_katalogu = _karakter_katalogu()
                mekan_katalogu = _mekan_katalogu()
                var_karakter = {k.character_id for k in karakter_katalogu.characters}
                var_mekan = {m.location_id for m in mekan_katalogu.locations}

                for i, kayit in enumerate(eslesen["characters"]):
                    if kayit["matched_character_id"]:
                        continue
                    ham = json.loads(st.session_state[f"aday_karakter_{i}"])
                    yeni = motor.adaydan_karakter(ham, series_id, bolum_no)
                    if yeni.character_id in var_karakter:
                        yeni = yeni.model_copy(update={"character_id": f"{yeni.character_id}_2"})
                    karakter_katalogu.characters.append(yeni)
                    var_karakter.add(yeni.character_id)

                for i, kayit in enumerate(eslesen["locations"]):
                    if kayit["matched_location_id"]:
                        continue
                    ham = json.loads(st.session_state[f"aday_mekan_{i}"])
                    yeni = motor.adaydan_mekan(ham, series_id, bolum_no)
                    if yeni.location_id in var_mekan:
                        yeni = yeni.model_copy(update={"location_id": f"{yeni.location_id}_2"})
                    mekan_katalogu.locations.append(yeni)
                    var_mekan.add(yeni.location_id)

                depo.karakterleri_kaydet(karakter_katalogu)
                depo.mekanlari_kaydet(mekan_katalogu)
                st.session_state.cikarilan = None
                st.success("Kataloglar güncellendi.")
                st.rerun()
            except (ValueError, json.JSONDecodeError) as hata:
                st.error(f"Adaylar kaydedilemedi: {hata}")

    st.divider()
    st.subheader("Sahneler")
    if st.button("Sahneleri üret", icon=":material/auto_awesome:", disabled=st.session_state.get("hikaye_metni", "").strip() == ""):
        try:
            bolum_no = int(st.session_state.get("bolum_no", sonraki_no))
            bolum_baslik = st.session_state.get("bolum_baslik", "")
            hikaye_metni = st.session_state.get("hikaye_metni", "")
            if not bolum_baslik.strip():
                raise ValueError("Önce hikâye ve bölüm başlığı girin.")
            episode = modeller.Episode(episode_no=bolum_no, title=bolum_baslik)
            senaryo = motor.sahne_uret(
                hikaye_metni, seri,
                _karakter_katalogu().characters,
                _mekan_katalogu().locations,
                episode,
            )
            st.session_state.senaryo = senaryo.model_dump()
            st.rerun()
        except Exception as hata:
            st.error(f"Sahne üretilemedi: {hata}")

    if st.session_state.senaryo is not None:
        duzenlenen = st.text_area(
            "Senaryo JSON (düzenlenebilir)",
            json.dumps(st.session_state.senaryo, ensure_ascii=False, indent=2),
            height=420,
        )
        if st.button("Senaryoyu kaydet", type="primary", icon=":material/save:"):
            try:
                senaryo = modeller.Senaryo.model_validate(json.loads(duzenlenen))
                # Slug her kayıtta başlıktan yeniden türetilir; oturumda taşınan
                # eski bir değer kullanılırsa başlık değişince yanlış klasöre yazılır.
                slug = depo.slugify(senaryo.episode.title)
                depo.senaryo_kaydet(
                    senaryo,
                    _karakter_katalogu(),
                    _mekan_katalogu(),
                    slug,
                )
                depo.hikaye_kaydet(
                    series_id, senaryo.episode.episode_no, slug,
                    st.session_state.get("hikaye_metni", ""),
                )
                st.success(
                    f"Senaryo ve hikâye kaydedildi: "
                    f"{senaryo.episode.episode_no:03d}_{slug}"
                )
                eski_klasorler = [
                    b["slug"] for b in depo.bolumler(series_id)
                    if b["episode_no"] == senaryo.episode.episode_no and b["slug"] != slug
                ]
                if eski_klasorler:
                    st.warning(
                        "Aynı bölüm numarası için başka klasör(ler) de var: "
                        f"{', '.join(eski_klasorler)}. Başlık değiştiyse eski klasörü elle silin."
                    )
            except Exception as hata:
                st.error(f"Senaryo kaydedilemedi: {hata}")

# ============================================================
# Bölümler (görüntüle ve düzelt)
# ============================================================
with bolumler_tab:
    st.subheader("Bölümleri görüntüle ve düzelt")
    bolum_listesi = depo.bolumler(series_id)
    if not bolum_listesi:
        st.caption("Henüz kayıtlı bölüm yok.")
    else:
        etiketler = {f"{b['episode_no']:03d} — {b['slug'].replace('_', ' ')}": b for b in bolum_listesi}
        secim = st.selectbox("Bölüm", list(etiketler), key="bolum_secim")
        bolum = etiketler[secim]

        hikaye_path = depo.hikaye_yolu(series_id, bolum["episode_no"], bolum["slug"])
        if hikaye_path.exists():
            with st.expander("Hikâye metni"):
                st.text(hikaye_path.read_text(encoding="utf-8"))

        if bolum["senaryo_var"]:
            senaryo = depo.senaryo_yukle(series_id, bolum["episode_no"], bolum["slug"])
            duzenlenen = st.text_area(
                "Senaryo JSON (düzenlenebilir)",
                json.dumps(senaryo.model_dump(), ensure_ascii=False, indent=2),
                height=480,
            )
            if st.button("Bölüm senaryosunu kaydet", type="primary", icon=":material/save:"):
                try:
                    yeni = modeller.Senaryo.model_validate(json.loads(duzenlenen))
                    depo.senaryo_kaydet(
                        yeni, _karakter_katalogu(), _mekan_katalogu(), bolum["slug"]
                    )
                    st.success("Bölüm senaryosu kaydedildi.")
                except Exception as hata:
                    st.error(f"Kaydedilemedi: {hata}")
        else:
            st.caption("Bu bölümde senaryo yok.")

# ============================================================
# Karakterler ve mekânlar (JSON düzenleyici)
# ============================================================
with karakter_tab:
    katalog = _karakter_katalogu()
    st.caption("Karakter kataloğu — kalıcı kimlikler (seri seviyesinde saklanır)")
    ham = st.text_area(
        "Karakterler JSON",
        json.dumps(katalog.model_dump(), ensure_ascii=False, indent=2),
        height=420,
    )
    if st.button("Karakterleri kaydet", icon=":material/save:"):
        try:
            depo.karakterleri_kaydet(modeller.KarakterKatalogu.model_validate(json.loads(ham)))
            st.success("Karakter kataloğu kaydedildi.")
        except Exception as hata:
            st.error(f"Kaydedilemedi: {hata}")

with mekan_tab:
    katalog = _mekan_katalogu()
    st.caption("Mekân kataloğu — kalıcı kimlikler (seri seviyesinde saklanır)")
    ham = st.text_area(
        "Mekânlar JSON",
        json.dumps(katalog.model_dump(), ensure_ascii=False, indent=2),
        height=420,
    )
    if st.button("Mekânları kaydet", icon=":material/save:"):
        try:
            depo.mekanlari_kaydet(modeller.MekanKatalogu.model_validate(json.loads(ham)))
            st.success("Mekân kataloğu kaydedildi.")
        except Exception as hata:
            st.error(f"Kaydedilemedi: {hata}")

# ============================================================
# Intro / outro (tanım + durum; medya üretimi sonraki aşamada)
# ============================================================
with intro_tab:
    _karakterler = _karakter_katalogu().characters
    _mekanlar = _mekan_katalogu().locations
    mevcut_intro = depo.intro_yukle(series_id)
    st.caption("Intro bu seri için bir kez üretilir; bölümlerde yeniden üretilmez.")
    if mevcut_intro:
        st.info(f"Mevcut durum: `{mevcut_intro.status}` · revizyon {mevcut_intro.revision}")

    karakter_secenek = {k.character_id: k.name for k in _karakterler}
    mekan_secenekleri, mekan_index, mekan_etiket = _mekan_secenekleri(
        _mekanlar, mevcut_intro.location_id if mevcut_intro else ""
    )
    with st.form("intro_form"):
        sure = st.number_input("Süre (sn)", min_value=1, value=(mevcut_intro.duration_sec if mevcut_intro else 5))
        kadro = st.multiselect("Intro karakterleri", list(karakter_secenek), format_func=karakter_secenek.get, default=(mevcut_intro.character_ids if mevcut_intro else []))
        durum = st.selectbox("Durum", DURUMLAR, index=(DURUMLAR.index(mevcut_intro.status) if mevcut_intro else 0), key="intro_durum")
        mekan = st.selectbox("Mekân (opsiyonel)", mekan_secenekleri, format_func=lambda x: mekan_etiket.get(x, x), index=mekan_index, key="intro_mekan")
        sabit_metin = st.text_input("Sabit başlık", value=(mevcut_intro.fixed_text if mevcut_intro else seri.name))
        gorsel = st.text_area("Görsel açıklama", value=(mevcut_intro.visual_description if mevcut_intro else ""))
        hareket = st.text_area("Hareket açıklaması", value=(mevcut_intro.action_description if mevcut_intro else ""))
        ses = st.text_area("Ses açıklaması", value=(mevcut_intro.audio_description if mevcut_intro else ""))
        kaydet = st.form_submit_button("Intro tanımını kaydet", icon=":material/save:")

    if kaydet:
        try:
            if not kadro:
                raise ValueError("Intro için en az bir karakter seçin.")
            intro = modeller.Intro(
                series_id=series_id,
                revision=(mevcut_intro.revision if mevcut_intro else 1),
                status=durum,
                duration_sec=int(sure),
                character_ids=list(kadro),
                location_id=("" if mekan == MEKAN_YOK else mekan),
                fixed_text=sabit_metin,
                visual_description=gorsel,
                action_description=hareket,
                audio_description=ses,
            )
            intro = intro.model_copy(
                update={"revision": modeller.revizyon_artir(mevcut_intro, intro)}
            )
            depo.intro_kaydet(intro, _karakter_katalogu(), _mekan_katalogu())
            st.success(f"Intro tanımı kaydedildi (revizyon {intro.revision}).")
        except Exception as hata:
            st.error(f"Kaydedilemedi: {hata}")
    st.caption(
        ":material/info: Durum elle işaretlenir; hiçbir durumda düzenleme kısıtlanmaz. "
        "Görsel/video/ses üretimi sonraki aşamada eklenecek."
    )

with outro_tab:
    _karakterler = _karakter_katalogu().characters
    _mekanlar = _mekan_katalogu().locations
    mevcut_outro = depo.outro_yukle(series_id)
    st.caption("Outro bu seri için bir kez üretilir; bölümlerde yeniden üretilmez.")
    if mevcut_outro:
        st.info(f"Mevcut durum: `{mevcut_outro.status}` · revizyon {mevcut_outro.revision}")

    karakter_secenek = {k.character_id: k.name for k in _karakterler}
    mekan_secenekleri, mekan_index, mekan_etiket = _mekan_secenekleri(
        _mekanlar, mevcut_outro.location_id if mevcut_outro else ""
    )
    with st.form("outro_form"):
        sure = st.number_input("Süre (sn)", min_value=1, value=(mevcut_outro.duration_sec if mevcut_outro else 7))
        kadro = st.multiselect("Outro karakterleri", list(karakter_secenek), format_func=karakter_secenek.get, default=(mevcut_outro.character_ids if mevcut_outro else []))
        durum = st.selectbox("Durum", DURUMLAR, index=(DURUMLAR.index(mevcut_outro.status) if mevcut_outro else 0), key="outro_durum")
        mekan = st.selectbox("Mekân (opsiyonel)", mekan_secenekleri, format_func=lambda x: mekan_etiket.get(x, x), index=mekan_index, key="outro_mekan")
        veda = st.text_input("Sabit veda metni", value=(mevcut_outro.fixed_text if mevcut_outro else ""))
        cta = st.text_input("Çağrı metni", value=(mevcut_outro.call_to_action if mevcut_outro else ""))
        gorsel = st.text_area("Görsel açıklama", value=(mevcut_outro.visual_description if mevcut_outro else ""))
        hareket = st.text_area("Hareket açıklaması", value=(mevcut_outro.action_description if mevcut_outro else ""))
        ses = st.text_area("Ses açıklaması", value=(mevcut_outro.audio_description if mevcut_outro else ""))
        kaydet = st.form_submit_button("Outro tanımını kaydet", icon=":material/save:")

    if kaydet:
        try:
            if not kadro:
                raise ValueError("Outro için en az bir karakter seçin.")
            outro = modeller.Outro(
                series_id=series_id,
                revision=(mevcut_outro.revision if mevcut_outro else 1),
                status=durum,
                duration_sec=int(sure),
                character_ids=list(kadro),
                location_id=("" if mekan == MEKAN_YOK else mekan),
                fixed_text=veda,
                call_to_action=cta,
                visual_description=gorsel,
                action_description=hareket,
                audio_description=ses,
            )
            outro = outro.model_copy(
                update={"revision": modeller.revizyon_artir(mevcut_outro, outro)}
            )
            depo.outro_kaydet(outro, _karakter_katalogu(), _mekan_katalogu())
            st.success(f"Outro tanımı kaydedildi (revizyon {outro.revision}).")
        except Exception as hata:
            st.error(f"Kaydedilemedi: {hata}")
    st.caption(
        ":material/info: Durum elle işaretlenir; hiçbir durumda düzenleme kısıtlanmaz. "
        "Görsel/video/ses üretimi sonraki aşamada eklenecek."
    )

# ============================================================
# Görsel üretim promptları
# ============================================================
with gorsel_tab:
    st.subheader("Görsel üretim prompt paketi")
    st.caption(
        "Karakter, mekân, intro, outro ve kaydedilmiş bölüm sahnelerini tek pakette toplar. "
        "Herhangi bir görsel üretim aracına yapıştırılabilir ve yerelde saklanır."
    )
    dil = st.segmented_control(
        "Çıktı dili", {"tr": "Türkçe", "en": "English"},
        default="tr", key="gorsel_prompt_dili",
    )
    paket = st.session_state.gorsel_prompt_paketi
    if not paket or paket["dil"] != dil:
        icerik = depo.gorsel_prompt_yukle(series_id, dil)
        paket = {"dil": dil, "icerik": icerik} if icerik else None
        st.session_state.gorsel_prompt_paketi = paket

    if st.button("Görsel prompt paketini oluştur ve kaydet", type="primary", icon=":material/auto_awesome:"):
        icerik = motor.gorsel_prompt_paketi_sablon(
            seri,
            _karakter_katalogu().characters,
            _mekan_katalogu().locations,
            depo.intro_yukle(series_id),
            depo.outro_yukle(series_id),
            _kayitli_senaryolar(series_id),
            dil,
            "Genel görsel üretim modeli",
        )
        depo.gorsel_prompt_kaydet(series_id, dil, icerik)
        paket = {"dil": dil, "icerik": icerik}
        st.session_state.gorsel_prompt_paketi = paket
        st.success("Prompt paketi yerelde kaydedildi.")

    if paket:
        dil_etiketi = "Türkçe" if paket["dil"] == "tr" else "English"
        st.text_area(
            f"{dil_etiketi} görsel üretim prompt paketi",
            paket["icerik"],
            height=520,
            key="gorsel_prompt_ciktisi",
        )
        st.download_button(
            "Prompt paketini indir",
            paket["icerik"],
            file_name=f"{seri.series_id}_gorsel_prompt_{paket['dil']}.txt",
            mime="text/plain",
            icon=":material/download:",
        )

# ============================================================
# Dışa aktar
# ============================================================
with disa_tab:
    st.subheader("Dışa aktar")
    indirilecekler = [
        ("seri.json", json.dumps(seri.model_dump(), ensure_ascii=False, indent=2)),
        ("karakterler.json", json.dumps(_karakter_katalogu().model_dump(), ensure_ascii=False, indent=2)),
        ("mekanlar.json", json.dumps(_mekan_katalogu().model_dump(), ensure_ascii=False, indent=2)),
    ]
    mevcut_intro = depo.intro_yukle(series_id)
    mevcut_outro = depo.outro_yukle(series_id)
    if mevcut_intro:
        indirilecekler.append(("intro.json", json.dumps(mevcut_intro.model_dump(), ensure_ascii=False, indent=2)))
    if mevcut_outro:
        indirilecekler.append(("outro.json", json.dumps(mevcut_outro.model_dump(), ensure_ascii=False, indent=2)))
    if st.session_state.senaryo is not None:
        indirilecekler.append(("senaryo.json", json.dumps(st.session_state.senaryo, ensure_ascii=False, indent=2)))

    for dosya_adi, icerik in indirilecekler:
        st.download_button(
            f"İndir: {dosya_adi}",
            icerik,
            file_name=dosya_adi,
            mime="application/json",
        )
