# PRD — Auditoría (dominio transversal del MVP)

> Dominio del MVP. Séptimo del roadmap, **después de Sincronización offline** (§10 del maestro).
> Este PRD **referencia** las decisiones transversales del maestro y los lineamientos; no las
> repite. Lectura previa obligatoria antes de tocar código: `docs/lineamientos-tecnicos.md`
> §2.2/§2.4/§2.6 y `docs/flujo-jira.md`.

## 0. Convención de nombres

- **Épica `ALPQ-77`** (creada 2026-09-04). HUs con prefijo **`AUD`**: `AUD-01..08` = `ALPQ-78..85`;
  el código `AUD-0X` es **etiqueta de orden** + nombre, el id es la clave Jira `ALPQ-N` (ver
  `docs/flujo-jira.md`). Todas en **Por hacer**.
- **Módulo hexagonal nuevo**: `audit` (físico **inglés**, `snake_case` vía `@map`, como todos los
  dominios nuevos desde ALPQ-24). La entidad del maestro `LogAuditoria` se materializa como
  `AuditEvent` / tabla `audit_event`.

---

## 1. Propósito y alcance del dominio

**Quién hizo qué, cuándo, y sobre qué** (§4 del maestro). Es el **rastro** de las operaciones del
producto: la base de accountability ante fraude, disputas y soporte. No es analítica —la detección
de anomalías es fase 2 (§9) y **se alimenta** de este rastro—, es el registro crudo y confiable.

### Lo que este dominio construye

- La **entidad `AuditEvent`** (tabla append-only, tenant-scoped) y su modelo.
- Un **mecanismo transversal** para capturar el rastro sin reescribir cada caso de uso a mano
  (§2). Es la decisión que define el dominio.
- El **enganche en las rutas de escritura sensibles** de los seis dominios existentes
  (**alcance amplio**, decisión del usuario — §11): ventas, caja, facturación, catálogo,
  inventario, plataforma/admin.
- El **lado operador** (Backoffice): quién suspendió/cambió el estado de un tenant y su plan —el
  consumidor que BKO-04/05 dejó esperando (§4 del maestro).
- Las **lecturas con consumidor real**: el dueño ve el rastro de **su** empresa; el operador ve el
  rastro **cross-tenant** (decisión del usuario — §11).

### Lo que NO construye (fase 2, §9 del maestro)

- **Detección de anomalías / fraude** (se alimenta de este rastro, no lo produce).
- **Reportes/analítica** sobre el rastro (dashboards, agregados) — es el dominio siguiente.
- **Impersonación** del operador y **soporte sobre datos** — este dominio es su **prerrequisito**,
  no su implementación.
- **Retención / archivado / exportación** del log (política de borrado por antigüedad, export a
  frío). El log nace append-only y crece; la política es costura (§7).

---

## 2. Ubicación en la arquitectura backend

Módulo `audit` con `domain/ application/ infrastructure/`. La particularidad del dominio: **casi no
tiene lógica propia** —un evento de auditoría es un hecho que se registra— y en cambio **toca a
todos los demás**. El diseño es sobre todo la respuesta a *cómo capturar el rastro sin ensuciar ni
reescribir los seis dominios*.

### 2.1 La decisión que define el dominio: un `AuditRecorder` con dos disparadores, no 70 llamadas a mano

**Alcance amplio ⇒ el enganche NO puede ser una llamada explícita copiada en cada caso de uso.** Con
~70 casos de uso de escritura, `auditRecorder.record(...)` a mano en cada uno es un retrofit masivo,
frágil y ruidoso. En su lugar, un único puerto **`AuditRecorder`** (escribe el `AuditEvent`) con
**dos disparadores**, según el camino:

- **Camino online — interceptor declarativo en el borde HTTP.** Un decorador `@Audit({ action,
  entity })` sobre las rutas de escritura sensibles + un interceptor Nest que arma el evento: el
  **actor sale de la request** (usuario autenticado), el **momento del `Clock`**, la **entidad/id**
  del parámetro de ruta o de la respuesta, y un **snapshot del payload**. Cubre todas las rutas de
  escritura de manera uniforme con **una línea por ruta** (el decorador), sin tocar el caso de uso.
  **Esto sortea la costura BKO-06** (el caso de uso no recibía al actor): el interceptor lo toma del
  contexto de la request, no del caso de uso.
