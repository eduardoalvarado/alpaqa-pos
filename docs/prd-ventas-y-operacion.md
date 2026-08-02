# PRD de dominio — Ventas y operación

> PRD de dominio (hermano de `prd-catalogo-e-inventario.md`). **Referencia** el PRD maestro
> (`alcance-mvp-pos.md`) y los lineamientos técnicos para lo transversal — no los repite.
> Cubre los módulos §4 **Órdenes (entidad unificada)**, **Mesas** y **Comandas/Cocina**.
> **No** cubre cobro/pagos ni caja (dominio *Cobros y caja*) ni comprobantes SUNAT (dominio
> *Facturación electrónica*): esos consumen la `Order` cerrada por costuras ya previstas.

## 0. Convención de nombres

Todo en **inglés**, incluida la **capa física** (decisión para dominios nuevos, ago-2026):
- Modelos/entidades, campos, funciones, rutas y `code` de error en inglés + camelCase
  (`Order`, `OrderItem`, `unitPriceSnapshot`, `channel`).
- **Tablas y columnas físicas en inglés `snake_case`** vía `@@map`/`@map`
  (`@@map("order_item")`, `@map("unit_price_snapshot")`, `@map("company_id")`). Se sigue usando
  `@map` solo para convertir PascalCase/camelCase → `snake_case`, no para traducir idioma.
- Caveat: `order` es palabra reservada de SQL; la tabla `@@map("order")` funciona porque el
  proyecto **siempre cita** los identificadores en el SQL crudo (RLS), igual que `"stock"`.
- Los dominios **ya existentes** (catálogo/inventario/plataforma) conservan su físico en español
  vía `@map` (ALPQ-24 lo dejó así a propósito); esta convención inglesa aplica al **físico nuevo**.
- Comentarios y documentación en español.

---

## 1. Propósito y alcance del dominio

Modelar la **operación de venta** de forma **rubro-agnóstica** (PRD maestro §1): el negocio
está en el **flujo de la orden**, no en el rubro. Una `Order` única se comporta según el
**canal** (venta directa vs. mesa) y según **capacidades** del negocio, nunca según un
`tipo_negocio`.

**Estructura del dominio — núcleo + capas opcionales:**

| Capa | Gate | Contenido | A quién sirve |
|---|---|---|---|
| **Núcleo `Order`** | siempre | crear orden, agregar ítems (con snapshot), descuentos/anulación por rol, cerrar; devolución con reingreso | **todo rubro** (tienda chica, tienda grande, restaurante) |
| **Mesas** | `Company.usesTables` | plano de mesas, orden abierta por etapas, asignación a mesero | negocios con salón |
| **Comandas/Cocina** | `Company.usesKitchen` | envío a cocina de ítems `requiresPreparation`, KDS + impresión | negocios con preparación |

**Invariante-guardrail del dominio:** el código **nunca ramifica por rubro**; solo por
**capacidad** (`Company.usesTables`/`usesKitchen`) y por el **flag de producto**
`requiresPreparation` (ALPQ-10). Una tienda de ropa usa el núcleo y jamás toca mesas/cocina;
un restaurante activa ambas capas — mismo código, sin ramas por rubro (PRD maestro §1/§7).

**Fuera de alcance (otros dominios / fase 2):** pagos y pago mixto, turnos/arqueo de caja
(*Cobros y caja*); boleta/factura, series, correlativo fiscal, notas de crédito SUNAT
(*Facturación electrónica*); delivery con tracking, split/merge de mesas, propinas, KDS
en tiempo real (costuras §7).

---

## 2. Ubicación en la arquitectura backend

Un módulo hexagonal nuevo `sales` en `alpaqa-pos-backend` (lineamientos §2.2), dominio rico:
la `Order` es un **agregado transaccional** con invariantes de dinero, snapshot y
concurrencia (orden abierta editada por etapas).

| Módulo | Estilo | Contenido |
|---|---|---|
| `sales` | **Hexagonal** | `Order`, `OrderItem`, `OrderItemModifier`, `DiningTable`, `KitchenTicket` |

- **Consume** (por puerto, sin importar internals de otros módulos): `PriceResolver` y datos
  de `Variant`/`Product` del catálogo (lectura), `Money`, `IdGenerator`, `Clock`, `PrinterPort`.
