# APH-Clima-2027: preparacion y despliegue

Estado: preparado localmente; NO publicado ni desplegado. No se ha conectado al servidor Ubuntu ni modificado otro servicio. Leer AUDITORIA_Y_PRUEBAS.md antes de autorizar produccion.

## Archivos finales y decisiones

compose.yaml es la configuracion definitiva base: Python Linux 3.13, UID/GID 10001, una replica, WAL, /data, volumen externo estable aph_clima_data y red externa dokploy-network. Sin puertos publicados. Dockerfile copia exclusivamente aplicacion y scripts, sin base, fuentes ni runtime Windows. No necesita pip. Limites: 1 CPU, 256 MiB, 96 procesos; logs rotados. El healthcheck verifica HTTP y una lectura de SQLite; no sustituye integrity_check.

.env.example es la plantilla definitiva, sin secretos. server.py y app.js contienen las correcciones. scripts/db_admin.py agrupa generacion de hash, inicializacion por importacion explicita, backup, restauracion y comprobacion. compose.internal.yaml y Caddyfile.internal permiten HTTPS privado por IP sin cambiar Traefik global. tests/test_acceptance.py contiene pruebas aisladas. README.md y DESPLIEGUE.md remiten a esta guia. AUDITORIA_Y_PRUEBAS.md registra hallazgos y limites.

Los HTML, CSS, graphics.py y fuentes originales se conservan. La carpeta runtime y los BAT originales siguen en disco pero estan excluidos de Git y Docker. No hay datos de demostracion en la aplicacion. En una instalacion nueva sin importacion, la base se crea vacia y el operador debe consultar el proveedor.

## 1. Preparar GitHub desde VS Code (sin publicar todavia)

Abrir esta carpeta en VS Code. En terminal PowerShell:

```powershell
python scripts/db_admin.py check tiempo_aph.db
python scripts/db_admin.py backup tiempo_aph.db backups/initial-consistent.db
python scripts/db_admin.py check backups/initial-consistent.db
python scripts/db_admin.py hash-password
```

El respaldo usa SQLite backup y lee las transacciones WAL; mantener juntos el DB original y sus WAL/SHM mientras se hace. No copiar solo el DB vivo ni eliminar sus sidecars. Los backups se crean con nombre nuevo, se verifican antes de publicarse y no se sobrescriben. Guardar otro respaldo fuera del equipo mediante un canal privado.

Cuando decidas crear el repositorio (estos comandos NO se ejecutaron):

```powershell
git init -b main
git add .
git status --short
git diff --cached --stat
git ls-files "*.db*" "*.otf" "*.ttf" ".env" "runtime/*"
```

La ultima orden debe estar vacia. Revisar tambien que no haya claves, contrasenas, archivos de soporte confidenciales ni certificados. Crear repositorio GitHub nuevo **privado**, APH-Clima-2027, sin README/licencia autogenerados. No declarar una licencia del codigo sin confirmar titularidad. Solo despues de revision y cuando autorices publicar:

```powershell
git commit -m "Preparar APH Clima para Dokploy con SQLite persistente"
git remote add origin https://github.com/ORGANIZACION/APH-Clima-2027.git
git push -u origin main
```

Alternativa VS Code: Control de codigo fuente > Inicializar repositorio > revisar staging > Commit > Publicar rama > repositorio privado. No usar Publicar hasta comprobar exclusiones. Las fuentes Galano no se publican: falta evidencia de licencia web/servidor; obtener autorizacion antes de habilitarlas. Conservarlas localmente y transferirlas por canal privado una vez autorizadas. El despliegue conserva sus nombres y CSS para mantener el diseno.

## 2. Prerrequisitos Ubuntu (solo recursos de aph-clima)

No ejecutar docker system prune, compose down -v, ni modificar daemon.json, Traefik global o redes de otros proyectos. Confirmar en Ubuntu que no existe otro servicio llamado aph-clima, que el puerto opcional 9443 esta libre y que existe la red:

```sh
docker network inspect dokploy-network
ss -ltn '( sport = :9443 )'
docker volume inspect aph_clima_data
```

Si el volumen no existe, crearlo. Si existe, inspeccionar propietarios y contenido antes de continuar; no inicializar a ciegas.

```sh
docker volume create aph_clima_data
docker run --rm --user 0:0 -v aph_clima_data:/data python:3.13-slim-bookworm python -c 'import os; os.chown("/data",10001,10001); os.chmod("/data",0o700)'
sudo install -d -m 0750 -o 10001 -g 10001 /opt/aph-clima/fonts
sudo install -d -m 0750 -o 10001 -g 10001 /opt/aph-clima/tls
```

