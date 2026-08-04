# PRD de dominio — Cobros y caja

> PRD de dominio (hermano de `prd-ventas-y-operacion.md` y `prd-catalogo-e-inventario.md`).
> **Referencia** el PRD maestro (`alcance-mvp-pos.md`) y los lineamientos técnicos para lo
> transversal — no los repite. Cubre los módulos §4 **Caja** (turnos, arqueo, movimientos) y
> **Cobro y pagos** (métodos, pago mixto, vuelto).
> **No** cubre la construcción/cierre de la `Order` (dominio *Ventas y operación*, ya cerrado)
> ni la emisión de comprobantes SUNAT / series / correlativo fiscal / notas de crédito (dominio
> *Facturación electrónica*): este dominio **cobra** una `Order` ya cerrada y **prepara la caja**
> que Facturación usará como ancla de serie. Separación deliberada «vender/cobrar» vs «emitir
> comprobante numerado» (PRD maestro §9.bis).

## 0. Convención de nombres

Todo en **inglés**, incluida la **capa física** (decisión para dominios nuevos, ago-2026; igual
que *Ventas*):
- Modelos/entidades, campos, funciones, rutas y `code` de error en inglés + camelCase
  (`CashShift`, `Payment`, `openingFloat`, `changeGiven`).
- **Tablas y columnas físicas en inglés `snake_case`** vía `@@map`/`@map`
  (`@@map("cash_shift")`, `@map("opening_float")`, `@map("company_id")`). `@map` solo convierte
  PascalCase/camelCase → `snake_case`, no traduce idioma.
- `payment` no es palabra reservada de SQL; sin el caveat de `order`.
- Los dominios **previos** (catálogo/inventario/plataforma) conservan su físico en español
  (ALPQ-24); esta convención inglesa aplica al **físico nuevo**.
- Comentarios y documentación en español.

---

## 1. Propósito y alcance del dominio

Modelar el **cobro de una venta** y la **operación de caja** de forma **universal**: a diferencia
de mesas/cocina (capas opcionales de *Ventas* gated por capacidad), **todo negocio cobra y cuadra
caja** — no hay `Company.capability` que apague este dominio. La `Order` la **cierra** *Ventas*
(SAL-05, congela totales y dispara `SALE` de inventario); aquí se **liquida** con uno o varios
`Payment` dentro de un **turno de caja** abierto, y al final del turno se hace **arqueo**.

**Estructura del dominio:**

| Bloque | Contenido | Fuente maestro |
|---|---|---|
| **Caja / turnos** | `CashRegister` (la caja física), `CashShift` (turno con fondo inicial, apertura/cierre/arqueo), `CashMovement` (ingreso/egreso/sangrado/suministro) | §4 Caja, §5 Caja |
| **Cobros** | `Payment` sobre `Order` cerrada; métodos efectivo/tarjeta/Yape/Plin; **pago mixto** (1..n líneas por orden); vuelto en efectivo; QR dinámico Yape/Plin | §4 Cobro y pagos, §8 |

**Invariante-guardrail del dominio:** el cobro **no muta** el agregado `Order` (inmutable tras
`CLOSED`, §6.A/D del maestro); el estado «liquidada» se **deriva** de la suma de pagos. Sin
pasarela de pago: solo se **registra** el método (PRD maestro §8). Confirmación de Yape/Plin
**manual** por el cajero. Conciliación en el cierre: **automática para efectivo**, **manual para
tarjeta/billeteras** (§8).

**Fuera de alcance (otros dominios / fase 2):** boleta/factura, series, correlativo fiscal,
notas de crédito SUNAT (*Facturación electrónica* — este dominio solo deja `CashRegister` como
ancla de serie, §6.B del maestro); integración con pasarela de pago y conciliación automática de
tarjeta/billeteras contra estado de cuenta (§9 fase 2); propinas (§9); sincronización offline de
pagos/movimientos (`clientUuid` listo, estrategia en *Sincronización*).

---

## 2. Ubicación en la arquitectura backend

Un módulo hexagonal nuevo **`cashbox`** en `alpaqa-pos-backend` (lineamientos §2.2), dominio rico:
el `CashShift` es un **agregado** con invariantes de dinero (arqueo esperado vs. contado por medio
de pago), ciclo de vida (abrir/cerrar, un turno abierto por caja) y consistencia con los `Payment`
y `CashMovement` del turno.

