# Datos sintéticos de prueba

Todo lo que hay bajo esta carpeta es **inventado** para las pruebas automatizadas: la fuente
`prueba`, la tabla `ELEMENTOS` y el catálogo `GRUPOS` no existen en MicroSIP ni describen la
estructura real de la base CONFIG. Sirven para ejercitar el pipeline completo sin necesitar un
CONFIG.FDB. Las pruebas copian esta carpeta a un directorio temporal (`CONFIG_MICROSIP_DATOS`)
antes de usarla, así que nunca se modifica.
