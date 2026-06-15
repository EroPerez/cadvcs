"""Conversión DWG → DXF.

El diff semántico opera sobre DXF, así que cada DWG necesita un DXF
espejo para entrar en el modelo de entidades. La conversión la hace un
**backend pluggable**: el motor real (Aspose.CAD, ODA File Converter) es
software propietario/licenciado que no se puede asumir presente, de modo
que se selecciona por entorno y, si no hay ninguno disponible, el sistema
sigue funcionando — los DWG se versionan como binarios opacos (igual que
hoy) y simplemente no obtienen DXF espejo ni diff de entidades.

Selección por `CADVCS_DWG_CONVERTER`:
  - "aspose": usa la librería Aspose.CAD (requiere `aspose-cad` + licencia)
  - "oda":    invoca el binario ODA File Converter (`CADVCS_ODA_BIN`)
  - "none" / ausente: sin conversión (DWG = binario opaco)

Añadir un backend es implementar `Converter.to_dxf(src, dst)`. El worker
y el resto del sistema solo conocen esta interfaz, nunca el motor concreto.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class ConversionUnavailable(RuntimeError):
    """No hay backend de conversión disponible/configurado."""


class Converter:
    """Interfaz de conversión. Subclases implementan `to_dxf`."""

    name = "base"

    def to_dxf(self, src: Path, dst: Path) -> Path:
        raise NotImplementedError

    def available(self) -> bool:
        return True


class NoopConverter(Converter):
    """Sin backend: declara que no puede convertir. El DWG se trata como
    binario opaco (se versiona, pero sin DXF espejo ni diff de entidades)."""

    name = "none"

    def available(self) -> bool:
        return False

    def to_dxf(self, src: Path, dst: Path) -> Path:
        raise ConversionUnavailable(
            "No hay conversor DWG configurado (CADVCS_DWG_CONVERTER). "
            "El DWG se versiona como binario opaco.")


class AsposeConverter(Converter):
    """Backend Aspose.CAD. Requiere `pip install aspose-cad` y licencia.

    Aspose carga el DWG y lo guarda como DXF con `CadRasterizationOptions`/
    `DxfOptions`. La importación es perezosa (solo al usarse) para no exigir
    la dependencia salvo cuando este backend está seleccionado y activo.
    """

    name = "aspose"

    def available(self) -> bool:
        try:
            import aspose.cad  # noqa: F401
            return True
        except Exception:
            return False

    def to_dxf(self, src: Path, dst: Path) -> Path:
        try:
            import aspose.cad as cad
            from aspose.cad.fileformats.cad import CadImage  # type: ignore
        except Exception as exc:  # pragma: no cover - depende de licencia
            raise ConversionUnavailable(f"Aspose.CAD no disponible: {exc}")
        # API de Aspose: cargar imagen CAD y exportar a DXF.
        image = cad.Image.load(str(src))
        try:
            opts = cad.imageoptions.DxfOptions()
            image.save(str(dst), opts)
        finally:
            image.dispose()
        return dst


class OdaConverter(Converter):
    """Backend ODA File Converter (binario externo, EULA propietaria).

    Invoca el ejecutable en modo batch: convierte un directorio de entrada
    a uno de salida en el formato/version destino. Ruta del binario en
    `CADVCS_ODA_BIN` (p.ej. /opt/ODAFileConverter/ODAFileConverter).
    """

    name = "oda"

    def __init__(self):
        self.bin = os.environ.get("CADVCS_ODA_BIN", "ODAFileConverter")

    def available(self) -> bool:
        return shutil.which(self.bin) is not None or Path(self.bin).exists()

    def to_dxf(self, src: Path, dst: Path) -> Path:  # pragma: no cover - binario externo
        src, dst = Path(src), Path(dst)
        in_dir = src.parent
        out_dir = dst.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        # ODAFileConverter <in> <out> <outVer> <outFmt> <recurse> <audit> <filter>
        # outFmt: ACAD2018 DXF ; outVer: "ACAD2018" ; filter por nombre
        cmd = [self.bin, str(in_dir), str(out_dir),
               "ACAD2018", "DXF", "0", "1", src.name]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        produced = out_dir / (src.stem + ".dxf")
        if not produced.exists():
            raise ConversionUnavailable(
                f"ODA no produjo DXF (rc={proc.returncode}): {proc.stderr[:200]}")
        if produced != dst:
            shutil.move(str(produced), str(dst))
        return dst


_BACKENDS = {
    "none": NoopConverter,
    "aspose": AsposeConverter,
    "oda": OdaConverter,
}


def get_converter() -> Converter:
    """Devuelve el conversor según CADVCS_DWG_CONVERTER (default: none)."""
    name = os.environ.get("CADVCS_DWG_CONVERTER", "none").lower()
    backend = _BACKENDS.get(name, NoopConverter)()
    return backend


def is_dwg(repo_path: str) -> bool:
    return repo_path.lower().endswith(".dwg")


class StubConverter(Converter):
    """Conversor de prueba: NO convierte DWG real (imposible sin motor
    licenciado), pero ejercita TODO el camino del worker tratando el
    'DWG' de entrada como un contenedor que ya es DXF válido. Permite
    verificar end-to-end el flujo de conversión, el espejo y el index
    sin depender de Aspose/ODA. Solo para tests."""

    name = "stub"

    def available(self) -> bool:
        return True

    def to_dxf(self, src: Path, dst: Path) -> Path:
        import shutil as _sh
        _sh.copyfile(src, dst)   # el 'DWG' de test ya contiene DXF válido
        return dst


_BACKENDS["stub"] = StubConverter