| Módulo | Estilo | Contenido |
|---|---|---|
| `cashbox` | **Hexagonal** | `CashRegister`, `CashShift`, `CashMovement`, `Payment` |

- **Consume** (por puerto, sin importar internals de otros módulos): `Money`, `Clock`,
  `IdGenerator` (shared kernel); `SalesReader` (nuevo — lee la `Order` **cerrada**: existencia,
  `status`, `total`, `branchId`); `PrinterPort` (recibo de pago y reporte de cierre Z);
  `QrGenerator` (nuevo — payload EMVCo para Yape/Plin).
- **No escribe cross-context.** No toca inventario ni catálogo; **no muta** la `Order` (§4.2).
- **Expone** el `Payment` y el `CashShift` cerrado para que *Facturación* los consuma (el
  comprobante se emite después del cobro, desde la serie de la caja del turno — §6.B del maestro).
- Estructura por módulo: `domain/` · `application/` · `infrastructure/` (lineamientos §2.2);
  dominio puro (no importa Prisma/Nest).

> Nombre de módulo (`cashbox`), prefijo de HU (`PAY`) y granularidad de permisos **confirmados**
> con el usuario (ago-2026); ver §11.

---

## 3. Modelo de datos

Todas las tablas son **tenant** (`companyId` + RLS en dos capas, invariante 4 / lineamientos §2.4)
y llevan `branchId` (scoping por sucursal, como Inventario y Ventas). UUID de cliente en lo
**creable offline** (`CashShift`, `Payment`, `CashMovement`) para idempotencia de sync (§6.C
maestro).

### 3.1 Caja y turnos

**`CashRegister`** (`@@map("cash_register")`) — la caja física; **ancla de serie** para Facturación:
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid FK → Company | tenant |
| branchId | uuid FK → Branch | sucursal |
| name | text | "Caja 1", "Barra" |
| active | boolean | borrado lógico (patrón catálogo) |

- Unicidad: `(branchId, name)`. **Costura Facturación:** `SerieComprobante` se asignará en
  exclusiva a un `CashRegister` (§6.B maestro); no se modela aquí, solo se deja la caja como ancla.

**`CashShift`** (`@@map("cash_shift")`) — turno de caja, agregado del arqueo:
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId / branchId | uuid FK | tenant + sucursal |
| clientUuid | uuid | idempotencia offline (§6.C) |
| cashRegisterId | uuid FK → CashRegister | |
| cashierId | uuid FK → User | cajero del turno (§4: turnos por cajero) |
| status | enum `ShiftStatus` | `OPEN` → `CLOSED` |
| openingFloat | numeric(12,4) | `Money`; fondo inicial |
| expectedCash | numeric(12,4) NULL | `Money`; efectivo esperado, calculado al cerrar |
| countedCash | numeric(12,4) NULL | `Money`; efectivo contado (ingresado por el cajero) |
| cashDifference | numeric(12,4) NULL | `Money`; `countedCash − expectedCash` |
| openedAt / closedAt | timestamp | `Clock` inyectable |
| openedById / closedById | uuid FK → User | auditoría |

- Unicidad/invariante: **un solo turno `OPEN` por caja** → índice único parcial
  `cash_shift(cash_register_id) WHERE status='OPEN'` **+** chequeo aplicativo (doble defensa, patrón
  «una orden abierta por mesa» de SAL-08).
- El desglose **por medio de pago** (tarjeta/billeteras, conciliación manual) vive en `ShiftMethodCount`.

**`ShiftMethodCount`** (`@@map("shift_method_count")`) — arqueo por medio de pago, escrito al cerrar:
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid FK | tenant |
| cashShiftId | uuid FK → CashShift | |
| method | enum `PaymentMethod` | CASH/CARD/YAPE/PLIN |
| expected | numeric(12,4) | `Money`; Σ pagos del método en el turno (para CASH, el neto de caja) |
| counted | numeric(12,4) | `Money`; contado/leído (automático efectivo, **manual** tarjeta/billeteras §8) |
| difference | numeric(12,4) | `Money`; `counted − expected` |

- Unicidad: `(cashShiftId, method)`.

