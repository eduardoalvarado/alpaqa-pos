# PRD de dominio — Facturación electrónica

> PRD de dominio (hermano de `prd-catalogo-e-inventario.md`, `prd-ventas-y-operacion.md` y
> `prd-cobros-y-caja.md`). **Referencia** el PRD maestro (`alcance-mvp-pos.md`) y los
> lineamientos técnicos para lo transversal — no los repite. Cubre el módulo §4 **Facturación
> electrónica** (comprobantes boleta/factura, notas de crédito, series/correlativo, integración
> PSE, entrega al cliente).
> **No** cubre la construcción/cierre de la `Order` (dominio *Ventas*, cerrado) ni el cobro/
> arqueo (dominio *Cobros y caja*, cerrado): este dominio **emite el comprobante numerado** de
> una `Order` ya **cerrada y liquidada**, tomando la serie de la **caja** del cobro. Separación
> deliberada «vender/cobrar» vs «emitir comprobante numerado» (§9.bis maestro).

## 0. Convención de nombres

Todo en **inglés**, incluida la **capa física** (decisión para dominios nuevos, igual que
*Ventas* y *Cobros*):
- Modelos/entidades, campos, funciones, rutas y `code` de error en inglés + camelCase
  (`ComprobanteSeries`, `Comprobante`, `CreditNote`, `currentCorrelative`, `sunatStatus`).
- **Tablas y columnas físicas en inglés `snake_case`** vía `@@map`/`@map`
  (`@@map("comprobante")`, `@map("cash_register_id")`).
- «Comprobante» se conserva como término de dominio (es el nombre legal peruano del documento);
  no se traduce a «receipt/invoice» genérico para no perder la distinción boleta/factura.
- Los dominios previos en español (catálogo/inventario/plataforma) conservan su físico; esta
  convención inglesa aplica al **físico nuevo**.
- Comentarios y documentación en español.

---

## 1. Propósito y alcance del dominio

Modelar la **emisión de comprobantes electrónicos** (boleta/factura) ante SUNAT vía un **PSE**
(Proveedor de Servicios Electrónicos), sus **notas de crédito**, y la **entrega** al cliente.
Es el eslabón legal tras el cobro: *Ventas* arma y cierra la `Order` (snapshot de líneas,
SAL-05), *Cobros* la liquida en una caja (PAY-03..06), y **aquí** se **emite el documento
numerado** que la respalda ante SUNAT.

**Estructura del dominio:**

| Bloque | Contenido | Fuente maestro |
|---|---|---|
| **Series** | `ComprobanteSeries` (serie por tipo, **exclusiva de una caja**, `currentCorrelative`) | §6.B |
| **Comprobantes** | `Comprobante` (+ `ComprobanteItem`) con snapshot de totales/IGV/cliente; ciclo `sunatStatus` | §4, §5, §6.D |
| **Notas de crédito** | `CreditNote` (anulación / devolución / corrección) que **rinde** un número | §4, §5 |
| **Clientes** | `Customer` (tipo/nº doc, nombre) capturado al emitir | §4 Clientes, §8 |
| **Integración** | `PsePort` (SUNAT vía Nubefact/Bizlinks **intercambiable**); ciclo `estado_sunat` | §4, §6, CLAUDE.md |

**Invariante-guardrail del dominio:** el comprobante es un **documento legal inmutable**: copia
sus totales, desglose de IGV y datos del cliente al emitir y **no los recalcula** leyendo la
orden (§6.D). El **correlativo es sin huecos por serie** y se asigna **local al emitir**; todo
número consumido **se rinde** (anulación → nota de crédito, nunca se reusa ni se salta, §6.B).

**Fuera de alcance (otros dominios / fase 2):**
- Generación del **XML firmado** desde cero: no se hace; se delega en el **PSE** vía `PsePort`
  (§4 maestro). El MVP integra el puerto con un **adapter stub/sandbox**; el PSE real (Nubefact/
  Bizlinks, credenciales) se cablea después **sin rediseñar** (decisión confirmada, §11).
