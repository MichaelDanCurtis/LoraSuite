from __future__ import annotations

import base64
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi
from PIL import Image, ImageOps

from lorasuite_engine.models import (
    CurationAnalysisEvidence,
    TrainingIntent,
    VisionCaptionEvidence,
    VisionProviderAuthMode,
    VisionProviderDialect,
    VisionProviderPreset,
)


PROVIDER_PRESETS = (
    {
        "id": "apple_local",
        "label": "Apple Local",
        "dialect": VisionProviderDialect.APPLE_FOUNDATION,
        "auth_mode": VisionProviderAuthMode.LOCAL,
        "base_url": "apple://foundation-model",
        "model": "system",
        "environment_key": None,
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "dialect": VisionProviderDialect.RESPONSES,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5",
        "environment_key": "OPENAI_API_KEY",
    },
    {
        "id": "grok",
        "label": "Grok API",
        "dialect": VisionProviderDialect.RESPONSES,
        "auth_mode": VisionProviderAuthMode.API_KEY,
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4.3",
        "environment_key": "XAI_API_KEY",
    },
    {
        "id": "grok_oauth",
        "label": "Grok OAuth",
        "dialect": VisionProviderDialect.GROK_CLI,
        "auth_mode": VisionProviderAuthMode.GROK_OAUTH,
        "base_url": "grok://local-oauth",
        "model": "grok-4.5",
        "environment_key": None,
    },
    {
        "id": "kimi_code",
        "label": "Kimi Code",
        "dialect": VisionProviderDialect.CHAT_COMPLETIONS,
        "auth_mode": VisionProviderAuthMode.API_KEY,
        "base_url": "https://api.kimi.com/coding/v1",
        "model": "kimi-for-coding",
        "environment_key": "KIMI_CODE_API_KEY",
    },
    {
        "id": "kimi_platform",
        "label": "Kimi Platform",
        "dialect": VisionProviderDialect.CHAT_COMPLETIONS,
        "auth_mode": VisionProviderAuthMode.API_KEY,
        "base_url": "https://api.moonshot.ai/v1",
        "model": "kimi-k2.5",
        "environment_key": "MOONSHOT_API_KEY",
    },
)


@dataclass(frozen=True)
class VisionProviderConfig:
    provider_id: str
    provider_label: str
    dialect: VisionProviderDialect
    base_url: str
    model: str
    api_key: str = ""
    auth_mode: VisionProviderAuthMode = VisionProviderAuthMode.API_KEY


class VisionCaptionProvider(Protocol):
    def caption(
        self,
        image_path: Path,
        intent: TrainingIntent,
        analysis_context: CurationAnalysisEvidence | None = None,
    ) -> VisionCaptionEvidence: ...


def provider_presets() -> list[VisionProviderPreset]:
    fallback_key = os.environ.get("LORASUITE_VISION_API_KEY", "")
    return [
        VisionProviderPreset(
            id=str(preset["id"]),
            label=str(preset["label"]),
            dialect=preset["dialect"],
            auth_mode=preset.get("auth_mode", VisionProviderAuthMode.API_KEY),
            base_url=str(preset["base_url"]),
            model=str(preset["model"]),
            configured=_provider_is_configured(preset, fallback_key),
        )
        for preset in PROVIDER_PRESETS
    ]


def resolve_api_key(provider_id: str, explicit_key: str | None) -> str:
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    preset = next(
        (candidate for candidate in PROVIDER_PRESETS if candidate["id"] == provider_id),
        None,
    )
    if preset is not None:
        environment_key = preset.get("environment_key")
        if environment_key:
            value = os.environ.get(str(environment_key), "").strip()
            if value:
                return value
    return os.environ.get("LORASUITE_VISION_API_KEY", "").strip()


def auth_mode_for_provider(provider_id: str) -> VisionProviderAuthMode:
    preset = next(
        (candidate for candidate in PROVIDER_PRESETS if candidate["id"] == provider_id),
        None,
    )
    if preset is None:
        return VisionProviderAuthMode.API_KEY
    return preset.get("auth_mode", VisionProviderAuthMode.API_KEY)


