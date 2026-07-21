# Épica: Catálogo e inventario — Historias de Usuario

> **Staging para Jira.** Este documento es el backlog de HUs de la épica, redactado en el
> hub para revisión versionada. Una vez cargado a Jira, **Jira es la fuente de verdad** y
> este archivo queda como snapshot de referencia. **No es el PRD de dominio** (ese se genera
> just-in-time antes de implementar, PRD §10).
>
> Referencias PRD maestro (`docs/alcance-mvp-pos.md`): §4 (Catálogo, Inventario), §4.bis
> (código de barras, venta por peso), §5 (modelo de datos), §6.A (snapshot), §9.bis (costuras:
> combos/BOM, resolución de precio). Lineamientos: `docs/lineamientos-tecnicos.md`
> (puertos `PriceResolver`, `Money`; monolito modular + hexagonal).

## Objetivo de la épica

Que un negocio pueda **modelar su catálogo** (categorías, productos, variantes con SKU,
modificadores, atributos, IGV, unidad de medida) y **controlar su stock por sucursal**
(existencias, movimientos con motivo, alertas de mínimo), dejando **abiertas las costuras**
de combos/BOM y resolución de precio sin construirlas aún.

## Alcance / No-alcance

**Dentro:** categorías, productos, variante-por-defecto y variantes por ejes (SKU único por
empresa), atributos descriptivos opcionales, flags (`requiere_preparacion`,
`controla_inventario`), `tipo_afectacion_igv`, `afecto_icbper`, unidad de medida y cantidad
fraccionada, grupos de modificadores, código de barras + búsqueda, stock por sucursal,
movimientos de inventario con motivo, alertas de stock mínimo.

**Fuera (referenciado, otra épica):** reingreso a stock por devolución (Ventas/Facturación),
consumo de catálogo en el flujo de venta (Ventas core), importación masiva CSV (fase 2),
balanza integrada y código de peso variable (fase 2, costura ya prevista), lógica de combos
(fase 2 — aquí solo se deja el hueco de modelo).

## Convenciones de las HU

Cada HU es **vertical** (una unidad de valor) con **notas por repo**:
- **Backend** (`alpaqa-pos-backend`): contrato/endpoint, reglas de dominio, puertos.
- **Frontend** (`alpaqa-pos-frontend`): superficie/app y pantalla afectada.
Salvo indicación, la superficie es **Gestión** (2.2). El POS (2.3) solo **consume** catálogo.

## Decisiones transversales que aplican (referenciar, no repetir)

- **SKU único por empresa**, vive en `Variante`. Todo producto tiene ≥1 variante (por defecto
  si no tiene variaciones reales). SKU, `codigo_barra` y `Stock` cuelgan de la variante. (PRD §4, §5)
- **Toda lectura de precio pasa por `PriceResolver`** — nunca leer el campo crudo disperso.
  Costura de precios por horario/listas. (PRD §9.bis; lineamientos)
- **Manejo de dinero centralizado** vía tipo/utilidad `Money`. (PRD §9.bis; lineamientos)
- **Composición/BOM opcional** en el modelo de producto (puerta a combos); sin lógica aún. (PRD §9.bis)
- **Multi-tenant**: `empresa_id` en toda tabla; filtro Prisma + RLS Postgres. (PRD §3)
- **Datos ricos desde el día uno** (categorías consistentes, motivos en movimientos) para IA fase 2. (PRD §9.bis)

---

## HU-CAT-01 — Gestionar categorías

**Como** dueño/administrador **quiero** crear, editar y desactivar categorías **para**
organizar mi catálogo.