- **Cola de contingencia offline / reintento de envío**: se deja como **costura** (el estado
  `GENERADO` local y el ciclo `sunatStatus` la habilitan); la cola/reintento real la construye el
  dominio transversal de **Sincronización** (PRD propio) — decisión confirmada (§11).
- **Billing propio del SaaS** (cómo se le cobra al negocio suscriptor): otro dominio (Backoffice),
  no confundir con facturar a los clientes del negocio.
- Retención/percepción, guías de remisión, notas de débito: no en el MVP (la separación
  «emitir comprobante numerado» deja la puerta abierta sin rediseño, §9.bis).

---

## 2. Ubicación en la arquitectura backend

Un módulo hexagonal nuevo **`billing`** en `alpaqa-pos-backend` (lineamientos §2.2), dominio rico:
el `Comprobante` es un **agregado** con invariantes fuertes (snapshot inmutable, correlativo sin
huecos por serie, ciclo `sunatStatus`) y la `ComprobanteSeries` guarda el **high-water mark** del
correlativo.

| Módulo | Estilo | Contenido |
|---|---|---|
| `billing` | **Hexagonal** | `ComprobanteSeries`, `Comprobante`, `ComprobanteItem`, `CreditNote`, `Customer` |

- **Consume** (por puerto, sin importar internals de otros módulos): `Money`, `Clock`,
  `IdGenerator` (shared kernel); **`PsePort`** (nuevo, obligatorio — envía a SUNAT vía PSE,
  intercambiable); `OrderReader` (nuevo — lee la `Order` **cerrada** con sus líneas snapshot e
  IGV, y su **liquidación** por Cobros, para construir el comprobante); `CashRegisterReader`
  (nuevo — valida la caja que ancla la serie); `PrinterPort` (existente — ticket térmico).
- **No escribe cross-context.** No muta `Order`, `Payment` ni el stock; el **reingreso a stock**
  de una devolución ya lo hace *Ventas* (SAL-06) — este dominio solo emite la **nota de crédito**.
- Estructura por módulo: `domain/` · `application/` · `infrastructure/`; dominio puro.

> Nombre de módulo (`billing`), prefijo de HU (`FAC`) y estrategia de PSE (puerto + stub)
> **confirmados** con el usuario; ver §11.

---

## 3. Modelo de datos

Todas las tablas son **tenant** (`companyId` + RLS en dos capas, invariante 4 / lineamientos
§2.4) y llevan `branchId` donde aplica. UUID de cliente en lo creable offline (`Comprobante`,
`CreditNote`) para idempotencia de sync (§6.C).

### 3.1 Series y correlativo

**`ComprobanteSeries`** (`@@map("comprobante_series")`) — serie de comprobante, **exclusiva de una caja**:
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId / branchId | uuid FK | tenant + sucursal |
| cashRegisterId | uuid FK → CashRegister | **ancla exclusiva** (§6.B); una serie ↔ una caja |
| type | enum `ComprobanteType` | BOLETA / FACTURA |
| series | text | "B001", "F001" (prefijo por tipo) |
| currentCorrelative | int | high-water mark del último correlativo emitido (recuperación) |
| active | boolean | borrado lógico |

- Unicidad: **`(cashRegisterId, type)`** (una serie por tipo por caja) **y** `(companyId, series)`
  (serie única en la empresa). La exclusividad serie↔caja es **regla de negocio crítica** (§6.B),
  no UI.

### 3.2 Comprobantes

**`Comprobante`** (`@@map("comprobante")`) — documento legal con **snapshot inmutable** (§6.D):
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId / branchId | uuid FK | tenant + sucursal |
| clientUuid | uuid | idempotencia offline (§6.C) |
| orderId | uuid FK → Order | la orden **cerrada y liquidada** que respalda |
| seriesId | uuid FK → ComprobanteSeries | |
| type | enum `ComprobanteType` | BOLETA / FACTURA |
| series | text | copia de la serie ("B001") |
| correlative | int | asignado **local al emitir**, sin huecos por serie |
| customerDocType | enum `DocumentType` | snapshot; SIN_DOCUMENTO para boleta sin DNI |
| customerDocNumber | text NULL | snapshot |
| customerName | text NULL | snapshot |
| subtotal / igv / otrosTributos / total | numeric(12,4) | `Money`; **otrosTributos** incluye ICBPER |
| sunatStatus | enum `SunatStatus` | GENERADO → ENVIADO → ACEPTADO / RECHAZADO / ANULADO |
| xml / cdr | text NULL | los devuelve el PSE al enviar (no se generan aquí) |
| deliveredTo | text NULL | correo/enlace al que se entregó (§4) |
| issuedAt | timestamp | `Clock`; momento de emisión |
| issuedById | uuid FK → User | auditoría |

