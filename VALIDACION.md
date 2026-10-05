# Validación · 05/10/2026

Resultado: **29 pruebas aprobadas** (`python -m pytest -q`).

Verificado sin contactar al banco:

- Firma RSA/RS256 del JWT, audience del realm, duración de 60 segundos e identificador único.
- Carga local de la llave adjunta: RSA de 2048 bits compatible con el mecanismo de autenticación.
- Autenticación local X-API-Key y uso del adherente 661395 en los payloads.
- Consultas de saldo; conversión de fechas y fecha actual de Argentina predeterminada en movimientos.
- División de rangos ante respuestas truncadas y detección de días todavía incompletos.
- Envíos únicamente a endpoints ConFirma y bloqueo de scopes de envío directo.
- Importes exactos como texto y reglas de fecha para transferencia, ECHC y ECHD.
- Vistas previas sin invocar al banco; recepción y conservación del estado bancario simulado.
- Reserva SQLite persistente, duplicados, timeout y respuestas sin idOperacion.
- Renovación del token tras 401 en consultas, sin reintentos automáticos de operaciones de pago.
- Validación de lotes de transferencia con CVU y eCheqs con chequera mixta.
- Configuración de fecha no fija para producción y generación del esquema OpenAPI.
- Los ejemplos extraídos del Excel validan al completar el CBU de débito.
- Entrega de la página HTML, JavaScript y CSS; clave local obligatoria para los datos bancarios y ejemplos.
- Selector de beneficiarios de emisión y bloqueo de órdenes/beneficiarios de homologación fuera de ese ambiente.
- Modo demo sin credenciales privadas del banco, con envío simulado y control de duplicados.

La verificación del recorrido visual en navegador quedó pendiente: el navegador disponible en esta sesión bloqueó el acceso al servidor local. Las pruebas anteriores verifican los endpoints y recursos servidos, pero no ejecutan los controles JavaScript del navegador.

Se emitió una advertencia de deprecación del transporte `httpx` de `TestClient` en la versión instalada de Starlette; no afecta el resultado de las pruebas ni el cliente HTTP del banco.

Pendiente: prueba end-to-end en homologación con token real, cuenta de débito habilitada, beneficiarios/firmantes del adherente y firma/activación en BIE. No se transmitieron transferencias ni emisiones de eCheq. No se presenta la integración como homologada por el banco.