- **Camino offline — generación por operación en el aplicador del lote.** El `@Audit` del borde
  registraría **un** evento para todo `/sync/batch`, no uno por operación. Por eso el
  `ApplySyncBatchUseCase` (Sincronización) llama al `AuditRecorder` **por cada operación aplicada**,
  con el actor y la acción de esa operación. Es coherente con lo que Sincronización §7 ya decidió:
  **el rastro se genera en el servidor al aplicar**, no viaja en el lote (un rastro que el cliente
  puede escribir vale menos). El **momento del hecho** es el que la operación ya trae (§6.A de
  Sincro), el momento del **registro** es el del servidor.

  > **Reconciliación AUD-08 (2026-09-05): `entity`/`entityId` de un sub-recurso offline difieren del
  > online.** El evento offline se arma con la entidad que el aplicador del lote **devuelve**
  > (`aplicado.id`), que para dos casos no es la misma que el borde online eligió: el **movimiento de
  > efectivo** queda `entity='cash_movement'` con su propio id (online lo cuelga del turno —
  > `cash_shift`), y la **nota de crédito** queda `entity='credit_note'` con su propio id (online la
  > cuelga del comprobante de origen). La `action` sí es uniforme entre caminos, así que cada evento
  > es hallable y correcto; lo que se pierde es la **agrupación "en un hilo"** (AUD-03/AUD-04) para los
  > eventos generados offline: `GET /audit?entity=cash_shift&entityId=<turno>` no trae los movimientos
  > sincronizados (sí `?action=CASHBOX.CASH_MOVEMENT_REGISTERED`). Alinearlos exigiría que el aplicador
  > exponga el id del **padre** (turno / comprobante de origen) por operación — **costura §7**, no se
  > hizo en AUD-08 por ser un cambio de plomería a cambio de una divergencia acotada a dos acciones.

Los dos disparadores escriben por el **mismo puerto** y la **misma tabla**; lo único que cambia es
quién arma el evento. `datos_antes/datos_despues` completos (diff previo/posterior) **no** los da el
borde —no conoce el estado previo—: en el MVP se capturan **parciales** (payload + resultado), y el
diff rico queda como enriquecimiento por operación (§7).

> **Reconciliación AUD-01 (2026-09-04).** El decorador `@Audit` y su metadata (`AuditMetadata`,
> `AUDIT_METADATA_KEY`) viven en **`shared/infrastructure/http`**, junto a `@RequirePermission`,
> `@Public` y `@CurrentUser` —no en `modules/audit`—: los usan los seis dominios y ninguno debe
> importar un módulo de dominio para declarar que una ruta se audita (mismo criterio que cerró
> BKO). El `AuditInterceptor` (en `audit`) es quien **lee** esa metadata, igual que el
> `PermissionsGuard` lee la de permisos. Así "decorar no es depender" es literal: `sales` no importa
> `audit`. Además el mecanismo se partió en dos puertos por responsabilidad: **`AuditRecorder`** (la
> red best-effort: reintento + dead-letter) y **`AuditEventRepository`** (el escritor append-only) —
> así la red de reintento se prueba con un repo en memoria que falla a voluntad, sin base.

### 2.2 Por qué el interceptor no rompe la regla de dependencias

`audit` expone el puerto `AuditRecorder` y el decorador `@Audit`. El interceptor vive en la infra de
`audit` (borde HTTP) y **no depende de los módulos de dominio**: lee la request (actor, ruta,
params, response) de forma genérica. Los seis dominios **no importan `audit`**: solo **decoran sus
rutas** con `@Audit` (un decorador es metadata, no una dependencia de módulo). El único cruce
deliberado es `sync → audit` en el aplicador del lote (una dependencia más, acotada como las de
Sincronización). **No se invierte la regla**: nadie de dominio llama a `audit`; `audit` observa.

### 2.3 El lado operador es cross-deployable

El Backoffice corre en **otro desplegable**, con **otro rol de BD** (`alpaqa_backoffice`) y otro
mundo de auth (`OperatorUser`). Cuando el operador suspende un tenant (BKO-04), el evento se registra
contra la **empresa afectada** (`empresa_id` = ese tenant) pero el **actor es un operador**, no un
`User`. Eso obliga a: (1) un actor **polimórfico** en el modelo (§3), y (2) que el rol
`alpaqa_backoffice` pueda **escribir** en `audit_event` con la política nominal del patrón BKO-04
(`GRANT` + policy `FOR INSERT TO alpaqa_backoffice`), **sin** `BYPASSRLS`. El interceptor `@Audit`
del desplegable de backoffice usa el mundo operador; el del desplegable de tenant, el mundo usuario.

---

## 3. Modelo de datos

**Una sola tabla nueva.** Lo demás ya existe (los actores, las entidades auditadas, el `Clock` y el
`IdGenerator` del shared kernel).

### `AuditEvent` (`@@map("audit_event")`) — tabla de tenant, append-only

| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid | La **empresa afectada**. Tabla de tenant: RLS + `GRANT` (invariante 4) |
| actorType | enum `USER` \| `OPERATOR` | Actor **polimórfico** (§2.3): un `User` del tenant o un `OperatorUser` del backoffice |
| actorId | uuid | Id del actor en su tabla (`usuario` u `operator_user`) |
| actorLabel | text | **Snapshot** del actor (nombre/email) al momento del hecho: el log se lee aunque el usuario se borre después |
| action | text | Código de acción `DOMINIO.VERBO` (p. ej. `SALES.ORDER_CANCELLED`, `BACKOFFICE.TENANT_SUSPENDED`). **Texto con convención**, no enum de BD: sumar una acción no debe pedir migración |
| entity | text | Tipo de entidad afectada (`order`, `comprobante`, `cash_shift`, `company`…) |
| entityId | uuid NULL | Id de la entidad; `null` para acciones sin una fila (p. ej. un login fallido, si se auditara) |
| dataBefore | jsonb NULL | Estado previo, **parcial en el MVP** (§2.1). `null` cuando el borde no lo tiene |
| dataAfter | jsonb NULL | Payload/resultado de la operación (snapshot) |
| metadata | jsonb NULL | Contexto: ruta, ip, `mode` (`online`/`batch`/`backoffice`), `payload` de la request (redactable), `clientUuid` si vino offline |
| createdAt | timestamp | **Momento del registro** (servidor, `Clock`). Para lo offline, el **momento del hecho** viaja en `metadata`/`dataAfter` |

**Append-only:** sin `updatedAt`, sin `UPDATE`, sin `DELETE` desde la app. Un registro de auditoría
que se puede editar no es auditoría. La inmutabilidad se refuerza en la política/permisos de BD
(solo `INSERT`/`SELECT` para los roles; nada de `UPDATE`/`DELETE`).

**Índices:** `(companyId, createdAt)` para la lectura del dueño (rastro reciente de su empresa) y
`(companyId, entity, entityId)` para "qué pasó con esta orden/este comprobante".

**RLS y GRANT:**
- Política `tenant_isolation` (patrón invariante 4): el tenant lee/escribe `companyId = empresa
  actual`. `GRANT SELECT, INSERT` a `alpaqa_app` (**no** `UPDATE`/`DELETE`: append-only).
- Política nominal para el operador (patrón BKO-04): `GRANT SELECT, INSERT ON audit_event TO
  alpaqa_backoffice` + policy `FOR SELECT` y `FOR INSERT TO alpaqa_backoffice USING (true) / WITH
  CHECK (true)` — el operador escribe eventos sobre cualquier tenant (los suyos, cross-tenant) y los
  lee todos. **Sin `BYPASSRLS`** (la lección de BKO-01): dos llaves, `GRANT` + política nominal.

---

## 4. Puertos y reglas de dominio

### 4.1 Puertos

| Puerto | Uso |
|---|---|
| **`AuditRecorder`** (nuevo) | Registra un `AuditEvent`. Lo llaman el interceptor del borde (online) y el aplicador del lote (offline). Tipos propios: el evento se arma con datos ya resueltos |
| **`AuditReader`** (nuevo) | Lee el rastro: por empresa (dueño) y cross-tenant filtrado (operador). Paginado |
| **`Clock`** (kernel) | `createdAt` del registro. Inyectado, no `Date.now()` |
| **`IdGenerator`** (kernel) | Id del evento |

### 4.2 Invariantes del dominio

1. **Append-only.** Un evento se crea y no se modifica ni se borra. Garantía en la app (no hay
   caso de uso de update/delete) **y** en la BD (grant sin `UPDATE`/`DELETE`).
2. **El rastro se genera en el servidor** (§2.1, Sincro §7). El cliente no manda eventos de
   auditoría; el servidor los produce al aplicar la escritura. El **actor** sale del contexto de
   auth, nunca de la carga.
3. **El actor se snapshotea** (`actorLabel`). Borrar o renombrar un usuario no debe reescribir la
   historia ni dejar un id colgado ilegible.
4. **Registrar auditoría nunca tumba la operación — con red de reintento.** El evento es
   *best-effort* respecto del acto de negocio: si el `INSERT` del rastro falla, la
   venta/cobro/factura **igual se completa**, el fallo no se propaga. Pero **no se pierde en el
   primer intento**: hay un **reintento asíncrono acotado** (cola en-proceso, backoff con jitter,
   tope de intentos). Al agotar el tope, el evento **cae a un log estructurado** —para que ops lo
   reconstruya— en vez de reintentar para siempre. Cubre el fallo **transitorio** (deadlock, pool
   saturado un instante), que es la mayoría. **Lo que el reintento NO cubre, dicho con todas las
   letras:** un **crash del proceso** con la cola en memoria pierde lo encolado (haría falta un spool
   durable, §7); un fallo **determinista** del `audit_event` (bug de política/constraint) no se
   arregla reintentando —por eso el tope + dead-letter—; y una **BD entera caída** no genera hueco,
   porque ahí la escritura de negocio también falló (no hay "venta hecha sin rastro"). El reintento
   es **en-proceso, no un worker** (coherente con "sin worker" de SYN-05).
