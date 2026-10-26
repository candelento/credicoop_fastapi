# Sistema Bancario | RONANFER

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

Generá una contraseña nueva para cada usuario sin pasarla por argumentos ni guardarla en el código: ejecutá `.\.venv\Scripts\python.exe scripts\hash_password.py` para cada persona y copiá sólo el hash Argon2id en `CREDICOOP_AUTH_USERS_JSON` de `.env` (roles `admin` o `user`). Configurá como mínimo `IMRCandela` y `IMRMelisa`; la primera cuenta administrativa puede crear, desactivar y restablecer usuarios desde **Usuarios y auditoría**. No reutilices contraseñas compartidas en chats. En HTTPS configurá `CREDICOOP_SESSION_COOKIE_SECURE=true`; el ejemplo false es sólo para localhost HTTP.

Abrí **http://127.0.0.1:8000/** e iniciá sesión con tu usuario. El navegador usa una cookie HttpOnly con expiración por inactividad; no necesita la clave API local. Cada **30 minutos desde la última validación de contraseña**, incluso con actividad, se bloquea la interfaz y se solicita la contraseña en una ventana. El servidor rechaza las operaciones de esa sesión con HTTP 428 hasta volver a autenticarse; la revalidación rota la cookie y conserva los límites de intentos fallidos. La expiración por inactividad sigue vigente y también solicita la contraseña si la pestaña está abierta. No se reenvían operaciones automáticamente y las vistas previas deben revisarse de nuevo. **Cerrar sesión** está al pie del menú lateral y también en el popup de bloqueo. Para integraciones/scripts y `/docs`, sigue disponible `CREDICOOP_API_KEY` y el header `X-API-Key`, sin este bloqueo interactivo.

La aplicación audita accesos, consultas y envíos con usuario y fecha/hora. Mantiene el registro transaccional en SQLite para evitar duplicados y genera junto a la base un XLSX diario (`data/auditoria-AAAA-MM-DD.xlsx`) con una hoja por tipo de operación y otra de actividad; también permite exportar períodos desde la interfaz.

En Linux/macOS, usá `python3 -m venv .venv`, `.venv/bin/python` y las mismas instrucciones con `/` como separador.

## Pantalla HTML y demo local

Para conocer la pantalla sin configurar `.env` ni la llave del banco, instalá `requirements.txt` y ejecutá desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.demo:create_demo_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

Abrí http://127.0.0.1:8000/ e iniciá sesión con las credenciales de demostración (no válidas para el servicio real):

```text
Usuario: demo
Contraseña: demo-local-credicoop-12345678901234567890
```

La pantalla muestra **Demo local · Sin banco**. Este servidor usa respuestas simuladas, cuentas ficticias y una llave RSA temporal. Las operaciones simuladas se pierden al reiniciar. No envía solicitudes a Credicoop y no usa la llave que recibiste del banco.

Para hacer una prueba verdadera en homologación, detené el demo con `Ctrl+C` y arrancá `app.main:create_app` con la configuración de `.env`, tal como se indica en Inicio rápido. La etiqueta pasa a **Homologación** y se debe iniciar sesión con el usuario configurado en `CREDICOOP_AUTH_USERS_JSON`.

### Cómo operar desde el navegador

