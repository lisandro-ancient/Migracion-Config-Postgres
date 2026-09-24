"""Herramienta de versionado (ci/version.py): la versión vive en tres lugares que
deben coincidir, y cortar una versión nueva mueve "Sin publicar" a la sección nueva."""

import importlib.util
from pathlib import Path

import allure
import pytest

pytestmark = allure.feature("Versionado")

_spec = importlib.util.spec_from_file_location("version", Path(__file__).resolve().parent.parent / "ci" / "version.py")
version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(version)


def test_la_version_del_proyecto_es_coherente():
    from config_microsip import __version__

    assert version.actual() == __version__
    assert version._SEMVER.match(__version__)


@pytest.mark.parametrize(
    ("actual", "parte", "esperada"),
    [
        ("1.0.0", "patch", "1.0.1"),
        ("1.0.7", "minor", "1.1.0"),
        ("1.4.2", "major", "2.0.0"),
    ],
)
def test_siguiente(actual, parte, esperada):
    assert version.siguiente(actual, parte) == esperada


def test_siguiente_rechaza_no_semver():
    with pytest.raises(version.ErrorDeVersion):
        version.siguiente("1.0", "patch")


CHANGELOG = """# Changelog

## Sin publicar

### Agregado

- Algo nuevo.

## 1.0.0 — 2026-09-23

- Primera versión.
"""


def test_cortar_changelog_mueve_sin_publicar_a_la_version_nueva():
    nuevo = version.cortar_changelog(CHANGELOG, "1.1.0", "2026-10-01")
    assert "## Sin publicar\n\n_Nada todavía._\n\n## 1.1.0 — 2026-10-01\n" in nuevo
    assert version.seccion(nuevo, "1.1.0").startswith("### Agregado")
    assert version.seccion(nuevo, "Sin publicar") == "_Nada todavía._"
    assert version.seccion(nuevo, "1.0.0") == "- Primera versión."


def test_no_se_corta_una_version_sin_cambios():
    vacio = version.cortar_changelog(CHANGELOG, "1.1.0", "2026-10-01")
    with pytest.raises(version.ErrorDeVersion, match="vacía"):
        version.cortar_changelog(vacio, "1.2.0", "2026-10-02")


def test_no_se_repite_una_version():
    with pytest.raises(version.ErrorDeVersion, match="ya tiene"):
        version.cortar_changelog(CHANGELOG, "1.0.0", "2026-10-01")


def test_verificar_etiqueta(monkeypatch):
    monkeypatch.setattr(version, "actual", lambda: "1.2.0")
    assert version.verificar_etiqueta("refs/tags/v1.2.0") == "1.2.0"
    with pytest.raises(version.ErrorDeVersion):
        version.verificar_etiqueta("v1.2.1")