- Unicidad: `(companyId, series, correlative)` (**sin huecos por serie**) y `(companyId, clientUuid)`
  (idempotencia). Índice `(orderId)`.
- **Inmutable tras emitir**: solo `sunatStatus`/`cdr`/`xml`/`deliveredTo` transicionan; los totales
  y datos del cliente **no cambian** (§6.D).

**`ComprobanteItem`** (`@@map("comprobante_item")`) — línea con **desglose de IGV** (snapshot):
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid FK | tenant |
| comprobanteId | uuid FK → Comprobante | |
| description | text | snapshot del nombre |
| quantity | numeric(14,4) | |
| unitPrice / lineSubtotal / lineIgv / lineTotal | numeric(12,4) | `Money`; desglose por línea (§8) |
| igvAffectation | enum `IgvAffectation` | gravado/exonerado/inafecto (snapshot del catálogo) |
| icbperAmount | numeric(12,4) NULL | ICBPER de la línea (bolsa), va a `otrosTributos` |

### 3.3 Notas de crédito

**`CreditNote`** (`@@map("credit_note")`) — rinde un número consumido (§6.B):
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId / branchId | uuid FK | tenant + sucursal |
| clientUuid | uuid | idempotencia offline |
| comprobanteId | uuid FK → Comprobante | el comprobante que modifica |
| reason | enum `CreditNoteReason` | ANULACION / DEVOLUCION / CORRECCION |
| series / correlative | text / int | su propia serie/correlativo (tipo nota de crédito) |
| sunatStatus | enum `SunatStatus` | mismo ciclo que el comprobante |
| xml / cdr | text NULL | del PSE |
| issuedAt / issuedById | timestamp / uuid | auditoría |

### 3.4 Clientes

**`Customer`** (`@@map("customer")`) — registro básico (§4 Clientes):
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| companyId | uuid FK | tenant |
| docType | enum `DocumentType` | DNI / RUC / CE / PASAPORTE |
| docNumber | text | |
| name | text | razón social / nombre |

- Unicidad: `(companyId, docType, docNumber)`.

### 3.5 Enums

`ComprobanteType {BOLETA, FACTURA}` ·
`SunatStatus {GENERADO, ENVIADO, ACEPTADO, RECHAZADO, ANULADO}` ·
`DocumentType {DNI, RUC, CE, PASAPORTE, SIN_DOCUMENTO}` ·
`CreditNoteReason {ANULACION, DEVOLUCION, CORRECCION}`.
`IgvAffectation` se reusa del catálogo (snapshot).

### 3.6 Índices clave

- `(cashRegisterId, type)` único en `ComprobanteSeries` (serie exclusiva por caja); `(companyId, series)` único.
- `(companyId, series, correlative)` único en `Comprobante` (sin huecos por serie); `(companyId, clientUuid)` único.
- `(orderId)` en `Comprobante`; `(comprobanteId)` en `CreditNote` y `ComprobanteItem`.
- `(companyId, docType, docNumber)` único en `Customer`.

---

## 4. Puertos y reglas de dominio

### 4.1 Puertos que este dominio usa/implementa (lineamientos §2.3)

