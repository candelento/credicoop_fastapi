# Credicoop API Empresas · Python + FastAPI

Proyecto para consultar cuentas, movimientos y Fondos Comunes de Inversión 1810, y generar transferencias, eCheqs y operaciones FCI **con firma posterior en Banca Internet Empresa (BIE)**. Incluye una CLI, vistas previas, consultas de estado, ejemplos y pruebas automatizadas sin operaciones bancarias reales.

## Inicio rápido en Windows

Necesitás Python 3.11 o superior. Descomprimí el proyecto, abrí una terminal dentro de `credicoop_fastapi` y ejecutá:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\configurar.py
```

Copiá tu archivo `30662210877-HOMOprivate.pem` a la carpeta `secrets`. Si el archivo descargado se llama `30662210877-HOMOprivate(1).pem`, renombrá esa copia al nombre indicado o ajustá la ruta en `.env`. La llave se lee desde disco: **no está incluida en este proyecto ni en el ZIP**.

Iniciá el servicio desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

Abrí **http://127.0.0.1:8000/** para usar la pantalla HTML. Ingresá el valor de `CREDICOOP_API_KEY` de tu `.env` y presioná **Conectar**. Es una clave local generada por `configurar.py`; no es el token del banco. La pantalla mantiene esa clave en memoria y no la guarda en el navegador.

La documentación técnica sigue disponible en http://127.0.0.1:8000/docs. Para usarla, hacé clic en **Authorize** e ingresá la misma clave local. Los endpoints de negocio exigen el header `X-API-Key`.

En Linux/macOS, usá `python3 -m venv .venv`, `.venv/bin/python` y las mismas instrucciones con `/` como separador.

## Pantalla HTML y demo local

Para conocer la pantalla sin configurar `.env` ni la llave del banco, instalá `requirements.txt` y ejecutá desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.demo:create_demo_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

Abrí http://127.0.0.1:8000/ e ingresá esta clave exclusiva del modo demo:

```text
demo-local-credicoop-12345678901234567890
```

La pantalla muestra **Demo local · Sin banco**. Este servidor usa respuestas simuladas, cuentas ficticias y una llave RSA temporal. Las operaciones simuladas se pierden al reiniciar. No envía solicitudes a Credicoop y no usa la llave que recibiste del banco.

Para hacer una prueba verdadera en homologación, detené el demo con `Ctrl+C` y arrancá `app.main:create_app` con la configuración de `.env`, tal como se indica en Inicio rápido. La etiqueta pasa a **Homologación** y debés ingresar la clave local de tu `.env`.

### Cómo operar desde el navegador

1. **Cuentas y saldos:** presioná Conectar o Actualizar cuentas. Las cuentas disponibles se cargan en los selectores. Elegí la cuenta de débito por su número; el sistema incorpora su CBU al payload.
2. **Movimientos:** elegí cuenta y fecha Desde. Hasta vacío usa hoy en Argentina. El botón Usar fechas de homologación propone el rango dinámico configurado por el servicio; si el banco rechaza fechas recientes, verificá con el banco el rango habilitado y usalo explícitamente. Podés descargar la respuesta en JSON; los encabezados de saldo se muestran aparte.
3. **Transferencias:** elegí cuenta de débito, beneficiario del Excel de homologación y un importe de prueba. El selector copia nombre normalizado, documento y CBU/CVU. Consultar beneficiario en el banco permite verificar su presencia en la agenda del adherente. Revisá la respuesta.
4. **eCheqs:** elegí un beneficiario de la lista específica de eCheq, un importe, tipo y fecha de pago. ECHC usa el día operativo; ECHD una fecha posterior. La fecha debe confirmarse con el banco para homologación; no se infiere del reloj local ni de la última fecha de movimientos aceptada.
5. **Revisión:** presioná Revisar vista previa. Ese paso valida el payload local y no envía pagos. Un cambio posterior en el formulario invalida la vista previa. Después de revisar, marcá la casilla y presioná Enviar a firma en el banco. Un cuadro muestra ambiente, importe, beneficiario, CBU de débito e ID para confirmar el envío.
6. **Seguimiento:** la respuesta conserva idOperacion, idOrigen y estado real del banco. Consultá de nuevo tras firmar y activar en BIE. Ante un error o timeout, revisá primero el registro local; no crees un nuevo ID para repetir el mismo pago.

El panel **Request / response a la API del banco** muestra los intercambios reales salientes del backend, incluidos método, URL y argumentos, headers, body y respuesta HTTP/body del banco. Si una operación no llegó a invocar al banco (por ejemplo, una validación local o un idOrigen duplicado), el panel lo indica. Los headers y campos que podrían contener credenciales se muestran redactados.

### Probar las órdenes de proveedores con otros destinatarios

**Preparación de pagos** muestra las tres órdenes del ejemplo y sus importes/retenciones originales. Elegí el medio de prueba de una orden y presioná Preparar prueba. La pantalla abre el formulario correspondiente con:

- Un idOrigen nuevo exclusivamente para esa prueba.
- Un importe inicial de **$15,79**, editable.
- El nombre y monto del proveedor original visibles como referencia.
- El selector de beneficiarios de homologación, que debés completar.
- Fechas basadas en el calendario operativo del banco, sin reutilizar las fechas originales de octubre.

Se conservan los PDFs y el Excel de preparación originales. La prueba usa la estructura de la orden, pero no sustituye los proveedores de la planilla real ni marca las órdenes originales como pagadas. Para procesar órdenes reales, usá la pestaña **Órdenes PDF** descrita a continuación.

Si la orden indica CHE, el selector de la prueba ofrece transferencia o eCheq. Esto sirve para validar el circuito electrónico; un cheque físico continúa fuera de la API. Las listas de nuevas altas del Excel no aparecen en el selector de emisión. Los datos de homologación y las órdenes de ejemplo quedan bloqueados por el servidor cuando la URL configurada corresponde a otro ambiente.

### Flujo real de órdenes PDF

La pestaña **Órdenes PDF** lee de Google Drive la carpeta configurada por `CREDICOOP_DRIVE_FOLDER_ID` (por defecto, la carpeta indicada para las órdenes) y procesa exclusivamente los archivos con MIME `application/pdf` cuyo nombre empieza por `op-` y termina en `.pdf`. La cuenta de servicio de Google debe tener acceso de lector a esa carpeta. Guardá el JSON de credenciales localmente como `credentials.json` —o configurá `CREDICOOP_DRIVE_CREDENTIALS_PATH`—; la integración solicita únicamente `drive.readonly`, no modifica ni mueve archivos y nunca muestra la clave privada.

El maestro `Beneficiarios_Credicoop.xlsx` debe estar en la raíz del proyecto, o se puede cambiar mediante `CREDICOOP_SUPPLIER_MASTER_PATH`. Se lee la hoja `Beneficiarios Transferencias` y las columnas `NOMBRE`, `CUIT-CUIL-CDI` y `CBU`. El sistema compara el nombre normalizado del PDF con nombres completos del maestro; no usa coincidencia aproximada. Si no hay exactamente un proveedor, los datos bancarios son inválidos, no puede extraerse un importe único de la misma línea que `TRB`/`CHE`, o la línea `CHE` no tiene exactamente una fecha válida, la orden queda en **Requiere revisión** y no puede enviarse.

Las órdenes se registran en la base SQLite configurada por `CREDICOOP_JOURNAL_PATH`. El `fileId` de Drive evita reprocesar el mismo archivo y el SHA-256 evita importar copias idénticas; si cambia el contenido de un archivo ya importado, queda bloqueado para revisión. El botón **Buscar órdenes nuevas** permite volver a escanear la carpeta sin duplicar pagos.

Para cada orden lista, seleccioná una cuenta de débito y revisá la vista previa. `TRB` genera una transferencia a ConFirma; `CHE` genera un eCheq “A la orden” (`caracter=1`). La fecha de la línea `CHE` se usa como fecha de pago y determina ECHC (igual a la fecha operativa configurada) o ECHD (posterior); una fecha anterior queda para revisión. Sólo al marcar la confirmación y aceptar el último cuadro se envía la operación a Credicoop para firma posterior en BIE. No se ejecutan pagos ni se completan firmas automáticamente. La importación desde Drive está deshabilitada en el modo Demo local.

Endpoints locales autenticados con `X-API-Key`: `GET /ordenes-pago` lista órdenes importadas, `POST /ordenes-pago/sincronizar` sincroniza de solo lectura, `POST /ordenes-pago/{fileId}/previsualizar` prepara una vista previa con el CBU de débito elegido, y `POST /ordenes-pago/{fileId}/enviar` envía la orden a ConFirma. Un intento existente, incluso con resultado incierto, no se puede reenviar; consultá el registro y el banco antes de cualquier acción.

La pantalla deja revisar una operación individual por vez. Los endpoints JSON mantienen el soporte para lotes documentado más abajo. El formulario permite un firmante opcional; para indicar varios operadores usá los endpoints JSON.

## Configuración inicial

| Dato | Valor inicial |
|---|---|
| Ambiente | Homologación |
| Adherente BIE | 661395 |
| Client ID | 30662210877 |
| API | https://homoapibccl.bancocredicoop.coop |
| Audience del JWT | https://homoapibccl.bancocredicoop.coop/auth/realms/homologacion |
| Endpoint de token | Realm + `/protocol/openid-connect/token` |
| Fecha operativa | No fijada por defecto; se usa la fecha actual de Argentina hasta que el banco confirme otra |

Los adherentes, cuentas, firmantes y fechas de ejemplo de Postman **no se usan como datos de tu empresa**. El adherente se incorpora desde `.env`. Los firmantes y el CBU de débito deben corresponder a tu habilitación real de homologación.

La autenticación genera una nueva assertion JWT RS256, con `iss`, `sub`, `aud`, `iat`, `exp` y `jti`, válida durante 60 segundos. Usa `client_credentials` y renueva el access token según `expires_in`; conserva el token sólo en memoria. La firma criptográfica de autenticación no firma ni autoriza los pagos.

El proyecto solicita únicamente los scopes que usa: `cuentas`, `transferenciasConFirma`, `echeqConFirma`, `fciConFirma`, `beneficiarioTransferencia`, `beneficiarioEcheq` y `consultaCbuCvuAlias`. No implementa VEP ni DEBIN en esta versión.

## Funciones bancarias implementadas

| Función | Endpoint local |
|---|---|
| Listar cuentas y sus saldos | `GET /cuentas` |
| Saldo de una cuenta | `GET /cuentas/{nro_cuenta}/saldo` |
| Movimientos entre fechas | `GET /cuentas/{nro_cuenta}/movimientos?fecha_desde=AAAA-MM-DD&fecha_hasta=AAAA-MM-DD` |
| Transferencia pendiente de firma | `POST /transferencias` |
| Emisión eCheq pendiente de firma | `POST /echeqs` |
| Consultar estado de transferencia | `GET /transferencias/estado?id_operacion=...` |
| Consultar beneficiario de transferencia | `GET /beneficiarios/transferencias?cbu_cvu=...` |
| Alta condicional de beneficiario de transferencia | `POST /beneficiarios/transferencias` |
| Consultar/alta beneficiario de eCheq | `GET`/`POST /beneficiarios/echeqs` |
| Consultar emisión eCheq | `GET /echeqs/estado?id_operacion=...` |
| Listar eCheqs generados o recibidos | `POST /echeqs/lista` |
| Previsualizar/gestionar eCheqs | `POST /echeqs/gestion/previsualizar` / `POST /echeqs/gestion` |

`nro_cuenta` es el campo `nroCuenta` devuelto por `/cuentas`, conservando ceros iniciales. Para pagos se usa el **CBU de 22 dígitos**, que también devuelve esa consulta.

### Movimientos y fecha predeterminada

`fecha_desde` es obligatoria. Si no indicás `fecha_hasta`, se toma la **fecha actual de Argentina**, como pediste. La API local acepta `AAAA-MM-DD` y convierte al formato `AAAAMMDD` del banco. La fecha operativa configurada sólo se usa para validar los pagos; no sustituye silenciosamente la fecha actual de las consultas.

No se conserva una fecha operativa bancaria fija: el `.env` local usa `CREDICOOP_FECHA_OPERATIVA=null`, por lo que la validación usa la fecha actual de Argentina. Esto no demuestra que el calendario de homologación coincida con el calendario local. Confirmá la fecha con el banco antes de emitir eCheqs; si el banco informa una fecha distinta, configúrala explícitamente. La consulta de movimientos usa el rango indicado y no deduce una fecha operativa a partir de la fecha del equipo. En una consulta real del 06/10/2026, homologación rechazó fecha hasta posterior al 28/08/2026 pero aceptó un rango histórico terminado ese día; esto no confirma la fecha operativa para pagos.

Si el banco devuelve `alerta` por exceso de registros, el cliente divide el rango en subrangos sin superposición. Si incluso un día excede el tope, devuelve `completa=false` y `rangos_incompletos`. No presenta resultados parciales como completos. Los `ENCABEZADO` se separan de los movimientos porque representan saldos. Se admiten rangos de hasta 367 días por consulta local. Las consultas grandes pueden tardar varios minutos por los límites del banco.

### Transferencias

1. Consultá `/cuentas` y elegí el CBU de débito.
2. Verificá el destinatario con `/beneficiarios/transferencias?cbu_cvu=...`. También podés consultar CBU/CVU/alias en `/destinatarios/consulta`.
3. Copiá y completá `ejemplos/transferencia.json`. Los ejemplos usan beneficiarios del Excel del banco para pruebas, no destinatarios productivos.
4. Usá `POST /transferencias/previsualizar` para ver el payload validado sin contactar al banco ni reservar el ID.
5. Enviá el mismo JSON a `POST /transferencias`.
6. Conservá `idOrigen` e `idOperacion` y consultá `/transferencias/estado?id_operacion=...` o `?id_origen=...`.
7. Los usuarios habilitados completan firma y activación en BIE. El servicio conserva el estado real que responde el banco, por ejemplo `Enviada a la firma` o `Rechazada`.

Los importes se ingresan como texto con punto decimal, por ejemplo `"1234.56"`; se rechazan floats, comas decimales, valores negativos y más de dos decimales. El campo `orden` se genera secuencialmente. Se admiten hasta 200 beneficiarios por transferencia múltiple; los CVU sólo se admiten en operaciones individuales. La documentación indica que actualmente se permiten transferencias en pesos, por eso esta versión valida `ARS`.

`fechaPago` de transferencias es opcional; si se indica, debe ser el día operativo del banco. No programa transferencias futuras. Los nombres admiten puntuación usual; deben corresponder exactamente al beneficiario bancario.

### eCheqs

El procedimiento es equivalente, con `ejemplos/echeq.json`, `/beneficiarios/echeqs?documento=...`, `/echeqs/previsualizar`, `/echeqs` y `/echeqs/estado?id_operacion=...`.

`tipoCheque=ECHC` requiere fecha de pago igual al día operativo. `ECHD` requiere una fecha posterior. La API compara estas fechas con la fecha operativa configurada (dinámica por defecto); confirmá ese día con el banco antes de enviar. Se exige modo cruzado (`modo="1"`) y el carácter se fija siempre como A la orden (`caracter="1"`). No se mezclan cheques con y sin `numeroCheque` dentro del mismo lote. El máximo de eCheqs por lote está parametrizado por el banco y lo valida el banco.

La colección Postman admite `idOrigen` para consultar emisión, mientras que la documentación pública sólo describe `idOperacion`. El endpoint local de eCheq utiliza el parámetro documentado `id_operacion`; si se pierde la respuesta de emisión, revisá el registro local y BIE o consultá al banco antes de repetir.

#### Listado, altas y gestión

`POST /echeqs/lista` recibe `idOrigen` y un `filtro` con `gestion=GENERADOS|RECIBIDOS`, estados documentados, rangos de fecha y `pagina` (por defecto 1) y `limite` (20). La respuesta vacía se conserva como respuesta real del banco.

Las altas de agenda usan `POST /beneficiarios/transferencias` y `POST /beneficiarios/echeqs`. El ejecutor de homologación primero consulta cada beneficiario y sólo intenta un alta cuando recibe el código oficial específico de “no existe en la agenda” (`APIE-7017` para transferencias o `APIE-8014` para eCheq). No toma errores de autenticación, conexión u otros errores de negocio como ausencia. Tras un intento de alta consulta otra vez; el `idOrigen` de cada alta es estable y el Journal impide volver a transmitirlo.

`POST /echeqs/gestion` acepta `ACEPTAR`, `ENDOSAR` y `DEPOSITAR`. ENDOSAR exige `tipoEndoso` y beneficiario; DEPOSITAR exige monto y fecha de pago por cada cheque. El listado devuelve el identificador como `chequeId` y el CMC7 completo como `cmc7completo`; el cliente los envía como `idCheque` y `cmc7`. Las previsualizaciones no consultan ni modifican el banco. Una respuesta de gestión puede carecer de `idOperacion`; no se exige ese campo para registrar una respuesta.

#### Consultas/evidencias reales de homologación

Desde PowerShell, en la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe .\scripts\probar_homologacion.py
```