**Criterios de aceptación**
```gherkin
Escenario: Crear categoría
  Dado que estoy autenticado como dueño de la empresa
  Cuando creo una categoría con nombre "Bebidas"
  Entonces la categoría queda asociada a mi empresa_id
  Y aparece disponible para asignar a productos

Escenario: Nombre de categoría único por empresa
  Dado que ya existe la categoría "Bebidas" en mi empresa
  Cuando intento crear otra categoría "Bebidas"
  Entonces el sistema rechaza la creación con un error de duplicado

Escenario: Desactivar categoría con productos
  Dado que la categoría "Bebidas" tiene productos asociados
  Cuando la desactivo
  Entonces la categoría deja de ofrecerse para nuevos productos
  Y los productos existentes conservan su referencia
```

**Backend** — `Categoria` (empresa_id, nombre, activo). Endpoints CRUD; unicidad de nombre
por `empresa_id`; borrado lógico (no romper productos). RBAC: dueño/admin.
**Frontend** — Gestión: pantalla lista + form de categorías. Mobile responsive (tabla densa
pensada para móvil, PRD §2.2).
**Dependencias** — Épica 0 (auth/empresa/roles).
**Ref PRD** — §4 Catálogo, §5 `Categoria`.

---

## HU-CAT-02 — Crear producto simple (con variante por defecto)

**Como** dueño **quiero** dar de alta un producto sin variaciones **para** empezar a
venderlo, sin lidiar con complejidad de variantes.

**Criterios de aceptación**
```gherkin
Escenario: Alta de producto simple
  Dado que existe la categoría "Bebidas"
  Cuando creo el producto "Agua 625ml" con precio 2.00 en "Bebidas"
  Entonces el sistema crea automáticamente una variante por defecto
  Y esa variante recibe un SKU único dentro de mi empresa
  Y el stock y el código de barras cuelgan de esa variante

Escenario: SKU único por empresa
  Dado que la variante por defecto tomó el SKU "AGUA-625"
  Cuando intento asignar "AGUA-625" a otra variante de mi empresa
  Entonces el sistema rechaza el SKU duplicado
```

**Backend** — `Producto` (empresa_id, categoria_id, nombre, precio base, unidad_medida…) +
creación transaccional de `Variante` por defecto con SKU. Unicidad SKU por empresa. Precio
se escribe crudo pero **toda lectura pasa por `PriceResolver`**. Dinero vía `Money`.
**Frontend** — Gestión: form "producto simple" que oculta la complejidad de variantes.
**Dependencias** — HU-CAT-01.
**Ref PRD** — §4 (variante por defecto), §5 `Producto`/`Variante`, §6.A (snapshot en venta),
§9.bis (PriceResolver, Money), §11 (patrón variante-por-defecto).

---

## HU-CAT-03 — Producto con variantes por ejes (talla/color → múltiples SKU)

**Como** dueño de tienda **quiero** definir ejes de variante (talla, color) **para** que cada
combinación sea una unidad de stock con su propio SKU y código de barras.

**Criterios de aceptación**
```gherkin
Escenario: Generar variantes por combinación de ejes
  Dado el producto "Polo básico"
  Cuando defino el eje Talla=[S,M,L] y el eje Color=[Rojo,Azul]
  Entonces el sistema propone 6 variantes (una por combinación)
  Y cada variante confirmada recibe su propio SKU único por empresa
  Y cada variante puede tener su propio código de barras y precio

Escenario: Stock independiente por variante
  Dado el producto "Polo básico" con variantes S-Rojo y M-Azul
  Entonces cada variante mantiene su cantidad de stock por sucursal por separado
```

**Backend** — modelo de ejes en `Variante`; generación de combinaciones; SKU por variante;
precio por variante (lectura vía `PriceResolver`). `Stock` por variante+sucursal.
**Frontend** — Gestión: editor de ejes + grilla de variantes generadas (activar/desactivar,
precio y código por fila).
**Dependencias** — HU-CAT-02.
**Ref PRD** — §4 (ejes de variante), §5 `Variante`/`Stock`.

---

## HU-CAT-04 — Atributos descriptivos opcionales del producto

**Como** dueño **quiero** registrar atributos descriptivos (peso, medidas, material, marca)
**para** enriquecer el producto **sin** que generen variantes.

