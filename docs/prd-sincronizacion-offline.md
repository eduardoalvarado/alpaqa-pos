# PRD de dominio — Sincronización offline

> Dominio transversal. Referencia el **PRD maestro** (`alcance-mvp-pos.md`) para las decisiones que
> cruzan dominios —snapshot en la línea (§6.A), serie por caja (§6.B), UUID de cliente (§6.C),
> snapshot en el comprobante (§6.D), ciclo `sunatStatus`— y los **lineamientos técnicos** para stack
> y arquitectura. No las repite.

---

## 0. Convención de nombres

Código en inglés y `camelCase`; físico de tablas nuevas en inglés `snake_case` vía `@map`;
comentarios y documentación en español. Prefijo de HU: **`SYN`**. El id/referencia de cada HU es su
clave Jira `ALPQ-N`; `SYN-0x` es etiqueta de orden que reinicia por segmento.

---

## 1. Propósito y alcance del dominio

**Que una venta no dependa de la conexión.** Un negocio pequeño en Perú opera con internet
intermitente; un POS que se detiene cuando se cae la conexión no es un POS, es una web.

El maestro es explícito en dos cosas que acotan este dominio (§2.3):

- **El POS es la única superficie que funciona offline.** La plataforma de gestión y el backoffice
  asumen conexión: administrar el catálogo, crear usuarios o suspender un tenant no son operaciones
  de mostrador.
- **El scope de datos del POS es acotado:** el catálogo de su sucursal, sus mesas y su turno de caja
  abierto. No es una réplica de la base; es el conjunto de trabajo de una caja.

### Lo que este dominio construye

1. **Empuje idempotente** de lo que el POS creó sin conexión: órdenes con sus ítems, turnos, pagos,
   movimientos de caja, comprobantes y notas de crédito.
2. **Bajada del conjunto de trabajo** que el POS necesita para operar sin conexión.
3. **Cola de contingencia SUNAT**: los comprobantes que se emitieron offline quedan en `GENERADO` y
   hay que rendirlos cuando vuelva la conexión. Es la costura que *Facturación* dejó abierta a
   propósito (su §11.3), con el estado `ENVIADO` ya reservado para estrenarla.
4. **Visibilidad del estado de sincronización**: qué quedó pendiente y por qué. Sin esto, "se
   sincronizó mal" es indistinguible de "no se sincronizó".

### Lo que NO construye

- **La cola del lado del cliente.** El almacenamiento local, la detección de conexión y el
  reintento viven en la app POS (repo `alpaqa-pos-frontend`). Este PRD define el **contrato** que
  esa cola consume, y las reglas del servidor. Es el mismo reparto que con el hardware: el puerto
  se define acá, el driver vive del otro lado.
- **Sincronización de administración.** Catálogo, usuarios, roles, empresa: online.
- **Resolución automática de conflictos de negocio.** Ver §6.C: los conflictos reales se rechazan
  con un motivo accionable, no se "resuelven" adivinando.

---

## 2. Ubicación en la arquitectura backend

Módulo hexagonal nuevo **`sync`**, con la particularidad de que **casi no tiene lógica de negocio
propia**: su trabajo es recibir un lote, ordenarlo, y **delegar en los casos de uso que ya existen**.

### 2.1 La decisión que define el dominio: reusar los casos de uso, no duplicarlos

Un endpoint de sincronización que escriba directo en la base sería más simple de escribir y es la
forma más rápida de que las reglas de negocio se bifurquen: la orden creada online valida stock,
capacidad y estado del turno, y la creada offline no. A los tres meses hay dos verdades sobre qué
es una orden válida, y la que corre por sync es la que nadie mira.

**Cómo quedó contenida (SYN-01, mejor que lo que este PRD anticipaba):** la dependencia **no**
atraviesa el módulo. El núcleo de `sync` habla con un puerto propio (`SalesSync`) que usa **tipos propios**
(`SyncOrderDraft`, con campos opacos) y **no sabe que Ventas existe**; quien lo sabe es **un único
adapter** en `sync/infrastructure/sales/`. Importar el input del caso de uso ajeno —el primer
intento— habría hecho que el dominio de `sync` no compilara sin Ventas; es el mismo criterio que ya
usan `CatalogReader` e `InventoryWriter`.

El adapter mapea **campo por campo, no con un spread**: copiar la carga entera dejaba que el POS
mandara `openedByUserId` y le atribuyera la venta a otro usuario, algo que el borde HTTP de Ventas
impide fijándolo desde el token. Ahora el borrador ni siquiera tiene ese campo, así que dejó de ser
una regla que recordar para ser una que el tipo impone. El beneficio
no es purismo: el recorrido del lote se prueba con un doble en memoria en vez de levantar medio
backend, y sumar Cobros (SYN-02) o Facturación (SYN-03) es agregar un puerto, no enredar el que ya
está.

**Confirmado en SYN-02**: Cobros entró como un segundo puerto (`CashboxSync`) con sus propios tipos
opacos y un único adapter (`CashboxSyncAdapter`), sin tocar el puerto de Ventas ni el recorrido del
lote más allá de sus cuatro `case` nuevos. El `switch` exhaustivo hizo su trabajo: los tipos nuevos
no compilaban hasta decidir su permiso y su rama.

**Y en SYN-03 con Facturación** (`BillingSync`), que es donde más importa: un comprobante tiene
reglas con consecuencias legales —orden cerrada y liquidada, uno por orden, la serie activa de la
caja que cobró, factura con RUC, snapshot de totales— y escribir directo en la base habría creado
una segunda definición de documento fiscal válido. Eso no es deuda técnica: es un problema con
SUNAT.

**Regla del dominio:** `sync` no crea entidades. Traduce cada operación del lote a la llamada del
caso de uso que ya la gobierna —`CreateOrderUseCase`, `RegisterPaymentUseCase`,
`EmitComprobanteUseCase`…— y colecta el resultado. Si una regla rechaza la operación, el rechazo
viaja al POS tal cual: **una venta offline que viola una regla no es una venta que haya que
salvar**, es una que hay que mostrarle al cajero.

Consecuencia de diseño: `sync` **depende de los módulos de dominio**, al revés que el resto del
backend. Es la primera dependencia módulo→módulo deliberada del proyecto, y por eso se acota:
depende de sus **casos de uso** (la capa de aplicación), nunca de sus repositorios ni de su Prisma.

