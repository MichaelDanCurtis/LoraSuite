import base64
import json
import subprocess
from pathlib import Path

from PIL import Image
import pytest

import lorasuite_engine.vision_caption as vision_caption
from lorasuite_engine.models import (
    CurationAnalysisEvidence,
    CurationRecommendation,
    MediaType,
    TrainingIntent,
    VisionProviderAuthMode,
    VisionProviderDialect,
)
from lorasuite_engine.vision_caption import (
    AppleFoundationVisionProvider,
    GrokOAuthVisionProvider,
    OpenAICompatibleVisionProvider,
    VisionProviderConfig,
    parse_vision_evidence,
    prepare_image_data_url,
    provider_presets,
)


def test_prepare_image_data_url_resizes_and_encodes_jpeg(tmp_path):
    image_path = tmp_path / "large.png"
    Image.new("RGB", (2400, 1600), color=(20, 80, 130)).save(image_path)

    data_url = prepare_image_data_url(image_path, maximum_dimension=640)

    assert data_url.startswith("data:image/jpeg;base64,")
    encoded = data_url.split(",", 1)[1]
    output_path = tmp_path / "prepared.jpg"
    output_path.write_bytes(base64.b64decode(encoded))
    with Image.open(output_path) as prepared:
        assert prepared.format == "JPEG"
        assert max(prepared.size) == 640


def test_parse_vision_evidence_accepts_fenced_json_and_normalizes_content():
    evidence = parse_vision_evidence(
        """```json
        {
          "expression": " smiling ",
          "pose": "standing with one hand raised",
          "clothing": "red dress",
          "environment": "indoors beside windows",
          "camera": "eye-level full-body view",
          "other_people": "none",
          "watermark": "none",
          "content": "bikini swim outfit",
          "confidence": 1.4
        }
        ```"""
    )

    assert evidence.expression == "smiling"
    assert evidence.content == "swimwear"
    assert evidence.confidence == 1.0


def test_provider_builds_responses_image_request_and_parses_output(tmp_path, monkeypatch):
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (320, 480), color=(90, 40, 110)).save(image_path)
    config = VisionProviderConfig(
        provider_id="grok",
        provider_label="Grok",
        dialect=VisionProviderDialect.RESPONSES,
        base_url="https://api.x.ai/v1",
        model="grok-test",
        api_key="secret",
    )
    provider = OpenAICompatibleVisionProvider(config)
    captured = {}

    def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"expression":"neutral","pose":"standing","clothing":"black dress","environment":"studio","camera":"eye level","other_people":"none","watermark":"none","content":"general","confidence":0.9}',
                        }
                    ]
                }
            ]
        }

    monkeypatch.setattr(provider, "_post_json", fake_post)
    analysis_context = CurationAnalysisEvidence(
        media_item_id="media_portrait",
        media_type=MediaType.IMAGE,
        recommendation=CurationRecommendation.KEEP,
        confidence=0.88,
        quality_score=0.81,
        face_count=1,
        face_area=0.12,
        body_coverage=0.44,
        pose_coverage=0.67,
        aesthetic_score=0.73,
        reasons=["one usable face"],
        analyzer="apple-vision-dataset-v1",
    )
    evidence = provider.caption(
        image_path,
        TrainingIntent(trigger_token="person_token"),
        analysis_context,
    )

    assert captured["endpoint"] == "https://api.x.ai/v1/responses"
    content = captured["payload"]["input"][0]["content"]
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")
    assert "fallible measurements" in content[0]["text"]
    assert '"face_count": 1' in content[0]["text"]
    assert '"pose_coverage": 0.67' in content[0]["text"]
    assert captured["payload"]["store"] is False
    assert evidence.clothing == "black dress"