El script usa `.env`, restringe el host a `homoapibccl.bancocredicoop.coop`, consulta cuentas, movimientos con `nroCuenta`, beneficiarios de la planilla de pruebas y listas GENERADOS/RECIBIDOS. Sin parámetros usa un rango reciente para movimientos; los parámetros opcionales `--movimientos-desde AAAA-MM-DD --movimientos-hasta AAAA-MM-DD` permiten indicar un rango en conjunto. Ante rechazo del banco, no supongas una fecha límite, confirmá con el banco el rango permitido. Prepara las vistas previas de ARS 1.00, pero **no envía pagos ni gestiones**. Sólo intenta altas cuando la respuesta bancaria confirma la ausencia con el código específico; las verifica con una nueva consulta.

Cada intercambio HTTP bancario —incluida autenticación, error o intento sin respuesta— se guarda junto con las llamadas locales de FastAPI en `evidencias/<fecha_hora>/`: `.request.txt`, `.response.txt`, JSON por llamada, `intercambios.jsonl`, `RESUMEN.md` y `RESUMEN.csv`. Authorization, tokens, client_assertion, claves y contraseñas se redactan. Un HTTP 200 sólo identifica una respuesta recibida; no prueba que un pago se haya completado ni que el scope esté homologado. Las mutaciones de transferencia, emisión y gestión quedan pendientes de confirmación conjunta de payloads antes de ejecutarse.