5. **Aislamiento.** El dueño ve **solo** su empresa (RLS). El operador ve cross-tenant (rol de
   backoffice). Un tenant **no** ve el rastro de otro; y **sí** ve las acciones del operador sobre
   él (transparencia: quién lo suspendió y cuándo).
6. **La auditoría no relaja permisos.** Auditar una acción no la autoriza: el `@Audit` va **después**
   de los guards; una acción rechazada por permiso no produce evento de "aplicada" (a lo sumo, si se
   decide, un evento de intento denegado — fuera del MVP).

---

## 5. Contrato de API

### Escritura
La escritura es **transversal e implícita**: no hay endpoint de "crear evento". Se produce sola al
decorar una ruta con `@Audit({ action, entity })` o al aplicar una operación del lote. Exponer un
`POST /audit` sería la puerta para que el cliente escriba su propia historia (viola invariante 2).

### Lectura
- **`GET /audit?entity=&entityId=&action=&since=&cursor=`** (plataforma de gestión, permiso
  **`ver_auditoria`** — nuevo, ver §8) — el rastro de **la empresa del usuario**, paginado y
  filtrable. "Qué pasó con esta orden", "qué anuló/descontó fulano".
- **`GET /backoffice/audit?companyId=&action=&since=&cursor=`** (backoffice, autenticado como
  operador) — el rastro **cross-tenant**; el consumidor que BKO dejó esperando (quién suspendió a
  qué tenant). Vive en el desplegable de backoffice, tras su cadena de guards propia.

Paginación **por cursor** desde el arranque: el log es la tabla que más crece del producto (una fila
por cada escritura sensible), así que un listado sin tope no es opción (la deuda que Backoffice §7
anotó para tenants, acá es obligatoria de entrada).

---

## 6. Decisiones de diseño del dominio

- **Interceptor declarativo, no llamadas dispersas** (§2.1). El alcance amplio lo exige: decorar es
  una línea por ruta; llamar a mano son 70 retrofits y un olvido silencioso por cada ruta nueva.
- **`action` es texto con convención `DOMINIO.VERBO`, no enum de BD.** Un vocabulario amplio y
  creciente no debe atarse a una migración por cada verbo nuevo. La convención se documenta y se
  centraliza en una constante por dominio (como `PERMISSIONS`), para que no proliferen strings
  sueltos.
- **Dos niveles de garantía, según cuánto duele el hueco** (invariante 4). Auditar en la misma
  transacción que la escritura haría que un fallo del rastro tire abajo una venta; para un POS eso es
  peor que un hueco. Pero un hueco tampoco es gratis. Por eso **dos niveles**:
  - **Default (toda escritura sensible)** → **best-effort + reintento asíncrono acotado** (cola
    en-proceso, backoff con jitter, tope → dead-letter a log). No acopla la caída y no pierde el
    caso transitorio. Es el camino del 95% de las acciones.
  - **El puñado crítico** (donde un hueco es inaceptable) → **auditoría transaccional**: el evento se
    escribe en la misma transacción que la acción. Cero huecos, acoplando ese fallo puntual a
    propósito. Se marca por acción, no es el default. **Decisión del usuario (2026-09-04): al
    arranque la única acción crítica-transaccional es la SUSPENSIÓN/cambio de estado de tenant**
    (`BACKOFFICE.TENANT_SUSPENDED`, AUD-06) — es la más sensible y de baja frecuencia, donde el costo
    transaccional no molesta. Las **anulaciones** quedan en el **nivel default con reintento**: son
    frecuentes y acoplar su fallo a la caída de la venta es justo lo que queremos evitar. Promover una
    acción a crítica después es marcarla, sin retrabajo (costura de anulación abierta, §7).
  La lista de acciones "críticas transaccionales" se mantiene **explícita** (una constante, no una
  convención implícita) y hoy tiene **un** elemento.

  > **Reconciliación AUD-01 (2026-09-04): el modo transaccional se construye con su consumidor, en
  > AUD-06.** AUD-01 entrega el **default** completo y probado de punta a punta (best-effort +
  > reintento asíncrono acotado + dead-letter). El modo transaccional **no** se cableó en AUD-01: su
  > **único** consumidor de arranque es la suspensión de tenant (`BACKOFFICE.TENANT_SUSPENDED`), que
  > es cross-deployable y llega en **AUD-06**. Construir el escritor transaccional ahora, sin esa
  > ruta, sería superficie de puerto sin consumidor ejercitado — el error que este proyecto ya pagó
  > varias veces (ADM-01: "no agregar superficie por si acaso"). Se difiere deliberadamente a AUD-06,
  > donde se escribe junto a la acción que lo usa y con su propio test. El `AuditRecorder` best-effort
  > queda intacto; el transaccional será un camino aparte (escribir en la tx de la acción), no una
  > variante del recorder.
  >
  > **Reconciliación AUD-06 (2026-09-04): el backoffice audita transaccionalmente TODAS sus acciones**
  > (suspender/reactivar y cambiar plan), no solo la suspensión que §11.5 exige. Motivo: el
  > desplegable de backoffice **no tiene** la infra de reintento async (es otro proceso, sin el
  > `AuditRecorder` best-effort ni el cliente de tenant), y sus acciones son de **baja frecuencia**
  > (un operador administrando tenants), así que la escritura en la misma tx no molesta y da cero
  > huecos. Es **más estricto** que §11.5, no contradictorio: "suspensión = transaccional" se cumple,
  > y las demás acciones del operador se suben al mismo nivel por conveniencia de implementación.