1. **Cuentas y saldos:** iniciá sesión y consultá las cuentas activas. Elegí la cuenta de débito por su número; el sistema incorpora su CBU al payload. El botón XLSX exporta el saldo actual.
2. **Movimientos:** elegí cuenta y fecha; usá los accesos rápidos de 24 horas/3/7 días o un rango personalizado. El resumen muestra operaciones, ingresos, egresos y saldo actual informado por el banco. Los filtros visibles permiten buscar por descripción, importe y tipo, con una acción para limpiarlos. La tabla se pagina; el XLSX incluye todo el período consultado, no solo las filas filtradas. Cambiar la cuenta o las fechas limpia la consulta anterior para evitar confundir resultados. Una respuesta incompleta se identifica como parcial, también en sus indicadores.
3. **Transferencias · TRB:** la sección muestra exclusivamente órdenes GECOM cuyo método de pago es TRB. Seleccioná la cuenta de débito, revisá la vista previa y enviá a firma en BIE.
4. **eCheqs · CHE:** la pantalla muestra solamente las órdenes GECOM de Drive cuyo método es CHE, con revisión y envío a firma. No incluye el listado bancario de eCheqs ni los formularios de aceptar, depositar, endosar o poner en custodia. Los endpoints de consulta y gestión se conservan para integraciones.
5. **Revisión:** la vista previa valida el payload sin enviarlo. Un cambio posterior invalida la vista previa. Después de revisar, confirmá el envío a firma. Para depósito/custodia se exige monto y fecha por cada cheque; el endoso requiere beneficiario.
6. **Inicio:** un encabezado compacto reúne el título, la fecha y los pendientes de firma, dejando más espacio a los indicadores, disponibilidad por cuenta y accesos directos a transferencias, eCheqs y movimientos. La fecha y la última sincronización se muestran por separado; el entorno aparece una sola vez en el encabezado (Demo, Homologación o Producción). Las operaciones de hoy muestran fecha/hora, usuario, beneficiario, importe, estado e idOrigen. El historial de actividad de Usuarios y auditoría lista operaciones, no solicitudes de consulta.

### Órdenes GECOM en Transferencias y eCheqs

Las órdenes se organizan dentro de **Transferencias · TRB** y **eCheqs · CHE**; no hay una sección genérica de órdenes ni una pantalla separada de preparación. En cada lugar se muestran únicamente los PDF `op-*.pdf` cuyo método detectado sea TRB o CHE, respectivamente. **Buscar en Drive** consulta exclusivamente la carpeta Google Drive configurada por `CREDICOOP_DRIVE_FOLDER_ID`; no se permite subir ni importar PDF locales desde la interfaz o la API. La lectura es de solo consulta. La cuenta de servicio de Google debe tener acceso de lector; guardá las credenciales localmente como `credentials.json` —o configurá `CREDICOOP_DRIVE_CREDENTIALS_PATH`—. Se solicita únicamente `drive.readonly` y no se modifican ni mueven archivos.

El maestro `Beneficiarios_Credicoop.xlsx` debe estar en la raíz del proyecto, o se puede cambiar mediante `CREDICOOP_SUPPLIER_MASTER_PATH`. Se lee la hoja `Beneficiarios Transferencias` y las columnas `NOMBRE`, `CUIT-CUIL-CDI` y `CBU`. El sistema compara el nombre normalizado del PDF con nombres completos del maestro; no usa coincidencia aproximada. Si no hay exactamente un proveedor, los datos bancarios son inválidos, no puede extraerse un importe único de la misma línea que `TRB`/`CHE`, o la línea `CHE` no tiene exactamente una fecha válida, la orden queda en **Requiere revisión** y no puede enviarse.

Las órdenes se registran en la base SQLite configurada por `CREDICOOP_JOURNAL_PATH`. El `fileId` de Drive evita reprocesar el mismo archivo y el SHA-256 evita importar copias idénticas; si cambia el contenido de un archivo ya importado, queda bloqueado para revisión.

Para cada orden lista, seleccioná una cuenta de débito y pulsá **Revisar**: se abre **Todo listo para revisar**, con el importe destacado, proveedor, destino y cuenta de débito en tarjetas. El indicador de pasos distingue la revisión, el envío a firma y la posterior autorización en BIE. El JSON bancario queda plegado en **Ver datos técnicos que recibirá el banco**. Marcá la verificación de los datos y pulsá **Confirmar y enviar a firma**; cerrar o volver no envía nada. **Revisar selección** abre una ventana equivalente con el detalle de cada orden y el total del lote. `TRB` genera una transferencia a ConFirma; `CHE` genera un eCheq “A la orden” (`caracter=1`). La fecha de la línea `CHE` se usa como fecha de pago y determina ECHC (igual a la fecha operativa configurada) o ECHD (posterior); una fecha anterior queda para revisión. El envío requiere confirmación explícita y la firma se completa después en BIE. La lectura desde Drive está deshabilitada en el modo Demo local.