- **Escribe cross-context** (por puerto, ver §4.1): movimientos de inventario `SALE`/`RETURN`
  al cerrar/devolver (dominio Inventario, tabla `movimiento_inventario` ya lista — ALPQ-12).
- **Expone** el agregado `Order` cerrado para que *Cobros y caja* y *Facturación* lo consuman.
- Estructura por módulo: `domain/` · `application/` · `infrastructure/` (lineamientos §2.2);
  dominio puro (no importa Prisma/Nest).

---

## 3. Modelo de datos

Todas las tablas son **tenant** (`companyId` + RLS en dos capas, invariante 4) y llevan
`branchId` (scoping por sucursal, como Inventario).

### 3.1 Núcleo de la orden

**`Order`** (`@@map("order")` — reservada, siempre citada) — agregado raíz de la venta:
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid FK → Company | tenant |
| branchId | uuid FK → Branch | sucursal donde se opera |
| clientUuid | uuid | **UUID de cliente** para creables offline (§6.C); idempotencia por UUID |
| number | int | correlativo **de display** por sucursal (no fiscal); el correlativo SUNAT vive en Facturación |
| channel | enum `OrderChannel` | `COUNTER`/`TAKEAWAY`/`DELIVERY` (venta directa) o `DINE_IN` (mesa) |
| status | enum `OrderStatus` | `OPEN` → `CLOSED` → (`CANCELLED`) |
| tableId | uuid FK → DiningTable NULL | solo `DINE_IN` (capa mesas) |
| waiterId | uuid FK → User NULL | mesero asignado (capa mesas) |
| customerId | uuid FK → Customer NULL | opcional (dominio Clientes, futuro) |
| subtotal | numeric(12,4) | `Money`; suma de líneas antes de descuento de orden |
| discountTotal | numeric(12,4) | `Money`; descuentos de orden + de línea |
| igvTotal | numeric(12,4) | `Money`; IGV calculado sobre el snapshot (no leído vivo) |
| total | numeric(12,4) | `Money`; subtotal − descuento + IGV (según régimen) |
| notes | text NULL | |
| openedAt / closedAt / cancelledAt | timestamp | `Clock` inyectable |
| cancelledById / cancelReason | uuid / text NULL | anulación con autorización (§4.2) |

- Unicidad: `(companyId, clientUuid)` — idempotencia offline. `(branchId, number)` display.

**`OrderItem`** (`@@map("order_item")`) — línea con **snapshot inmutable** (§6.A):
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid FK | tenant |
| orderId | uuid FK → Order | |
| variantId | uuid FK → Variant | **solo trazabilidad**; el importe NO se relee del catálogo |
| nameSnapshot | text | nombre del producto/variante al agregar |
| unitPriceSnapshot | numeric(12,4) | `Money`, **resuelto por `PriceResolver` al agregar** y congelado |
| igvAffectationSnapshot | enum `IgvAffectation` | copiado del producto (ALPQ-6) |
| unitOfMeasureSnapshot | enum `UnitOfMeasure` | copiado (ALPQ-7) |
| requiresPreparationSnapshot | boolean | copiado (ALPQ-10) → decide comanda |
| quantity | numeric(14,4) | decimal si el producto `allowsFractionalQuantity`; si no, entero (`assertQuantityAllowed`, ALPQ-7) |
| lineDiscount | numeric(12,4) | `Money`; descuento de línea (autorizado) |
| lineTotal | numeric(12,4) | `Money`; `(unitPrice + Σ modifiers) × quantity − lineDiscount` |

**`OrderItemModifier`** (`@@map("order_item_modifier")`) — modificadores elegidos, snapshot:
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid FK | tenant |
| orderItemId | uuid FK → OrderItem | |
| nameSnapshot | text | del modificador (ALPQ-8) |
| priceDeltaSnapshot | numeric(12,4) | `Money`; admite negativo ("sin queso") |

### 3.2 Mesas (capa `usesTables`)

**`DiningTable`** (`@@map("dining_table")`):
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId / branchId | uuid FK | tenant + sucursal |
| name | text | "Mesa 5", "Barra 2" |
| zone | text NULL | salón/zona |
| status | enum `TableStatus` | `FREE`/`OCCUPIED` (derivable de la orden abierta, pero se persiste para el plano) |

