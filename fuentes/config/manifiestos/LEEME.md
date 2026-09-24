# Manifiestos de la fuente `config`

Vacío a propósito: la estructura de la base CONFIG no se supone, se lee. Para agregar una tabla:

1. `python -m config_microsip.cli inspeccionar` — lista las tablas reales de tu CONFIG.FDB.
2. `python -m config_microsip.cli generar-manifiesto --tabla <TABLA>` — escribe aquí
   `<tabla>.yaml` con `estado: borrador`, derivado del esquema real.
3. Revisar el borrador (reglas, S/N, catálogos, llaves foráneas anotadas) y pasarlo a `estado: vigente`.
4. `python -m config_microsip.cli capturar --tabla <tabla>` — snapshot en `fixtures/config/`.
5. (Opcional, recomendado) escribir a mano `../golden/<tabla>.json` con casos verificados.
6. `python -m config_microsip.cli extraer --tabla <tabla>`.