El ejecutor usa `ejemplos/beneficiarios_homologacion.csv`, que está disponible en este proyecto, y compara CBU con `Beneficiarios_Credicoop.xlsx`. Si falta el libro del banco `BeneficiariosHomologacionAPI EMPRESA(3).xls`, lo informa y no deduce de ello que falten beneficiarios en la agenda.

### Firmantes

`operadoresFirmantes` es opcional en la documentación. Si conocés los operadores habilitados para este adherente, agregalos:

```json
"operadoresFirmantes": [
  {"documento": "DOCUMENTO_REAL_DEL_OPERADOR", "documentoTipo": "DNI"}
]
```

Si dejás `[]`, el campo se omite y el banco resuelve la operatoria según las habilitaciones del adherente. No se reutiliza el DNI de muestra de Postman. Antes de la prueba transaccional, verificá con el banco que el esquema de firmas y los operadores estén habilitados. Los beneficiarios deben existir en la agenda BIE; este proyecto los consulta y no realiza altas automáticamente.

## Fondos comunes de inversión 1810

La integración sigue las nueve páginas de la [documentación oficial de FCI del Banco Credicoop](https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/introFci): consulta de cuentas comitentes, lista de fondos, suscripción, estado de suscripción, rescate, estado de rescate, saldos, movimientos y detalle de movimiento.