def test_provider_builds_chat_completions_request(tmp_path, monkeypatch):
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (320, 480), color=(90, 40, 110)).save(image_path)
    config = VisionProviderConfig(
        provider_id="kimi_code",
        provider_label="Kimi Code",
        dialect=VisionProviderDialect.CHAT_COMPLETIONS,
        base_url="https://api.kimi.com/coding/v1",
        model="kimi-for-coding",
        api_key="secret",
    )
    provider = OpenAICompatibleVisionProvider(config)
    captured = {}

    def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"expression":"neutral","pose":"standing","clothing":"black dress","environment":"studio","camera":"eye level","other_people":"none","watermark":"none","content":"general","confidence":0.8}'
                    }
                }
            ]
        }

    monkeypatch.setattr(provider, "_post_json", fake_post)
    evidence = provider.caption(image_path, TrainingIntent())

    assert captured["endpoint"] == "https://api.kimi.com/coding/v1/chat/completions"
    assert captured["payload"]["model"] == "kimi-for-coding"
    assert captured["payload"]["temperature"] == 1
    image_part = captured["payload"]["messages"][1]["content"][1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert evidence.pose == "standing"


def test_apple_local_provider_uses_on_device_structured_image_prompt(
    tmp_path,
    monkeypatch,
):
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (320, 480), color=(90, 40, 110)).save(image_path)
    config = VisionProviderConfig(
        provider_id="apple_local",
        provider_label="Apple Local",
        dialect=VisionProviderDialect.APPLE_FOUNDATION,
        base_url="apple://foundation-model",
        model="system",
        auth_mode=VisionProviderAuthMode.LOCAL,
    )
    captured = {}

    monkeypatch.setattr(vision_caption.shutil, "which", lambda name: "/usr/bin/fm")
    monkeypatch.setattr(
        vision_caption,
        "apple_foundation_is_available",
        lambda: True,
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        schema_path = Path(command[command.index("--schema") + 1])
        prepared_image_path = Path(command[command.index("--image") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        captured["prepared_image"] = prepared_image_path.read_bytes()
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "expression": "pouting",
                    "pose": "standing while holding hair",
                    "clothing": "black sleeveless top and black skirt",
                    "environment": "room with large windows",
                    "camera": "eye-level medium shot",
                    "other_people": "none",
                    "watermark": "none",
                    "content": "general",
                    "confidence": 0.86,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(vision_caption.subprocess, "run", fake_run)
    evidence = AppleFoundationVisionProvider(config).caption(
        image_path,
        TrainingIntent(),
    )

    command = captured["command"]
    assert command[:4] == ["/usr/bin/fm", "respond", "--model", "system"]
    assert "--no-stream" in command
    assert "--schema" in command
    assert "--image" in command
    assert captured["schema"]["title"] == "VisionEvidence"
    assert captured["schema"]["x-order"][0] == "expression"
    assert captured["prepared_image"].startswith(b"\xff\xd8")
    assert evidence.pose == "standing while holding hair"
    assert evidence.confidence == 0.86


def test_apple_local_preset_reports_on_device_availability(monkeypatch):
    monkeypatch.setattr(
        vision_caption,
        "apple_foundation_is_available",
        lambda: True,
    )

    apple = next(provider for provider in provider_presets() if provider.id == "apple_local")

    assert apple.configured is True
    assert apple.auth_mode == VisionProviderAuthMode.LOCAL
    assert apple.dialect == VisionProviderDialect.APPLE_FOUNDATION
    assert apple.model == "system"


def test_grok_oauth_provider_uses_local_cli_image_blocks(tmp_path, monkeypatch):
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (320, 480), color=(90, 40, 110)).save(image_path)
    config = VisionProviderConfig(
        provider_id="grok_oauth",
        provider_label="Grok OAuth",
        dialect=VisionProviderDialect.GROK_CLI,
        base_url="grok://local-oauth",
        model="grok-4.5",
        auth_mode=VisionProviderAuthMode.GROK_OAUTH,
    )
    captured = {}

    monkeypatch.setattr(vision_caption.shutil, "which", lambda name: "/test/grok")
    monkeypatch.setattr(vision_caption, "grok_oauth_is_authenticated", lambda: True)

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "structuredOutput": {
                        "expression": "smiling",
                        "pose": "standing",
                        "clothing": "black dress",
                        "environment": "studio",
                        "camera": "eye level",
                        "other_people": "none",
                        "watermark": "none",
                        "content": "general",
                        "confidence": 0.8,
                    }
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(vision_caption.subprocess, "run", fake_run)
    evidence = GrokOAuthVisionProvider(config).caption(image_path, TrainingIntent())

    command = captured["command"]
    blocks = json.loads(command[command.index("--prompt-json") + 1])
    schema = json.loads(command[command.index("--json-schema") + 1])
    assert command[0] == "/test/grok"
    assert command[command.index("--model") + 1] == "grok-4.5"
    assert "--no-memory" in command
    assert blocks[1]["type"] == "image"
    assert blocks[1]["mimeType"] == "image/jpeg"
    assert blocks[1]["data"]
    assert schema["properties"]["confidence"]["type"] == "number"
    assert evidence.expression == "smiling"


def test_grok_oauth_provider_surfaces_exhausted_usage_balance(tmp_path, monkeypatch):
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (320, 480), color=(90, 40, 110)).save(image_path)
    config = VisionProviderConfig(
        provider_id="grok_oauth",
        provider_label="Grok OAuth",
        dialect=VisionProviderDialect.GROK_CLI,
        base_url="grok://local-oauth",
        model="grok-4.5",
        auth_mode=VisionProviderAuthMode.GROK_OAUTH,
    )
    monkeypatch.setattr(vision_caption.shutil, "which", lambda name: "/test/grok")
    monkeypatch.setattr(vision_caption, "grok_oauth_is_authenticated", lambda: True)
    monkeypatch.setattr(
        vision_caption.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr='API error (status 402 Payment Required): Grok Build usage balance exhausted',
        ),
    )

    provider = GrokOAuthVisionProvider(config)
    with pytest.raises(
        ValueError,
        match=r"Grok Build usage balance exhausted \(HTTP 402\)",
    ):
        provider.caption(image_path, TrainingIntent())