- Unicidad: `(branchId, name)`. Una mesa `OCCUPIED` tiene a lo sumo **una** `Order` `OPEN`.

### 3.3 Comandas / Cocina (capa `usesKitchen`)

**`KitchenTicket`** (`@@map("kitchen_ticket")`) — envío a cocina, append-only por tanda:
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId / branchId | uuid FK | |
| orderId | uuid FK → Order | |
| sequence | int | tanda dentro de la orden (mesa: se envían varias comandas) |
| status | enum `KitchenTicketStatus` | `PENDING`/`IN_PROGRESS`/`READY`/`SERVED` |
| sentAt | timestamp | `Clock` |

**`KitchenTicketItem`** (`@@map("kitchen_ticket_item")`) — qué ítems entraron a la tanda:
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid FK | |
| kitchenTicketId | uuid FK → KitchenTicket | |
| orderItemId | uuid FK → OrderItem | solo ítems con `requiresPreparationSnapshot=true` |
| quantity | numeric(14,4) | la cantidad enviada en esta tanda |

### 3.4 Enums

`OrderChannel {COUNTER, TAKEAWAY, DELIVERY, DINE_IN}` · `OrderStatus {OPEN, CLOSED, CANCELLED}` ·
`TableStatus {FREE, OCCUPIED}` · `KitchenTicketStatus {PENDING, IN_PROGRESS, READY, SERVED}`.
(Reutiliza `IgvAffectation`, `UnitOfMeasure`, `MovementType` de catálogo/inventario.)

### 3.5 Índices clave

- `(companyId, clientUuid)` único en `Order` (idempotencia offline).
- `(branchId, number)` único (display), `(branchId, status)` (listado de órdenes abiertas).
- `(orderId)` en `OrderItem`/`KitchenTicket`; `(branchId, name)` único en `DiningTable`.
- `(branchId, status)` en `KitchenTicket` (cola de KDS por sucursal).

---

## 4. Puertos y reglas de dominio

### 4.1 Puertos que este dominio usa/implementa (lineamientos §2.3)

| Puerto | Uso |
|---|---|
| **`PriceResolver`** | resolver el precio de la variante **al agregar** el ítem; se **snapshotea** en `unitPriceSnapshot` (no se relee). |
| **`Money`** | todo importe (línea, modificador, descuento, totales) se construye/opera con `Money`. Sin float. |
| **`Clock`** | timestamps de orden/comanda inyectables. |
| **`IdGenerator`** | UUID de `Order`/`OrderItem` (compatibilidad offline/sync, §6.C). |
| **`PrinterPort`** (§4.bis) | impresión de comanda (cocina) y de ticket de venta; adapter ESC/POS del lado POS. |
| **`InventoryWriter`** (nuevo) | puerto del dominio para registrar `MovementType.SALE`/`RETURN` en inventario al cerrar/devolver; el adapter llama al dominio Inventario (tabla ya lista, ALPQ-12). Desacopla Ventas de los internals de Inventario. |
| **`CatalogReader`** (nuevo) | lectura de la variante (existencia, `requiresPreparation`, afectación, unidad) para armar el snapshot; adapter sobre el catálogo. |

### 4.2 Invariantes del dominio

1. **Snapshot inmutable (§6.A):** `OrderItem` copia nombre/precio/IGV/unidad/modificadores **al
   agregarse**; nunca relee el catálogo. Editar el catálogo no altera órdenes ya armadas ni
   comprobantes.
2. **Dinero vía `Money`, nunca float.** Totales derivados por `Money` (líneas → subtotal →
   descuento → IGV según régimen → total).
3. **Cantidad fraccionada** solo si el producto lo permite (`assertQuantityAllowed`, ALPQ-7).
4. **Autorización por permiso, no por rubro (PRD §7):** aplicar descuento exige `aplicar_descuento`
   y respeta `Role.maxDiscountPct`; anular exige `anular_venta`. Nunca por nombre de rol.
5. **Orden abierta = una transacción por edición:** agregar/quitar ítems y recomputar totales
   ocurre atómico; la mesa mantiene a lo sumo una `Order` `OPEN`.