Endpoints locales autenticados con sesión de usuario o `X-API-Key`: `GET /ordenes-pago` lista órdenes registradas, `POST /ordenes-pago/sincronizar` sincroniza Drive en modo de solo lectura, `POST /ordenes-pago/{fileId}/previsualizar` prepara una vista previa y `POST /ordenes-pago/{fileId}/enviar` envía a ConFirma. El endpoint de carga local `POST /ordenes-pago/subir` ya no está disponible. Un intento existente, incluso con resultado incierto, no se puede reenviar.

### Consulta de estado bancario

La consulta está en **Inicio**. Para transferencias, la documentación bancaria ofrece una consulta individual que necesita `idOperacion` o `idOrigen`; la interfaz evita pedir esos datos manualmente y lista las transferencias registradas por esta aplicación. El botón de cada fila consulta al banco usando el `idOrigen` ya guardado. Esto no incluye transferencias iniciadas fuera de la aplicación. Para eCheqs, el endpoint oficial de listado permite filtrar y paginar sin que el usuario ingrese `idOperacion`; la interfaz genera un `idOrigen` técnico para la solicitud y pide los rangos de emisión y pago.

La documentación consultada: [Consulta de Transferencia](https://www.bancocredicoop.coop/apiempresas/docs/apis/transferencias/consultaTransferencia/) y [Consulta Listado de Echeqs](https://www.bancocredicoop.coop/apiempresas/docs/apis/echeq/listarEcheqs/).

## Configuración inicial

| Dato | Valor inicial |
|---|---|
| Ambiente | Homologación |
| Adherente BIE | 661395 |
| Client ID | 30662210877 |
| API | https://homoapibccl.bancocredicoop.coop |
| Audience del JWT | https://homoapibccl.bancocredicoop.coop/auth/realms/homologacion |
| Endpoint de token | Realm + `/protocol/openid-connect/token` |
| Fecha operativa de prueba | 2026-08-28, informada por el banco |

Los adherentes, cuentas, firmantes y fechas de ejemplo de Postman **no se usan como datos de tu empresa**. El adherente se incorpora desde `.env`. Los firmantes y el CBU de débito deben corresponder a tu habilitación real de homologación.

La autenticación genera una nueva assertion JWT RS256, con `iss`, `sub`, `aud`, `iat`, `exp` y `jti`, válida durante 60 segundos. Usa `client_credentials` y renueva el access token según `expires_in`; conserva el token sólo en memoria. La firma criptográfica de autenticación no firma ni autoriza los pagos.

El acceso web usa usuarios con hashes Argon2id definidos inicialmente en `CREDICOOP_AUTH_USERS_JSON`; la contraseña no se configura en texto plano. Ejecutá `scripts/hash_password.py` por usuario para generar cada hash. Las sesiones usan cookie HttpOnly/SameSite, vencimiento absoluto e inactividad configurable (`CREDICOOP_SESSION_IDLE_MINUTES`), bloqueo temporal tras cinco fallos y auditoría de accesos. El administrador puede crear usuarios, desactivarlos lógicamente y restablecer contraseñas; cada usuario puede cambiar la propia. La cuenta API `X-API-Key` se conserva sólo para compatibilidad de integraciones y `/docs`.

El proyecto solicita únicamente los scopes que usa: `cuentas`, `transferenciasConFirma`, `echeqConFirma`, `fciConFirma`, `beneficiarioTransferencia`, `beneficiarioEcheq` y `consultaCbuCvuAlias`. `echeqConFirma` se usa para consultar el listado y gestionar eCheqs con firma en BIE; no se habilitan acciones de envío directo. No implementa VEP ni DEBIN en esta versión.

## Las cuatro funciones solicitadas

| Función | Endpoint local |
|---|---|
| Listar cuentas y sus saldos | `GET /cuentas` |
| Saldo de una cuenta | `GET /cuentas/{nro_cuenta}/saldo` |
| Movimientos entre fechas | `GET /cuentas/{nro_cuenta}/movimientos?fecha_desde=2026-08-01&fecha_hasta=2026-08-28` |
| Transferencia pendiente de firma | `POST /transferencias` |
| Emisión eCheq pendiente de firma | `POST /echeqs` |
| Consultar eCheqs con filtros y paginación | `POST /echeqs/listar` |
| Previsualizar y gestionar eCheqs a firma | `POST /echeqs/gestionar/previsualizar`, `POST /echeqs/gestionar` |

`nro_cuenta` es el campo `nroCuenta` devuelto por `/cuentas`, conservando ceros iniciales. Para pagos se usa el **CBU de 22 dígitos**, que también devuelve esa consulta.

### Movimientos y fecha predeterminada

La integración con el banco consulta cuentas en `GET /api/cuentas/v2/listaCuentas` y movimientos en `GET /api/cuentas/v2/{nroCuenta}/movimientos`, enviando `fechaDesde` y `fechaHasta` en formato `AAAAMMDD` y, si corresponde, `codOperativo`.

`fecha_desde` es obligatoria. Si no indicás `fecha_hasta`, se toma la **fecha actual de Argentina**, como pediste. La API local acepta `AAAA-MM-DD` y convierte al formato `AAAAMMDD` del banco. La fecha operativa fija sólo se usa para validar los pagos; no sustituye silenciosamente la fecha actual de las consultas.

Como homologación está posicionada en el 28/08/2026, para probar agosto indicá `fecha_hasta=2026-08-28`. Las consultas posteriores pueden ser rechazadas por el banco. `/configuracion` muestra ambas fechas, y la respuesta de movimientos advierte si consultaste más allá de la fecha de prueba configurada. Si el banco mueve el ambiente, actualizá `CREDICOOP_FECHA_OPERATIVA`.

Si el banco devuelve `alerta` por exceso de registros, el cliente divide el rango en subrangos sin superposición. Si incluso un día excede el tope, devuelve `completa=false` y `rangos_incompletos`. No presenta resultados parciales como completos. Los `ENCABEZADO` se separan de los movimientos porque representan saldos. Se admiten rangos de hasta 367 días por consulta local. Las consultas grandes pueden tardar varios minutos por los límites del banco.

Cada consulta de movimientos (cuentas corrientes y FCI, lista y detalle) registra en el log de la aplicación el REQUEST enviado al banco —método, ruta, parámetros y body— y el RESPONSE recibido —código HTTP, duración y payload— con los secretos redactados. Se controla con `CREDICOOP_LOG_MOVIMIENTOS` (`true` por defecto); las demás consultas no se loguean.

### Transferencias

1. Consultá `/cuentas` y elegí el CBU de débito.
2. Verificá el destinatario con `/beneficiarios/transferencias?cbu_cvu=...`. También podés consultar CBU/CVU/alias en `/destinatarios/consulta`.
3. Copiá y completá `ejemplos/transferencia.json`. Los ejemplos usan beneficiarios del Excel del banco para pruebas, no destinatarios productivos.
4. Usá `POST /transferencias/previsualizar` para ver el payload validado sin contactar al banco ni reservar el ID.
5. Enviá el mismo JSON a `POST /transferencias`.
6. Conservá `idOrigen` e `idOperacion` y consultá `/transferencias/estado?id_operacion=...` o `?id_origen=...`.
7. Los usuarios habilitados completan firma y activación en BIE. El servicio conserva el estado real que responde el banco, por ejemplo `Enviada a la firma` o `Rechazada`.

Los importes se ingresan como texto con punto decimal, por ejemplo `"1234.56"`; se rechazan floats, comas decimales, valores negativos y más de dos decimales. El campo `orden` se genera secuencialmente. Se admiten hasta 200 beneficiarios por transferencia múltiple; los CVU sólo se admiten en operaciones individuales. La documentación indica que actualmente se permiten transferencias en pesos, por eso esta versión valida `ARS`.

`fechaPago` de transferencias es opcional; si se indica, debe ser el día operativo del banco. No programa transferencias futuras. Los textos de nombres, observaciones y referencias se validan sin signos especiales; ingresá nombres normalizados sin tildes ni comas y verificá su correspondencia con el beneficiario bancario.

### eCheqs

El procedimiento es equivalente, con `ejemplos/echeq.json`, `/beneficiarios/echeqs?documento=...`, `/echeqs/previsualizar`, `/echeqs` y `/echeqs/estado?id_operacion=...`.

`tipoCheque=ECHC` requiere fecha de pago igual al día operativo. `ECHD` requiere una fecha posterior. En homologación se comparan con 28/08/2026. Se exige modo cruzado (`modo="1"`) y el carácter se fija siempre como A la orden (`caracter="1"`). No se mezclan cheques con y sin `numeroCheque` dentro del mismo lote. El máximo de eCheqs por lote está parametrizado por el banco y lo valida el banco.

La colección Postman admite `idOrigen` para consultar emisión, mientras que la documentación pública sólo describe `idOperacion`. El endpoint local de eCheq utiliza el parámetro documentado `id_operacion`; si se pierde la respuesta de emisión, revisá el registro local y BIE o consultá al banco antes de repetir.

El listado oficial se consulta con `POST /echeqs/listar`, enviando un `idOrigen` técnico generado por la aplicación y un objeto `filtro` con gestión, estado, fechas y paginación. Estos endpoints están disponibles para integraciones y documentación de la API; el listado bancario y sus formularios de gestión se retiraron de la interfaz web. La sección **eCheqs** conserva únicamente las órdenes CHE leídas desde Drive. La gestión usa `POST /echeqs/gestionar/previsualizar` y `POST /echeqs/gestionar`; admite `ACEPTAR`, `DEPOSITAR`, `ENDOSAR` y `PONER-EN-CUSTODIA`, y se envía únicamente a `/api/echeq/v1/ConFirma/gestion`. Depósito/custodia requieren monto y fecha por cheque; endoso requiere tipo `NOM` y beneficiario. Los envíos quedan registrados por `idOrigen`; la respuesta de gestión documentada no contiene `idOperacion`, por lo que el seguimiento se hace con el registro local y BIE.

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

Las consultas de cuentas y fondos generan un `idOrigen` nuevo automáticamente. Las consultas de saldos y movimientos aceptan `cuentaComitente` con `tipoCuenta`, `sucursalCuenta` y `numeroCuenta`; la app agrega adherente e identificador y convierte las fechas al formato `AAAAMMDD` del banco. Para detalle se requiere la referencia del movimiento (`tipo`, `numero`, `sucursal`, `formula`).

Suscripción: enviá `idOrigen`, `cbuCuentaDebito`, `cuentaComitente` y `solicitudSuscripcion` (`codigoFondo`, `moneda`, `monto`, `avanzarTestVencido`, `aceptarRiesgoExcedido`). Los dos últimos campos son decisiones explícitas: deben ser `true` para avanzar, respectivamente, con un test vencido o con un perfil de riesgo excedido. No se activan automáticamente.

Rescate: enviá `idOrigen`, `cbuCuentaCredito`, `cuentaComitente` y `solicitudRescate` con `codigoFondo` y `moneda`, además de **exactamente uno** entre `monto` y `cuotapartes`. Los datos del fondo, moneda, perfil de riesgo, plazo, horario y monto mínimo se consultan en la respuesta del banco y en [ProAhorro](https://www.proahorro.com.ar/); la API bancaria valida límites y condiciones vigentes.

Las rutas `POST` de envío reservan `idOrigen` en el registro SQLite antes de invocar al banco. Si hay timeout o se pierde la respuesta, consultá el estado por `idOrigen` y el registro local; no reenvíes con un ID nuevo. `Enviada a la firma` no significa que la operación esté concretada: los firmantes deben completar el circuito en BIE. La pantalla **Fondos 1810** cubre consultas, vista previa, envío a firma y seguimiento.

## Uso como script

Con FastAPI iniciado, abrí otra terminal. En Windows, reemplazá `python` por `.\.venv\Scripts\python.exe` si no activaste el entorno:

```bash
python credicoop.py cuentas
python credicoop.py saldo NUMERO_CUENTA
python credicoop.py movimientos NUMERO_CUENTA --desde 2026-08-01 --hasta 2026-08-28 --salida movimientos.json
python credicoop.py movimientos NUMERO_CUENTA --desde 2026-08-01
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