- **Actor polimórfico en una tabla, no dos logs** (§2.3, §3). Un solo rastro por empresa, donde el
  dueño ve también las acciones del operador sobre su tenant (transparencia). Dos tablas separadas
  aislarían mejor pero partirían "la historia de esta empresa" en dos lugares y le esconderían al
  dueño quién lo suspendió.
- **`dataBefore`/`dataAfter` parciales en el MVP.** El borde tiene el payload y el resultado, no el
  estado previo. Capturar el diff rico exige que el caso de uso lo provea —el retrofit que el
  interceptor evita—. Se difiere el diff completo; el MVP registra acción + entidad + actor +
  payload, que es lo que sostiene accountability. Honesto en §7.

---

## 7. Costuras dejadas abiertas

- **Diff completo `antes/después`.** El MVP captura parcial (§6). Cuando una acción necesite el
  estado previo exacto (p. ej. "qué precio tenía antes"), el caso de uso lo provee por un mecanismo
  explícito; no reescribe el interceptor.
- **Redacción de datos sensibles en `dataAfter` (respuesta)** (anotado en AUD-01). El interceptor
  captura dos cosas: la **carga de entrada** (`req.body`) en `metadata.payload` y el **resultado**
  (la respuesta) en `dataAfter`. Existe redacción **por ruta en las dos direcciones**:
  `@Audit({ redactBody: [...] })` para la carga de entrada (AUD-01) y `redactResponse: [...]` para el
  resultado (AUD-05, que lo estrenó para no filtrar la `temporaryPassword` que devuelven el alta de
  usuario y el reset). **Costura que queda:** la redacción es una **lista explícita por ruta**, no
  automática; una ruta futura que devuelva o reciba un secreto y **olvide** declararlo lo filtraría al
  `jsonb`. Un default más seguro (allowlist de campos a capturar, o denylist global de nombres tipo
  `*password*`) cerraría el riesgo de olvido; se difiere.
- **Spool durable para el crash del proceso** (invariante 4). El reintento asíncrono vive en memoria:
  cubre el fallo transitorio, pero un crash del proceso pierde lo encolado. Un buffer durable local
  (append-log en disco que se relee al arrancar) cerraría ese hueco; es infra extra que para el MVP
  no rinde todavía. Nombrado para no descubrirlo tarde. Mientras, las acciones que no toleran **ningún**
  hueco usan el nivel **transaccional** (§6), que no pasa por la cola.
- **Tuning del reintento** (tope de intentos, backoff, tamaño de cola, formato del dead-letter):
  valores de construcción en AUD-01, a calibrar con datos de producción.
- **Anulación como acción crítica-transaccional** (decisión diferida, §6). Hoy la anulación de venta
  va por el nivel default (best-effort + reintento). Si en producción se ve que un hueco en el rastro
  de anulaciones duele (fraude, disputas), se **promueve** agregándola a la lista de críticas —es
  marcarla, no reescribir—. Se deja nombrada para que la promoción sea una decisión, no un
  descubrimiento.
- **Retención / archivado / exportación.** El log crece sin tope. Política de borrado por antigüedad,
  archivado a almacenamiento frío, export para una fiscalización: todo fase 2.
- **Auditoría de intentos denegados / lecturas.** El MVP audita **escrituras aplicadas**. Registrar
  intentos rechazados por permiso, o accesos de lectura sensibles, es ampliación posterior.
- **La detección de anomalías** (fase 2, §9 del maestro) consume esta tabla; su forma (batch, tiempo
  real, umbrales) se decide en su momento.

---

## 8. Decisiones cerradas

- Módulo `audit`, prefijo `AUD`, físico inglés. Entidad `AuditEvent` / tabla `audit_event`.
- **Append-only**; sin update/delete en app ni en grant.
- **Rastro generado en el servidor**, nunca enviado por el cliente (alineado con Sincro §7).
- **Dos niveles de garantía** (§6): best-effort + **reintento asíncrono acotado** (dead-letter a log
  al agotar) para el default; **transaccional** para el puñado crítico. Spool durable = fase 2.