La operacion root anterior es inicializacion de permisos del volumen nuevo; el proceso de aplicacion siempre usa UID 10001. No hacer chown recursivo sobre volumen existente. Transferir las dos fuentes autorizadas a /opt/aph-clima/fonts; nombres exactos GalanoGrotesqueRegular.otf y GalanoGrotesqueBold.otf, propietario 10001:10001, modo 0640. No incluir estos archivos en Git.

## 3. Acceso HTTPS por IP sin dominio publico

Opcion concreta: proxy Caddy aislado de este proyecto con compose.internal.yaml. No toca Traefik. Solicitar a la CA corporativa un certificado TLS con IP SAN **172.20.16.195** y cadena de confianza instalada en cada PC de operador y vMix. Colocar fullchain.pem y privkey.pem en /opt/aph-clima/tls, propietario 10001:10001, directorio 0750, clave 0600. No incluir clave/certificados privados en repositorio. No ignorar errores de certificado ni usar curl -k. No deshabilitar HTTPS.

Completar variables en Dokploy (o copia privada .env para CLI):

```dotenv
PUBLIC_ORIGIN=https://172.20.16.195:9443
OPERATOR_USER=<identificador de operador>
OPERATOR_PASSWORD_HASH=<salida de hash-password>
MET_USER_AGENT=<APH-Clima/1.0 con email real o URL real de contacto>
APH_FONT_DIR=/opt/aph-clima/fonts
CORPORATE_CIDRS=<subredes corporativas reales en CIDR separadas por espacios>
APH_TLS_DIR=/opt/aph-clima/tls
```

No pegar literalmente los marcadores. No asumir /24 a partir de la IP. PUBLIC_ORIGIN debe coincidir exactamente con URL, esquema y puerto del navegador, sin barra final. Configurar ACL de red para permitir 9443 solo desde las subredes aprobadas; Caddy aplica ademas una lista de IPs antes del proxy. En Docker, verificar reglas DOCKER-USER/firewall corporativo: UFW por si solo puede no filtrar puertos publicados. No abrir 9010. Si Docker traduce todas las IPs origen en el entorno, no ampliar la allowlist al gateway; resolver el enrutamiento antes de aceptar produccion.

`auto_https off` en Caddy desactiva emision automatica y redirecciones, NO TLS: el sitio es explicitamente https:// y usa los certificados corporativos. La publicacion esta ligada a 172.20.16.195:9443, nunca 0.0.0.0.

Alternativa Traefik: usar solo un router de este servicio, puerto destino 9010, red dokploy-network, TLS con certificado corporativo ya disponible y middleware IPAllowList con subredes reales. Puede usar un nombre DNS estrictamente interno. No crear dominio publico ni cambiar configuracion global para esto. Validar certificado, aislamiento, CSRF y streaming antes de elegir esta alternativa. La base compose.yaml no crea automaticamente un router ni garantiza un certificado.

## 4. Crear servicio Compose en Dokploy

Abrir la instalacion existente de Dokploy en **172.20.16.195**, usando la URL/puerto administrativo que ya utiliza tu organizacion; no se conoce su puerto ni version y no se inventa. Crear un proyecto nuevo APH-Clima-2027, entorno produccion, servicio de tipo Docker Compose llamado **aph-clima**. Elegir proveedor GitHub, autorizar solamente el repositorio privado nuevo, rama main y directorio raiz `/`. Configurar archivo compose.yaml. Pegar variables anteriores en Environment de ese servicio. Mantener una replica y desactivar despliegues automaticos hasta aceptar pruebas.

Para el acceso por IP, configurar la combinacion `-f compose.yaml -f compose.internal.yaml` si la version de Dokploy admite archivos multiples. Si solo admite un archivo, generar localmente el archivo combinado **sin interpolar secretos**, revisarlo, subirlo al repositorio y seleccionar ese archivo:

```sh
docker compose -f compose.yaml -f compose.internal.yaml config --no-interpolate > compose.dokploy.yaml
```

No generar con interpolacion ni guardar salida que contenga secretos. La variable APH_TLS_DIR sigue siendo ruta del host Ubuntu y APH_FONT_DIR tambien. No anadir dominio en Dokploy cuando se usa Caddy. Construir imagen. **Antes del primer inicio**, importar la base siguiendo seccion 5 usando esa imagen aph-clima:local. Si Dokploy inicia automaticamente al construir, detener solo aph-clima y aph-clima-tls; si se creo una DB vacia, conservarla renombrando el trio como en la restauracion antes de importar. No sobrescribirla.

Con Docker disponible en Ubuntu, comprobar antes del inicio:

```sh
docker compose -f compose.yaml -f compose.internal.yaml config --quiet
docker compose -f compose.yaml -f compose.internal.yaml build aph-clima
```

