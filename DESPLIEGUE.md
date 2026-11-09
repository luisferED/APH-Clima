# Instrucciones de despliegue actualizadas

La guia portable anterior queda reemplazada por [DESPLIEGUE_DOKPLOY.md](DESPLIEGUE_DOKPLOY.md).

El servidor ahora requiere autenticacion del operador y origen HTTPS. Los lanzadores BAT originales se conservan para referencia; no configuran las variables de seguridad ni importan datos y no deben usarse como procedimiento de produccion. El acceso desde otra PC se hace mediante el proxy TLS corporativo, nunca exponiendo directamente Python.