> Deuda conocida que este dominio hereda: `sales → inventory` ya es una dependencia
> módulo→módulo (vía `prisma-inventory-writer`). Conviene resolverla o darle nombre antes de
> multiplicarla; ver §11.

### 2.2 Por qué no es un worker aparte

La cola de contingencia SUNAT es trabajo diferido y la tentación es un proceso worker. **No en el
MVP**: son dos desplegables ya (§2.2 de lineamientos) y un tercero se paga en operación, no en
código. El reintento corre **en el proceso de tenant**, disparado por el propio POS al
sincronizar y por un temporizador acotado. Cuando el volumen lo pida, la costura es mover el
disparador; el caso de uso no cambia.

---

## 3. Modelo de datos

**Casi todo ya existe.** El cimiento dejó puesta la costura, y esto es lo que hay que verificar
antes de agregar nada:

| Ya existe | Dónde | Para qué sirve acá |
|---|---|---|
| `clientUuid` + `@@unique([companyId, clientUuid])` | `Order`, `CashShift`, `Payment`, `CashMovement`, `Comprobante`, `CreditNote` | **Idempotencia del empuje.** Reenviar un lote no duplica nada: la base lo impide |
| `ComprobanteSeries` con `@@unique([cashRegisterId, type])` | Facturación | **Serie por caja** (§6.B): cada dispositivo es dueño de su numeración, así que offline no hay que coordinar con nadie |
| `currentCorrelative` | `ComprobanteSeries` | High-water mark reconciliado (§6.B) |
| `sunatStatus` con `ENVIADO` | Facturación | El estado intermedio que estrena la cola |
| Snapshot de precio/IGV en la línea | Ventas (§6.A) | Un lote viejo **no** se recalcula con el catálogo de hoy |

### 3.1 Lo único nuevo: el estado de la cola de contingencia

**`SunatDispatch`** (`@@map("sunat_dispatch")`) — el estado de reintento de un comprobante:

| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid | tabla de tenant: RLS + `GRANT` (invariante del cimiento) |
| comprobanteId | uuid único | uno por comprobante |
| attempts | int | cuántas veces se intentó |
| lastAttemptAt | timestamp NULL | |
| nextAttemptAt | timestamp | backoff; la cola solo toma los vencidos |
| lastError | text NULL | el motivo del último rechazo, para que el dueño lo vea |

**Por qué una tabla y no columnas en `Comprobante`:** el comprobante es un documento legal e
inmutable (§6.D). El estado de una cola de reintentos no es parte del documento; mezclarlos hace
que cada reintento "toque" una fila que el modelo declara inmutable.

### 3.2 Deuda de cobertura que SYN-01 deja anotada

La idempotencia bajó a la base —el repositorio de órdenes resuelve el `P2002` de sus dos únicos
preguntándole a la base cuál chocó, porque este driver no puebla `meta.target`— pero **ese camino
no tiene cobertura determinista**: una carrera real no se fuerza desde afuera. Hay un e2e que manda
cuatro lotes idénticos en paralelo y exige que ninguno dé 500 y que exista una sola orden, pero
puede resultar **vacuo** si las requests no se solapan en la ventana justa. Está dicho así en el
propio test. Cerrarlo de verdad exigiría una prueba a nivel de repositorio con contexto de tenant
abierto a mano; se anota como deuda antes que fingir que está probado.

### 3.3 SYN-02: ninguna tabla nueva, y una columna que la auditoría rescató

El momento del hecho de la caja ya tenía dónde vivir, y el reparto quedó igual que en SYN-01b:

- **`CashShift.openedAt` / `closedAt` son el momento del hecho** —lo manda el dispositivo si el
  turno se abrió o se arqueó sin conexión— y `createdAt`/`updatedAt` son cuándo llegó al servidor.
  No hizo falta un `recordedAt`: a diferencia de `Order`, esta tabla ya tenía separados el momento
  del negocio y el de la fila.
- **`Payment.createdAt` y `CashMovement.createdAt` son el momento del hecho**, mismo criterio que el
  movimiento de stock en SYN-01b: son asientos, y el instante del asiento **es** el del hecho.
- **`Payment.recordedAt` y `CashMovement.recordedAt` son nuevas** (migración `syn02_recorded_at`).
  El primer intento las dio por innecesarias apoyándose en el precedente del movimiento de stock, y
  la auditoría de arquitectura lo objetó con el argumento correcto: al dejar que el lote fijara
  `created_at` se **borró el sello del servidor**, y estos son los registros del arqueo, fechados
  por el **reloj del dispositivo** —que se acepta sin cota hacia el pasado, porque una semana sin
  conexión es el caso de uso—. Sin `recorded_at` no quedaba ningún dato del servidor sobre un
  movimiento de dinero, y la diferencia entre los dos momentos es justo lo que permite ver que un
  dispositivo estuvo días sin sincronizar (lo que `GET /sync/status` va a mostrar en SYN-06).
  `CashShift` no la necesitó: ya tenía separados el momento del negocio (`opened_at`/`closed_at`) y
  el de la fila (`created_at`).
- El `GRANT` no cambió en ninguna de las tres tablas: son de tabla, no por columna. (Sí hay que
  recordar que Prisma manda las columnas con `@default` **nombradas** en el `INSERT`, lineamientos
  §2.4, así que un `GRANT` por columna sí habría tenido que incluirlas.)

**Actualización SYN-02:** el mismo backstop bajó a la base para **turno, cobro y
movimiento** —`P2002` → releer por `clientUuid`; y si al abrir turno el que chocó fue el
índice parcial `WHERE status='OPEN'`, `SHIFT_ALREADY_OPEN`—, y el **cierre** dejó de
poder pisar un arqueo firmado: cierra con `UPDATE ... WHERE id = ? AND status = 'OPEN'` y
decide por las filas afectadas. Sin eso, dos cierres solapados reescribían el arqueo,
chocaban al insertar el desglose por método, tumbaban el lote con un 500 y **reimprimían
el reporte Z**.

Y la cobertura mejoró respecto de SYN-01: el e2e de cuatro lotes idénticos en paralelo
**sí muerde hoy** —comprobado por mutación: quitando el `catch` del `P2002` o el guard del
`UPDATE`, se pone rojo con un 500—. La reserva se mantiene igual (si las requests dejaran
de solaparse en la ventana justa, el camino no se ejercitaría), así que lo que la prueba
garantiza siempre es que ninguna dé 500 y que exista una sola fila de cada cosa.

