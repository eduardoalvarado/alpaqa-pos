# PRD de dominio — Catálogo e inventario

> **Fecha:** 2026-07-21 · **Estado:** borrador para revisión · **Dominio:** Catálogo e inventario
>
> PRD de dominio generado **just-in-time** antes de implementar (PRD maestro §10). Traduce las
> HUs (`docs/hus/epica-catalogo-e-inventario.md`, cargadas a Jira KAN-1..KAN-14 — Jira es la
> fuente de verdad del backlog) en el **diseño técnico** del dominio: modelo de datos, módulos,
> puertos, contrato de API e invariantes.
>
> **Este documento referencia, no repite, las decisiones transversales.** Fuentes:
> - PRD maestro (`docs/alcance-mvp-pos.md`): §4 (Catálogo, Inventario), §4.bis (código de
>   barras, venta por peso), §5 (modelo de datos), §6.A (snapshot), §7 (ejes ortogonales),
>   §9.bis (costuras), §11 (pendientes).
> - Lineamientos técnicos (`docs/lineamientos-tecnicos.md`): §2.2 (hexagonal), §2.3 (puertos
>   `PriceResolver`, `Money`, `Clock`, `IdGenerator`), §2.4 (multi-tenancy RLS), §2.5
>   (invariantes del cimiento).

---

## 1. Propósito y alcance del dominio

Modelar el **catálogo** (categorías, productos, variantes con SKU, modificadores, atributos,
tributación, unidad de medida) y el **control de stock por sucursal** (existencias,
movimientos con motivo, alertas de mínimo), dejando **abiertas las costuras** de combos/BOM y
resolución de precio sin construirlas.

**Dentro** (13 HUs): CAT-01..09 (catálogo), INV-10..12 (inventario), CAT-13 (costura BOM).
Detalle y criterios de aceptación en el archivo de HUs; aquí no se repiten.

**Fuera (referenciado, otros dominios):**
- **Consumo** del catálogo en la venta (snapshot en `OrdenItem`, comanda por
  `requiere_preparacion`, descuento de stock por venta/devolución) → dominio **Ventas y
  operación** y **Facturación**. Este dominio **define** los campos; otros los **consumen**.
- **Empresa, sucursal, usuario, rol** → dominio **Plataforma y administración** (Épica 0). Son
  **prerrequisito** de este dominio (tenancy y scoping por sucursal).
- Importación masiva CSV, balanza integrada, lectura de código por cámara, lógica de combos →
  **fase 2** (costuras previstas más abajo).

---

## 2. Ubicación en la arquitectura backend

Dos bounded contexts en `alpaqa-pos-backend`, siguiendo lineamientos §2.2:

| Módulo | Estilo | Contenido |
|---|---|---|
| `catalogo` | **Hexagonal** (dominio rico: SKU, variantes, resolución de precio) | `Categoria`, `Producto`, `Variante`, ejes, `GrupoModificador`/`Modificador`, `ComponenteProducto` (costura BOM) |
| `inventario` | **Hexagonal** (movimiento + stock transaccional) | `Stock`, `MovimientoInventario`, alertas de mínimo |

- **Categorías** y **modificadores** son sub-áreas más CRUD; viven dentro de `catalogo` sin
  ceremonia hexagonal completa (CRUD ligero, lineamientos §2.2), pero **producto/variante/SKU
  y toda lectura de precio** sí pasan por dominio puro + puertos.
- **`Producto`/`Variante` son la raíz de agregado** del catálogo: la creación de un producto y
  su variante por defecto es **transaccional** (una unidad).
- **`inventario` es hexagonal** porque el par *«registrar movimiento + actualizar stock»* es
  una invariante transaccional y es una fuente de datos ricos para IA (§9.bis).

Estructura por módulo: `domain/` (entidades, VOs, puertos) · `application/` (casos de uso) ·
`infrastructure/` (repos Prisma, controllers). El dominio no importa Prisma/Nest (lineamientos §2.2).

---

## 3. Modelo de datos