**`CashMovement`** (`@@map("cash_movement")`) — ingresos/egresos de efectivo del turno, motivo obligatorio:
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId / branchId | uuid FK | tenant + sucursal |
| clientUuid | uuid | idempotencia offline |
| cashShiftId | uuid FK → CashShift | pertenece al turno abierto |
| type | enum `CashMovementType` | DEPOSIT/WITHDRAWAL/CASH_DROP/CASH_SUPPLY |
| amount | numeric(12,4) | `Money`; siempre positivo, el signo lo da `type` |
| reason | text | **obligatorio** (dato rico, §9.bis maestro); vacío → 422 |
| userId | uuid FK → User | quién lo registró |
| createdAt | timestamp | `Clock` |

### 3.2 Cobros

**`Payment`** (`@@map("payment")`) — línea de pago sobre una `Order` cerrada (1..n = pago mixto):
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId / branchId | uuid FK | tenant + sucursal |
| clientUuid | uuid | idempotencia offline (§6.C) |
| orderId | uuid FK → Order | la orden **cerrada** que se liquida (leída por `SalesReader`) |
| cashShiftId | uuid FK → CashShift | turno **abierto** en que se cobra |
| method | enum `PaymentMethod` | CASH/CARD/YAPE/PLIN |
| amount | numeric(12,4) | `Money`; importe **aplicado a la orden** (= tendered − change en efectivo) |
| tendered | numeric(12,4) NULL | `Money`; efectivo recibido (solo CASH); = amount para no-efectivo |
| changeGiven | numeric(12,4) NULL | `Money`; vuelto (solo CASH; `max(0, tendered − outstanding)`) |
| operationNumber | text NULL | `numero_operacion` para conciliación futura (tarjeta/billeteras) |
| createdAt | timestamp | `Clock` |

- Unicidad: `(companyId, clientUuid)` (idempotencia offline). Índice `(orderId)` (liquidación),
  `(cashShiftId, method)` (arqueo).
- **Contribución al efectivo de caja** de un pago CASH = `tendered − changeGiven = amount`
  (por eso el arqueo suma `amount`, no `tendered`).

### 3.3 Enums

`ShiftStatus {OPEN, CLOSED}` ·
`PaymentMethod {CASH, CARD, YAPE, PLIN}` ·
`CashMovementType {DEPOSIT, WITHDRAWAL, CASH_DROP, CASH_SUPPLY}`
(DEPOSIT=ingreso, WITHDRAWAL=egreso, CASH_DROP=sangrado/retiro a caja fuerte, CASH_SUPPLY=suministro/reposición de fondo).

### 3.4 Índices clave

- `cash_shift(cash_register_id) WHERE status='OPEN'` único parcial (un turno abierto por caja).
- `(branchId, name)` único en `CashRegister`; `(companyId, clientUuid)` único en `CashShift`/`Payment`/`CashMovement`.
- `(orderId)` en `Payment` (liquidación); `(cashShiftId, method)` en `Payment` y `(cashShiftId, method)` único en `ShiftMethodCount` (arqueo).
- `(branchId, status)` en `CashShift` (turno abierto por sucursal).

---

## 4. Puertos y reglas de dominio

### 4.1 Puertos que este dominio usa/implementa (lineamientos §2.3)

| Puerto | Uso |
|---|---|
| **`Money`** | todo importe (fondo, pago, vuelto, movimiento, arqueo) se construye/opera con `Money`. Sin float. |
| **`Clock`** | timestamps de turno/pago/movimiento inyectables. |
| **`IdGenerator`** | UUID de `CashShift`/`Payment`/`CashMovement` (creables offline, §6.C). |
| **`SalesReader`** (nuevo) | lee la `Order` **cerrada** para cobrar: existencia, `status=CLOSED`, `total`, `branchId`. Cross-context de **solo lectura** confinado a infraestructura (patrón: adapter de inventario que lee catálogo, ALPQ-11). No muta la orden. |
| **`PrinterPort`** (§4.bis, existente) | recibo de pago al cliente y **reporte de cierre (Z)** del turno; adapter ESC/POS stub del lado backend (como SAL-09), la impresión física vive del POS y **nunca tumba** el cobro/cierre si el hardware falla. |
| **`QrGenerator`** (nuevo) | payload **EMVCo** (QR interoperable) para Yape/Plin con el monto incluido; **generación local**, no integración de API (§8). Se cierra al implementar su HU. |

### 4.2 Invariantes del dominio