**SYN-03 encontró el límite de esas pruebas, y no era el que se creía.** La prueba en paralelo solo
miraba el código de estado, y este contrato **transporta el resultado en el cuerpo**: un rechazo de
dominio viaja dentro de un 200. Al agregarle la aserción que faltaba —que las cuatro respuestas
digan `applied`— se puso roja **contra el código real** y destapó tres carreras: cerrar una orden,
cobrarla y arquear el turno devolvían `rejected` por hechos que sí habían ocurrido. El arreglo es el
del invariante 1.

**Ninguna de esas ramas se puede forzar desde afuera**: contra la base las requests se serializan
en el bloqueo de la serie y la ventana no se abre —comprobado por mutación: el e2e pasa con
cualquiera de ellas borrada—. Así que las cuatro se cubren donde sí son deterministas, con un doble
que devuelve **una vez** la lectura vieja: tres en el spec de su caso de uso (emitir comprobante,
cobrar, emitir nota) y la del lote en el suyo, con las dos mitades —el hecho que ya era verdad se
reporta `applied`, y el que no ocurrió sigue rechazado—. Es la respuesta honesta: cuando el nivel
caro no puede ejercitar la garantía, se baja al nivel que sí, en vez de dejar una prueba que no
puede fallar.

### 3.4 SYN-03 tampoco necesitó tabla ni columna

Los dos momentos ya estaban repartidos en las dos tablas: **`issuedAt` es el momento del hecho**
—cuándo se emitió, lo manda el dispositivo si fue sin conexión— y `createdAt` es cuándo llegó la
fila. Igual que `CashShift`, y por el mismo motivo: son entidades que ya distinguían el instante
del negocio del de la fila.

Lo único que cambió en el modelo de dominio es que **`Comprobante` expone su `branchId`**, que la
tabla siempre tuvo y la entidad no: el lote lo necesita para verificar que sus operaciones no
mezclen sucursales.

**Qué NO se persiste:** la cola en sí. Los pendientes son **derivados** —`sunatStatus IN
(GENERADO, RECHAZADO)`—, misma decisión que las métricas (BKO-06) y el onboarding (ADM-08). Una
tabla-cola paralela al estado del comprobante es una segunda verdad que se desincroniza.

---

## 4. Puertos y reglas de dominio

### 4.1 Puertos

| Puerto | Uso |
|---|---|
| **`Clock`** (kernel) | `nextAttemptAt`, backoff. Inyectado, no `Date.now()`: el backoff se prueba sin esperar |
| **`PsePort`** (Facturación, existente) | El envío real. `sync` **no** habla con SUNAT: reintenta lo que Facturación ya sabe enviar |
| **`SyncClock`/temporizador** (nuevo, del lado infra) | Dispara la cola. Aislado tras un puerto para que el caso de uso no dependa de `setInterval` |
| **`SalesSync`** (SYN-01) | Lo que Ventas le presta al lote: crear, buscar, cerrar y anular una orden |
| **`CashboxSync`** (SYN-02) | Lo que Cobros le presta al lote: abrir y cerrar turno, buscar turno por UUID de cliente, cobrar, mover efectivo, y **la sucursal de una caja** |
| **`BillingSync`** (SYN-03) | Lo que Facturación le presta al lote: emitir comprobante **con el número que trae**, buscar comprobante por UUID de cliente, y emitir nota de crédito |

### 4.2 Invariantes del dominio

1. **Idempotencia por `clientUuid` para lo que se crea, y por estado resultante para lo que
   transiciona.** Crear es idempotente por el índice único. Cerrar y anular lo son porque el lote
   mira el estado: si la orden ya está cerrada, el hecho que la operación describe **ya es verdad**
   y se reporta `applied`. Sin esto, un reintento normal devolvería un rechazo y el cajero vería un
   error por una venta que sí se registró. Reenviar una operación ya aplicada nunca da 409. Ojo con el efecto lateral: la idempotencia no
   alcanza con no duplicar la fila, tiene que no duplicar **sus consecuencias**. Ese trabajo ya
   está hecho del lado del inventario —`registerSale` es idempotente por `orderId`, así que
   reasentar una venta no descuenta stock dos veces—, y es el patrón a verificar en cada
   consecuencia nueva que una HU sume.

   **Precisión de SYN-03, y es la más cara del dominio: la idempotencia por estado resultante
   también tiene ventana de carrera.** El estado se mira en una transacción y se actúa en otra, así
   que un reenvío que se solapa ve el mundo de antes, intenta la operación y recibe un rechazo que
   *parece* legítimo —«la orden no se puede cerrar», «la orden ya está liquidada», «ese comprobante
   ya está anulado»— por un hecho que **sí ocurrió**. El POS lo mostraría como error al cajero. Por
   eso el estado se mira **dos veces**: antes de delegar, y otra vez cuando el dominio rechaza. Si
   para entonces el hecho ya es verdad, la operación se reporta `applied`. Con un límite que no se
   negocia: **los rechazos propios del lote no se reconsideran nunca**. Dar por aplicada una
   operación que rechazamos por falta de permiso convertiría este camino en la puerta trasera que el
   invariante 4 cierra. Esa pertenencia la decide el **tipo** (`SyncError`, base de los errores del
   módulo) y no el prefijo del código: la auditoría de arquitectura señaló que una convención de
   nombres que nadie verifica se cae en silencio y hacia el lado peligroso. El POS reintenta ante cualquier duda —y debe
   poder hacerlo sin miedo: una respuesta perdida en la red es indistinguible de una operación no
   aplicada.
2. **El lote se aplica en orden de dependencia.** Un pago no puede aplicarse antes que su orden.
   El servidor **no reordena** adivinando: el POS envía en el orden en que ocurrió, que es el
   orden correcto por construcción.
3. **Una operación fallida no cancela el lote, pero sí a sus dependientes.** Si la orden se
   rechaza, su pago no se intenta: se reporta como *omitido por dependencia*, no como error
   propio. Reportar `PAYMENT_ORDER_NOT_FOUND` para algo cuya causa es otra operación manda al
   cajero a mirar el lugar equivocado.