Aterriza PRD §5 a columnas concretas para el esquema Prisma. **Toda tabla lleva `empresa_id`**
(multi-tenancy, PRD §3) con **filtro Prisma automático + RLS Postgres** (lineamientos §2.4).
`created_at`/`updated_at` en todas; se omiten abajo por brevedad. Dinero en `numeric`, nunca
float (lineamientos §2.1); cantidades de stock en `numeric` decimal.

### 3.1 Catálogo

**`Categoria`**
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| empresa_id | uuid FK | tenant |
| nombre | text | |
| activo | boolean | **borrado lógico** (no romper productos) |

- Unicidad: `(empresa_id, nombre)` **global (incluye desactivadas)**. Al intentar crear una que
  existe desactivada, se ofrece **reactivarla** (evita duplicados fantasma). Desactivar no
  borra; productos existentes conservan la FK.

**`Producto`**
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| empresa_id | uuid FK | tenant |
| categoria_id | uuid FK → Categoria | |
| nombre | text | |
| precio_base | numeric(12,4) | precio del producto simple; las variantes pueden sobreescribir. **Nunca se lee crudo: vía `PriceResolver`** |
| tipo_afectacion_igv | enum `TipoAfectacionIgv` | `GRAVADO` \| `EXONERADO` \| `INAFECTO` |
| afecto_icbper | boolean | bolsas plásticas |
| unidad_medida | enum `UnidadMedida` | `UNIDAD, KG, G, L, ML, M`… |
| permite_cantidad_fraccionada | boolean | propaga a `Stock` y (contrato) a `OrdenItem` |
| requiere_preparacion | boolean | lo consume **Ventas** (comanda) |
| controla_inventario | boolean | lo consume **Inventario** (descuento/exigencia de stock) |
| atributos_opcionales | jsonb | descriptivos flexibles (peso, medidas, material, marca). **JSON flexible**, decisión MVP (PRD §11) |
| activo | boolean | borrado lógico |

**`Variante`** — todo producto tiene ≥1; SKU, código de barras y stock cuelgan de aquí (PRD §4/§5).
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| empresa_id | uuid FK | tenant |
| producto_id | uuid FK → Producto | |
| es_default | boolean | `true` = variante por defecto de un producto simple |
| sku | text | **único por empresa** (`(empresa_id, sku)`) |
| codigo_barra | text NULL | único por empresa cuando presente (`(empresa_id, codigo_barra)` parcial) |
| precio | numeric(12,4) NULL | override; `NULL` ⇒ hereda `Producto.precio_base`. **Lectura vía `PriceResolver`** |
| activo | boolean | borrado lógico |

**Ejes de variante** (definición para generar combinaciones — HU-CAT-03):
- **`EjeVariante`**: id, producto_id, nombre (`Talla`), orden.
- **`ValorEje`**: id, eje_id FK, valor (`S`), orden.
- **`VarianteValor`** (puente): variante_id FK, valor_eje_id FK. La combinación de valores de
  una variante es única por producto.
- Decisión de modelado (PRD §5): **ejes = unidades de stock distintas** → normalizados y con
  integridad referencial (querables, «datos ricos» §9.bis). Los **descriptivos** van en
  `Producto.atributos_opcionales` (JSON) y **no** generan variantes.

**Modificadores** (restaurante — HU-CAT-07):
- **`GrupoModificador`**: id, empresa_id, producto_id FK, nombre, `seleccion_min` int,
  `seleccion_max` int (`NULL` = ilimitado), obligatorio boolean, orden, activo.
  Obligatorio + única = `min=1, max=1`.
- **`Modificador`**: id, grupo_id FK, nombre, `precio_delta` numeric(12,4) (vía `Money`),
  activo, orden.

**Costura BOM/combos** (HU-CAT-13 — solo modelo, sin lógica):
- **`ComponenteProducto`**: id, empresa_id, producto_padre_id FK, componente_variante_id FK,
  cantidad numeric(14,4). **Vacía por defecto** ⇒ producto atómico. Sin endpoints ni expansión
  de precio/stock en el MVP (PRD §9.bis). Es *no cerrar la puerta*.