1. **La `Order` se cobra solo si está `CLOSED`** (leída por `SalesReader`); una orden `OPEN`/
   `CANCELLED` → 409. El cobro **no muta** la orden (inmutable tras cierre, §6.A/D maestro).
2. **Dinero vía `Money`, nunca float.** Vuelto, esperado, contado y diferencia son operaciones de `Money`.
3. **Liquidación derivada, no persistida en la orden:** `outstanding = order.total − Σ Payment.amount(orderId)`.
   La orden queda «liquidada» cuando `outstanding ≤ 0`. No se agrega columna a `Order` (se respeta el
   agregado de *Ventas*); la settlement se calcula leyendo pagos.
4. **Vuelto solo en efectivo, sin sobrepago en no-efectivo:**
   - CASH: `changeGiven = max(0, tendered − outstanding)`, `amount = min(tendered, outstanding)`.
   - CARD/YAPE/PLIN: `amount ≤ outstanding` (no hay vuelto en tarjeta/billetera) → si excede, 422.
5. **Pago mixto = varias `Payment` de la misma orden**, cada una con su método; la suma de `amount`
   no puede exceder `order.total` (el excedente en efectivo es vuelto, no pago).
6. **Todo pago/movimiento pertenece a un turno `OPEN`** (`cashShiftId` **NOT NULL**); si el turno
   está `CLOSED` o no hay turno abierto en la caja del cajero → `409 NO_OPEN_SHIFT`. **Confirmado
   (ago-2026):** no existe cobro fuera de turno.
7. **Un solo turno `OPEN` por caja** (índice único parcial + chequeo aplicativo, §3.1).
8. **Motivo obligatorio en `CashMovement`** (dato rico para IA/auditoría, §9.bis); vacío → 422.
9. **Arqueo al cerrar (regla pura):** por método,
   `efectivo esperado = openingFloat + Σ(CASH.amount) + Σ(CASH_SUPPLY) + Σ(DEPOSIT) − Σ(CASH_DROP) − Σ(WITHDRAWAL)`;
   no-efectivo `esperado = Σ(pagos del método.amount)`; `difference = counted − expected`.
   **Efectivo: contado ingresado y diferencia automática; tarjeta/billeteras: contado manual** (§8).
   Cerrar es **irreversible** (`CLOSED`) y libera la caja para un nuevo turno.
10. **Aislamiento por tenant en dos capas** (filtro + RLS) incluido el scoping por `branchId`;
    escrituras tenant-scoped (`updateMany`, patrón multi-tenancy del backend).

### 4.3 Relación con otros dominios (costuras — se **respetan**, no se implementan aquí)

- **Ventas:** consume la `Order` `CLOSED` por `SalesReader` (solo lectura). No la muta ni la
  reabre; anular una venta ya cobrada es asunto de *Facturación* (nota de crédito), no de este dominio.
- **Facturación:** el comprobante se emite **después** del cobro, tomando la serie de la
  `CashRegister` del turno (§6.B: una serie por caja). Este dominio **deja la caja como ancla**;
  `SerieComprobante`/correlativo fiscal viven allí. La separación «cobrar» vs «emitir comprobante
  numerado» es deliberada (§9.bis maestro).
- **Reportes:** cierres de caja con diferencia, pagos por método y por usuario se alimentan de
  `CashShift`/`ShiftMethodCount`/`Payment` (dato rico, §9.bis). Solo lectura, otro dominio.
- **Auditoría (transversal):** apertura/cierre de caja, sangrados y diferencias de arqueo son focos
  de auditoría (§4 maestro); se registran con `Clock`/usuario desde el día uno.

---

## 5. Contrato de API (REST + OpenAPI, lineamientos §2.1/§5)

Recursos bajo el tenant autenticado (JWT + RBAC). DTOs con class-validator en el borde.

- **Cajas (setup)** — `GET/POST /cash-registers`, `PATCH /cash-registers/:id` (activar/desactivar,
  renombrar). Alta/edición = **setup del negocio** → `gestionar_configuracion` (como el plano de
  mesas en SAL-07); **listar** es superficie POS → `vender`.
- **Turnos** — `POST /cash-registers/:id/shifts` (abrir turno con `openingFloat`; exige caja sin
  turno abierto), `GET /shifts?branchId=&status=`, `GET /shifts/:id` (con arqueo derivado),
  `POST /shifts/:id/close` (arqueo: body con `countedCash` y `counted` por método no-efectivo).
  Abrir/consultar → `operar_caja`; **cerrar/arqueo** → `cerrar_caja` (sensible, `puede_cerrar_caja`
  del maestro §5).
