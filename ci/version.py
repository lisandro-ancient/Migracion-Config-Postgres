"""Versión del proyecto: una sola fuente de verdad repartida en tres lugares que
deben coincidir siempre — ``pyproject.toml``, ``src/config_microsip/__init__.py`` y
la sección correspondiente de ``CHANGELOG.md``. Política completa en docs/VERSIONADO.md.

    python ci/version.py actual                 # imprime la versión (y falla si los lugares no coinciden)
    python ci/version.py subir patch|minor|major  # corta una versión nueva con lo que haya en "Sin publicar"
    python ci/version.py subir patch --fecha 2026-10-01 --simular
    python ci/version.py verificar-etiqueta v1.2.0  # la etiqueta de git coincide con todo lo anterior (CI)
    python ci/version.py notas 1.2.0            # notas de la release (sección del CHANGELOG)

``subir`` no hace commit ni crea la etiqueta: imprime los comandos de git para
hacerlo a mano después de revisar el cambio.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PYPROJECT = RAIZ / "pyproject.toml"
INIT = RAIZ / "src" / "config_microsip" / "__init__.py"
CHANGELOG = RAIZ / "CHANGELOG.md"

SIN_PUBLICAR = "## Sin publicar"
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_VERSION_PYPROJECT = re.compile(r'^(version\s*=\s*")([^"]+)(")', re.M)  # regex y no tomllib: 3.11 no escribe TOML
_VERSION_INIT = re.compile(r'(__version__\s*=\s*")([^"]+)(")')


class ErrorDeVersion(ValueError):
    pass


def _leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


def version_pyproject(texto: str | None = None) -> str:
    m = _VERSION_PYPROJECT.search(texto if texto is not None else _leer(PYPROJECT))
    if not m:
        raise ErrorDeVersion("pyproject.toml no declara version")
    return m.group(2)


def version_paquete(texto: str | None = None) -> str:
    m = _VERSION_INIT.search(texto if texto is not None else _leer(INIT))
    if not m:
        raise ErrorDeVersion("__init__.py no declara __version__")
    return m.group(2)


def seccion(changelog: str, version: str) -> str | None:
    """Cuerpo de la sección ``## <version>`` (o ``## Sin publicar``), sin el encabezado."""
    titulo = SIN_PUBLICAR if version == "Sin publicar" else f"## {re.escape(version)}"
    m = re.search(rf"^{titulo}\b[^\n]*\n(.*?)(?=^## |\Z)", changelog, flags=re.M | re.S)
    return m.group(1).strip() if m else None


def siguiente(version: str, parte: str) -> str:
    m = _SEMVER.match(version)
    if not m:
        raise ErrorDeVersion(f"La versión actual no es SemVer X.Y.Z: {version!r}")
    mayor, menor, parche = (int(x) for x in m.groups())
    if parte == "major":
        return f"{mayor + 1}.0.0"
    if parte == "minor":
        return f"{mayor}.{menor + 1}.0"
    if parte == "patch":
        return f"{mayor}.{menor}.{parche + 1}"
    raise ErrorDeVersion(f"Parte desconocida: {parte!r} (major, minor o patch)")


def actual() -> str:
    """La versión, verificando que pyproject.toml, __init__.py y el CHANGELOG coincidan."""
    en_pyproject, en_paquete = version_pyproject(), version_paquete()
    if en_pyproject != en_paquete:
        raise ErrorDeVersion(f"pyproject.toml dice {en_pyproject} y __init__.py dice {en_paquete}")
    if not _SEMVER.match(en_pyproject):
        raise ErrorDeVersion(f"La versión no es SemVer X.Y.Z: {en_pyproject!r}")
    if seccion(_leer(CHANGELOG), en_pyproject) is None:
        raise ErrorDeVersion(f"CHANGELOG.md no tiene una sección para {en_pyproject}")
    return en_pyproject


def cortar_changelog(changelog: str, nueva: str, fecha: str) -> str:
    """Convierte "## Sin publicar" en "## <nueva> — <fecha>" y deja un "Sin publicar" vacío arriba."""
    cuerpo = seccion(changelog, "Sin publicar")
    if cuerpo is None:
        raise ErrorDeVersion(f'CHANGELOG.md no tiene la sección "{SIN_PUBLICAR}"')
    if not cuerpo or cuerpo.startswith("_Nada"):
        raise ErrorDeVersion(f'La sección "{SIN_PUBLICAR}" está vacía: no hay cambios que publicar')
    if seccion(changelog, nueva) is not None:
        raise ErrorDeVersion(f"CHANGELOG.md ya tiene una sección {nueva}")
    return re.sub(
        rf"^{SIN_PUBLICAR}[^\n]*\n",
        f"{SIN_PUBLICAR}\n\n_Nada todavía._\n\n## {nueva} — {fecha}\n",
        changelog,
        count=1,
        flags=re.M,
    )


def subir(parte: str, fecha: str, simular: bool) -> str:
    anterior = actual()
    nueva = siguiente(anterior, parte)
    changelog = cortar_changelog(_leer(CHANGELOG), nueva, fecha)
    pyproject = _VERSION_PYPROJECT.sub(rf"\g<1>{nueva}\g<3>", _leer(PYPROJECT), count=1)
    init = _VERSION_INIT.sub(rf"\g<1>{nueva}\g<3>", _leer(INIT), count=1)
    if not simular:
        CHANGELOG.write_text(changelog, encoding="utf-8")
        PYPROJECT.write_text(pyproject, encoding="utf-8")
        INIT.write_text(init, encoding="utf-8")
    return nueva


def verificar_etiqueta(etiqueta: str) -> str:
    version = actual()
    limpia = etiqueta.removeprefix("refs/tags/").removeprefix("v")
    if limpia != version:
        raise ErrorDeVersion(f"La etiqueta {etiqueta} no coincide con la versión del proyecto ({version})")
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="accion", required=True)
    subs.add_parser("actual")
    p = subs.add_parser("subir")
    p.add_argument("parte", choices=["major", "minor", "patch"])
    p.add_argument("--fecha", default=dt.date.today().isoformat())
    p.add_argument("--simular", action="store_true", help="Mostrar la versión resultante sin escribir nada")
    subs.add_parser("verificar-etiqueta").add_argument("etiqueta")
    subs.add_parser("notas").add_argument("version")
    args = parser.parse_args(argv)
    try:
        if args.accion == "actual":
            print(actual())
        elif args.accion == "subir":
            nueva = subir(args.parte, args.fecha, args.simular)
            if args.simular:
                print(f"{version_pyproject()} → {nueva} (simulación: no se escribió nada)")
            else:
                print(f"Versión {nueva} preparada en pyproject.toml, __init__.py y CHANGELOG.md.\n")
                print("Revisa el cambio y publícalo:")
                print("  git diff")
                print(f'  git commit -am "Versión {nueva}"')
                print(f"  git tag -a v{nueva} -m 'Versión {nueva}'")
                print(f"  git push origin main v{nueva}")
        elif args.accion == "verificar-etiqueta":
            print(
                f"Versión {verificar_etiqueta(args.etiqueta)} coherente en la etiqueta, pyproject.toml, __init__.py y CHANGELOG.md"
            )
        elif args.accion == "notas":
            cuerpo = seccion(_leer(CHANGELOG), args.version.removeprefix("v"))
            if cuerpo is None:
                raise ErrorDeVersion(f"CHANGELOG.md no tiene una sección para {args.version}")
            sys.stdout.write(cuerpo + "\n")
    except ErrorDeVersion as exc:
        print(f"::error::{exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
