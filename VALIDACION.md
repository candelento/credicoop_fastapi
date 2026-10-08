# Validación · 06/10/2026

Resultado: **52 pruebas aprobadas** (`.\.venv\Scripts\python.exe -m pytest -q`).

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

## Homologación real

Ejecución registrada en `evidencias/20261006_093423_667051_-0300/`:

- OAuth respondió HTTP 200 y entregó los scopes de consulta/beneficiarios y los scopes `transferenciasConFirma` y `echeqConFirma`. Esto no acredita por sí solo homologación del scope ni el estado de una operación.
- Cuentas respondió HTTP 200. Movimientos se consultó usando `nroCuenta` y respondió HTTP 200 para `2026-08-01` a `2026-08-28`.
- Una consulta del 06/10/2026 con rango reciente recibió `E-103313 - FECHA HASTA DEBE SER MAYOR A FECHA DESDE` aunque el rango enviado estaba ordenado cronológicamente. La aceptación del rango histórico hasta el 28/08 no demuestra cuál es la fecha operativa de pagos.
- Consultas de las agendas de beneficiarios respondieron HTTP 200. En la ejecución anterior ya se hicieron ocho altas condicionales (tres de transferencia y cinco de eCheq) sólo luego de recibir los códigos bancarios específicos de ausencia; después se consultaron nuevamente. En esta ejecución no se hicieron altas.
- Listas GENERADOS y RECIBIDOS respondieron HTTP 200 con `echeqs: []` y `totalCheques: 0`. La gestión queda **PENDIENTE POR FALTA DE ECHEQS DE PRUEBA**; no se inventaron identificadores ni se invocó una acción de gestión.
- Las vistas previas locales de transferencia y emisión de ARS 1,00 respondieron HTTP 200. **No se transmitió** transferencia, emisión ni gestión, y no se firmó en BIE. La fecha propuesta de eCheq (07/10/2026) es expresamente no verificada; confirmar fecha operativa con el banco antes de considerar ese payload para envío.
- No se encontró `BeneficiariosHomologacionAPI EMPRESA(3).xls`. El ejecutor informó la ausencia y utilizó el CSV disponible para consultas; no dedujo de ello que un beneficiario faltara en la agenda.

El registro del primer recorrido real está en `evidencias/20261006_092703_937280_-0300/`; incluye las consultas y las altas condicionales con sus verificaciones posteriores. La reejecución indicada arriba dejó un registro separado y no repitió las altas.

La evidencia conserva requests y responses HTTP bancarios y locales, además del resumen CSV/Markdown. Está excluida de Git por contener datos operativos. La hoja XLS entregada por el banco y la planilla local de beneficiarios deben incorporarse al paquete manual de evidencias si se requieren como anexos.

Pendiente: confirmar con el banco la fecha operativa de homologación y proporcionar un eCheq recibido por el adherente en estado apto, con identificador real y datos de acción. Luego de mostrar conjuntamente los payloads y recibir confirmación explícita, se podrán considerar los envíos únicos de transferencia y emisión. No se presenta la integración como homologada por el banco.