- **Interceptor `@Audit` + `AuditRecorder`** como mecanismo transversal; `sync` llama al recorder por
  operación aplicada.
- **Una tabla, actor polimórfico** (`USER`/`OPERATOR`); RLS tenant + política nominal para
  `alpaqa_backoffice` (patrón BKO-04, sin `BYPASSRLS`).
- **Permiso nuevo `ver_auditoria`** para la lectura del dueño. Es el **primer permiso que agrega este
  dominio**; el resto del vocabulario ya existe. (`ver_totales` queda para Reportes.)
- **Paginación por cursor** en las dos lecturas desde el arranque.

---

## 9. Mapa HU → entregable técnico

| HU | Entregable |
|---|---|
| `AUD-01` | **Cimiento**: modelo `AuditEvent` + migración (RLS + GRANT append-only + política nominal de backoffice) + puerto `AuditRecorder` (con el **reintento asíncrono acotado + dead-letter a log**) + el mecanismo `@Audit`/interceptor del borde + `Clock`/`IdGenerator`. Se prueba enganchando **una** acción de alto riesgo (anulación de venta) de punta a punta, y **el best-effort en las dos direcciones** (un fallo del rastro no tumba la venta; el reintento recupera el transitorio). **Hecho 2026-09-04** (Jira `ALPQ-78`). El modo **transaccional** para acciones críticas se difiere a **AUD-06** (su único consumidor, la suspensión de tenant) — ver reconciliación en §6 |
| `AUD-02` | Enganche **Ventas**: anulación, descuento (quién y cuánto), edición de orden, devolución. **Hecho 2026-09-04** (`ALPQ-79`). Acciones `SALES.*` en una constante por dominio (`sales-audit-actions.ts`); rutas decoradas: descuento, agregar/quitar/cambiar-cantidad de ítem, **reasignar mesero** (`SALES.WAITER_ASSIGNED`, accountability sensible — se incluyó por criterio explícito, no por omisión) y devolución (la anulación ya venía de AUD-01). **Crear y cerrar orden NO se auditan** (no son foco de fraude/disputa; costura si se necesita). El interceptor ganó captura de **todos los params de ruta** en `metadata.params`, para no perder el `itemId` de un sub-recurso. Cobertura e2e de descuento, agregar/cambiar-cantidad/quitar ítem y devolución; la de mesero se difiere (misma mecánica ya probada, requiere capacidad `usaMesas`) |
| `AUD-03` | Enganche **Caja**: apertura/cierre de turno (con la diferencia del arqueo), movimientos de efectivo. **Hecho 2026-09-04** (`ALPQ-80`). Acciones `CASHBOX.*` (`cashbox-audit-actions.ts`): `SHIFT_OPENED`/`SHIFT_CLOSED`/`CASH_MOVEMENT_REGISTERED`, todas contra la entidad **`cash_shift`** (movimiento y cierre cuelgan de su turno → "qué pasó en este turno" en un hilo). El cierre lleva el arqueo (esperado/contado) en `dataAfter`. El interceptor ganó `entityIdFromResponse` (abrir turno: el `:id` de ruta es la caja, no el turno). **Los cobros (`payment`) NO se auditan** — no están en el mapa §9; ver decisión abierta en §12 |
| `AUD-04` | Enganche **Facturación**: emisión, envío a SUNAT, nota de crédito. **Hecho 2026-09-04** (`ALPQ-81`). Acciones `BILLING.*` (`billing-audit-actions.ts`): `COMPROBANTE_ISSUED` (emitir, `entityIdFromResponse` — la ruta es `/orders/:orderId/comprobante`), `COMPROBANTE_SENT_TO_SUNAT` (enviar), `CREDIT_NOTE_ISSUED` (nota de crédito). Las tres contra la entidad **`comprobante`** (la nota cuelga de su comprobante de origen → "qué pasó con este comprobante" en un hilo). Entrega (PDF/email) y lecturas (XML/PDF) no se auditan (no son actos fiscales) |
| `AUD-05` | Enganche **Catálogo/Inventario/Admin** (alcance amplio): cambios de precio, config, flags, movimientos de inventario, y **usuarios/roles/permisos** (alta, cambio de rol, anti-lockout). **Hecho 2026-09-04** (`ALPQ-82`). Tres constantes (`CATALOG_/INVENTORY_/ADMIN_AUDIT_ACTIONS`), **28 rutas** decoradas: Catálogo (categoría CRUD; producto crear/actualizar/tax/measurement/flags; barcode; grupos y modificadores); Inventario (movimiento, stock mínimo); Admin (empresa datos+capacidades; sucursales; roles CRUD; usuarios alta/edición/asignaciones/reset-password; cambio de la propia contraseña). **Bootstrap fuera de alcance** (`POST /auth/register`, `POST /companies`: sin contexto de tenant, el interceptor los omite). **Nuevo `redactResponse`** en el decorador: cierra la costura §7 para las dos respuestas que traen `temporaryPassword` (alta de usuario y reset). `me/password` redacta el body. **`entityIdFromResponse` ahora acepta un dot-path** (`'user.id'` para el alta de usuario, cuya respuesta anida el id; `'variantId'` para movimiento y stock mínimo, cuyas respuestas no traen id propio → el rastro cuelga del stock de la variante); el modificador agregado cuelga de su grupo (`entity:'modifier_group'`). Cobertura e2e representativa (una acción por dominio + prueba de redacción de la temporal + aserción real del `entityId`); el resto reusa el mismo mecanismo ya probado. La auditoría de plan atrapó dos `entityId` que quedaban null (respuesta sin `id` raíz) y un e2e cuyas aserciones de `entityId` no mordían — todo corregido |
| `AUD-06` | **Lado operador** (Backoffice): quién suspendió/reactivó un tenant y cambió su plan (cross-deployable, actor `OPERATOR`, política nominal). Cierra la costura BKO-04/05/06. **Hecho 2026-09-04** (`ALPQ-83`). Acciones `BACKOFFICE.*` (`TENANT_SUSPENDED`/`TENANT_REACTIVATED`/`TENANT_PLAN_ASSIGNED`/`TENANT_PLAN_CLEARED`), entidad `company`. **Modo transaccional real:** el evento se escribe en la **misma transacción** que el cambio (`$transaction` sobre el cliente `alpaqa_backoffice`, GRANT INSERT + política nominal `WITH CHECK(true)`, **sin BYPASSRLS**); si el tenant no existe la tx se revierte entera y no queda rastro. El e2e cross-deployable lo prueba (actor OPERATOR, y 404 → sin rastro). **Los casos de uso importan `stampAuditEvent` del dominio `audit`** — segunda dependencia módulo→módulo deliberada tras `sync→audit`, acotada a tipos puros |
| `AUD-07` | **Lecturas**: `GET /audit` (dueño, su empresa, `ver_auditoria`) y `GET /backoffice/audit` (operador, cross-tenant), ambas paginadas por cursor. **Hecho 2026-09-04** (`ALPQ-84`). Permiso nuevo `ver_auditoria` agregado al vocabulario. Puerto `AuditReader` con **dos adapters por régimen de aislamiento**: `PrismaAuditReader` (tenant, corre en `withTenant` → RLS acota a la empresa) y `BackofficeAuditReader` (cliente backoffice, cross-tenant, política nominal `FOR SELECT` sin BYPASSRLS). **Keyset por `id`** (orden estable `createdAt` desc + `id` desc, `take: limit+1`), techo de página 100. Helpers de query **puros** compartidos (`audit-query.ts`, sin `PrismaService`, para no arrastrar la conexión de tenant al desplegable de backoffice). El e2e del dueño **cierra la costura RLS de AUD-01**: prueba que otra empresa no ve el rastro, el 403 sin permiso, el filtro y el cursor |
| `AUD-08` | Enganche **Sincronización**: el aplicador del lote registra un evento por operación aplicada (actor + acción de esa operación; momento del hecho vs. del registro). **Hecho 2026-09-05** (`ALPQ-85`). `ApplySyncBatchUseCase` llama al **mismo `AuditRecorder`** best-effort (2ª dependencia módulo→módulo tras backoffice→audit: `sync` importa `AuditModule`). Solo en la **aplicación fresca** (no en la rama idempotente); solo las operaciones **sensibles** (`SYNC_AUDIT_ACTIONS`: anulación, turnos, movimiento, comprobante, nota de crédito — **crear/cerrar orden y cobro NO**, igual que online). Actor del contexto de auth; `metadata.mode='offline'` + `clientUuid` + momento del hecho; `createdAt` = momento del registro (servidor). **★ Dedup del retry:** una operación de transición es idempotente-por-éxito en su adapter, así que un reintento del lote re-auditaba (duplicaba el rastro). Resuelto con una columna `client_uuid` + `@@unique(companyId, clientUuid)`: el online la deja en `NULL` (no colisiona), el offline la lleva, y el `P2002` del reintento el recorder lo trata como **éxito idempotente**. e2e con el adapter real prueba mode offline + no-duplicación en el retry |
| `AUD-09` | **Cobros** (`ALPQ-86`, cierra §12): registrar cobro (`CASHBOX.PAYMENT_REGISTERED`, `entityIdFromResponse`) y **anular cobro** (`CASHBOX.PAYMENT_VOIDED`, `entityIdParam:'paymentId'`), contra la entidad `payment`; + el offline `REGISTER_PAYMENT` en `SYNC_AUDIT_ACTIONS`. **Hecho 2026-09-05.** Abierta como HU nueva bajo la épica ya cerrada (precedente FAC-07). Supersede el "cobro NO" de AUD-02/08 |

