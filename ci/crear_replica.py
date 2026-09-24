"""Crea, en un Firebird Server, la réplica de CONFIG que usa la CI: estructura
real (ci/config_replica.sql) + filas inventadas (ci/datos_replica.sql).

Es el ÚNICO código del repositorio que escribe en Firebird, y solo puede
*crear* una base nueva: ``create_database`` falla si el archivo ya existe, y el
script se niega a correr en modo embebido (sin FIREBIRD_HOST), así que no puede
tocar una CONFIG.FDB local. Lee la misma configuración que el proyecto
(FIREBIRD_HOST, FIREBIRD_PORT, FIREBIRD_DATABASE, FIREBIRD_USER, FIREBIRD_PASSWORD,
FIREBIRD_CLIENT_LIBRARY).

    python ci/crear_replica.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent


def sentencias(ruta: Path) -> list[str]:
    texto = "\n".join(l for l in ruta.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("--"))  # noqa: E741
    return [s.strip() for s in re.split(r";\s*\n", texto) if s.strip()]


def main() -> int:
    host = os.environ.get("FIREBIRD_HOST")
    base = os.environ.get("FIREBIRD_DATABASE")
    if not host or not base:
        print("Se requiere FIREBIRD_HOST y FIREBIRD_DATABASE (nunca modo embebido).", file=sys.stderr)
        return 2
    import firebird.driver as fb

    if os.environ.get("FIREBIRD_CLIENT_LIBRARY"):
        fb.driver_config.fb_client_library.value = os.environ["FIREBIRD_CLIENT_LIBRARY"]
    dsn = f"{host}/{os.environ.get('FIREBIRD_PORT') or 3050}:{base}"
    usuario, password = os.environ.get("FIREBIRD_USER", "SYSDBA"), os.environ.get("FIREBIRD_PASSWORD", "")
    con = fb.create_database(dsn, user=usuario, password=password, overwrite=False)  # falla si ya existe
    con._encoding = os.environ.get("FIREBIRD_CODIFICACION") or "iso8859_1"  # mismos bytes que MicroSIP (charset NONE)
    try:
        for sql in sentencias(DIR / "config_replica.sql"):
            con.execute_immediate(sql)
            con.commit()
        with con.cursor() as cur:
            for sql in sentencias(DIR / "datos_replica.sql"):
                cur.execute(sql)
        con.commit()
    finally:
        con.close()
    print(f"Réplica de CONFIG creada en {dsn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
