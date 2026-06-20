#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║   Instalando J.A.R.V.I.S  v1.0 ║"
echo "  ╚══════════════════════════════════╝"
echo ""

python3 --version >/dev/null 2>&1 || { echo "Error: Python 3 requerido"; exit 1; }

if [ ! -d ".venv" ]; then
    echo "→ Creando entorno virtual..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "→ Instalando dependencias..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo ""
read -p "¿Instalar soporte de voz? [s/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Ss]$ ]]; then
    echo "→ Instalando dependencias de voz..."
    pip install --quiet SpeechRecognition pyttsx3
    pip install --quiet pyaudio 2>/dev/null || \
        echo "  ⚠️  pyaudio falló. Instala: sudo apt install portaudio19-dev python3-pyaudio"
fi

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "  ⚠️  IMPORTANTE: Edita jarvis/.env y agrega tu ANTHROPIC_API_KEY"
    echo "  Obtén tu key en: https://console.anthropic.com/"
else
    echo "→ .env ya existe, no se sobreescribió"
fi

cat > "$SCRIPT_DIR/../run_jarvis.sh" << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/jarvis/.venv/bin/activate"
python3 -m jarvis "$@"
EOF
chmod +x "$SCRIPT_DIR/../run_jarvis.sh"

echo ""
echo "  ✓ Jarvis listo"
echo ""
echo "  Uso:"
echo "    ./run_jarvis.sh                        # Modo interactivo"
echo "    ./run_jarvis.sh -q '¿cuánta RAM tengo?'  # Consulta rápida"
echo "    ./run_jarvis.sh --voice                # Con voz"
echo ""