### 3.2 Inventario

**`Stock`** (existencia actual, autoritativa por variante+sucursal):
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| empresa_id | uuid FK | tenant |
| variante_id | uuid FK → Variante | |
| sucursal_id | uuid FK → Sucursal | scoping por sucursal (PRD §5) |
| cantidad | numeric(14,4) | decimal según unidad de medida |
| stock_minimo | numeric(14,4) NULL | umbral de alerta (HU-INV-12) |

- Unicidad: `(variante_id, sucursal_id)`. Variantes de productos con
  `controla_inventario=false` **no exigen** fila de stock.

**`MovimientoInventario`** (libro de auditoría append-only — fuente de datos ricos §9.bis):
| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | UUID (compatible con sync, lineamientos §2.5 / `IdGenerator`) |
| empresa_id | uuid FK | tenant |
| variante_id | uuid FK | |
| sucursal_id | uuid FK | |
| tipo | enum `TipoMovimiento` | `VENTA \| COMPRA \| AJUSTE \| DEVOLUCION` |
| cantidad | numeric(14,4) | con signo (o `sentido` +/−); + entra, − sale |
| motivo | text | **obligatorio** (rechazo si falta — HU-INV-11) |
| referencia_tipo | text NULL | `ORDEN` \| `NOTA_CREDITO` (para movimientos de otros dominios) |
| referencia_id | uuid NULL | |
| usuario_id | uuid FK | quién lo registró |

- **Invariante transaccional:** registrar un movimiento y actualizar `Stock.cantidad` ocurren
  en **una sola transacción**. `Stock.cantidad` es el valor vigente; los movimientos son el
  ledger reconstruible.
- Este dominio **expone solo** `AJUSTE` y `COMPRA` manual (HU-INV-11). `VENTA` y `DEVOLUCION`
  los generan **Ventas/Facturación** escribiendo en esta misma tabla (costura ya prevista).

### 3.3 Enums

`TipoAfectacionIgv {GRAVADO, EXONERADO, INAFECTO}` · `UnidadMedida {UNIDAD, KG, G, L, ML, M}`
(**enum fijo en MVP**; sin unidades personalizadas por empresa — se amplía con migración si
falta alguna, preservando consistencia para reportes/IA) · `TipoMovimiento {VENTA, COMPRA, AJUSTE, DEVOLUCION}`.

### 3.4 Índices clave

- `(empresa_id, sku)` único; `(empresa_id, codigo_barra)` único parcial (lookup del POS, §4.bis).
- `(variante_id, sucursal_id)` único en `Stock`.
- `(empresa_id, categoria_id)`, `(producto_id)` en `Variante` para listados.
- `(empresa_id, sucursal_id, variante_id, created_at)` en `MovimientoInventario` (historial/IA).

---

## 4. Puertos y reglas de dominio

### 4.1 Puertos que este dominio **implementa/toca** (lineamientos §2.3)

| Puerto | Uso en este dominio |
|---|---|
| **`PriceResolver`** | **Único punto de lectura de precio.** Firma: `resolver(variante, contexto) → Money`. En el MVP resuelve `Variante.precio ?? Producto.precio_base`. El `contexto` (fecha/hora, lista, cantidad) queda en la firma para precios por horario/listas en fase 2 **sin cambiar los llamadores** (§9.bis). Ningún caso de uso lee el campo crudo. |
| **`Money`** | Todo importe (precio, `precio_delta`, cálculo peso×precio) se construye/opera con `Money`. Sin float. |
| **`Clock`** | Timestamps de movimientos inyectables (testabilidad + datos ricos). |
| **`IdGenerator`** | UUID de `MovimientoInventario` (compatibilidad con sync). |

### 4.2 Invariantes del dominio

1. **Todo producto tiene ≥1 variante.** Crear producto simple crea, transaccionalmente, la
   variante `es_default=true` con su SKU (HU-CAT-02).