El token requiere el scope `fciConFirma`, habilitado por el banco para el adherente. El `.env.example` ya lo incluye. Si tu `.env` se creó antes de esta integración, agregá `fciConFirma` a `CREDICOOP_SCOPES` sólo después de confirmar la habilitación con el banco; la app responde con un error explícito en las rutas FCI si falta. No agregues el scope `fci` de envío directo: las operaciones de inversión se transmiten exclusivamente a firma en BIE.

El firmante de todas las suscripciones y rescates FCI se fija en el servidor como DNI `44379155`. El cliente no puede sustituir ese dato; verificá que corresponda a un operador habilitado para el adherente. El DNI se agrega únicamente a las operaciones FCI, no altera los firmantes de transferencias ni eCheqs.

Si el banco no informa `cuentasVinculadas`, la API local asocia automáticamente el CBU de la empresa `1910054455005400309496` para débito/crédito en FCI y expone un aviso en la respuesta de `GET /fci/cuentas-comitentes`.

| Función | Endpoint local |
|---|---|
| Consultar cuentas comitentes, CBU vinculados, perfil y vigencia del test | `GET /fci/cuentas-comitentes` |
| Consultar fondos, código, moneda, valor, perfil y plazo | `GET /fci/fondos` |
| Previsualizar una suscripción, sin contactar al banco | `POST /fci/suscripciones/previsualizar` |
| Enviar suscripción a firma | `POST /fci/suscripciones` |
| Consultar el estado de suscripción | `GET /fci/suscripciones/estado?id_operacion=...` o `?id_origen=...` |
| Previsualizar un rescate, sin contactar al banco | `POST /fci/rescates/previsualizar` |
| Enviar rescate a firma | `POST /fci/rescates` |
| Consultar el estado de rescate | `GET /fci/rescates/estado?id_operacion=...` o `?id_origen=...` |
| Consultar tenencia valorizada | `POST /fci/saldos` |
| Consultar movimientos por comitente | `POST /fci/movimientos` |
| Consultar detalle de un movimiento | `GET /fci/movimientos/detalle?tipo=...&numero=...&sucursal=...&formula=...` |