6. **Cerrar es irreversible hacia cobro:** `CLOSED` congela la orden y dispara los movimientos
   de inventario `SALE` de las variantes que controlan stock (invariante 5 de Inventario).
   **Decisión de implementación (SAL-05):** como `withTenant` no anida transacciones, el cierre
   y la salida de stock son **dos escrituras ordenadas** (primero el `SALE`, luego el `CLOSED`)
   en vez de una sola transacción; el `registerSale` es **idempotente por `orderId`**
   (`referenceType=ORDER`, `referenceId=orderId`), de modo que un reintento tras una falla parcial
   ni descuenta stock dos veces ni deja la orden cerrada sin movimiento. El pago y el comprobante
   los hacen otros dominios.
7. **Comanda solo para `requiresPreparation`:** solo ítems con el flag entran a `KitchenTicket`;
   sin cocina (`!usesKitchen`) no se generan comandas — la venta funciona igual.
8. **Aislamiento por tenant en dos capas** (filtro + RLS) incluido el scoping por `branchId`.

### 4.3 Relación con otros dominios (costuras — se **respetan**, no se implementan aquí)

- **Inventario:** cerrar una orden → `MovementType.SALE`; una devolución → `RETURN` con reingreso
  (ALPQ-12 ya soporta ambos tipos con `referenceType/Id`).
- **Facturación:** la `Order` `CLOSED` es la fuente que el comprobante **snapshotea** (§6.D). La
  **devolución** genera nota de crédito allí. El **correlativo fiscal** por serie/caja vive en
  Facturación (§6.B), no en `Order.number`.
- **Cobros y caja:** los `Payment` (incluido pago mixto) cuelgan de la `Order` cerrada.

---

## 5. Contrato de API (REST + OpenAPI, lineamientos §2.1/§5)

Recursos bajo el tenant autenticado (JWT + RBAC). DTOs con class-validator en el borde.

- **Órdenes (núcleo)** — `POST /orders` (crear venta directa con ítems), `GET /orders?branchId=&status=`,
  `GET /orders/:id`, `POST /orders/:id/items` / `PATCH|DELETE /orders/:id/items/:itemId`
  (editar orden abierta), `PATCH /orders/:id/discount` (permiso `aplicar_descuento`; body `{ itemId?, amount }`),
  `POST /orders/:id/close`, `POST /orders/:id/cancel` (permiso `anular_venta`).
- **Devoluciones** — `POST /orders/:id/returns` (reingreso a stock + costura nota de crédito).
- **Mesas (`usesTables`)** — `GET/POST /tables`, `PATCH /tables/:id`; `POST /orders` con
  `channel=DINE_IN` + `tableId` abre orden de mesa; `POST /orders/:id/items` la construye por etapas.
- **Comandas (`usesKitchen`)** — `POST /orders/:id/kitchen-tickets` (enviar tanda a cocina),
  `GET /kitchen-tickets?branchId=&status=` (cola KDS), `PATCH /kitchen-tickets/:id` (avanzar estado).

Permisos RBAC nuevos que este dominio agrega (al nacer, lineamientos): `vender`,
`aplicar_descuento`, `anular_venta` (ya existen `vender`/`aplicar_descuento`/`anular_venta` en el
vocabulario — se usan esos; ver `permission.ts`). Impresión de comanda/ticket vía `PrinterPort`.

---

## 6. Decisiones de diseño del dominio

- **Precio congelado al agregar, no al cerrar:** el `unitPriceSnapshot` se fija cuando el ítem
  entra a la orden (el precio que se le cotizó al cliente), no al cobrar.
- **`Order.number` es de display, no fiscal:** correlativo por sucursal para identificar la
  orden en pantalla/ticket; el correlativo SUNAT sin huecos por caja es de Facturación (§6.B).
- **Venta directa y mesa comparten `Order`:** la diferencia es `channel` + `tableId` + el flujo
  de edición por etapas; sin entidades separadas por rubro.
- **KDS del MVP = consultable:** la cola se lee por `GET /kitchen-tickets`; el push en tiempo
  real (WebSocket) es costura de fase 2. Impresión física siempre disponible vía `PrinterPort`.
- **Totales e IGV según régimen** (`Company.regimenTributario`): la lógica de desglose vive en un
  cálculo puro del dominio, ramificado por régimen (PRD maestro §8), no por rubro.

---

## 7. Costuras dejadas abiertas (diseñar ahora, construir en fase 2 — §9.bis)