4. **La autorización tampoco se relaja por venir de un lote.** Cada operación exige **su propio
   permiso**, el mismo que exigiría por HTTP: anular dentro de un lote pide `anular_venta`, igual
   que `POST /orders/:id/cancel`. El permiso del endpoint es solo `acceso_pos` —la llave de la
   superficie—; lo demás se verifica por operación y se rechaza sola, sin tumbar el resto. Un
   permiso único para todo el lote fallaba de las dos maneras: pidiendo `vender`, un cajero sin
   `anular_venta` anulaba ventas mandando un lote; pidiendo el más alto, un cajero no podía ni
   sincronizar las suyas.
5. **La forma de la carga se valida antes de delegar.** El borde HTTP valida el sobre y deja las
   **reglas** al dominio de destino —eso evita duplicar los DTO de cada módulo—, pero la **forma**
   se valida en `sync`: sin eso, un `variantId` que no es UUID llega al driver de Postgres,
   revienta con un error que no es de dominio, y el lote entero responde 500. Como el POS
   reintenta ante un 500, una sola operación mal formada atascaría la cola para siempre.
6. **Las reglas de negocio no se relajan por venir de un lote.** Sin excepciones. Si una regla es
   demasiado estricta para operar offline, se cambia la regla —en su dominio, con su HU—, no se
   la esquiva por este camino.
7. **El correlativo lo asignó el dispositivo** (§6.B). El servidor **no** renumera: acepta el
   número recibido y avanza su `currentCorrelative` a `max(actual, recibido)`. Renumerar en el
   servidor rompería el ticket que el cliente ya se llevó impreso.

   **Construido en SYN-03, con tres precisiones que aparecieron al hacerlo:**
   - La marca de agua se mueve con un `UPDATE` condicional (`WHERE current_correlative < recibido`):
     atómico, sin lectura previa y **monótono**. Un lote viejo que llega después de uno nuevo no
     puede hacer retroceder la serie y volver a repartir números ya entregados.
   - **La serie se verifica, no se confía.** El papel del cliente dice «B001-000123»: las dos
     mitades son el documento. Si el dispositivo declara una serie que su caja no emite —una
     configuración vieja— se rechaza con `COMPROBANTE_SERIES_MISMATCH` en vez de guardar el número
     bajo otra serie y que el papel deje de coincidir con el registro fiscal.
   - **Un número reclamado por dos hechos distintos no se resuelve renumerando.** Si el único
     `(empresa, serie, correlativo)` choca y el `clientUuid` es otro, se rechaza con
     `COMPROBANTE_CORRELATIVE_TAKEN` para que lo mire un humano. Si el `clientUuid` es el mismo, es
     un reenvío y se devuelve el documento que ya existe — **sin esa rama, cada reintento quemaría
     un número fiscal**, que es exactamente lo que esta HU existía para impedir.
8. **La bajada es de solo lectura y acotada a la sucursal** del turno. El POS no baja otras
   sucursales ni datos de administración.
9. **Un dispositivo avisa a las 72 h sin sincronizar, pero no deja de vender** (§11.2). El aviso
   es visible en el POS y el pendiente aparece en `/sync/status`. Cortar la venta al vencer el tope
   sería exactamente el fallo que este dominio existe para evitar.
10. **Un lote pertenece a una sucursal.** La fija la primera operación que prospera —deducirla
   de lo aplicado evita que un encabezado mienta sobre el contenido—, y una operación de otra
   sucursal se rechaza con `SYNC_MIXED_BRANCH`. **Se rechaza la operación, no el lote**
   (precisión de SYN-01 sobre el enunciado original): tirar abajo ventas legítimas por una fila
   intrusa es justo lo que el resultado por operación existe para evitar.

   **La otra mitad —un lote, un turno de caja— la cerró SYN-02**, y con una precisión que importa:
   el turno del lote se lleva **por UUID de cliente**, no por id del servidor. El id recién existe
   *después* de abrir el turno, así que verificar con él obligaría a rechazar una operación cuyo
   efecto ya ocurrió — un turno realmente abierto dentro de una operación reportada como
   rechazada, y esa caja no admitiría un turno nuevo nunca más. Por el mismo motivo, la sucursal de
   un `OPEN_SHIFT` se pregunta a la caja **antes** de abrir (`CashboxSync.findRegisterBranch`).
   Regla general que deja la HU: **cuando el efecto no se puede deshacer, el invariante se verifica
   antes de causarlo, no después**.

---

## 5. Contrato de API

### Empuje
- **`POST /sync/batch`** — cuerpo: `{ operations: [...] }`. **No hay `deviceId`**: este PRD lo
  anunciaba y el DTO nunca lo declaró, así que un `deviceId` enviado se descartaba en silencio.
  Se corrige acá en vez de agregarlo: hoy no lo usa nadie, y el dispositivo del que vino un lote es
  un dato que recién hace falta en `GET /sync/status` (SYN-06). Se agrega ahí, con su consumidor.
  El resto del cuerpo: Cada operación lleva su
  `type`, su `clientUuid` y su carga; y su **referencia a lo que depende**: `orderClientUuid`
  (SYN-01) y `shiftClientUuid` (SYN-02). Un cobro depende de las dos, y por eso la dependencia es
  una lista y no un campo: con uno solo, el cobro de una orden buena en un turno rechazado se
  intentaba igual y fallaba con «turno inexistente», mandando al cajero a mirar el lugar
  equivocado. Tipos vigentes: `CREATE_ORDER`, `CLOSE_ORDER`, `CANCEL_ORDER` (SYN-01) y
  `OPEN_SHIFT`, `REGISTER_PAYMENT`, `REGISTER_CASH_MOVEMENT`, `CLOSE_SHIFT` (SYN-02) y
  `EMIT_COMPROBANTE`, `ISSUE_CREDIT_NOTE` (SYN-03, con `comprobanteClientUuid` como tercera
  referencia: una nota siempre rinde un comprobante concreto).

  **Obligación del POS: un lote, un turno.** El invariante 10 hace que el cliente tenga que
  **partir la cola por turno de caja** — un dispositivo que estuvo 72 h sin conexión acumuló varios
  turnos y no puede mandarlos juntos: del segundo en adelante se rechazan con `SYNC_MIXED_SHIFT`.
  Es una obligación del contrato, no un rechazo de negocio, y se escribe acá porque la app POS la
  tiene que implementar (lo señaló la auditoría de plan: `rejected` significa «mostrale esto al
  cajero», y este caso significa «reloteá»). Si en la práctica resultara incómodo, la alternativa
  es relajar el invariante 10 a «un lote, una sucursal» y dejar que cada operación de caja lleve su
  turno — se decide con datos de `/sync/status`, no antes. Respuesta: **un resultado por operación**
  (`applied` / `rejected` / `skipped`), con el id del servidor cuando aplica y el código de error
  de dominio cuando no. **Tres resultados, no cuatro** (corregido al construir SYN-01): se
  evaluó distinguir `duplicate` de `applied` y se descartó — para el POS son el mismo hecho («ya
  está, sacala de la cola») y el servidor no puede computar la diferencia sin una lectura previa
  que además tiene ventana de carrera. Un valor del contrato que no se puede emitir con honestidad
  es peor que no tenerlo. Responde **200**, no 201: el lote no crea *un* recurso. **Nunca un 500 por una operación mala**: el lote responde
  200 con el detalle, porque el POS necesita saber *cuál* falló, no que "algo" falló.

