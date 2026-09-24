import allure
import pytest

from config_microsip.conexion import identificador_seguro
from config_microsip.config import ConfigFirebird, ConfiguracionIncompleta

pytestmark = allure.feature("Configuración de conexión")


def test_embebido_resuelve_ruta_absoluta(monkeypatch, tmp_path):
    monkeypatch.setattr("config_microsip.config.cargar_env", lambda: None)
    monkeypatch.delenv("FIREBIRD_HOST", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FIREBIRD_DATABASE", "CONFIG.FDB")
    monkeypatch.delenv("FIREBIRD_CHARSET", raising=False)
    c = ConfigFirebird.desde_entorno()
    assert c.embebido and c.dsn() == str(tmp_path.resolve() / "CONFIG.FDB")
    assert c.descripcion_segura()["charset_conexion"] == "NONE"
    assert "password" not in c.descripcion_segura()


def test_remoto(monkeypatch):
    monkeypatch.setattr("config_microsip.config.cargar_env", lambda: None)
    monkeypatch.setenv("FIREBIRD_HOST", "servidor")
    monkeypatch.setenv("FIREBIRD_PORT", "3051")
    monkeypatch.setenv("FIREBIRD_DATABASE", "C:\\Microsip datos\\CONFIG.FDB")
    assert ConfigFirebird.desde_entorno().dsn() == "servidor/3051:C:\\Microsip datos\\CONFIG.FDB"


def test_sin_base_configurada(monkeypatch):
    monkeypatch.setattr("config_microsip.config.cargar_env", lambda: None)
    monkeypatch.delenv("FIREBIRD_DATABASE", raising=False)
    with pytest.raises(ConfiguracionIncompleta):
        ConfigFirebird.desde_entorno()


@pytest.mark.parametrize("malo", ["X; DROP TABLE Y", 'A"B', "1ABC", ""])
def test_identificador_seguro_rechaza(malo):
    with pytest.raises(ValueError):
        identificador_seguro(malo)


def test_identificador_seguro_acepta():
    assert identificador_seguro("empresas") == '"EMPRESAS"'
    assert identificador_seguro("RDB$RELATIONS") == '"RDB$RELATIONS"'