| Puerto | Uso |
|---|---|
| **`Money`** | todo importe (subtotal, IGV, otros tributos, total, correlativos monetarios). Sin float. |
| **`Clock`** | `issuedAt` y transiciones de `sunatStatus` inyectables. |
| **`IdGenerator`** | UUID de `Comprobante`/`CreditNote` (creables offline, §6.C). |
| **`PsePort`** (nuevo, obligatorio) | envía el comprobante/nota al **PSE** y devuelve `cdr`/estado. **Intercambiable** (Nubefact/Bizlinks). MVP: **adapter stub/sandbox** que simula el ciclo; el real se cablea después (§11). No se genera XML firmado propio. |
| **`OrderReader`** (nuevo) | lee la `Order` **cerrada** (líneas snapshot, IGV, totales) y su **liquidación** (por Cobros) para construir el comprobante. Cross-context de **solo lectura** confinado a infraestructura (patrón `SalesReader` de PAY-03). |
| **`CashRegisterReader`** (nuevo) | valida la caja que ancla la serie (existe/activa). Solo lectura. |
| **`PrinterPort`** (existente) | ticket térmico del comprobante; adapter ESC/POS stub, **nunca tumba** la emisión si el hardware falla (patrón SAL-09/PAY-06). |

### 4.2 Invariantes del dominio

1. **Serie exclusiva por caja** (§6.B): una `ComprobanteSeries` pertenece a una sola `CashRegister`
   por tipo (único `(cashRegisterId, type)`). No se comparte espacio de numeración entre cajas.
2. **Correlativo sin huecos por serie, asignado local al emitir** (§6.B): al emitir se toma
   `currentCorrelative + 1` de la serie de forma **atómica** (transacción + bloqueo de fila);
   el número se imprime al instante. No hay coordinación entre cajas.
3. **Todo número consumido se rinde** (§6.B): anular un comprobante emitido → **nota de crédito**;
   el número queda quemado, **nunca se reusa ni se salta**. Un `RECHAZADO` se corrige y reenvía o
   se da de baja; el número no desaparece.
4. **Solo se emite de una `Order` `CLOSED` y liquidada** (`outstanding ≤ 0`, leído por `OrderReader`):
   una orden abierta o con saldo pendiente → 409. El comprobante **no muta** la orden.
5. **Snapshot inmutable** (§6.D): el comprobante copia totales, desglose de IGV, ICBPER y datos del
   cliente al emitir; tras emitir, solo `sunatStatus`/`cdr`/`xml`/`deliveredTo` cambian.
6. **Desglose de IGV por línea** (§8): cada `ComprobanteItem` lleva su `lineIgv` según
   `igvAffectation` (snapshot). En **Nuevo RUS** no se desglosa en el documento, pero el dato se
   **guarda** para reportes internos (flag de régimen de la empresa).
7. **ICBPER en otros tributos** (§4): el producto "bolsa" marcado afecto a ICBPER (catálogo) suma
   `icbperAmount` por línea, consolidado en `Comprobante.otrosTributos`. No aplica a negocios solo
   exonerados del IGV.
8. **Datos del cliente según tipo** (§8): **factura → RUC obligatorio**; **boleta → DNI opcional**
   (SIN_DOCUMENTO permitido). Validado al emitir.
9. **Ciclo `sunatStatus`** (§6): `GENERADO` (local, puede ser offline) → `ENVIADO` → `ACEPTADO` /
   `RECHAZADO`; `ANULADO` vía baja. Las transiciones son **monótonas** salvo corrección de rechazo.
10. **Dinero vía `Money`, nunca float.** **Multi-tenancy en dos capas** (filtro + RLS) incluido el
    scoping por `branchId`; escrituras tenant-scoped (`updateMany`).

### 4.3 Relación con otros dominios (costuras — se **respetan**, no se implementan aquí)

- **Cobros y caja:** la `CashRegister` es el **ancla de serie** (PAY-01 la dejó lista); Facturación
  crea `ComprobanteSeries` sobre ella. Lee la liquidación de la orden (por `OrderReader`), no toca
  `Payment`/`CashShift`.
- **Ventas:** consume la `Order` `CLOSED` (solo lectura) con sus líneas snapshot e IGV. La
  **devolución con reingreso a stock** ya la hizo *Ventas* (SAL-06); aquí solo se emite la **nota
  de crédito** que la respalda.