### Bajada
- **`GET /sync/working-set?branchId=&since=`** (permiso `acceso_pos`) — catálogo de la sucursal con
  **precios ya resueltos** (§11.3), categorías, sus **modificadores**, mesas y turno abierto, en una
  sola respuesta para que el POS no encadene seis llamadas con conexión intermitente. `since` (ISO
  8601) da el **delta**: presente → solo lo que cambió desde ese instante, **incluyendo lo
  desactivado** para que el POS lo quite; ausente → foto completa **solo activa**. La respuesta trae
  `generatedAt` (sello del servidor) que el POS devuelve como `since` la próxima vez. Detalle del
  diseño en §6.quinquies. **Implementada en SYN-04.**

### Contingencia
- **`POST /sync/sunat/flush`** — empuja la cola de contingencia de la caja (idempotente).
- **`GET /sync/status?branchId=`** — cuántos comprobantes pendientes, el error más reciente, desde
  cuándo. Es lo que el POS y la plataforma muestran como "N comprobantes sin rendir".

**Permisos:** `acceso_pos` para empuje y bajada (es el POS operando). `ver_totales` para
`/sync/status` desde la plataforma de gestión. Ningún permiso nuevo en el vocabulario.

---

## 6. Decisiones de diseño del dominio

- **Reusar los casos de uso** (§2.1). Es la decisión que impide que existan dos definiciones de
  "venta válida".
- **Idempotencia en la base, no en la aplicación.** El `@@unique([companyId, clientUuid])` ya
  existe: el duplicado lo detecta Postgres, no un `findFirst` previo que tiene una ventana de
  carrera entre la lectura y la escritura. Mismo criterio que el `code` de los planes (BKO-05).
- **Sin "last write wins".** El POS no edita lo que ya subió: crea. Una estrategia de merge
  resolvería un problema que este modelo no tiene, y lo haría inventando datos.
- **Conflictos reales, rechazo explícito.** Solo hay dos con sustancia: **mesa ocupada** por otro
  dispositivo —ya lo impide el índice único parcial de SAL-08— y **turno de caja** duplicado en la
  misma caja. Los dos se rechazan con su código de dominio y el POS los muestra. Adivinar acá es
  perder una venta o duplicarla.
- **El stock no se valida offline** (§11.1). El POS vende y el servidor concilia; el saldo puede
  quedar negativo y se corrige con un ajuste. Lo decisivo al verificarlo contra el código: **el
  camino de venta online tampoco valida stock** —`PrismaInventoryWriter.registerSale` asienta el
  movimiento negativo sin rechazar por insuficiencia—, así que esta decisión **no** crea una
  divergencia entre online y offline. Es la misma regla en los dos caminos, que es exactamente lo
  que exige el invariante 4.

  Validar contra la última foto local daría falsa seguridad: dos cajas offline con la misma foto
  venden igual la última unidad, y encima se rechazan ventas legítimas. Se paga el costo del
  rechazo sin obtener la garantía que lo justificaría.
- **Backoff con tope y sin cola infinita.** Un comprobante rechazado por SUNAT no se reintenta
  eternamente: tras el tope queda visible en `/sync/status` con su motivo, para que alguien lo
  corrija. Un reintento silencioso e infinito es cómo un error de datos se vuelve invisible.

---

### 6.bis El alcance de SYN-01, y el hueco que dejó nombrado

SYN-01 transporta **crear, cerrar y anular**. Deliberadamente **no** transporta *agregar ítem* ni
*aplicar descuento*, y el motivo es que **hoy no se pueden reenviar sin cambiar el resultado**:

- `OrderItem` **no tiene `clientUuid`**, así que agregar el mismo ítem dos veces son dos ítems — y
  eso es correcto para una interacción, pero rompe el reenvío.
- El descuento se aplica por un caso de uso aparte, y aplicarlo dos veces lo duplica.

Encaja con el principio del lote —transporta **hechos**, no interacciones— y por eso una venta
offline viaja como *la orden con sus líneas* más *su cierre*, no como el replay de los toques del
cajero.

> **Los dos huecos de abajo quedaron CERRADOS** (SYN-01b y SYN-01c, con decisión del usuario el
> 2026-08-31). Se conserva el texto porque explica por qué la solución es la que es.

**~~El hueco más ancho, y no es el descuento~~ — cerrado en SYN-01b: el hecho viajaba sin su momento.** El lote no transporta
`occurredAt`, así que una venta del viernes sincronizada el lunes queda fechada el lunes —para el
kardex, para el arqueo y para cualquier reporte por fecha—. Afecta a **todas** las ventas offline,
no solo a las que llevan descuento, y es la contradicción de fondo con "el lote transporta hechos":
un hecho sin su momento es media verdad. Resolverlo exige que Ventas acepte el instante del cliente,
lo que abre una decisión propia (¿se confía en el reloj del dispositivo? ¿se acota su desvío?), así
que se decidió aparte: **se guardan los dos momentos**. `openedAt`/`closedAt` son el momento del
hecho —lo manda el dispositivo— y `recordedAt` es cuándo llegó al servidor. El desvío se acota
**hacia el futuro** (5 minutos) y no hacia el pasado: un reloj mal puesto no puede fechar ventas en
un período ya cerrado, pero un dispositivo sí puede haber estado una semana sin conexión, y ese es
el caso de uso y no el error. El movimiento de stock no necesitó columna nueva: su `created_at` ya
**es** el momento del hecho.

