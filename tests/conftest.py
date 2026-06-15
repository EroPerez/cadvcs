"""Configuración de pytest: hace importable el paquete cadvcs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