Orden: `AUD-01` (mecanismo, con una acción real) → `AUD-02..05` (enganche por dominio, en paralelo
conceptual) → `AUD-06` (operador) → `AUD-07` (lecturas, cuando ya hay qué leer) → `AUD-08`
(el camino offline, que reusa lo de `AUD-01`).

---

## 10. Prerrequisitos y orden

**Prerrequisito duro (cumplido):** los seis dominios de escritura y **Sincronización** completos.
Auditoría va **después de Sincro** (§10 del maestro) a propósito: Sincro reescribió *cómo se escribe*
(operaciones encoladas, escrituras diferidas), y el enganche de auditoría se cuelga justo de esas
rutas; construirla antes era diseñarla contra rutas por cambiar y contestar sin datos si el rastro se
sincroniza o se genera en el servidor. **Ya está contestado: se genera en el servidor.**

**Riesgos a vigilar:**
- **AUD-01 define el mecanismo.** Equivocar el interceptor/recorder se paga en las cinco HUs de
  enganche. Es la HU de mayor radio: toca el borde HTTP transversal (patrón, no un módulo).
- **Alcance amplio = retrofit ancho.** El decorador mantiene el costo por ruta en una línea, pero son
  muchas rutas; auditar que **ninguna ruta de escritura sensible quede sin decorar** necesita un
  criterio explícito (una lista viva de acciones por dominio, no "lo que se acordó de decorar").
