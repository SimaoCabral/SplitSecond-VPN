#!/usr/bin/env bash
# Compila splitsecond_vpn.py num binário standalone para Linux.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[*] A criar venv…"
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "[*] A compilar com PyInstaller…"
pyinstaller \
    --noconfirm \
    --onefile \
    --windowed \
    --name splitsecond-vpn \
    --collect-all customtkinter \
    splitsecond_vpn.py

echo
echo "Binário pronto em: $(pwd)/dist/splitsecond-vpn"