- **Catálogo:** la afectación de IGV y el flag ICBPER del producto ya viven en catálogo (ALPQ-6);
  llegan al comprobante **por snapshot** vía la orden, no se releen.
- **Sincronización (transversal):** el estado `GENERADO` offline + `sunatStatus` dejan la costura
  para la **cola de contingencia**; la construye ese dominio (§11).
- **Auditoría (transversal):** emisión, anulación y rechazos son focos de auditoría; se registran
  con `Clock`/usuario desde el día uno.

---

## 5. Contrato de API (REST + OpenAPI, lineamientos §2.1/§5)

Recursos bajo el tenant autenticado (JWT + RBAC). DTOs con class-validator en el borde.

- **Series (setup)** — `GET/POST /comprobante-series`, `PATCH /comprobante-series/:id`
  (activar/desactivar). Asignar la serie a una caja = **setup del negocio** →
  `gestionar_configuracion`.
- **Clientes** — `GET /customers?doc=`, `POST /customers` (alta rápida al cobrar). Permiso `cobrar`
  o `vender` (captura en el flujo POS).
- **Emitir comprobante** — `POST /orders/:id/comprobante` (`{ type, customerId? | customerDoc? }`;
  exige orden `CLOSED` + liquidada; asigna correlativo local). Permiso nuevo `emitir_comprobante`.
- **Envío a SUNAT** — `POST /comprobantes/:id/send` (encola/llama `PsePort`; transiciona
  `sunatStatus`). Permiso `emitir_comprobante`. (En MVP el stub responde ACEPTADO/RECHAZADO.)
- **Consulta** — `GET /comprobantes/:id`, `GET /comprobantes?orderId=` (con estado y desglose).
- **Nota de crédito** — `POST /comprobantes/:id/credit-notes` (`{ reason }`). Permiso
  `emitir_comprobante` (o `anular_venta` para ANULACION; ver §11).
- **Entrega** — `POST /comprobantes/:id/deliver` (`{ email }`), `GET /comprobantes/:id/pdf` /
  `/xml`. Permiso `cobrar`/`emitir_comprobante`.

**Permisos RBAC nuevos:** `emitir_comprobante` (emitir/enviar/nota de crédito). Setup de series
reusa `gestionar_configuracion`; captura de cliente reusa `cobrar`/`vender`. Impresión vía
`PrinterPort`.

---

## 6. Decisiones de diseño del dominio

- **No se genera XML firmado propio:** se delega en el **PSE** vía `PsePort` (§4). El MVP usa un
  **adapter stub/sandbox** que simula el ciclo `sunatStatus`; el PSE real (Nubefact/Bizlinks) es
  intercambiable y se cablea después sin rediseñar (§11).
- **Correlativo local, sin huecos por serie:** se asigna en la transacción de emisión con bloqueo
  de la fila de la serie (`currentCorrelative++`). Como cada serie vive en una caja, es secuencial
  por construcción, incluso offline por días (§6.B).
- **Emitir es un acto separado de cobrar:** el comprobante se emite **después** del cobro, sobre una
  orden liquidada. Evita acoplar la numeración fiscal con el flujo de caja (§9.bis).
- **Snapshot en el comprobante:** documento legal inmutable; no recalcula leyendo la orden (§6.D).
- **Nota de crédito rinde el número:** anular no borra ni reusa el correlativo; lo respalda una NC.
- **Contingencia offline como costura:** `GENERADO` + `sunatStatus` habilitan la cola; la construye
  *Sincronización* (§11). Facturación no implementa reintentos/colas ahora.

---

## 7. Costuras dejadas abiertas (diseñar ahora, construir después — §9.bis)

- **PSE real:** `PsePort` intercambiable ya define el contrato; el adapter Nubefact/Bizlinks se
  cablea cuando haya credenciales (§11). El stub cierra el flujo end-to-end del MVP.
- **Cola de contingencia / reintento de envío:** el estado `GENERADO` local y `sunatStatus` la
  dejan lista; la construye *Sincronización* (PRD propio).
- **Otros documentos** (notas de débito, guías de remisión, retención/percepción): la separación
  «emitir comprobante numerado» + el ciclo `sunatStatus` los admiten sin rediseño (fase 2).