Desplegar unicamente este servicio/proyecto. Verificar logs, estado healthy de aph-clima y certificados desde la PC de produccion. No conectar este proyecto a bases ni volumenes de otros servicios.

## 5. Importacion inicial consistente

En Windows, crear backups/initial-consistent.db con el comando de seccion 1 y transferir ese unico **snapshot verificado** por SCP/canal corporativo a /opt/aph-clima/import/initial.db en Ubuntu. No transferir una copia suelta del DB activo original. Guardar hash SHA256 en origen y compararlo con sha256sum en destino. El archivo es privado. Con servicio detenido y volumen preparado:

```sh
docker run --rm --user 10001:10001 -e APH_OFFLINE_MAINTENANCE=YES -v aph_clima_data:/data -v /opt/aph-clima/import:/import:ro aph-clima:local python scripts/db_admin.py import /import/initial.db /data/tiempo_aph.db
docker run --rm --user 10001:10001 -v aph_clima_data:/data aph-clima:local python scripts/db_admin.py check /data/tiempo_aph.db
```

Asegurar que UID 10001 puede leer /import/initial.db (directorio 0750, archivo 0640, grupo 10001). El import rechaza destino existente, valida integridad y exige 9 ciudades/36 pronosticos. No hay autoimportacion ni copia de base incluida en la imagen. El estado del operador se conserva sin regenerarlo. La base original tiene consulta del 2026-11-04: son datos historicos, actualizar manualmente antes de emitir. Iniciar proyecto y verificar fecha del panel.

## 6. Backup, restauracion y rollback

Backup consistente con servicio activo, sin tocar otros servicios:

```sh
docker compose exec -T aph-clima python scripts/db_admin.py backup /data/tiempo_aph.db /data/backup-20261109-01.db
docker compose exec -T aph-clima python scripts/db_admin.py check /data/backup-20261109-01.db
docker compose cp aph-clima:/data/backup-20261109-01.db ./backup-20261109-01.db
```

Elegir siempre nombre nuevo. Sacar copia privada fuera del servidor; un backup en el mismo volumen no protege contra perdida del volumen. Definir retencion corporativa. Para restaurar, primero hacer un backup de la base actual, luego detener **solo** servicio y proxy de este proyecto. Nunca restaurar con servidor activo; APH_OFFLINE_MAINTENANCE es una confirmacion explicita, no detecta otros procesos.

```sh
docker compose -f compose.yaml -f compose.internal.yaml stop aph-clima aph-clima-tls
docker run --rm --user 10001:10001 -v aph_clima_data:/data aph-clima:local python -c 'from pathlib import Path; d=Path("/data"); old=d/"rollback-before-restore-01"; old.mkdir(mode=0o700); [(d/n).rename(old/n) for n in ("tiempo_aph.db","tiempo_aph.db-wal","tiempo_aph.db-shm") if (d/n).exists()]'
docker run --rm --user 10001:10001 -e APH_OFFLINE_MAINTENANCE=YES -v aph_clima_data:/data aph-clima:local python scripts/db_admin.py restore /data/backup-20261109-01.db /data/tiempo_aph.db
docker run --rm --user 10001:10001 -v aph_clima_data:/data aph-clima:local python scripts/db_admin.py check /data/tiempo_aph.db
docker compose -f compose.yaml -f compose.internal.yaml up -d
```

Renombrado mantiene juntos DB/WAL/SHM originales y no borra datos. Si restauracion falla, mantener detenido. Rollback: apartar en un directorio nuevo el trio recien restaurado con el mismo procedimiento, y devolver los archivos de rollback-before-restore-01 a /data, sin sobrescribir nada. Verificar integrity_check y estado antes de iniciar. No mezclar sidecars entre bases. Para rollback de codigo, seleccionar commit anterior compatible y reconstruir; conservar el volumen externo. Nunca docker volume rm aph_clima_data ni down -v.

## 7. Operador y vMix

Panel: https://172.20.16.195:9443/ solicita usuario/contrasena por HTTP Basic sobre TLS. No hay credenciales predeterminadas ni contrasena en JS. Usar contrasena unica larga generada por gestor; cambiar hash y reiniciar para rotarla. El navegador puede conservar autenticacion hasta cerrar todas las ventanas del perfil; usar perfil dedicado. No hay sesion ni boton de cierre de sesion; no usar equipos compartidos sin cerrar perfil.

Salidas sin credenciales, solo lectura y dentro de ACL corporativa:

- https://172.20.16.195:9443/output.html?view=current
- https://172.20.16.195:9443/output.html?view=extended
- https://172.20.16.195:9443/output.html (sigue vista del panel)