2. **SKU único por empresa**, editable mientras la variante no tenga movimientos;
   **inmutable una vez con historial** (protege trazabilidad de inventario/ventas e importación
   CSV, que usa `(empresa_id, sku)` como llave).
3. **Precio nunca se lee crudo** — siempre vía `PriceResolver`.
4. **Motivo obligatorio** en todo `MovimientoInventario`.
5. **Movimiento + stock = una transacción.**
6. **Borrado lógico** en catálogo (categoría/producto/variante/modificador): nunca se borra
   físico para no romper referencias de snapshots pasados (PRD §6.A).
7. **Aislamiento por tenant** en dos capas (filtro Prisma + RLS), incluido el scoping por
   `sucursal_id` en `Stock`/movimientos.

### 4.3 Relación con el snapshot de venta (PRD §6.A — se **respeta**, no se implementa aquí)

`OrdenItem` copiará (nombre, precio, unidad, `tipo_afectacion_igv`) al vender. Este dominio
garantiza que esos campos existan y sean estables; **no** los lee vivos en la venta. La
edición de catálogo no altera comprobantes ya emitidos.

---

## 5. Contrato de API (REST + OpenAPI, lineamientos §2.1/§5)

Recursos bajo el tenant autenticado (JWT + RBAC). Alto nivel; el detalle de DTOs se define con
`class-validator` en el borde.

- **Categorías** — `GET/POST /categorias`, `PATCH /categorias/:id`, desactivar (soft).
- **Productos** — `GET/POST /productos`, `GET/PATCH /productos/:id`. POST de producto simple
  crea variante por defecto (transaccional). Sub-recursos: `atributos`, flags, afectación IGV.
- **Variantes / ejes** — `POST /productos/:id/ejes` (define ejes+valores),
  `POST /productos/:id/variantes:generar` (propone combinaciones), `PATCH /variantes/:id`
  (SKU, código, precio, activo).
- **Búsqueda por código** — `GET /variantes/buscar?codigo=` → resuelve por `codigo_barra`;
  «no encontrado» sin error de sistema (HU-CAT-08). Contrato **agnóstico a plataforma** (el POS
  captura con lector HID; cámara = costura fase 2).
- **Modificadores** — `GET/POST /productos/:id/grupos-modificadores` y modificadores anidados.
- **Stock** — `GET /stock?sucursal_id=` (existencias por variante), `GET /stock/alertas?sucursal_id=`
  (bajo mínimo, señal consultable; push = fuera de MVP).
- **Movimientos** — `POST /inventario/movimientos` (ajuste/compra con motivo, transaccional),
  `GET /inventario/movimientos?variante_id=` (historial).

Superficie: todo lo de escritura vive en **Gestión** (RBAC dueño/admin). El **POS** solo
**consume** (búsqueda por código, lectura de catálogo/precio vía `PriceResolver`).

---

## 6. Decisiones de diseño del dominio

- **Variante por defecto explícita** (`es_default`), no implícita: el form «producto simple»
  oculta la complejidad; el modelo siempre tiene la variante como raíz de SKU/stock.
- **SKU autogenerado por secuencia por empresa** (correlativo, p. ej. `SKU-000123`), editable
  al crear para evitar fricción; unicidad por empresa validada en el borde y en BD. **Inmutable
  una vez que la variante tiene movimientos** (ver invariante §4.2.2).
- **Ejes normalizados** (no JSON) por integridad y querabilidad; **descriptivos en JSON** por
  flexibilidad. Es la línea que traza PRD §5.
- **`Stock.cantidad` autoritativo + ledger de movimientos**: no se recalcula el stock leyendo
  todo el ledger en caliente; el ledger es para auditoría/IA y reconstrucción.
- **Alerta de mínimo = consulta derivada** (`cantidad < stock_minimo`), no entidad ni job en
  el MVP.
- **Movimientos de venta/devolución = misma tabla, otros productores**: este dominio no los
  emite, pero deja el contrato (`referencia_tipo/id`) listo.

---