- **Sincronización offline** de comprobantes/notas: `clientUuid` + idempotencia listos.

---

## 8. Decisiones del dominio cerradas

- Módulo hexagonal **`billing`**, prefijo de HU **`FAC`**, físico inglés `snake_case`.
- **`PsePort` obligatorio** + **adapter stub/sandbox** en el MVP; PSE real diferido e intercambiable.
- **Serie exclusiva por caja**, **correlativo sin huecos por serie** asignado **local al emitir**.
- **Snapshot inmutable** en el comprobante; solo transiciona `sunatStatus`/`cdr`/`xml`/`deliveredTo`.
- Se emite solo de **orden `CLOSED` + liquidada**; el comprobante **no muta** la orden.
- **Nota de crédito** para anulación/devolución/corrección; el número **se rinde**, nunca se reusa.
- **Contingencia offline = costura** (la construye *Sincronización*).
- Reusa `Money`/`Clock`/`IdGenerator`/`PrinterPort`; puertos nuevos `PsePort`/`OrderReader`/
  `CashRegisterReader`.

---

## 9. Mapa HU → entregable técnico

| HU (código) | Entregable principal |
|---|---|
| `FAC-01` | `ComprobanteSeries` (setup + **asignación exclusiva a una caja**; tipos boleta/factura; `currentCorrelative`; `gestionar_configuracion`) |
| `FAC-02` | `Customer` (registro básico tipo/nº doc, nombre; captura al cobrar; boleta DNI opcional / factura RUC obligatorio) |
| `FAC-03` | **Emitir `Comprobante`** desde orden cerrada+liquidada: snapshot de totales/IGV/cliente, **correlativo local sin huecos**, desglose IGV por línea, ICBPER; `emitir_comprobante` |
| `FAC-04` | **Envío a SUNAT** vía `PsePort` (stub) + ciclo `sunatStatus` (contingencia = costura) |
| `FAC-05` | `CreditNote` (anulación / devolución / corrección) — rinde el número consumido |
| `FAC-06` | **Entrega** del comprobante (PDF/XML por correo/enlace) + ticket (`PrinterPort`) |

> Códigos `FAC-0x` = etiqueta de orden que reinicia por segmento; el id/referencia de cada HU es
> su clave Jira `ALPQ-N` (se asigna al crear la épica).

---

## 10. Prerrequisitos y orden de implementación

**Prerrequisito duro (ya cumplido):** *Ventas* (la `Order` cierra con snapshot, SAL-05) y *Cobros y
caja* (la orden se liquida y la `CashRegister` es ancla de serie, PAY-01..06) completos; núcleo
tenant con RLS; shared kernel (`Money`/`Clock`/`IdGenerator`/`PrinterPort`); afectación IGV/ICBPER
en catálogo (ALPQ-6).

**Orden sugerido (serie primero, emisión después):**
`FAC-01` (serie sobre la caja) → `FAC-02` (cliente) → `FAC-03` (emitir con correlativo+snapshot) →
`FAC-04` (envío PSE + estado) → `FAC-05` (nota de crédito) → `FAC-06` (entrega + ticket). Cada HU con
el ritual de cierre (auditoría `audit-plan` + `audit-arquitectura` → suites vía `test-runner` →
commit sin coautoría → push → mover el ticket en Jira).

---

## 11. Decisiones confirmadas con el usuario

1. **Módulo `billing`, prefijo `FAC`**, físico inglés `snake_case`.
2. **PSE = `PsePort` + adapter stub/sandbox** en el MVP; la integración real (Nubefact/Bizlinks,
   credenciales) se cablea después sin rediseñar. No se genera XML firmado propio.
3. **Cola de contingencia offline = costura:** el estado `GENERADO` + el ciclo `sunatStatus` quedan
   listos; la cola/reintento la construye el dominio **Sincronización** (PRD propio), no Facturación.
4. Pendiente de decisión al llegar a la HU: el **permiso** exacto de la nota de crédito por anulación
   (`emitir_comprobante` vs `anular_venta`), y la elección concreta del **PSE** para el adapter real.