- **Movimientos de caja** — `POST /shifts/:id/movements` (DEPOSIT/WITHDRAWAL/CASH_DROP/CASH_SUPPLY,
  `reason` obligatorio), `GET /shifts/:id/movements`. Permiso `operar_caja`.
- **Cobros** — `POST /orders/:id/payments` (registrar un pago; body `{ method, tendered|amount,
  operationNumber? }`; abre/usa el turno del cajero), `GET /orders/:id/payments` (líneas + `outstanding`),
  `DELETE /orders/:id/payments/:paymentId` (corregir un pago del turno abierto, antes de comprobante).
  Permiso `cobrar`. El pago mixto es simplemente varios `POST` sobre la misma orden.
- **QR Yape/Plin** — `POST /orders/:id/payment-qr` (`{ method: YAPE|PLIN, amount }` → payload EMVCo
  para mostrar; **no** registra el pago — la confirmación es manual y luego se hace `POST .../payments`).
  Permiso `cobrar`.

**Permisos RBAC nuevos que este dominio agrega** (al nacer, lineamientos): `operar_caja` (abrir
turno, movimientos), `cerrar_caja` (arqueo/cierre — mapea a `puede_cerrar_caja` del maestro §5),
`cobrar` (registrar pagos / generar QR). Setup de cajas reusa `gestionar_configuracion`; listar
reusa `vender`. Ver §11 sobre granularidad. Impresión de recibo/Z vía `PrinterPort`.

---

## 6. Decisiones de diseño del dominio

- **Cobrar no muta la `Order`:** la settlement se **deriva** (`Σ amount` vs `total`); el agregado de
  *Ventas* permanece inmutable tras `CLOSED`. Evita acoplar dos módulos por una columna compartida.
- **`amount` es lo aplicado a la orden; `tendered`/`changeGiven` solo para efectivo:** así el arqueo
  suma `amount` sin recalcular vueltos y el efectivo en caja cuadra por construcción.
- **Sin pasarela (§8):** el pago **registra** el método; tarjeta la cobra el POS físico del banco;
  Yape/Plin se confirman **manualmente** tras mostrar el QR. `operationNumber` opcional para
  conciliación futura (fase 2).
- **QR = generación local EMVCo, no API:** `QrGenerator` arma el payload interoperable con monto; el
  cajero confirma el abono. Nada de webhooks/consultas al banco en el MVP.
- **Arqueo por medio de pago:** efectivo automático (esperado calculado, contado ingresado); tarjeta y
  billeteras **manual** en el MVP (§8) — el desglose se persiste en `ShiftMethodCount` para Reportes.
- **Caja universal, sin gate de capacidad:** a diferencia de mesas/cocina, no hay
  `Company.capability` que apague este dominio; todo negocio cobra y cuadra caja.

---

## 7. Costuras dejadas abiertas (diseñar ahora, construir en fase 2 — §9.bis)

- **Serie por caja (Facturación):** `CashRegister` ya es el ancla; `SerieComprobante`/correlativo
  fiscal llegan con *Facturación electrónica* sin rediseñar la caja (§6.B maestro).
- **Conciliación automática** de tarjeta/billeteras contra estado de cuenta bancario: hoy manual;
  `operationNumber` ya se captura por pago (§9 fase 2).
- **Integración con pasarela de pago:** hoy solo se registra el método; el enum `PaymentMethod` y el
  puerto de cobro dejan la puerta abierta (§9 fase 2).
- **Propinas y comisiones de mesero:** no en el MVP (§9); el `Payment`/`CashShift` no las modela aún.
- **Sincronización offline** de pagos/turnos/movimientos: `clientUuid` + idempotencia listos; la
  estrategia de conflictos la define el PRD de *Sincronización*.

---

## 8. Decisiones del dominio cerradas

