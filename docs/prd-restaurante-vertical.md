# PRD — Restaurante (vertical vendible)

> **Fase 2** del frente de verticales vendibles (maestro §7). **Reclasificación, no
> reescritura:** mesas, comandas y KDS ya existen en *Ventas y operación* (SAL-07/08/09);
> este dominio los **empaqueta** como el vertical comercial `restaurante`, detrás del
> feature-gating de la Fase 1. Referencia: maestro §7/§10, `docs/prd-verticales-feature-gating.md`,
> y `docs/lineamientos-tecnicos.md` §2.2/§2.6.

## 0. Convención de nombres
- Épica nueva; HUs con prefijo **`RST`**. La clave Jira `ALPQ-N` es el id.
- **No hay módulo nuevo ni tablas nuevas:** mesas/cocina siguen en el módulo `sales`. Este
  dominio solo agrega el **candado comercial** encima.

---

## 1. Propósito
Que "restaurante" sea un **vertical que se vende**: un tenant solo opera mesas/cocina si su
plan incluye la feature `restaurante`. La Fase 1 ya construyó el mecanismo; esta fase lo
**aplica a restaurante** y cierra la compatibilidad de lo que ya estaba libre.

## 2. Qué ya existe (no reconstruir)
- **Ventas (SAL-07/08/09):** `DiningTable` (mesas), orden `DINE_IN`, `KitchenTicket` (comandas/KDS),
  gateadas por capacidad (`usesTables`/`usesKitchen`) en sus casos de uso.
- **Fase 1 (FGT):** vocabulario `FEATURES`, `tenant_features`, `@RequireFeature` + `FeatureGuard`,
  y el **gate del toggle** (FGT-02): **ya** no se puede *prender* `usaMesas`/`usaCocina` sin
  `restaurante` en el plan. `VERTICALS.restaurante = [usesTables, usesKitchen]` (feature **coarse**,
  decidida en FGT-02).

## 3. Lo que falta (Fase 2)

### 3.1 Backstop por ruta (cierra el caso *downgrade*)
El toggle ya está gateado, pero si un tenant tenía `restaurante`, prendió mesas/cocina y **luego
pierde la feature** (cambio/retiro de plan), sus capacidades siguen en `true` (invariante 3 de FGT:
"apaga acceso, conserva datos") — y sin backstop sus rutas seguirían respondiendo. Por eso se
decoran con **`@RequireFeature('restaurante')`**:
- **`TableController`** (`/tables`, SAL-07) — a **nivel de clase** (incluye lecturas: sin el
  vertical, no se ve ni gestiona el plano de mesas).
- **`KitchenTicketController`** (comandas/KDS, SAL-09) — a **nivel de clase**.
- **`OrderController` → `PATCH /orders/:id/waiter`** (asignar mesero) — ruta suelta en un
  controller compartido.

**Lo que NO se gatea:** `POST /orders` (creación) es **compartida** (mostrador también la usa), así
que no lleva `@RequireFeature`. Una orden `DINE_IN` igual queda bloqueada en la práctica: necesita
una mesa, y gestionar mesas está detrás de la feature. Costura menor nombrada (§6).

### 3.2 Migración / compatibilidad
- **Datos reales:** pre-launch, no hay tenants productivos. Cuando los haya, la migración es
  **asignar un plan con `restaurante` a los tenants que hoy usan mesas/cocina** (documentado acá).
- **Seed:** el demo actual es una **tienda** (`controlaInventario:true`, sin mesas/cocina), así que
  no necesita plan `restaurante` (verificado en RST-02). Si un demo futuro usa mesas/cocina, recibirá
  el plan.
- **Fixtures de test:** los e2e que ejercitan mesas/cocina (`table`, `order-table`, `kitchen-ticket`,
  `order` si usa mesero, `sync-conflicts`) deben asignar un plan `restaurante` a su tenant, porque el
  backstop por ruta corta **independientemente de cómo se prendió la capacidad** (esos e2e siembran
  capacidades por `owner`, saltándose el toggle, pero no saltan el guard de ruta).

## 4. Decisiones
- **Feature `restaurante` coarse** (agrupa mesas + cocina) — ya fijada en FGT-02.
- **Gate a nivel de clase** en los controllers exclusivos (incluye GETs): sin el vertical, cero
  acceso. La ruta `waiter` se gatea suelta por vivir en el controller compartido de órdenes.
- **`POST /orders` no se gatea** (compartida); el bloqueo de dine-in es indirecto (vía mesas).

## 5. Mapa HU → entregable
| HU | Entregable |
|---|---|
| `RST-01` | Backstop por ruta: `@RequireFeature('restaurante')` en `TableController`, `KitchenTicketController` y la ruta `waiter`. Fix de los fixtures e2e de mesas/cocina (asignar plan `restaurante`). e2e que prueba el corte: sin la feature, `/tables` y `/kitchen-tickets` → 403. **Hecho 2026-09-07** (`ALPQ-92`): gate a nivel de clase (incluye GETs); helper de test `grantFeatures`; e2e de downgrade (capacidades on + sin plan → 403) mutation-tested. Suites 789 unit + 447 e2e |
| `RST-02` | Migración/seed. **Hecho 2026-09-07** (`ALPQ-93`): el **seed es una tienda** (`controlaInventario:true`, sin mesas/cocina), así que **no requiere plan `restaurante` ni cambios**. **No hay datos productivos** (pre-launch), así que no hay migración que correr ahora. El **procedimiento** para prod queda documentado (§3.2): asignar un plan con `restaurante` a los tenants que tengan `usaMesas`/`usaCocina` en `true` antes de que el backstop les corte el acceso. Sin código |

## 6. Costuras
- **Dine-in por `POST /orders` sin la feature:** la ruta compartida no se gatea; el acceso a mesas
  (prerrequisito real de una orden `DINE_IN`) sí. Si se quisiera cortar también la creación, el caso
  de uso de crear orden `DINE_IN` chequearía la feature — no se hace en el MVP del vertical.
- **Auto-apagado de capacidades al perder la feature:** hoy se conserva el `true` y se corta por
  ruta (invariante 3 de FGT). Auto-apagar la capacidad al downgrade es una alternativa; se deja como
  decisión abierta.

## 7. Prerrequisitos y orden
Fase 1 (FGT-01/02/03) completa. **Riesgo:** el backstop por ruta tiene radio en los e2e de
mesas/cocina (esos tenants necesitan el plan) — cambio mecánico pero ancho; correr las suites y
verificar que ninguno quede en 403 espurio.