**Criterios de aceptación**
```gherkin
Escenario: Agregar atributos descriptivos
  Dado el producto "Polo básico"
  Cuando registro material="algodón" y marca="X"
  Entonces esos atributos se guardan como datos opcionales del producto
  Y NO generan nuevas variantes ni unidades de stock
```

**Backend** — `atributos_opcionales` como **JSON flexible** en `Producto` (decisión MVP,
PRD §11). Validación laxa; clave-valor.
**Frontend** — Gestión: sección "atributos" con pares clave-valor libres.
**Dependencias** — HU-CAT-02.
**Ref PRD** — §4, §5 (nota de modelado ejes vs. descriptivos), §11.

---

## HU-CAT-05 — Configurar afectación de IGV e ICBPER por producto

**Como** dueño **quiero** marcar el tratamiento tributario de cada producto **para** que la
facturación desglose el IGV correctamente y consigne el ICBPER en bolsas.

**Criterios de aceptación**
```gherkin
Escenario: Afectación de IGV por producto
  Cuando creo/edito un producto
  Entonces puedo elegir tipo_afectacion_igv en {gravado, exonerado, inafecto}

Escenario: Marcar bolsa como afecta a ICBPER
  Dado un producto "Bolsa plástica"
  Cuando lo marco afecto_icbper = true
  Entonces la facturación podrá consignar cantidad de bolsas e importe de ICBPER
```

**Backend** — campos `tipo_afectacion_igv`, `afecto_icbper` en `Producto`. Este dato se
**snapshotea** en `OrdenItem` al vender (no se lee vivo). No implementa cálculo de comprobante
(Facturación).
**Frontend** — Gestión: selector de afectación + toggle ICBPER en el form de producto.
**Dependencias** — HU-CAT-02.
**Ref PRD** — §4 (IGV/ICBPER), §6.A (snapshot), §8 (manejo de IGV).

---

## HU-CAT-06 — Unidad de medida y cantidad fraccionada

**Como** dueño **quiero** definir cómo se vende cada producto (unidad, kg, l…) y si admite
decimales **para** vender a granel/por peso correctamente.

**Criterios de aceptación**
```gherkin
Escenario: Producto vendido por peso
  Cuando defino "Jamón" con unidad_medida=kg y permite_cantidad_fraccionada=true
  Entonces el stock y las líneas de orden aceptan cantidades decimales (2.5)
  Y el precio se calcula como precio por unidad × cantidad

Escenario: Producto solo en enteros
  Cuando defino "Gaseosa" con permite_cantidad_fraccionada=false
  Entonces el sistema no permite cantidades decimales de ese producto
```

**Backend** — `unidad_medida`, `permite_cantidad_fraccionada` en `Producto`; propagación a
`Stock` y (contrato) a `OrdenItem`. Cálculo de precio vía `PriceResolver`/`Money`.
**Frontend** — Gestión: selector de unidad + toggle de fracción.
**Dependencias** — HU-CAT-02.
**Ref PRD** — §4, §4.bis (venta por peso, peso a mano en MVP), §5.

---

## HU-CAT-07 — Grupos de modificadores (restaurante)

**Como** dueño de restaurante **quiero** definir grupos de modificadores (ej. "Término",
"Extras") **para** que el POS ofrezca opciones al agregar el ítem.

**Criterios de aceptación**
```gherkin
Escenario: Definir grupo de modificadores
  Dado el producto "Hamburguesa"
  Cuando creo el grupo "Extras" con modificadores {Queso +2.00, Tocino +3.00}
  Y marco el grupo como selección múltiple opcional
  Entonces el POS podrá ofrecer esos modificadores con su precio al vender

Escenario: Grupo obligatorio de selección única
  Dado el grupo "Término" {Rojo, Medio, Bien cocido}
  Cuando lo marco obligatorio y selección única
  Entonces el contrato exige elegir exactamente una opción al agregar el ítem
```