- **KDS en tiempo real** (WebSocket/SSE): hoy consultable; el contrato de estados ya lo permite.
- **Split / merge / transferencia de mesas**, división de cuenta, propinas.
- **Delivery con tracking** y canales externos (apps): `channel=DELIVERY` ya existe como enum.
- **Cliente en la orden** (`customerId`): relación nullable lista; el dominio Clientes llega después.
- **Sincronización offline** de órdenes/comandas: `clientUuid` + idempotencia listos; la estrategia
  de conflictos la define el PRD de Sincronización.

---

## 8. Decisiones del dominio cerradas

- La `Order` es rubro-agnóstica; mesas y cocina son **capas gated por capacidad**, no pilares.
- Snapshot en `OrderItem` al agregar; catálogo nunca releído para el importe.
- `SALE`/`RETURN` a inventario por el puerto `InventoryWriter`, reusando el ledger transaccional
  de Inventario. Cierre/devolución y movimiento son **dos escrituras ordenadas + idempotencia por
  `orderId`** (no una sola transacción; ver §4.2 invariante 6).
- Autorización de descuento/anulación por **permiso** (+ `maxDiscountPct`), nunca por rubro/rol-nombre.
- **Todo en inglés, incluido el físico** (tablas/columnas `snake_case` vía `@map`); los dominios
  previos conservan su físico español (ver §0).
- Puertos nuevos `InventoryWriter` y `CatalogReader` **confirmados** (desacoplan Ventas de los
  internals de Inventario/Catálogo).

---

## 9. Mapa HU → entregable técnico

**Núcleo agnóstico (sirve a toda tienda, con o sin las capas):**
| HU (código) | Entregable principal |
|---|---|
| `SAL-01` | `Order` + `OrderItem` con snapshot (precio vía `PriceResolver`, IGV, unidad); crear venta directa con ítems |
| `SAL-02` | Editar orden abierta: agregar/quitar ítems, cambiar cantidad, recomputar totales (`Money`) |
| `SAL-03` | Descuentos por línea y por orden con autorización (`aplicar_descuento` + `maxDiscountPct`) |
| `SAL-04` | Anular orden con autorización (`anular_venta`) + `cancelReason` |
| `SAL-05` | Cerrar orden (`CLOSED`) + movimiento de inventario `SALE` transaccional (puerto `InventoryWriter`) |
| `SAL-06` | Devolución con reingreso a stock (`RETURN`) + costura nota de crédito |

**Capa mesas (`usesTables`):**
| HU | Entregable |
|---|---|
| `SAL-07` | `DiningTable` (plano, zonas, estado libre/ocupada) |
| `SAL-08` | Orden en mesa (`DINE_IN`): abrir mesa, orden abierta por etapas, asignar mesero, cerrar mesa |

**Capa cocina (`usesKitchen`):**
| HU | Entregable |
|---|---|
| `SAL-09` | `KitchenTicket`/`KitchenTicketItem`: enviar tanda a cocina (ítems `requiresPreparation`), estados KDS, impresión (`PrinterPort`) |

> Códigos `SAL-0x` = etiqueta de orden que reinicia por segmento (convención vigente); el
> id/referencia de cada HU es su clave Jira `ALPQ-N`.

---

## 10. Prerrequisitos y orden de implementación

**Prerrequisito duro (ya cumplido):** catálogo (variantes, precio, modificadores, flags
operativos), inventario (stock + movimientos), núcleo tenant (Company/Branch/User/Role) con
tenancy + RLS.

**Orden sugerido (agnóstico primero, capas después):**
`SAL-01 → SAL-02 → SAL-03 → SAL-04 → SAL-05` (núcleo de venta completo y usable por cualquier
tienda) → `SAL-06` (devolución) → `SAL-07 → SAL-08` (mesas, si `usesTables`) → `SAL-09`
(cocina, si `usesKitchen`). Cada HU con el ritual de cierre (auditoría + suites + Jira).

**Decidido (ago-2026):** puertos `InventoryWriter`/`CatalogReader` confirmados; físico de las
tablas nuevas en **inglés** `snake_case` (§0). El detalle fino del contrato `PrinterPort`
(ESC/POS) se cierra al implementar `SAL-09` (cocina), no bloquea el núcleo.