**El otro hueco — cerrado en SYN-01c:** un **descuento aplicado offline no podía viajar**, porque el hecho
"orden creada" no sabe expresarlo (`CreateOrderItemInput` no tiene campo de descuento, aunque
`OrderItem.lineDiscount` exista en la base). Se eligió que **la creación de orden acepte descuentos**, en vez de darle `clientUuid` a
`OrderItem`: completa el modelo de "hecho", mantiene todo idempotente y no agrega operaciones al
lote. Y la regla del tope por rol **se movió con el dato** —`assertDiscountWithinLimit` vive ahora
en el dominio y la usan los dos caminos—, porque duplicarla habría sido la forma de que el camino
offline terminara con un tope distinto del online.

---

### 6.ter SYN-02: el turno se nombra, no se deduce

Cobrar por HTTP no dice en qué turno cae el cobro: lo **deduce** el servidor —el turno `OPEN` del
cajero en la sucursal— y está bien, porque online hay uno solo posible. El lote no puede hacer eso:
un cobro del viernes que sincroniza el lunes caería en el turno del lunes y cuadraría un arqueo que
no es el suyo, **sin que nada fallara**. Es la misma clase de error que el momento del hecho
(SYN-01b), pero sobre el agregado en vez de sobre la fecha.

Por eso el lote **nombra** el turno (`shiftClientUuid`) y `RegisterPaymentUseCase` acepta un
`cashShiftId` explícito. Lo que la deducción garantizaba por construcción pasa a verificarse:

- el turno tiene que ser **del cajero** y de la **sucursal de la orden**, o el lote sería la forma de
  meter un cobro en el turno de otro (`PAYMENT_SHIFT_MISMATCH`, 409);
- y tiene que **seguir abierto**: un turno cerrado ya se arqueó, y un cobro posterior cambiaría un
  cierre firmado (`SHIFT_NOT_OPEN`). El cobro rezagado se rechaza contra **su** turno en vez de
  colarse en el de hoy, que es exactamente el resultado que se busca.

**La consecuencia idempotente de esta HU es el arqueo.** Reenviar el lote no puede recalcularlo:
`CLOSE_SHIFT` sobre un turno ya `CLOSED` se reporta `applied` sin volver a llamar a Cobros —si no,
el cierre se recalcularía y el reporte Z se reimprimiría—. Es el mismo corte que SYN-01 hizo con el
cierre de orden, y por el mismo motivo.

**Permiso por operación** (invariante 4), sin novedades de vocabulario: `OPEN_SHIFT` y
`REGISTER_CASH_MOVEMENT` piden `operar_caja`, `REGISTER_PAYMENT` pide `cobrar`, y `CLOSE_SHIFT`
pide `cerrar_caja`. Un cajero que no arquea no puede arquear mandando un lote.

**La forma del importe también es una regla que no se relaja.** El borde online exige a lo sumo
4 decimales (las columnas son `numeric(12,4)`); el lote exige lo mismo. Sin la cota de escala, un
`0.000012345` entraba por el lote y Postgres lo redondeaba **en silencio** mientras online era un
400; sin la cota de magnitud, el importe desbordaba la columna con un error que **no es de dominio**
y tumbaba el lote con un 500 —el fallo que la validación de forma existe para evitar—.

**Los enums viajan opacos.** `method` y `type` cruzan el dominio de `sync` como `string` —importar
los enums de Cobros haría que `sync` no compile solo— y es el **adapter** quien verifica que el
valor exista, porque es el único archivo que puede mirar esa lista sin copiarla. Sin esa
verificación, un método inventado llega al driver de Postgres, da un error que no es de dominio y el
lote entero responde 500: como el POS reintenta ante un 500, una sola operación mal formada atasca
la cola para siempre.

---

### 6.quater SYN-03: el documento llega con su número puesto

Todo lo demás que el lote empuja pide identidad al servidor. Un comprobante no: **cuando llega ya
la tiene**, porque el dispositivo le asignó el correlativo y lo imprimió (§6.B). Eso invierte la
relación —el servidor registra un hecho fiscal que ya existe en papel— y de ahí salen las reglas:

- **No se renumera.** El repositorio usa el número recibido y solo avanza la marca de agua de la
  serie. La regla vive en **una sola función** (`asignarCorrelativo`) que comparten el comprobante y
  la nota, porque duplicarla sería la forma de que un día la nota renumere y el comprobante no.
- **Los importes no viajan.** El comprobante los snapshotea de la orden que factura (§6.A/§6.D);
  dejar que el lote los declarara abriría la puerta a un documento legal cuyos números no salen de
  la venta que documenta. El borrador del lote no tiene dónde ponerlos, y un test lo fija.
- **La cola de contingencia empieza acá sin código nuevo.** Un comprobante emitido offline queda en
  `GENERADO`, que es exactamente el estado del que SYN-05 va a tirar. No se adelantó nada.
- **Permiso `emitir_comprobante` para las dos operaciones**, incluida la nota: quemar un número
  fiscal es acto de quien factura (decisión de FAC-05), y el lote no relaja eso.

**Lo que SYN-03 no arregló, y por qué se arregló enseguida:** un comprobante que el POS no puede
emitir online tampoco lo puede emitir offline —la regla es una sola, y eso es lo correcto—, pero una
de esas deudas se volvió urgente por culpa de este dominio. SYN-01c habilitó descuentos sin
conexión y el descuento a nivel de orden **no era facturable**, así que el POS podía imprimir una
boleta offline que el servidor rechazaría siempre: un documento en manos del cliente que no existe
para SUNAT, que es peor que un hueco de correlativos. Se cerró en **FAC-07** (prorrateo del
descuento por línea). ICBPER en 0 sigue abierta y no tiene esta urgencia: no impide emitir.

### 6.quinquies SYN-04: la bajada, y el delta que sabe quitar

Las cinco HU anteriores empujan; esta **baja**. `GET /sync/working-set?branchId=&since=` junta en una
sola respuesta lo que hoy sirven tres superficies —catálogo con **precios ya resueltos** (§11.3),
mesas y turno abierto— para que un dispositivo con conexión intermitente no encadene seis llamadas.
Es solo lectura: `acceso_pos`, la misma llave de superficie que el empuje, sin permiso por operación.

- **Tres readers de solo lectura, ningún import de módulo.** Cada fuente tiene su puerto propio
  (`WorkingSetCatalogReader`/`TablesReader`/`ShiftReader`) con **tipos propios** de `sync`, y su
  adapter lee las tablas del dominio ajeno en el mismo desplegable (RLS por empresa), el patrón ya
  avalado para el `CatalogReader` de Ventas. A diferencia del empuje —que **delega en casos de uso**
  porque escribe y no puede tener dos definiciones de "venta válida"— la bajada es lectura, así que
  leer las tablas directo es correcto y `sync` no gana ninguna dependencia de módulo nueva.
