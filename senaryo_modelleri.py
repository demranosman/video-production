"""Hikâyeden senaryo üretim ürününün veri sözleşmeleri (Pydantic).

Bu modül yalnızca yapısal doğrulama yapar. Karakter/mekân referanslarının
kataloglarda gerçekten var olup olmadığı depo katmanında (seri_deposu.py)
doğrulanır, çünkü o doğrulama katalog verisine ihtiyaç duyar.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

VarlikDurumu = Literal["draft", "approved", "producing", "ready", "locked", "failed"]
KarakterRolu = Literal["main", "recurring", "supporting", "guest"]


class Seri(BaseModel):
    schema_version: int = 1
    series_id: str
    name: str
    description: str = ""
    target_audience: str = ""
    language: str = "tr"
    visual_style: str = ""
    default_aspect_ratio: str = "16:9"
    genre: str = "genel"
    format: Literal["kisa", "orta", "uzun"] = "orta"
    target_duration_sec: int = Field(default=180, ge=1)
    created_at: str = ""

    @model_validator(mode="after")
    def _kimlik_bos_olmasin(self) -> Seri:
        if not self.name.strip():
            raise ValueError("Seri adı boş olamaz.")
        if not self.series_id.strip():
            raise ValueError("series_id boş olamaz.")
        return self


class Karakter(BaseModel):
    character_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    type: str = ""
    role: KarakterRolu = "supporting"
    first_seen_episode: int | None = None
    visual_identity: dict[str, Any] = Field(default_factory=dict)
    default_clothing: str = ""
    personality: list[str] = Field(default_factory=list)
    speech_style: str = ""
    voice_description: str = ""
    # ElevenLabs voice_id (opsiyonel). Boşsa dil/cinsiyet varsayılanı kullanılır.
    voice_id: str = ""
    consistency_rules: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _gerekli_alanlar(self) -> Karakter:
        if not self.character_id.strip():
            raise ValueError("character_id boş olamaz.")
        if not self.name.strip():
            raise ValueError("Karakter adı boş olamaz.")
        if not self.visual_identity:
            raise ValueError(f"{self.character_id} için visual_identity boş olamaz.")
        return self


class KarakterKatalogu(BaseModel):
    series_id: str
    characters: list[Karakter] = Field(default_factory=list)


class Mekan(BaseModel):
    location_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    first_seen_episode: int | None = None
    visual_identity: dict[str, Any] = Field(default_factory=dict)
    consistency_rules: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _gerekli_alanlar(self) -> Mekan:
        if not self.location_id.strip():
            raise ValueError("location_id boş olamaz.")
        if not self.name.strip():
            raise ValueError("Mekân adı boş olamaz.")
        if not self.visual_identity:
            raise ValueError(f"{self.location_id} için visual_identity boş olamaz.")
        return self


class MekanKatalogu(BaseModel):
    series_id: str
    locations: list[Mekan] = Field(default_factory=list)


class Episode(BaseModel):
    episode_no: int = Field(ge=1)
    title: str
    summary: str = ""
    moral: str = ""


class Sahne(BaseModel):
    scene_id: str
    order: int = Field(ge=1)
    title: str = ""
    source_excerpt: str = ""
    location_id: str = ""
    character_ids: list[str] = Field(default_factory=list)
    character_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    location_state: dict[str, Any] = Field(default_factory=dict)
    story_event: str = ""
    narration: str = ""
    dialogue: list[dict[str, Any]] = Field(default_factory=list)
    visual_description: str = ""
    # Üretim için İngilizce görsel komut (opsiyonel); boşsa visual_description kullanılır.
    image_prompt: str = ""
    # FFmpeg Ken Burns yönü: "zoom in", "zoom out", "pan left", "pan right" vb.
    motion: str = ""
    # Kullanıcı fotoğraf/video eklediyse Gemini görseli yerine kolaj üretilir.
    # [{"path": "medya/dosya.jpg", "type": "image"}]
    media: list[dict[str, Any]] = Field(default_factory=list)
    estimated_duration_sec: int = Field(ge=1)

    @model_validator(mode="after")
    def _gerekli_alanlar(self) -> Sahne:
        if not self.scene_id.strip():
            raise ValueError("scene_id boş olamaz.")
        if not self.source_excerpt.strip():
            raise ValueError(f"{self.scene_id} için source_excerpt boş olamaz.")
        if not self.location_id.strip():
            raise ValueError(f"{self.scene_id} için location_id boş olamaz.")
        return self


class Senaryo(BaseModel):
    schema_version: int = 1
    series_id: str
    episode: Episode
    intro_id: str = "series_intro"
    outro_id: str = "series_outro"
    scenes: list[Sahne] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sahne_sirasi_tekrarsiz(self) -> Senaryo:
        if not self.scenes:
            raise ValueError("Senaryo en az bir sahne içermelidir.")
        orders = [s.order for s in self.scenes]
        if len(orders) != len(set(orders)):
            raise ValueError("Sahne sıraları benzersiz olmalıdır.")
        if orders != sorted(orders):
            raise ValueError("Sahne sıraları artan olmalıdır.")
        ids = [s.scene_id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_id değerleri benzersiz olmalıdır.")
        return self


class Intro(BaseModel):
    schema_version: int = 1
    intro_id: str = "series_intro"
    series_id: str
    revision: int = Field(default=1, ge=1)
    status: VarlikDurumu = "draft"
    duration_sec: int = Field(ge=1)
    character_ids: list[str] = Field(default_factory=list)
    location_id: str = ""
    visual_description: str = ""
    action_description: str = ""
    fixed_text: str = ""
    audio_description: str = ""
    generation: dict[str, str] = Field(default_factory=dict)


class Outro(BaseModel):
    schema_version: int = 1
    outro_id: str = "series_outro"
    series_id: str
    revision: int = Field(default=1, ge=1)
    status: VarlikDurumu = "draft"
    duration_sec: int = Field(ge=1)
    character_ids: list[str] = Field(default_factory=list)
    location_id: str = ""
    visual_description: str = ""
    action_description: str = ""
    fixed_text: str = ""
    call_to_action: str = ""
    audio_description: str = ""
    generation: dict[str, str] = Field(default_factory=dict)


# --- Revizyon kuralı ---
# `status` bir üretim işareti, içerik değişikliği değildir; tek başına durum
# değiştirmek revizyonu artırmaz. Aynı şekilde `revision` kendi kendini saymaz.
_REVIZYON_DISI = {"revision", "status"}


def revizyon_artir(mevcut: Intro | Outro | None, yeni: Intro | Outro) -> int:
    """Yeni kaydın revizyon numarasını döner; içerik değişmediyse mevcut kalır."""
    if mevcut is None:
        return 1
    if mevcut.model_dump(exclude=_REVIZYON_DISI) == yeni.model_dump(exclude=_REVIZYON_DISI):
        return mevcut.revision
    return mevcut.revision + 1