def create_vision_provider(config: VisionProviderConfig) -> VisionCaptionProvider:
    if config.auth_mode == VisionProviderAuthMode.LOCAL:
        return AppleFoundationVisionProvider(config)
    if config.auth_mode == VisionProviderAuthMode.GROK_OAUTH:
        return GrokOAuthVisionProvider(config)
    return OpenAICompatibleVisionProvider(config)


def start_grok_oauth_login() -> str:
    executable = shutil.which("grok")
    if not executable:
        raise ValueError("Grok CLI is not installed; install Grok Build before connecting OAuth")
    try:
        subprocess.Popen(
            [executable, "login", "--oauth"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        raise ValueError(f"could not start Grok OAuth login: {error}") from error
    return "Grok OAuth sign-in opened in your browser. Finish it, then refresh providers."


def _provider_is_configured(preset: dict[str, Any], fallback_key: str) -> bool:
    if preset.get("auth_mode") == VisionProviderAuthMode.LOCAL:
        return apple_foundation_is_available()
    if preset.get("auth_mode") == VisionProviderAuthMode.GROK_OAUTH:
        return grok_oauth_is_authenticated()
    environment_key = preset.get("environment_key")
    return bool(fallback_key or (environment_key and os.environ.get(str(environment_key), "")))


def grok_oauth_is_authenticated() -> bool:
    executable = shutil.which("grok")
    if not executable:
        return False
    try:
        result = subprocess.run(
            [executable, "models"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "logged in" in result.stdout.casefold()


def apple_foundation_is_available() -> bool:
    executable = shutil.which("fm")
    if not executable:
        return False
    try:
        result = subprocess.run(
            [executable, "available", "--model", "system"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "available" in result.stdout.casefold()


class OpenAICompatibleVisionProvider:
    def __init__(self, config: VisionProviderConfig, *, timeout_seconds: int = 120):
        self.config = config
        self.timeout_seconds = timeout_seconds
        parsed = urlparse(config.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("vision provider base URL must be HTTP or HTTPS")
        if not config.api_key:
            raise ValueError("vision provider API key is required")
        if not config.model.strip():
            raise ValueError("vision provider model is required")

    def caption(
        self,
        image_path: Path,
        intent: TrainingIntent,
        analysis_context: CurationAnalysisEvidence | None = None,
    ) -> VisionCaptionEvidence:
        image_url = prepare_image_data_url(image_path)
        prompt = _caption_prompt(intent, analysis_context)
        if self.config.dialect == VisionProviderDialect.RESPONSES:
            endpoint = f"{self.config.base_url.rstrip('/')}/responses"
            payload = {
                "model": self.config.model,
                "store": False,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {
                                "type": "input_image",
                                "image_url": image_url,
                                "detail": "high",
                            },
                        ],
                    }
                ],
            }
        else:
            endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": self.config.model,
                # Kimi Code only accepts temperature=1 for its coding models.
                "temperature": 1 if self.config.provider_id == "kimi_code" else 0.1,
                "max_tokens": 800,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return only valid JSON. Describe observable image facts without identifying the person.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url, "detail": "high"},
                            },
                        ],
                    },
                ],
            }
        response = self._post_json(endpoint, payload)
        return parse_vision_evidence(_response_text(response, self.config.dialect))

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "LoraSuite/0.1",
            },
            method="POST",
        )
        context = ssl.create_default_context(cafile=certifi.where())
        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
                context=context,
            ) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise ValueError(
                f"vision provider returned HTTP {error.code}: {detail}"
            ) from error
        except (TimeoutError, URLError) as error:
            raise ValueError(f"vision provider request failed: {error}") from error
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:
            raise ValueError("vision provider returned invalid JSON response") from error
        if not isinstance(parsed, dict):
            raise ValueError("vision provider returned an unexpected response")
        return parsed