- Caja es **universal** (sin capability gate); mesas/cocina eran capas, la caja no.
- El cobro **no muta** la `Order`; liquidación **derivada** de la suma de pagos.
- **Pago mixto** = varias `Payment` por orden; sin sobrepago en no-efectivo; vuelto solo en efectivo.
- **Sin pasarela**: se registra el método; Yape/Plin con **QR local EMVCo** + confirmación manual (§8).
- **Arqueo**: efectivo automático, tarjeta/billeteras manual; desglose por método en `ShiftMethodCount`.
- **Un turno abierto por caja** (índice único parcial + chequeo aplicativo).
- **Todo en inglés, incluido el físico** (`snake_case` vía `@map`); dominios previos conservan su
  físico español (§0).
- Puerto nuevo `SalesReader` (lectura de la `Order` cerrada) y `QrGenerator` (EMVCo) **propuestos**;
  reusa `Money`/`Clock`/`IdGenerator`/`PrinterPort`.

---

## 9. Mapa HU → entregable técnico

**Caja / turnos:**
| HU (código) | Entregable principal |
|---|---|
| `PAY-01` | `CashRegister` CRUD (setup, `gestionar_configuracion`); ancla de serie para Facturación |
| `PAY-02` | Abrir turno (`CashShift` con `openingFloat`; un turno abierto por caja; `operar_caja`) |
| `PAY-05` | `CashMovement` (ingreso/egreso/sangrado/suministro, motivo obligatorio; `operar_caja`) |
| `PAY-06` | Cerrar turno + arqueo (`ShiftMethodCount`, esperado vs contado por método; `cerrar_caja`; Z vía `PrinterPort`) |

**Cobros:**
| HU | Entregable |
|---|---|
| `PAY-03` | `Payment` sobre `Order` cerrada (método, vuelto en efectivo, `operationNumber`; `SalesReader`; `cobrar`) |
| `PAY-04` | Pago mixto: varias líneas por orden, `outstanding` derivado, sin sobrepago en no-efectivo |
| `PAY-07` | QR dinámico Yape/Plin (EMVCo, `QrGenerator`, confirmación manual) |

> Códigos `PAY-0x` = etiqueta de orden que reinicia por segmento (convención vigente); el
> id/referencia de cada HU es su clave Jira `ALPQ-N` (se asigna al crear la épica).

---

## 10. Prerrequisitos y orden de implementación

**Prerrequisito duro (ya cumplido):** *Ventas y operación* completo — la `Order` se **cierra**
(SAL-05) y expone su total; núcleo tenant (Company/Branch/User/Role) con tenancy + RLS; shared
kernel (`Money`/`Clock`/`IdGenerator`/`PrinterPort`).

**Orden sugerido (caja primero, cobro después):**
`PAY-01 → PAY-02` (caja abierta y operable) → `PAY-03` (cobro simple sobre orden cerrada) →
`PAY-04` (pago mixto) → `PAY-05` (movimientos) → `PAY-06` (cierre + arqueo, cierra el ciclo) →
`PAY-07` (QR Yape/Plin). Cada HU con el ritual de cierre (auditoría `audit-plan` + `audit-arquitectura`
→ suites vía `test-runner` → commit sin coautoría → push → mover el ticket en Jira).

**Decisiones de arranque confirmadas (§11):** cobro siempre en turno abierto, liquidación derivada
sin tocar `Order`, tres permisos (`cobrar`/`operar_caja`/`cerrar_caja`), QR Yape/Plin en el MVP,
módulo `cashbox` y prefijo `PAY`.

---

## 11. Decisiones confirmadas con el usuario (ago-2026)

1. **Cobro siempre dentro de un turno abierto:** `Payment.cashShiftId` **NOT NULL**; sin turno
   abierto en la caja → `409 NO_OPEN_SHIFT` (§4.2 inv. 6). No hay venta sin caja abierta.
2. **Liquidación derivada, sin tocar `Order`:** `outstanding = total − Σ Payment.amount`; el
   agregado de *Ventas* permanece inmutable tras `CLOSED` (§4.2 inv. 3). Cero acoplamiento por columna.
3. **Tres permisos:** `cobrar` (pagos/QR), `operar_caja` (abrir turno + movimientos), `cerrar_caja`
   (arqueo, sensible; mapea a `puede_cerrar_caja` del maestro §5).
4. **QR Yape/Plin (PAY-07) entra al MVP:** generación local EMVCo + confirmación manual (§8 maestro).
5. **Nombre de módulo `cashbox` y prefijo de HU `PAY`** adoptados (defaults; renombrables antes de
   scaffoldear si el usuario lo pide).
