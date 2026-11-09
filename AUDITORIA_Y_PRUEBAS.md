# Auditoria tecnica y evidencia local

Fecha de referencia: 9 de noviembre de 2026, America/La_Paz.

## Alcance y hallazgos

Se revisaron server.py, graphics.py, app.js, ambos HTML, los tres CSS, launcher.py, BAT, documentacion, inventario de assets y manifest. runtime es una distribucion Python para Windows y no es dependencia de Linux. La aplicacion no importa paquetes de terceros: http.server, SQLite, urllib, threading, futures, datetime y otras bibliotecas estandar.

Flujo real: operador solicita consulta manual MET para nueve coordenadas; parseo UTC-4; estado en kv_store; datos en weather_cache; cuatro dias siguientes por ciudad en forecast_days. Transaccion unica de las nueve ciudades ya existia y se conserva. El actual es dato de modelo, no medicion observada; extremos de hoy usan horas disponibles. SSE envia cambios de estado y JS controla dos iframes para transiciones; output admite vista fija por query o vista del operador. graphics.py renderiza canvas 1920x1080 con iconos CSS locales y transparencia. No se ha reescrito esta representacion.

Problemas corregidos:

- SimpleHTTPRequestHandler permitia servir todo el proyecto, incluso DB/WAL/SHM, Python, runtime y documentacion: GET y HEAD ahora tienen lista exacta de recursos permitidos; sin listado de directorios, traversal o rutas internas.
- CORS wildcard y escrituras publicas: panel con Basic autenticado sobre proxy HTTPS, hash PBKDF2-SHA256 con sal aleatoria/600000 iteraciones, sin defaults; Origin exacto y cabecera personalizada obligatorios en POST. Las salidas y APIs GET permanecen accesibles solo dentro de ACL corporativa, sin permisos de escritura.
- JSON invalido respondia error pero podia continuar y mutar estado: ahora se corta; solo objeto JSON, maximo 8192 bytes, sin Transfer-Encoding.
- Hilos y SSE sin limite, colas infinitas, clientes muertos retenidos: maximo 64 conexiones, 24 SSE, colas de 8 estados, timeout de socket, heartbeat cada 10s y bloqueo del registro de clientes. Snapshot inicial y registro SSE se toman bajo el mismo bloqueo para evitar inversion de eventos.
- Read/modify/write de operador y notificacion fuera del lock: serializados. Lectura de ciudad y extendido para render bajo lock. Se mantiene transaccion de actualizacion completa.
- Conexiones SQLite no se cerraban explicitamente al salir de `with`: contextmanager ahora confirma/revierte y cierra; WAL y busy_timeout 20s. DB_PATH configurable y directorio creado con permisos del usuario no root.
- Refresh sin limite y User-Agent generico: consulta manual unica activa, cooldown 10min, contacto obligatorio configurable, maximo 3 workers, 2 intentos, timeout 12s, sin reintentar 400/403/429. No hay tareas de consulta automatica. Cuando falla cualquier ciudad o parseo se conserva la base previa.
- Actualizacion de cache no invalidaba iframes existentes: cambio de updatedAt y SSE tras commit; JS mantiene transiciones originales y evita polling de estado mientras SSE esta conectado. Panel sincroniza seleccion de vista y recarga metadatos al recibir estado.
- Dependencia de ruta junto a codigo y riesgo de copia de base activa: /data persistente en Docker, importacion explicita con backup SQLite, integrity_check, publicacion atomica por hardlink exclusivo y rechazo de destino existente. Se conserva motor SQLite y no se incluye DB en imagen/repositorio.
- No habia contenedor, permisos ni aislamiento Linux: Docker/Compose con usuario 10001, rootfs read-only, tmpfs limitado, capacidades eliminadas, no-new-privileges, limites y logs rotados. Volumen/red externos evitan cambios sobre servicios ajenos. Bootstrap de permisos es un helper root limitado al volumen nuevo; no es el proceso del servicio.

## Fuentes y publicacion

Solo se encontraron GalanoGrotesqueRegular.otf y GalanoGrotesqueBold.otf, sin contrato/EULA del usuario. No se acredita redistribucion por provenir de un equipo de produccion. La ficha del distribuidor distingue licencias web/desktop y restricciones. Se conservan originales y CSS exactos, pero se excluyen archivos de fuente de Git e imagen; montaje privado opcionalmente habilitado tras acreditar derechos. Esto queda como requisito pendiente de produccion, no como licencia aprobada.

Referencias consultadas: https://www.myfonts.com/collections/galano-grotesque-font-rene-bieder?tab=licensing ; https://api.met.no/doc/GettingStarted ; https://api.met.no/doc/TermsOfService ; https://api.met.no/weatherapi/locationforecast/2.0/documentation . MET exige User-Agent identificable con contacto. No se ha hecho una consulta meteorologica real durante esta tarea.

