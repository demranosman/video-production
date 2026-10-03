"""OpenMontage-backed video provider router.

Keeps scene-image generation outside the router. The router only converts an
existing scene image into video and tries providers in the configured order.

Important: OpenMontage's selector is scored. To implement an explicit fallback
order, this adapter calls video_selector once per provider with
allowed_providers=[provider]. A provider is therefore never silently replaced
by OpenMontage's internal ranking.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_POLICY_PATH = Path(__file__).with_name("video_provider_policy.json")


def _load_policy(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    policy_path = Path(path or os.environ.get("VIDEO_PROVIDER_POLICY", DEFAULT_POLICY_PATH))
    with policy_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _openmontage_selector():
    openmontage_path = os.environ.get("OPENMONTAGE_PATH", r"C:\Users\fikret\Desktop\OpenMontage")
    if not Path(openmontage_path).is_dir():
        raise RuntimeError(
            f"OpenMontage dizini bulunamadı: {openmontage_path}. "
            "OPENMONTAGE_PATH ortam değişkenini doğru klasöre ayarlayın."
        )
    if openmontage_path not in os.sys.path:
        os.sys.path.insert(0, openmontage_path)

    try:
        from tools.video.video_selector import VideoSelector  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise RuntimeError(
            "OpenMontage video_selector yüklenemedi. OPENMONTAGE_PATH ve Python bağımlılıklarını kontrol edin."
        ) from exc
    return VideoSelector()


def _error_text(result: Any) -> str:
    return str(getattr(result, "error", None) or getattr(result, "data", None) or result)


def _is_quota_error(message: str) -> bool:
    text = message.lower()
    markers = (
        "quota", "credit", "credits", "insufficient", "usage limit",
        "rate limit", "resource_exhausted", "billing", "exceeded",
        "too many requests", "429",
    )
    return any(marker in text for marker in markers)


def _is_auth_error(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in (
        "401", "403", "unauthorized", "forbidden", "api key", "authentication",
        "credentials", "not set", "invalid key",
    ))


def _is_transient_error(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in (
        "timeout", "timed out", "temporarily", "connection", "502", "503", "504",
        "throttled", "server error", "network",
    ))


def _provider_attempt(
    selector: Any,
    provider: str,
    prompt: str,
    image_path: str,
    output_path: str,
    duration: int,
    generate_audio: bool,
    negative_prompt: str = "",
) -> Any:
    if not Path(image_path).is_file():
        raise FileNotFoundError(f"Sahne görseli bulunamadı: {image_path}")

    # Selector yalnızca ortak video sözleşmesini alır. Provider'a özgü model
    # seçimini policy'de zorlamıyoruz; böylece provider kendi geçerli varsayılanını kullanır.
    inputs: dict[str, Any] = {
        "prompt": prompt,
        "preferred_provider": provider,
        "preferred_provider_gap": 1.0,
        "allowed_providers": [provider],
        "operation": "image_to_video",
        "aspect_ratio": "16:9",
        "duration": str(duration),
        "reference_image_path": str(Path(image_path).resolve()),
        "output_path": str(Path(output_path).resolve()),
    }

    # Bunlar selector tarafından provider'a iletilebilir; desteklemeyen provider
    # bunları kullanmaz. Native audio isteği özellikle korunur.
    inputs["generate_audio"] = bool(generate_audio)
    if negative_prompt:
        inputs["negative_prompt"] = negative_prompt

    return selector.execute(inputs)


def _result_output_path(result: Any, requested_path: str) -> str:
    data = getattr(result, "data", None) or {}
    candidates = []
    if isinstance(data, dict):
        for key in ("output_path", "output", "video_path"):
            value = data.get(key)
            if isinstance(value, str) and value:
                candidates.append(value)
        artifacts = data.get("artifacts")
        if isinstance(artifacts, (list, tuple)):
            candidates.extend(str(x) for x in artifacts if isinstance(x, str))
    candidates.append(requested_path)
    for candidate in candidates:
        if Path(candidate).is_file() and Path(candidate).stat().st_size > 0:
            return str(Path(candidate).resolve())
    return ""


def generate_video_via_openmontage(
    *,
    prompt: str,
    image_path: str,
    output_path: str,
    duration: int,
    generate_audio: bool = True,
    negative_prompt: str = "",
    policy_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Generate video from an existing scene image using OpenMontage.

    Returns a dict with provider attempts and the successful provider. Raises
    RuntimeError only after every configured provider fails.
    """
    policy = _load_policy(policy_path)
    providers = list(policy.get("preferred_order") or [])
    if not providers:
        raise RuntimeError("video_provider_policy.json içinde preferred_order boş.")

    selector = _openmontage_selector()
    retries = max(0, int(policy.get("max_retries_per_provider", 1)))
    attempts: list[dict[str, Any]] = []

    for provider in providers:
        for attempt_index in range(retries + 1):
            started = time.time()
            try:
                result = _provider_attempt(
                    selector=selector,
                    provider=provider,
                    prompt=prompt,
                    image_path=image_path,
                    output_path=output_path,
                    duration=duration,
                    generate_audio=generate_audio,
                    negative_prompt=negative_prompt,
                )
                if getattr(result, "success", False):
                    data = dict(getattr(result, "data", {}) or {})
                    actual_output = _result_output_path(result, output_path)
                    if actual_output:
                        attempts.append({
                            "provider": provider,
                            "attempt": attempt_index + 1,
                            "success": True,
                            "elapsed_seconds": round(time.time() - started, 2),
                            "data": data,
                            "output_path": actual_output,
                        })
                        return {
                            "success": True,
                            "provider": provider,
                            "output_path": actual_output,
                            "attempts": attempts,
                        }
                    error = "OpenMontage başarılı döndü ancak geçerli MP4 çıktı dosyası bulunamadı."
                    attempts.append({
                        "provider": provider,
                        "attempt": attempt_index + 1,
                        "success": False,
                        "elapsed_seconds": round(time.time() - started, 2),
                        "error": error,
                        "error_class": "invalid_output",
                    })
                    break

                error = _error_text(result)
                attempts.append({
                    "provider": provider,
                    "attempt": attempt_index + 1,
                    "success": False,
                    "elapsed_seconds": round(time.time() - started, 2),
                    "error": error,
                    "error_class": (
                        "quota" if _is_quota_error(error)
                        else "auth" if _is_auth_error(error)
                        else "transient" if _is_transient_error(error)
                        else "provider"
                    ),
                })

                # Retry only transient failures. Quota/auth/provider failures
                # immediately advance to the next provider.
                if not _is_transient_error(error):
                    break
                if attempt_index >= retries:
                    break
                time.sleep(2)

            except Exception as exc:
                error = str(exc)
                attempts.append({
                    "provider": provider,
                    "attempt": attempt_index + 1,
                    "success": False,
                    "elapsed_seconds": round(time.time() - started, 2),
                    "error": error,
                    "error_class": (
                        "quota" if _is_quota_error(error)
                        else "auth" if _is_auth_error(error)
                        else "transient" if _is_transient_error(error)
                        else "exception"
                    ),
                })
                if not _is_transient_error(error) or attempt_index >= retries:
                    break
                time.sleep(2)

    summary = "; ".join(
        f"{a['provider']}: {a['error']}" for a in attempts if not a.get("success")
    )
    raise RuntimeError(f"Tüm video sağlayıcıları başarısız oldu. {summary}")
