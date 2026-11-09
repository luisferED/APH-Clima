# APH-Clima-2027

Panel Python/SQLite y salidas transparentes 1920x1080 para vMix. Se conserva el diseno original y la consulta manual de MET Norway.

Preparacion Linux/Dokploy: [DESPLIEGUE_DOKPLOY.md](DESPLIEGUE_DOKPLOY.md).
Auditoria y pruebas: [AUDITORIA_Y_PRUEBAS.md](AUDITORIA_Y_PRUEBAS.md).

No arrancar con las instrucciones portables antiguas: PUBLIC_ORIGIN HTTPS es obligatorio. AUTH_ENABLED=true es el valor predeterminado y exige usuario y hash de contrasena; AUTH_ENABLED=false explicito permite acceso sin credenciales, incluidas operaciones administrativas. Mantener restricciones de red y CSRF; ver la guia. No hay credenciales predeterminadas. El runtime Windows y BAT se conservan como originales, pero no se publican ni se incluyen en Docker.

La base incluida es privada y esta excluida de Git/imagen. Importar un snapshot consistente explicitamente; no copiar una base activa sin WAL. Las fuentes Galano tambien se excluyen de distribucion hasta acreditar licencia apropiada.

```sh
python scripts/db_admin.py hash-password
python scripts/db_admin.py check tiempo_aph.db
python -m unittest discover -s tests -v
```

Las pruebas requieren la base original local (9 ciudades/36 dias), excluida del repositorio, y solo modifican una copia temporal. No realizan peticiones a MET ni prueban vMix real. Datos meteorologicos: MET Norway, atribucion https://www.met.no/ y https://api.met.no/ (CC BY 4.0). La temperatura actual corresponde al pronostico disponible, no a una observacion de estacion.

No se ha hecho push ni despliegue. Validar los pendientes de aceptacion antes de produccion.