**Backend** — `GrupoModificador` (min/max selección, obligatorio) y `Modificador`
(nombre, precio vía `Money`). Asociación a producto. Consumo real en Ventas core.
**Frontend** — Gestión: editor de grupos/modificadores por producto.
**Dependencias** — HU-CAT-02.
**Ref PRD** — §4 (modificadores), §5 `GrupoModificador`/`Modificador`.

---

## HU-CAT-08 — Código de barras y búsqueda por código

**Como** cajero **quiero** encontrar un producto escaneando su código de barras **para**
agregarlo a la venta rápido.

**Criterios de aceptación**
```gherkin
Escenario: Asignar código de barras a variante
  Dado la variante "Agua 625ml (por defecto)"
  Cuando registro codigo_barra="7501234567890"
  Entonces la búsqueda por ese código resuelve a esa variante

Escenario: Búsqueda por código resuelve variante
  Dado un código de barras existente
  Cuando el POS envía el código (lector HID emula teclado + Enter)
  Entonces la API devuelve la variante correspondiente (SKU, precio, afectación)

Escenario: Código inexistente
  Cuando se busca un código que no existe en la empresa
  Entonces la API responde "no encontrado" sin error del sistema
```

**Backend** — `codigo_barra` en `Variante`; endpoint de **búsqueda por código** (resuelve por
ese campo, PRD §4.bis). Índice para lookup rápido. Contrato agnóstico a plataforma.
**Frontend** — **Gestión**: campo de código en el editor de variante. **POS** (consume):
campo de captura HID bien diseñado; escaneo por cámara en mobile queda como costura (PRD §11,
librería a definir en su momento — no en esta HU).
**Dependencias** — HU-CAT-02/03.
**Ref PRD** — §4.bis (lector, cámara), §5 `Variante.codigo_barra`, §11.

---

## HU-CAT-09 — Flags operativos del producto (preparación / control de inventario)

**Como** dueño **quiero** marcar si un producto requiere preparación en cocina y si controla
inventario **para** que el flujo de orden y de stock se comporten según el producto, no según
el rubro.

**Criterios de aceptación**
```gherkin
Escenario: Producto que va a cocina
  Cuando marco "Lomo saltado" con requiere_preparacion=true
  Entonces al venderse generará comanda a cocina (comportamiento en Ventas core)

Escenario: Producto sin control de inventario
  Cuando marco un servicio con controla_inventario=false
  Entonces no se le exige ni descuenta stock
```

**Backend** — `requiere_preparacion`, `controla_inventario` en `Producto`. Estos flags los
**consumen** Ventas (comanda) e Inventario (descuento); aquí solo se definen.
**Frontend** — Gestión: toggles en el form de producto.
**Dependencias** — HU-CAT-02.
**Ref PRD** — §1 (modelo unificado), §4, §7 (capacidades ortogonales).

---

## HU-INV-10 — Consultar stock por sucursal

**Como** dueño/administrador **quiero** ver existencias por variante y sucursal **para**
saber qué tengo y dónde.

**Criterios de aceptación**
```gherkin
Escenario: Ver stock de una sucursal
  Dado que mi empresa tiene sucursales A y B
  Cuando consulto el stock de la sucursal A
  Entonces veo la cantidad por variante que controla inventario en esa sucursal

Escenario: Variantes sin control de inventario
  Entonces las variantes con controla_inventario=false no exigen ni muestran stock
```

**Backend** — `Stock` (variante_id, sucursal_id, cantidad decimal, stock_minimo). Consulta
filtrada por `empresa_id`/`sucursal_id`.
**Frontend** — Gestión: vista de stock por sucursal (tabla densa, mobile pensado).
**Dependencias** — HU-CAT-03, Épica 0 (sucursales).
**Ref PRD** — §4 Inventario, §5 `Stock`.

---

## HU-INV-11 — Registrar movimiento de inventario (ajuste con motivo)