Browser Input vMix 1920x1080 con transparencia habilitada. Confiar en la CA desde el equipo y el navegador integrado de vMix. Las salidas leen /api/state, /api/weather y /api/events y cargan /weather/local; no consultan MET. No configurar usuario de operador en vMix. /weather/local muestra una ciudad fija, no reemplaza a output.html para sincronizacion.

Las escrituras requieren autenticacion, Origin exacto y X-APH-Request: operator. CORS no habilitado; no publicar wildcard. Cambiar ciudad/vista o limpiar desde el panel; SSE notifica a todas las salidas y fallback consulta estado solo si falla SSE. Al actualizar meteorologia se notifica un nuevo updatedAt para recargar la grafica una vez; no se reinicia el HTML principal. Consulta manual, 9 ciudades en paralelo limitado a 3; maximo 2 intentos, timeout 12s por intento, sin reintentos en 400/403/429, cooldown de 10 minutos y solo una consulta activa. Fallo parcial conserva toda la base previa.

MET es pronostico, incluida la temperatura llamada actual: no son observaciones de estacion. Min/max de hoy solo usa horas disponibles. Fechas locales Bolivia UTC-4. Panel muestra fecha de consulta; no afirmar frescura de un respaldo antiguo. Mostrar creditos MET Norway en documentacion operativa (datos bajo CC BY 4.0); no redisenar las salidas.

Keycloak futuro: proxy OIDC dedicado para rutas del panel y escrituras, sesiones seguras y rol operador; mantener output/APIs GET bajo ACL y sin login interactivo. Validar tokens en componente de confianza, no aceptar cabeceras de identidad de clientes ni desactivar CSRF. Requiere implementacion y pruebas; no se agrega como dependencia ahora.

## 8. Aceptacion previa a produccion

Ejecutar en entorno de ensayo del servidor; no autorizar con pendientes:

1. Build Linux, inicio UID 10001, permisos /data, healthy, limites y rotacion de logs. Confirmar volumen y red por docker inspect. Confirmar ningun recurso ajeno modificado.
2. Importar snapshot: integrity_check ok, exactamente 9 ciudades y 36 dias, mismos kv_store que respaldo. Reiniciar y reconstruir solo aph-clima; verificar mismos datos/estado. No borrar volumen.
3. Desde IP permitida, abrir panel con credenciales correctas; sin ellas 401. POST sin auth 401, Origin ajeno/sin cabecera 403, JSON invalido 400, cuerpo >8192 bytes 413. GET/HEAD de DB/WAL/SHM/.env/server.py/rutas de traversal 404. CORS sin wildcard.
4. Desde una IP fuera de allowlist verificar 403 o rechazo de red, incluyendo salida. Verificar no hay listener 0.0.0.0:9010 ni publicacion accidental por Dokploy. Revisar que clave TLS y bases no estan en Git/imagen.
5. Dos navegadores y dos entradas vMix: cambiar las 9 ciudades, vistas y limpiar; ambos siguen estado. Desconectar/reconectar SSE y comprobar recuperacion. No reconsultas meteorologicas automaticas. Validar heartbeat y ausencia de buffering.
6. Consulta MET real con contacto autorizado: nueve ciudades y 36 dias, fecha nueva, salida actualizada una vez. Repetir en menos de 10 minutos: rechazo sin trafico al proveedor. Simular fallo de red en ensayo y confirmar mismos datos y mensaje de fallo. No provocar carga ni bloqueos deliberados del proveedor.
7. vMix real con fondo de produccion: alpha transparente, 1920x1080, Galano correcta, animaciones, cuatro dias/fechas, sin negro, parpadeo ni recargas periodicas. Comparar visualmente con original. Probar TLS confiable en cada PC.
8. Backup bajo WAL activo, restauracion y rollback en volumen de ensayo: integrity_check, 9/36, estado conservado. Ensayar caida de proceso/arranque y permisos denegados; debe fallar sin inventar datos. Revisar logs sin contrasenas.

No se han ejecutado estas pruebas en el servidor ni en vMix. Ver resultados locales y pendientes en AUDITORIA_Y_PRUEBAS.md.

## Referencias

- MET identificacion y uso: https://api.met.no/doc/TermsOfService y https://api.met.no/doc/GettingStarted
- Pronosticos: https://api.met.no/weatherapi/locationforecast/2.0/documentation
- Licencias Galano: https://www.myfonts.com/collections/galano-grotesque-font-rene-bieder?tab=licensing

Los terminos del proveedor exigen identificacion de contacto; la licencia de escritorio de una fuente no demuestra permiso de web embedding o redistribucion. Confirmar contrato especifico antes del uso servidor.
