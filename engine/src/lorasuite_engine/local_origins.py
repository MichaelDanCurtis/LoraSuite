"""The local browser and packaged desktop origins accepted by the engine."""
import re

DESKTOP_ORIGINS = ("tauri://localhost", "http://tauri.localhost", "https://tauri.localhost")
LOCAL_UI_PATTERN = r"^http://(?:127\.0\.0\.1|localhost)(?::\d+)?$"


def is_local_ui_origin(origin: str) -> bool:
    return origin in DESKTOP_ORIGINS or re.fullmatch(LOCAL_UI_PATTERN, origin) is not None