- **AUD-06 es cross-deployable** (como BKO): probar que el operador escribe/lee con su política
  nominal **sin** `BYPASSRLS`, y que un token de tenant no alcanza el rastro cross-tenant.
- **El best-effort** (invariante 4) hay que probarlo en las dos direcciones: que un fallo del rastro
  **no** tumba la venta, y que en el camino feliz el evento **sí** queda.

---

## 11. Decisiones confirmadas con el usuario (2026-09-04)

1. **Alcance amplio**: se audita **toda escritura sensible** de los seis dominios (no solo el
   conjunto de alto riesgo del §4). Implica el enganche transversal de §2.1 y el retrofit ancho de
   `AUD-02..05`; se acepta el costo a cambio de cobertura.
2. **Lecturas con consumidor real**: el MVP **captura el rastro y expone las lecturas que ya tienen
   consumidor** — el operador cross-tenant (BKO lo espera) y el dueño sobre su propia empresa (nuevo
   permiso `ver_auditoria`). Sin analítica (eso es Reportes/fase 2).
3. **Generación en el servidor** (heredado de Sincro §7, ratificado): el rastro nunca viaja en el
   lote; lo produce el servidor al aplicar.
4. **Red de reintento para el best-effort**: el usuario pidió no perder el rastro ante un fallo del
   `INSERT`. Se resuelve con **reintento asíncrono acotado + dead-letter a log** (default) y
   **auditoría transaccional** para el puñado crítico (§6). El **spool durable** (para el crash del
   proceso) queda en fase 2, nombrado en §7. Se aceptó explícitamente que el reintento en memoria
   cubre el fallo transitorio, no el crash.
5. **Crítico-transaccional = solo suspensión de tenant** al arranque. Las anulaciones se quedan en el
   nivel default con reintento; su promoción a crítica queda como costura abierta (§7).

---

## 12. Decisiones abiertas (a resolver con el usuario)

- **¿Se auditan los cobros (`payment`)? — RESUELTO (2026-09-05): sí, HU `AUD-09` (`ALPQ-86`).** El
  usuario decidió abrir una HU nueva bajo la épica (precedente FAC-07): se auditan **registrar cobro**
  (`POST /orders/:orderId/payments` → `CASHBOX.PAYMENT_REGISTERED`) y **anular cobro**
  (`DELETE /orders/:orderId/payments/:paymentId` → `CASHBOX.PAYMENT_VOIDED`), contra la entidad
  `payment`; y el **offline** `REGISTER_PAYMENT` en el aplicador del lote. Nivel default (best-effort).
  El texto original de la decisión, por si hace falta el contexto:

- ~~**¿Se auditan los cobros (`payment`)?**~~ El mapa §9 enumera para Caja solo turnos y movimientos de
  efectivo; los **cobros** (`POST /orders/:orderId/payments`) y, sobre todo, la **anulación de un
  cobro** (`DELETE /orders/:orderId/payments/:paymentId`) son movimientos de dinero sensibles pero **no aparecen en ninguna
  fila del §9** (ni Caja ni Facturación). Hoy quedan **sin auditar** (AUD-03 se ciñó a su ticket).
  **Recomendación:** auditar al menos la anulación de cobro (quemar/deshacer dinero recibido es de lo
  más sensible), y probablemente el registro de cobro. Es una línea `@Audit` por ruta; el mecanismo ya
  está. Decisión de alcance del usuario.
