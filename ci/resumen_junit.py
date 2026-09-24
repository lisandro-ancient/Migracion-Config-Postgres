"""Escribe en el resumen del job de GitHub ($GITHUB_STEP_SUMMARY, o stdout) una
tabla con el resultado de un reporte JUnit de pytest: totales y cada prueba
fallida con su mensaje. Reusa el lector del panel (config_microsip.pruebas).

    python ci/resumen_junit.py "Pruebas unitarias" junit.xml
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from config_microsip.pruebas import leer_junit


def main() -> int:
    titulo, ruta = sys.argv[1], Path(sys.argv[2])
    if not ruta.exists():
        texto = f"### {titulo}\n\n⚠️ No se generó el reporte JUnit ({ruta}).\n"
    else:
        r = leer_junit(ruta)
        icono = "✅" if r["fallaron"] == 0 and r["errores"] == 0 else "❌"
        texto = (
            f"### {icono} {titulo}\n\n| Total | Aprobadas | Fallidas | Errores | Omitidas |\n|---|---|---|---|---|\n"
            f"| {r['total']} | {r['pasaron']} | {r['fallaron']} | {r['errores']} | {r['saltadas']} |\n"
        )
        malas = [c for c in r["casos"] if c["resultado"] in ("failed", "error")]
        if malas:
            texto += "\n**Pruebas con problemas:**\n\n" + "\n".join(f"- `{c['nombre']}`: {c['mensaje']}" for c in malas) + "\n"
        omitidas = [c for c in r["casos"] if c["resultado"] == "skipped"]
        if omitidas:
            texto += (
                "\n<details><summary>Omitidas</summary>\n\n"
                + "\n".join(f"- `{c['nombre']}`: {c['mensaje']}" for c in omitidas)
                + "\n</details>\n"
            )
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    else:
        print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
