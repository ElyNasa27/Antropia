"""Demostración local de A1 con respuestas FICTICIAS del formulario.

Imprime un informe por respuesta, solo para la persona revisora. No lee ni
escribe en Notion, no envía nada y no toma decisiones.

Uso:
    .\\.venv\\Scripts\\python.exe demo_a1.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from encuentros.a1_revision import revisar
from encuentros.formulario import cargar_respuestas_json

DATOS = Path(__file__).resolve().parent / "datos" / "formulario_ficticio.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("AVISO: respuestas FICTICIAS. A1 solo informa; decide una persona.\n")
    for respuesta in cargar_respuestas_json(DATOS):
        print(revisar(respuesta).texto())
        print("-" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
