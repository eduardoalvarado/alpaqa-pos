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

### 4.2 Invariantes del dominio

1. **Idempotencia por `clientUuid`.** Reenviar una operación ya aplicada devuelve **el mismo
   recurso y un resultado de éxito**, no un 409. Ojo con el efecto lateral: la idempotencia no
   alcanza con no duplicar la fila, tiene que no duplicar **sus consecuencias**. Ese trabajo ya
   está hecho del lado del inventario —`registerSale` es idempotente por `orderId`, así que
   reasentar una venta no descuenta stock dos veces—, y es el patrón a verificar en cada
   consecuencia nueva que una HU sume. El POS reintenta ante cualquier duda —y debe
   poder hacerlo sin miedo: una respuesta perdida en la red es indistinguible de una operación no
   aplicada.
2. **El lote se aplica en orden de dependencia.** Un pago no puede aplicarse antes que su orden.
   El servidor **no reordena** adivinando: el POS envía en el orden en que ocurrió, que es el
   orden correcto por construcción.
3. **Una operación fallida no cancela el lote, pero sí a sus dependientes.** Si la orden se
   rechaza, su pago no se intenta: se reporta como *omitido por dependencia*, no como error
   propio. Reportar `PAYMENT_ORDER_NOT_FOUND` para algo cuya causa es otra operación manda al
   cajero a mirar el lugar equivocado.
4. **Las reglas de negocio no se relajan por venir de un lote.** Sin excepciones. Si una regla es
   demasiado estricta para operar offline, se cambia la regla —en su dominio, con su HU—, no se
   la esquiva por este camino.
5. **El correlativo lo asignó el dispositivo** (§6.B). El servidor **no** renumera: acepta el
   número recibido y avanza su `currentCorrelative` a `max(actual, recibido)`. Renumerar en el
   servidor rompería el ticket que el cliente ya se llevó impreso.
6. **La bajada es de solo lectura y acotada a la sucursal** del turno. El POS no baja otras
   sucursales ni datos de administración.
7. **Un dispositivo avisa a las 72 h sin sincronizar, pero no deja de vender** (§11.2). El aviso
   es visible en el POS y el pendiente aparece en `/sync/status`. Cortar la venta al vencer el tope
   sería exactamente el fallo que este dominio existe para evitar.
8. **Un lote pertenece a un turno de caja y a una sucursal.** No se aceptan operaciones de
   sucursales distintas en el mismo lote: acota el radio de un error y hace el rechazo legible.

---

## 5. Contrato de API

### Empuje
- **`POST /sync/batch`** — cuerpo: `{ deviceId, operations: [...] }`. Cada operación lleva su
  `type`, su `clientUuid` y su carga. Respuesta: **un resultado por operación**
  (`applied` / `duplicate` / `rejected` / `skipped`), con el id del servidor cuando aplica y el
  código de error de dominio cuando no. **Nunca un 500 por una operación mala**: el lote responde
  200 con el detalle, porque el POS necesita saber *cuál* falló, no que "algo" falló.

### Bajada
- **`GET /sync/working-set?branchId=&since=`** — catálogo de la sucursal con **precios ya
  resueltos** (§11.3), mesas y turno abierto. `since` permite delta; sin él, completo. Es **el mismo dato** que sirven los endpoints de
  catálogo y mesas, agrupado en una sola respuesta para que el POS no encadene seis llamadas con
  conexión intermitente.

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

## 7. Costuras dejadas abiertas

- **Worker aparte** para la contingencia (§2.2), si el volumen lo pide.
- **Delta de bajada por versión**, si `since` por timestamp se queda corto.
- **Sincronización de auditoría**: cuando exista el dominio de Auditoría, hay que decidir si sus
  registros viajan en el lote o se generan en el servidor al aplicarlo. **Recomendación
  anticipada:** en el servidor — el actor y el momento de aplicación son datos del servidor, y un
  rastro de auditoría que el cliente puede escribir vale menos.
- **Resolución asistida de conflictos** (que el cajero elija), si los rechazos resultan frecuentes.
  Primero hay que medirlos: `/sync/status` es lo que permite saberlo.

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
| `SYN-01` | Módulo `sync` + `POST /sync/batch` con órdenes e ítems: orden de dependencia, resultado por operación, idempotencia verificada por reenvío del mismo lote |
| `SYN-02` | El lote acepta caja: turnos, pagos y movimientos (delegando en Cobros) |
| `SYN-03` | El lote acepta comprobantes y notas, respetando el correlativo del dispositivo y avanzando el high-water mark |
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
  reenviar el mismo lote **no consuma un correlativo nuevo**.
- **SYN-01/02** heredan idempotencia de consecuencias ya resuelta en inventario; hay que
  verificar que cada consecuencia nueva la tenga, no asumirlo.
- **SYN-04** es la primera respuesta grande del proyecto. Hay que medir su tamaño con un catálogo
  realista antes de darla por buena.
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