- **El precio viaja resuelto, con la regla en un solo lugar de verdad.** El adapter resuelve con
  `resolveMvpUnitPrice`, un helper puro nuevo en `shared/domain/pricing/` que es ahora la **única**
  definición de `variant.price ?? product.basePrice`: lo consumen el reader de Ventas, este de
  Sincronización **y** `MvpPriceResolver` (el `PriceResolver` del catálogo, que le agrega encima la
  capa de `context`). Antes vivía copiado en los tres. Costura consciente: cuando llegue el precio
  por horario/lista (§9.bis del maestro), la regla contextual vive en el `PriceResolver`; un reader
  que necesite el precio contextual deberá atravesar ese puerto, no enriquecer el helper. Duplicar
  el resolutor en el cliente sería la segunda verdad que este dominio evita.
- **Semántica del `since`, y por qué el delta debe traer lo inactivo.** Sin `since`, foto completa y
  **solo lo activo** (dispositivo nuevo). Con `since`, lo que cambió desde ese instante
  **incluyendo lo desactivado** (`active:false`): filtrarlo dejaría en el POS ítems fantasma que ya
  no se venden. El POS reemplaza en su copia local lo que baja y quita lo inactivo.
- **El delta es por producto, pero mira a sus hijos.** Editar una variante o un modificador no toca
  el `updatedAt` del producto; un delta que filtrara solo por el producto se los perdería. El
  producto entra si cambió **él o cualquiera de sus variantes/modificadores**, y baja entero. Los
  modificadores **sí** viajan en la bajada (un POS con cocina no puede armar una orden configurable
  sin ellos); el delta de un modificador reenvía el producto completo, no el modificador suelto.
- **`generatedAt` lo sella el servidor (`Clock`), no el proceso.** Es el instante que el POS
  guarda y devuelve como `since` la próxima vez. A diferencia de `leerMomento` (§7), acá se usó el
  puerto `Clock` inyectable desde el principio.

---

## 7. Costuras dejadas abiertas

- **Worker aparte** para la contingencia (§2.2), si el volumen lo pide.
- **Delta de bajada por versión**, si `since` por timestamp se queda corto.
- **La bajada (SYN-04) no valida la sucursal** con un 404 como hace `/stock`: el catálogo es de la
  empresa (la RLS lo acota) y una `branchId` ajena a la empresa devuelve simplemente mesas y turno
  vacíos, sin fuga (RLS por empresa). Si algún día se quiere el 404 explícito, hace falta un reader
  de sucursal.
- **La bajada no incluye las capacidades de la empresa** (`usaMesas`/`usaCocina`): hoy la presencia
  de mesas es la señal. Si el POS necesita configurarse por capacidad aun sin mesas cargadas, se
  agrega un bloque `capabilities` (lectura de `Company`), sin migración.
- **Ventana de skew entre el reloj de la app y el de la BD (SYN-04, la nombró la auditoría de plan).**
  El cursor del delta (`generatedAt`) lo sella el **reloj de la app** (`Clock`), mientras el filtro
  del delta compara contra `updatedAt`, que puebla el **reloj de la BD** (`now()`). Si el reloj de la
  app va adelantado respecto del de la BD, un cambio de catálogo hecho en esa ventana puede quedar
  con `updatedAt` menor que el `generatedAt` que el POS reenvía como `since`, y el `gt` lo saltaría
  en la próxima bajada. Mitiga (no elimina) que `generatedAt` se captura **antes** de las lecturas, y
  que es catálogo (se auto-cura en el próximo cambio del ítem o en una bajada completa) —no es
  pérdida de una venta—. Si se quiere cerrar, sellar `generatedAt` con el reloj de la BD (misma
  fuente que `updatedAt`) en vez del `Clock` de la app. El e2e sí ejercita el round-trip real
  (`generatedAt` → `since`), que en una sola máquina no expone el skew.
- **Sincronización de auditoría**: cuando exista el dominio de Auditoría, hay que decidir si sus
  registros viajan en el lote o se generan en el servidor al aplicarlo. **Recomendación
  anticipada:** en el servidor — el actor y el momento de aplicación son datos del servidor, y un
  rastro de auditoría que el cliente puede escribir vale menos.
- **Resolución asistida de conflictos** (que el cajero elija), si los rechazos resultan frecuentes.
  Primero hay que medirlos: `/sync/status` es lo que permite saberlo.
- **Guardrail contra el salto de la marca de agua** (SYN-03, la nombró la auditoría de plan).
  Hoy la serie avanza a **cualquier** número mayor que reciba, y es irreversible: un dispositivo mal
  configurado que mande `correlative: 1000000` deja esa serie ahí para siempre, el lote responde
  `applied` y del 123 al 999999 quedan **quemados** —números que nunca se emitieron—. El PRD ya
  prevé ojo humano para el **choque** de números, pero no para el salto.
  **Decisión tomada con el usuario (2026-09-03), consultada con su contador:** en numeración
  electrónica la serie **no debe tener saltos** y no existe mecanismo de justificación ante SUNAT,
  así que el criterio **no** es «tolerar el salto hasta una cota `N` y quemar los números
  intermedios» (eso *fabrica* el hueco que hay que evitar). El criterio es el inverso: **un número
  que abre un hueco es una anomalía → se rechaza y se pone en cuarentena para revisión humana, sin
  avanzar la serie oficial.** La serie se mantiene densa. Esto **cierra también** el punto de
  «informar números no usados»: el diseño no debe *producir* números no usados, no hay HU de reporte
  de saltos. En la operación normal no aparece el problema: el dispositivo asigna correlativos
  densos localmente (1, 2, 3…) por serie, y aunque los documentos lleguen desordenados la serie
  queda densa. **Invariante del lado del dispositivo que sostiene la densidad** (para el frontend
  POS): el correlativo se asigna **solo en el instante de emitir e imprimir**, nunca en un borrador,
  de modo que un pedido cancelado antes de emitirse no consume número y todo número asignado
  corresponde a un documento impreso que va a sincronizar. *Pendiente de implementación:* el servidor
  hoy no distingue «rellena un hueco» de «abre un hueco» (solo lleva high-water mark); el guardrail
  se construye en una HU futura de Sincronización.