class AppleFoundationVisionProvider:
    """Uses Apple's on-device Foundation Model without a cloud credential."""

    def __init__(self, config: VisionProviderConfig, *, timeout_seconds: int = 120):
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.executable = shutil.which("fm")
        if config.auth_mode != VisionProviderAuthMode.LOCAL:
            raise ValueError("Apple Local provider requires local authentication")
        if config.dialect != VisionProviderDialect.APPLE_FOUNDATION:
            raise ValueError("Apple Local provider requires the Apple Foundation format")
        if not self.executable:
            raise ValueError(
                "Apple Foundation Models are not installed on this Mac"
            )
        if config.model.strip() != "system":
            raise ValueError("Apple Local currently supports the on-device system model")
        if not apple_foundation_is_available():
            raise ValueError(
                "Apple's on-device Foundation Model is unavailable; enable Apple Intelligence and try again"
            )

    def caption(
        self,
        image_path: Path,
        intent: TrainingIntent,
        analysis_context: CurationAnalysisEvidence | None = None,
    ) -> VisionCaptionEvidence:
        image_url = prepare_image_data_url(image_path)
        _, encoded_image = _image_data_parts(image_url)
        prompt = _apple_caption_prompt(intent, analysis_context)
        with tempfile.TemporaryDirectory(prefix="lorasuite-apple-local-") as working_directory:
            working_path = Path(working_directory)
            prepared_image_path = working_path / "image.jpg"
            prepared_image_path.write_bytes(base64.b64decode(encoded_image))
            schema_path = working_path / "vision-evidence.schema.json"
            schema_path.write_text(
                json.dumps(_APPLE_VISION_EVIDENCE_SCHEMA),
                encoding="utf-8",
            )
            command = [
                str(self.executable),
                "respond",
                "--model",
                "system",
                "--guardrails",
                "permissive-content-transformations",
                "--no-stream",
                "--schema",
                str(schema_path),
                "--image",
                str(prepared_image_path),
                "--text",
                prompt,
            ]
            try:
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError("Apple Local caption request timed out") from error
        if result.returncode != 0:
            detail = _local_cli_error_detail(result.stderr)
            raise ValueError(
                f"Apple Local caption request failed: {detail}"
                if detail
                else "Apple Local caption request failed; check Apple Intelligence availability"
            )
        return parse_vision_evidence(result.stdout)


