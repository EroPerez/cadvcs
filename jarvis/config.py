import os
from pathlib import Path
from dotenv import load_dotenv

_env_file = Path(__file__).parent / ".env"
load_dotenv(_env_file)

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
JARVIS_MODEL: str = os.getenv("JARVIS_MODEL", "claude-haiku-4-5-20251001")
JARVIS_NAME: str = os.getenv("JARVIS_NAME", "Jarvis")
VOICE_ENABLED: bool = os.getenv("JARVIS_VOICE_ENABLED", "false").lower() == "true"
HISTORY_FILE: Path = Path(
    os.getenv("JARVIS_HISTORY_FILE", "~/.jarvis_history.json")
).expanduser()
MAX_HISTORY: int = int(os.getenv("JARVIS_MAX_HISTORY", "50"))