## 7. Costuras dejadas abiertas (diseñar ahora, construir en fase 2 — §9.bis)

- **Combos/BOM** → `ComponenteProducto` vacía; sin lógica.
- **Precios por horario / listas** → todo pasa por `PriceResolver`; agregar reglas será un
  módulo, no cirugía.
- **Multi-moneda** → todo importe vía `Money`.
- **Balanza integrada + código de peso variable (EAN-13 prefijo 2)** → `unidad_medida` +
  `permite_cantidad_fraccionada` ya en el modelo; el parseo/hardware se apoya en el servicio de
  captura de código previsto, no toca el cimiento.
- **Importación masiva CSV** → los endpoints de alta idempotentes por `(empresa_id, sku)`
  facilitan un importador posterior.

---

## 8. Decisiones del dominio cerradas (2026-07-21)

| Tema | Decisión |
|---|---|
| **Mutabilidad del SKU** | **Editable mientras no haya movimientos; inmutable con historial.** Protege trazabilidad e importación CSV (llave `(empresa_id, sku)`). |
| **Escala de `numeric`** | **`numeric(12,4)`** para precio unitario e importes (soporta precio por unidad de medida en venta por peso). |
| **Unicidad de nombre de categoría** | **`(empresa_id, nombre)` global** (incluye desactivadas); si existe desactivada, se **reactiva** en vez de duplicar. |
| **Autogeneración de SKU** | **Secuencia por empresa** (correlativo tipo `SKU-000123`), editable al crear; sin colisiones ni normalización de texto. |
| **`UnidadMedida`** | **Enum fijo en MVP** (`UNIDAD, KG, G, L, ML, M`); sin unidades personalizadas por empresa. Se amplía con migración. |

No quedan pendientes de decisión abiertos en este dominio.

---

## 9. Mapa HU → entregable técnico

| HU | Entregable técnico principal |
|---|---|
| CAT-01 | `Categoria` + CRUD + unicidad + soft delete |
| CAT-02 | `Producto` + creación transaccional de `Variante` `es_default`; SKU único; `PriceResolver`/`Money` |
| CAT-03 | `EjeVariante`/`ValorEje`/`VarianteValor`; generación de combinaciones; SKU/precio/código por variante |
| CAT-04 | `Producto.atributos_opcionales` (jsonb) |
| CAT-05 | `tipo_afectacion_igv`, `afecto_icbper` (snapshot en venta, no cálculo aquí) |
| CAT-06 | `unidad_medida`, `permite_cantidad_fraccionada`; cálculo peso×precio vía `Money` |
| CAT-07 | `GrupoModificador`/`Modificador` (min/max/obligatorio) |
| CAT-08 | `codigo_barra` + `GET /variantes/buscar`; índice de lookup |
| CAT-09 | flags `requiere_preparacion`, `controla_inventario` (los consumen otros dominios) |
| INV-10 | `Stock` + consulta por sucursal |
| INV-11 | `MovimientoInventario` (ajuste/compra, motivo obligatorio) + update transaccional |
| INV-12 | `stock_minimo` + consulta de alertas |
| CAT-13 | `ComponenteProducto` (costura, sin lógica) |

---

## 10. Prerrequisitos y orden de implementación

**Prerrequisito duro:** cimiento del backend (init NestJS, estructura hexagonal, Prisma +
Postgres, y **núcleo de tenancy**: `Empresa`, `Sucursal`, `Usuario`, `Rol` + `empresa_id`/RLS).
Este dominio **cuelga** de ese núcleo (Épica 0 / Plataforma). No se implementa Catálogo sin él.

Orden sugerido (del archivo de HUs): CAT-01→02 (cimiento del catálogo) → CAT-05/06/09 (campos
del producto, baratos y de alto valor) → CAT-03/04 (variantes por ejes y descriptivos) →
CAT-08 (código de barras, habilita POS) → INV-10→11→12 (stock y movimientos) → CAT-07
(modificadores, si el piloto es restaurante) → CAT-13 (costura BOM, junto con CAT-02).