class GrokOAuthVisionProvider:
    """Uses the local Grok CLI so its OAuth credentials never leave that client."""

    def __init__(self, config: VisionProviderConfig, *, timeout_seconds: int = 180):
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.executable = shutil.which("grok")
        if config.auth_mode != VisionProviderAuthMode.GROK_OAUTH:
            raise ValueError("Grok OAuth provider requires grok_oauth authentication")
        if not self.executable:
            raise ValueError("Grok CLI is not installed; install Grok Build before using OAuth")
        if not config.model.strip():
            raise ValueError("Grok OAuth model is required")
        if not grok_oauth_is_authenticated():
            raise ValueError("Grok OAuth is not connected; sign in with Grok before generating captions")

    def caption(
        self,
        image_path: Path,
        intent: TrainingIntent,
        analysis_context: CurationAnalysisEvidence | None = None,
    ) -> VisionCaptionEvidence:
        image_url = prepare_image_data_url(image_path)
        mime_type, encoded_image = _image_data_parts(image_url)
        prompt = _caption_prompt(intent, analysis_context)
        prompt_blocks = [
            {"type": "text", "text": prompt},
            {"type": "image", "data": encoded_image, "mimeType": mime_type},
        ]
        command = [
            str(self.executable),
            "--prompt-json",
            json.dumps(prompt_blocks),
            "--json-schema",
            json.dumps(_VISION_EVIDENCE_SCHEMA),
            "--output-format",
            "json",
            "--model",
            self.config.model,
            "--max-turns",
            "1",
            "--no-memory",
            "--no-subagents",
            "--disallowed-tools",
            "run_terminal_cmd,web_search,web_fetch,search_replace",
        ]
        with tempfile.TemporaryDirectory(prefix="lorasuite-grok-oauth-") as working_directory:
            command.extend(["--cwd", working_directory])
            try:
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError("Grok OAuth caption request timed out") from error
        if result.returncode != 0:
            detail = _grok_cli_error_detail(result.stderr)
            raise ValueError(
                f"Grok OAuth caption request failed: {detail}"
                if detail
                else "Grok OAuth caption request failed; check the local Grok session"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ValueError("Grok OAuth returned an invalid caption response") from error
        structured = payload.get("structuredOutput") if isinstance(payload, dict) else None
        if isinstance(structured, dict):
            return VisionCaptionEvidence.model_validate(structured)
        if isinstance(payload, dict) and isinstance(payload.get("text"), str):
            return parse_vision_evidence(payload["text"])
        raise ValueError("Grok OAuth response did not contain structured caption evidence")


def _grok_cli_error_detail(stderr: str) -> str:
    cleaned = re.sub(r"\x1b\[[0-9;]*m", "", stderr or "")
    if "usage balance exhausted" in cleaned.casefold():
        return "Grok Build usage balance exhausted (HTTP 402)"
    error_lines = [
        line.strip()
        for line in cleaned.splitlines()
        if line.strip() and " WARN " not in line
    ]
    return error_lines[-1][:300] if error_lines else ""


def _local_cli_error_detail(stderr: str) -> str:
    cleaned = re.sub(r"\x1b\[[0-9;]*m", "", stderr or "")
    error_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return error_lines[-1][:300] if error_lines else ""


_VISION_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "expression",
        "pose",
        "clothing",
        "environment",
        "camera",
        "lighting",
        "visual_style",
        "other_people",
        "watermark",
        "content",
        "confidence",
    ],
    "properties": {
        "expression": {
            "type": "string",
            "description": "Plainly visible facial expression only, or unknown.",
        },
        "pose": {
            "type": "string",
            "description": "Visible body posture or action only, or unknown.",
        },
        "clothing": {
            "type": "string",
            "description": "Specific visible garments only, or unknown.",
        },
        "environment": {
            "type": "string",
            "description": "Physical setting and background only, or unknown.",
        },
        "camera": {
            "type": "string",
            "description": "Composition, framing, or camera angle only; never a device or setting.",
        },
        "lighting": {
            "type": "string",
            "description": "Visible light source, direction, softness, or contrast only.",
        },
        "visual_style": {
            "type": "string",
            "description": "Literal medium or treatment such as candid photo, studio photo, illustration, or unknown.",
        },
        "other_people": {
            "type": "string",
            "description": "None, or a literal description of other visible people.",
        },
        "watermark": {
            "type": "string",
            "description": "None, or visible overlaid text, logo, or watermark.",
        },
        "content": {
            "type": "string",
            "description": "Exactly general, swimwear, revealing clothing, or nudity.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

_APPLE_VISION_EVIDENCE_SCHEMA = {
    **_VISION_EVIDENCE_SCHEMA,
    "title": "VisionEvidence",
    "x-order": list(_VISION_EVIDENCE_SCHEMA["required"]),
    "properties": {
        **_VISION_EVIDENCE_SCHEMA["properties"],
        "confidence": {"type": "number"},
    },
}


def prepare_image_data_url(path: Path, *, maximum_dimension: int = 1280) -> str:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((maximum_dimension, maximum_dimension), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _image_data_parts(image_url: str) -> tuple[str, str]:
    prefix, separator, encoded = image_url.partition(",")
    if not separator or not prefix.startswith("data:"):
        raise ValueError("prepared image did not produce a data URL")
    mime_type = prefix.removeprefix("data:").split(";", 1)[0]
    if not mime_type.startswith("image/") or not encoded:
        raise ValueError("prepared image data URL is malformed")
    return mime_type, encoded


def parse_vision_evidence(value: str) -> VisionCaptionEvidence:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("vision provider did not return a JSON object")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as error:
        raise ValueError("vision provider returned malformed evidence JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("vision provider evidence must be a JSON object")
    normalized: dict[str, Any] = {}
    for field in (
        "expression",
        "pose",
        "clothing",
        "environment",
        "camera",
        "lighting",
        "visual_style",
        "other_people",
        "watermark",
        "content",
    ):
        normalized[field] = _clean_observation(payload.get(field), default="unknown")
    normalized["other_people"] = _clean_observation(
        payload.get("other_people"), default="none"
    )
    normalized["watermark"] = _clean_observation(
        payload.get("watermark"), default="none"
    )
    normalized["content"] = _content_label(payload.get("content"))
    try:
        normalized["confidence"] = max(
            0.0, min(1.0, float(payload.get("confidence", 0.0)))
        )
    except (TypeError, ValueError):
        normalized["confidence"] = 0.0
    return VisionCaptionEvidence.model_validate(normalized)


def _response_text(
    response: dict[str, Any], dialect: VisionProviderDialect
) -> str:
    if dialect == VisionProviderDialect.CHAT_COMPLETIONS:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("vision provider response did not contain message content") from error
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
            ]
            return "\n".join(texts)
        raise ValueError("vision provider returned unsupported message content")

    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text
    texts: list[str] = []
    for output in response.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("type") in {
                "output_text",
                "text",
            }:
                texts.append(str(content.get("text", "")))
    if not texts:
        raise ValueError("vision provider response did not contain output text")
    return "\n".join(texts)


def _caption_prompt(
    intent: TrainingIntent,
    analysis_context: CurationAnalysisEvidence | None = None,
) -> str:
    local_context = ""
    if analysis_context is not None:
        context_payload = analysis_context.model_dump(
            mode="json",
            exclude={"media_item_id", "analyzed_at"},
            exclude_none=True,
        )
        local_context = f"""

Local machine-analysis hints are included below. Treat them as fallible measurements,
verify every semantic claim against the image, and do not include numeric scores in the caption:
{json.dumps(context_payload, sort_keys=True)}
"""
    return f"""
Analyze this single training image for a {intent.target_type.value} LoRA dataset.
Do not identify the person. Do not infer name, age, ethnicity, personality, intent, attractiveness, or emotion beyond a plainly visible facial expression.
Describe only observable facts. Use short literal phrases suitable for a diffusion-model caption.

The dataset wants these attributes to remain controllable: {', '.join(intent.controllable_attributes) or 'none specified'}.
The dataset does not want these attributes bound to identity: {', '.join(intent.excluded_attributes) or 'none specified'}.
{local_context}

Return exactly one JSON object with these keys:
{{
  "expression": "visible expression or unknown",
  "pose": "body action or posture or unknown",
  "clothing": "specific visible garments or unknown",
  "environment": "literal setting/background or unknown",
  "camera": "camera angle or composition or unknown",
  "lighting": "literal visible lighting or unknown",
  "visual_style": "literal photographic or visual treatment or unknown",
  "other_people": "none or a short literal description",
  "watermark": "none or visible text/watermark",
  "content": "general, swimwear, revealing clothing, or nudity",
  "confidence": 0.0
}}
Do not use subjective terms such as sexy, beautiful, fashionable, good, or bad.
""".strip()


def _apple_caption_prompt(
    intent: TrainingIntent,
    analysis_context: CurationAnalysisEvidence | None = None,
) -> str:
    target = intent.target_type.value.replace("_", " ")
    return (
        f"Extract literal visual evidence from this image for {target} LoRA training. "
        "Describe the main subject's visible expression, body pose or action, specific "
        "garments, background setting, framing or camera angle, visible lighting, "
        "photographic or visual treatment, any other people, and any "
        "overlaid text or logo. Classify content as exactly general, swimwear, "
        "revealing clothing, or nudity. Never guess identity, age, ethnicity, emotion "
        "beyond a plainly visible expression, or camera device. The camera field must "
        "describe only composition, framing, or angle, never a phone or camera model. "
        "Fill every schema field with short observations from the image, not field instructions."
    )


def _clean_observation(value: Any, *, default: str) -> str:
    if not isinstance(value, str):
        return default
    cleaned = " ".join(value.strip().strip(".,").split())[:180]
    return cleaned or default


def _content_label(value: Any) -> str:
    cleaned = _clean_observation(value, default="general").casefold()
    if "nude" in cleaned or "nudity" in cleaned:
        return "nudity"
    if "swim" in cleaned or "bikini" in cleaned or "bathing" in cleaned:
        return "swimwear"
    if "reveal" in cleaned or "underwear" in cleaned or "lingerie" in cleaned:
        return "revealing clothing"
    return "general"