| Método banco | Ruta banco | Uso en la pantalla |
|---|---|---|
| `GET` | `/api/fci/v1/cuentas-comitentes` | Cuentas comitentes, perfil, test y CBU vinculados |
| `GET` | `/api/fci/v1/fondos` | Fondos disponibles |
| `POST` | `/api/fci/v1/ConFirma/suscripcion` | Envío de suscripción a firma |
| `POST` | `/api/fci/v1/ConFirma/rescate` | Envío de rescate a firma |

Las consultas de cuentas y fondos generan un `idOrigen` nuevo automáticamente. Las consultas de saldos y movimientos aceptan `cuentaComitente` con `tipoCuenta`, `sucursalCuenta` y `numeroCuenta`; la app agrega adherente e identificador y convierte las fechas al formato `AAAAMMDD` del banco. Para detalle se requiere la referencia del movimiento (`tipo`, `numero`, `sucursal`, `formula`).

Suscripción: enviá `idOrigen`, `cbuCuentaDebito`, `cuentaComitente` y `solicitudSuscripcion` (`codigoFondo`, `moneda`, `monto`, `avanzarTestVencido`, `aceptarRiesgoExcedido`). Los dos últimos campos son decisiones explícitas: deben ser `true` para avanzar, respectivamente, con un test vencido o con un perfil de riesgo excedido. No se activan automáticamente.