- **Respaldo del dispositivo perdido antes de sincronizar.** Un documento **emitido e impreso** cuyo
  dispositivo se pierde o se destruye antes del primer sync consumió su número (hay un papel en manos
  del cliente) pero nunca llega al servidor ni a SUNAT. Esto **no** es un salto que el software pueda
  evitar —es continuidad operativa, no numeración—. **Recomendación operativa al cliente
  (2026-09-03):** mientras el dispositivo esté offline, emitir las boletas/tickets **por duplicado**
  y conservar la copia como respaldo, para que una persona pueda **reconstruir y reemitir** esos
  documentos si el dispositivo no vuelve. Es recomendación de procedimiento, no garantía del sistema.
- **`leerMomento` mira el reloj del proceso**, no el puerto `Clock` que los lineamientos §2.3
  declaran obligatorio (viene de SYN-01b). Importa más desde SYN-03, porque ese instante ahora fecha
  un documento legal: el desvío hacia el futuro se acota contra `Date.now()` y no contra un reloj
  inyectable, así que el borde no se puede probar con un reloj congelado.

---

## 8. Decisiones cerradas

- Módulo `sync`, prefijo `SYN`, físico inglés.
- **Delega en los casos de uso existentes**; no escribe entidades por su cuenta.
- **Idempotencia por `clientUuid`**, ya modelada en seis entidades.
- **Resultado por operación**, no un éxito/fallo de lote.
- **El correlativo del dispositivo manda**; el servidor lleva high-water mark.
- **`SunatDispatch`** es la única tabla nueva; la cola es derivada.
- Sin worker aparte en el MVP.

---

## 9. Mapa HU → entregable técnico

| HU | Entregable |
|---|---|
| `SYN-01` | Módulo `sync` + `POST /sync/batch` con `CREATE_ORDER` / `CLOSE_ORDER` / `CANCEL_ORDER`: orden de dependencia, resultado por operación, idempotencia verificada por reenvío del mismo lote contra la BD real |
| `SYN-02` | El lote acepta caja: `OPEN_SHIFT` / `REGISTER_PAYMENT` / `REGISTER_CASH_MOVEMENT` / `CLOSE_SHIFT` delegando en Cobros, con el turno **nombrado** por el lote (§6.ter), el momento del hecho en turno/cobro/movimiento, «un lote, un turno» verificado antes de causar efecto, y el arqueo idempotente ante el reenvío |
| `SYN-03` | `EMIT_COMPROBANTE` / `ISSUE_CREDIT_NOTE` delegando en Facturación: el número del dispositivo se respeta, la marca de agua avanza **solo hacia adelante**, la serie se verifica contra la caja, el reenvío **no consume un número nuevo** (ni el solapado), y el momento del hecho es el de la emisión |
| `SYN-04` | `GET /sync/working-set`: catálogo de la sucursal, mesas y turno abierto, con `since` |
| `SYN-05` | Cola de contingencia SUNAT: `SunatDispatch`, backoff con tope, `POST /sync/sunat/flush` |
| `SYN-06` | `GET /sync/status` + el rechazo legible de los dos conflictos reales (mesa, turno) |

---

## 10. Prerrequisitos y orden

**Prerrequisito duro (cumplido):** Ventas, Cobros y Facturación completos — son los casos de uso en
los que este dominio delega. Sin ellos, `sync` no tendría a quién llamarle.

**Orden:** `SYN-01` (el mecanismo, con el dominio más simple) → `SYN-02` → `SYN-03` (el más
delicado: numeración legal) → `SYN-04` (bajada) → `SYN-05` (contingencia) → `SYN-06` (visibilidad).
Cada HU con el ritual: `audit-plan` + `audit-arquitectura` → suites vía `test-runner` →
mutation-testing de cada garantía nueva → commit → push → mover el ticket.

**Riesgos a vigilar:**
- **SYN-01** define la forma del lote. Equivocarse ahí se paga en las cinco HU siguientes.
- **SYN-03** toca numeración legal. El test que importa no es que el comprobante se cree: es que
  reenviar el mismo lote **no consuma un correlativo nuevo**. **Cubierto**: el e2e verifica contra
  la BD real que `currentCorrelative` no se mueve al reenviar, ni con el reenvío secuencial ni con
  cuatro lotes en paralelo.
- **SYN-01/02** heredan idempotencia de consecuencias ya resuelta en inventario; hay que
  verificar que cada consecuencia nueva la tenga, no asumirlo. **Verificado en SYN-02**: la
  consecuencia nueva es el **arqueo**, y el e2e comprueba contra la BD real que reenviar la jornada
  no crea un segundo turno, ni un segundo cobro, ni recalcula el cierre.
- **SYN-04** es la primera respuesta grande del proyecto. **Medido (e2e con BD real):** ~60
  productos con su variante por defecto bajan en ~29,5 KB (~0,5 KB por producto), muy holgado; el
  e2e lleva una red de seguridad que falla si la respuesta supera 1 MB (caza un cambio que incluya
  relaciones de más). A escala de miles de productos conviene revisar paginación/compresión, pero el
  tamaño no es un riesgo en el MVP.
- La dependencia `sync → módulos de dominio` es nueva en el proyecto (§2.1): conviene que la
  auditoría de arquitectura la mire en SYN-01, no en SYN-06.

---

## 11. Decisiones confirmadas con el usuario (ago-2026)

1. **El POS NO valida stock offline.** Vende y el servidor concilia; el saldo puede quedar negativo
   y se corrige con un ajuste. Verificado contra el código: **el camino online tampoco valida**, así
   que no hay dos reglas. La alternativa —validar contra la última foto local— da falsa seguridad,
   porque dos cajas offline venden igual la misma última unidad, y además rechaza ventas legítimas.
2. **Tope de 72 h sin sincronizar**, con aviso visible. Cubre un fin de semana largo sin alarmas
   falsas. **El aviso no corta la venta**: un POS que deja de vender por no haber sincronizado es
   el fallo que este dominio existe para evitar.
3. **`/sync/working-set` manda precios resueltos**, no reglas. Respuesta más chica y POS más
   simple, que es lo que importa en una conexión intermitente. No cierra la puerta a precios por
   horario: el resolutor ya está centralizado (costura del maestro §9.bis), así que mandar reglas
   después es cambiar qué se serializa, no rearmar el POS. Duplicar el resolutor en el cliente hoy
   sería justo la segunda verdad que este dominio evita en todo lo demás.