**Como** administrador **quiero** ajustar stock registrando el motivo **para** cuadrar
existencias con trazabilidad (y alimentar reportes/IA futura).

**Criterios de aceptación**
```gherkin
Escenario: Ajuste manual de stock
  Dado la variante "Agua 625ml" en sucursal A con 10 unidades
  Cuando registro un ajuste de +5 con motivo "recepción de compra"
  Entonces el stock queda en 15
  Y se crea un MovimientoInventario tipo=ajuste con el motivo y timestamp

Escenario: Motivo obligatorio
  Cuando registro un movimiento sin motivo
  Entonces el sistema lo rechaza
```

**Backend** — `MovimientoInventario` (tipo venta/compra/ajuste/devolución, motivo, cantidad,
referencia). Este endpoint cubre **ajuste/compra manual**; venta y devolución los generan
Ventas/Facturación. Actualización de `Stock` transaccional. **Motivo obligatorio** (dato rico
para IA, PRD §9.bis).
**Frontend** — Gestión: form de ajuste con motivo; historial de movimientos por variante.
**Dependencias** — HU-INV-10.
**Ref PRD** — §4 Inventario, §5 `MovimientoInventario`, §9.bis (datos ricos).

---

## HU-INV-12 — Alertas de stock mínimo

**Como** dueño **quiero** que se me avise cuando una variante baje de su stock mínimo
**para** reabastecer a tiempo.

**Criterios de aceptación**
```gherkin
Escenario: Marcar stock mínimo
  Cuando defino stock_minimo=5 para "Agua 625ml" en sucursal A

Escenario: Detectar bajo mínimo
  Dado stock_minimo=5 y cantidad actual=4 en sucursal A
  Cuando consulto alertas de stock
  Entonces "Agua 625ml" aparece como bajo mínimo en la sucursal A
```

**Backend** — `stock_minimo` por `Stock`; consulta/derivación de variantes bajo mínimo por
sucursal. (Notificación push/programada = fuera, solo la señal consultable en MVP.)
**Frontend** — Gestión: indicador/lista de alertas de stock bajo.
**Dependencias** — HU-INV-10, HU-INV-11.
**Ref PRD** — §4 (alertas de stock mínimo), §5 `Stock.stock_minimo`.

---

## HU-CAT-13 — (Costura) Dejar abierta la composición de producto (BOM/combos)

**Como** equipo **queremos** que el modelo de producto **permita** una composición opcional
de otros productos **para** poder agregar combos en fase 2 sin cirugía.

**Criterios de aceptación**
```gherkin
Escenario: Modelo admite composición opcional
  Entonces un producto puede referenciar 0..n componentes (otro producto/variante + cantidad)
  Y la ausencia de composición = producto atómico (comportamiento por defecto)
  Y NO se implementa lógica de precio/stock de combos en el MVP
```

**Backend** — dejar la relación de composición en el modelo (nullable/vacía por defecto). Sin
endpoints de combos ni lógica de expansión. Es **solo no cerrar la puerta**.
**Frontend** — ninguno en MVP.
**Dependencias** — HU-CAT-02.
**Ref PRD** — §9.bis (combos/paquetes → composición/BOM opcional).

---

## Notas de secuencia sugerida (para ordenar el sprint)

1. HU-CAT-01 → CAT-02 (cimiento: categoría + producto simple + variante/SKU).
2. CAT-05, CAT-06, CAT-09 (atributos tributarios y operativos del producto — baratos, alto valor).
3. CAT-03, CAT-04 (variantes por ejes y atributos descriptivos).
4. CAT-08 (código de barras + búsqueda — habilita POS).
5. INV-10 → INV-11 → INV-12 (stock y movimientos).
6. CAT-07 (modificadores — solo si el negocio piloto es restaurante).
7. CAT-13 (costura BOM — junto con CAT-02, es una decisión de modelo, no una feature).