Rescate: enviá `idOrigen`, `cbuCuentaCredito`, `cuentaComitente` y `solicitudRescate` con `codigoFondo` y `moneda`, además de **exactamente uno** entre `monto` y `cuotapartes`. Los datos del fondo, moneda, perfil de riesgo, plazo, horario y monto mínimo se consultan en la respuesta del banco y en [ProAhorro](https://www.proahorro.com.ar/); la API bancaria valida límites y condiciones vigentes.

Las rutas `POST` de envío reservan `idOrigen` en el registro SQLite antes de invocar al banco. Si hay timeout o se pierde la respuesta, consultá el estado por `idOrigen` y el registro local; no reenvíes con un ID nuevo. `Enviada a la firma` no significa que la operación esté concretada: los firmantes deben completar el circuito en BIE. La pantalla **Fondos 1810** cubre consultas, vista previa, envío a firma y seguimiento.

## Uso como script

Con FastAPI iniciado, abrí otra terminal. En Windows, reemplazá `python` por `.\.venv\Scripts\python.exe` si no activaste el entorno:

```bash
python credicoop.py cuentas
python credicoop.py saldo NUMERO_CUENTA
python credicoop.py movimientos NUMERO_CUENTA --desde AAAA-MM-DD --hasta AAAA-MM-DD --salida movimientos.json
python credicoop.py movimientos NUMERO_CUENTA --desde AAAA-MM-DD
python credicoop.py transferencia ejemplos/transferencia.json
python credicoop.py echeq ejemplos/echeq.json
```

Los dos últimos comandos sólo previsualizan. Después de completar y revisar los archivos, agregá `--enviar` para transmitir la instrucción a firma:

```bash
python credicoop.py transferencia ejemplos/transferencia.json --enviar
python credicoop.py echeq ejemplos/echeq.json --enviar
python credicoop.py estado transferencia --id-operacion ID_DEVUELTO_POR_EL_BANCO
python credicoop.py estado echeq --id-operacion ID_DEVUELTO_POR_EL_BANCO
```

## Control de duplicados y resultados inciertos

Cada instrucción exige un `idOrigen` único, de hasta 36 caracteres. Generá uno una sola vez para cada nuevo pago y guardalo junto a la instrucción. Podés usar `python -c "import uuid; print(uuid.uuid4())"`. No se genera un nuevo ID automáticamente al reenviar un formulario.

El servicio reserva el ID en SQLite **antes** de contactar al banco y nunca repite automáticamente los POST. Cualquier segundo envío con el mismo tipo e ID devuelve HTTP 409, aunque cambies importe o reinicies el servicio. El registro persiste en `data/operaciones.sqlite3`; no borres esa base para reintentar.

Consultá `GET /operaciones/transferencia/{id_origen}` o `/operaciones/echeq/{id_origen}` para ver el registro local. `RESPUESTA_RECIBIDA` describe el resultado de la comunicación, no que el pago esté ejecutado. El estado bancario se conserva en `resultado` y debe consultarse nuevamente después de la firma.

Ante `RESULTADO_INCIERTO` o `ENVIO_INICIADO` sin resultado, revisá el banco/BIE antes de crear otra instrucción. Incluso tras un error confirmado, esta versión mantiene bloqueado el ID; una instrucción corregida requiere un nuevo ID y confirmar previamente que la anterior no se ejecutó. Si un lote tiene aceptación parcial, verificá cada elemento antes de crear pagos de los que faltan.

El registro local protege reenvíos del **mismo ID**. Usar otro ID para el mismo pago puede duplicarlo: mantené un ID por instrucción dentro de tu sistema de gestión.

## Pruebas y alcance

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Las pruebas usan un servidor bancario simulado con `httpx.MockTransport` y una llave RSA temporal. Cubren firma JWT, fecha operativa, montos exactos, autenticación local, consultas FCI, payloads ConFirma con DNI fijo, validación del rescate, renovación de token en lecturas, ausencia de reintentos de pagos, duplicados persistentes, respuestas inválidas, rangos truncados y fecha hasta predeterminada. No envían dinero, eCheqs ni operaciones FCI al banco.

La llave PEM adjunta fue comprobada localmente como RSA utilizable para RS256. **No se validaron el token ni las operaciones contra el banco**. Faltan el CBU de débito de homologación, la verificación de firmantes/beneficiarios de tu adherente y la prueba real de ida y vuelta incluyendo firma en BIE. El banco puede exigir otros permisos o validaciones de negocio; los errores se conservan para revisarlos.

## Ejecución y datos

Ejecutá una sola instancia y un solo worker: el regulador local mantiene unas 48 solicitudes/minuto incluyendo autenticación, y el banco fija 50/minuto globalmente. Otros consumidores del mismo acceso también cuentan para ese límite. Para múltiples servidores se necesita un limitador y registro transaccional compartidos.

El ejemplo escucha en `127.0.0.1`. Para acceso remoto, agregá HTTPS y el control de usuarios de tu infraestructura antes de publicarlo. Se verifica TLS del banco; si hay un certificado privado, configurá el CA entregado por el banco en `CREDICOOP_CA_BUNDLE`.

No incluyas `.env`, la llave PEM ni `data/` en repositorios. La base local conserva respuestas con información bancaria; protegé esa carpeta y respaldala. El ZIP no contiene credenciales privadas, tokens, ni la colección original.

Para producción, obtené del banco las URLs y credenciales productivas, configurá el entorno correspondiente y quitá la fecha operativa fija: `CREDICOOP_FECHA_OPERATIVA=null`. No cambies solamente el host dejando credenciales o fechas de homologación.

## Fuentes verificadas

Documentación oficial consultada el 05/10/2026:

- https://www.bancocredicoop.coop/apiempresas/docs/intro/
- https://www.bancocredicoop.coop/apiempresas/docs/autenticacion/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/cuentas/listarCuentas/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/movimientos/listarMovimientos/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/transferencias/transferir/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/transferencias/consultaTransferencia/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/echeq/emitirEcheq/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/echeq/consultaEcheq/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/introFci/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/consultaCuentasComitentes/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/consultaListaFCI/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/suscribirFCI/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/consultaOperacionSuscripcionFCI/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/rescatarFCI/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/consultaOperacionRescateFCI/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/consultaSaldosPorComitente/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/consultaMovimientosPorComitente/
- https://www.bancocredicoop.coop/apiempresas/docs/apis/fci/consultaDetalleMovimientoPorComitente/

También se contrastaron la colección `APi Empresas ConFirma HOMOLOGACION.postman_collection(1).json`, el Excel `BeneficiariosHomologacionAPI EMPRESA(1).xls` y los datos de adherente/client ID indicados en el mensaje del banco. Los archivos `ejemplos/beneficiarios_homologacion.json` y `.csv` conservan las listas separadas entre emisión y nuevas altas. Usalas exclusivamente en homologación.