## Pruebas ejecutadas

En Windows, Python 3.14.6:

- `python scripts/db_admin.py check tiempo_aph.db`: integrity_check ok, 9 ciudades, 36 pronosticos. Estado original: outputMode vacio, weatherCity santa-cruz, weatherView current, updatedAt 2026-11-04T14:52:38Z.
- `python -m unittest discover -s tests -v`: 6 pruebas aprobadas, sobre copia temporal consistente de DB original. Incluyen GET/HEAD de rutas internas 404; panel sin auth 401/con auth 200; POST sin auth 401, origen ajeno 403, JSON no objeto 400 y exceso 413; rutas de salida y salud 200 sin CORS abierto; dos clientes HTTP SSE reciben cambio de ciudad; estado conservado al reinicializar DB; backup preserva kv_store y rechaza sobrescritura; fallo externo preserva datos; refresh simulado actualiza 9/36, parseo incompleto conserva base. Datos sinteticos solo en DB temporal, nunca en DB original ni imagen.
- `python -m py_compile server.py graphics.py scripts/db_admin.py tests/test_acceptance.py`: correcto.
- `node --check app.js`: correcto.
- `docker compose -f compose.yaml -f compose.internal.yaml config --quiet`: codigo 0 con valores temporales de validacion; no son configuracion de produccion ni aprobacion de subredes. CLI advierte acceso denegado a config de Docker del usuario, pero validacion Compose termina correctamente.
- Comparacion SHA256 con MANIFEST-SHA256.json original: sin cambios en index.html, output.html, styles.css, graphics.css, fonts.css, graphics.py, ambas fuentes y tiempo_aph.db. Se preserva diseno/codigo de render original; esto no sustituye prueba visual real. Manifest historico se conserva excluido de publicacion porque ya no describe archivos modificados.

## Pendientes y limites

- Docker CLI 29.5.3 presente, daemon no disponible (pipe docker_engine ausente). No se pudo construir/arrancar imagen Linux ni verificar Caddy, healthcheck en contenedor, UID, limites, reinicio de volumen o recreacion real. Validacion de Compose es solo estructural.
- No hubo acceso al servidor 172.20.16.195 ni modificacion de recursos remotos. Dokploy version/URL administrativa desconocidas: guia describe flujo y alternativa de compose combinado; validar controles en version instalada. No se afirma que el proyecto este desplegado.
- Sin vMix ni pruebas visuales en navegador/alpha/GPU. Dos clientes SSE son clientes HTTP de prueba, no dos navegadores reales. Debe hacerse QA de transparencia, fuentes, animaciones y transiciones en produccion/ensayo.
- MET real, certificados/CA, subredes reales, firewall, permisos de fuentes, DNS interno opcional, streaming tras proxy, stress y caidas reales pendientes. No se verifico licencia especifica del titular.
- Restauracion y rollback completos se documentan, no se ejecutaron en volumen real. La prueba local verifica backup, integridad y conservacion, no una restauracion de produccion.
- Basic tiene credenciales cacheadas por navegador y sin logout aplicativo; usar perfil dedicado, TLS confiable y ACL de red. PBKDF2 y conexiones acotadas reducen abuso pero no sustituyen limitacion perimetral ante ataques internos sostenidos. Backend HTTP es solo interno de Docker; no exponerlo directamente.
- Servicio estandar http.server endurecido para entorno interno con proxy TLS, no plataforma para Internet publico. No se agrega Keycloak; se documenta evolucion OIDC.
- Caddy usa imagen de rama 2 y Python rama 3.13: antes de produccion validar build y fijar digest aprobado por el procedimiento corporativo para reproducibilidad. No se inventan digests.
- El import/restore requiere declaracion de mantenimiento offline, no puede impedir por si mismo que otro proceso use la base. Parar servicio es obligatorio. Archivos originales no se eliminan. No se hizo git init, commit, push ni despliegue.

## Inventario de entrega

Modificados: server.py, app.js, README.md, DESPLIEGUE.md.
Creados: Dockerfile, compose.yaml, compose.internal.yaml, Caddyfile.internal, .dockerignore, .gitignore, .env.example, scripts/db_admin.py, tests/test_acceptance.py, DESPLIEGUE_DOKPLOY.md, AUDITORIA_Y_PRUEBAS.md.

No se requiere modificar ningun otro proyecto, base, red o servicio global. La configuracion opcional usa puerto dedicado 9443 ligado a la IP corporativa y TLS con CA interna, sin dominio publico. Verificar que este libre antes de aplicar. La puesta en produccion depende de superar la lista de aceptacion de DESPLIEGUE_DOKPLOY.md.
