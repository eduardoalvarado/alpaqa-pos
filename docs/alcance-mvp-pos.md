# Alcance del MVP — SaaS POS unificado (tiendas y restaurantes)

> Documento de alcance para servir como base a la generación del PRD, el diseño y los lineamientos técnicos en Claude Code. Captura la visión, las decisiones tomadas y las restricciones. No es el PRD final ni contiene detalle de implementación.

---

## 1. Visión del producto

SaaS de punto de venta dirigido a tiendas y restaurantes en Perú. El objetivo no es ofrecer dos productos distintos (uno para tiendas, otro para restaurantes), sino **un único sistema unificado** que un negocio configura según su forma de operar.

La idea central: el negocio real está en el **flujo de la orden**, no en el rubro. Una venta al mostrador en una tienda y un "para llevar" en un restaurante son, en el fondo, la misma transacción. Lo único que cambia es el canal (mesa vs. venta directa) y si algún producto requiere preparación en cocina.

### El modelo unificado de orden

En lugar de un campo rígido `tipo_negocio = tienda | restaurante`, el sistema se apoya en:

- Una **única entidad `Orden`** que se comporta según el canal, no según el rubro.
- **Capacidades configurables** por negocio (¿usa mesas?, ¿usa cocina/KDS?, ¿controla inventario?).
- Una propiedad a nivel de producto, `requiere_preparacion`, que decide si un ítem pasa por cocina — no depende del tipo de negocio.

Consecuencia práctica: una tienda de ropa nunca activa mesas ni cocina; un restaurante activa ambas; un café que también vende productos embotellados para llevar usa el mismo flujo sin ramas de código separadas.

---

## 2. Las tres superficies (aplicaciones)

El sistema se compone de **tres frontends sobre un mismo backend/API**. Son aplicaciones distintas, con distinto público, scope de autenticación y patrón de uso.

**Requisito transversal — mobile no es opcional.** Las tres superficies deben funcionar en mobile (responsive o app, a definir en lineamientos técnicos), no solo en desktop. El diseño parte de mobile, no lo adapta después. El énfasis máximo está en el POS, donde se busca una experiencia de usuario moderna de primera clase (ver 2.3).

**Requisito transversal — tema claro y oscuro.** Las tres superficies soportan tema claro y oscuro intercambiable por el usuario. Esto se resuelve a nivel de **design tokens** (colores como variables temáticas, no hardcodeadas) desde el sistema de diseño compartido, no como un parche por pantalla. La preferencia de tema se recuerda por usuario.

### 2.1 Backoffice del operador (super-admin)
Herramienta interna del operador del SaaS. Nunca la ve un cliente.
- Gestión de tenants: alta, activación, suspensión.
- Gestión de planes y feature gating (qué features incluye cada plan).
- Métricas globales.
- Mobile responsive (el operador puede necesitar suspender/consultar desde el móvil); es la superficie con menor exigencia de UX mobile de las tres.

### 2.2 Plataforma de gestión (dueño + empleados con permiso)
Panel de administración del negocio. Acceso según rol.
- Configuración de la empresa, sucursales, usuarios y roles.
- Catálogo, inventario, series de comprobantes.
- Reportes y configuración de capacidades del negocio.
- Pantallas densas (tablas, filtros, reportes). Asume conexión.
- Mobile responsive real: el dueño consulta reportes y hace ajustes desde el celular. Las tablas y reportes densos requieren un diseño mobile pensado (no una tabla desktop encogida).

### 2.3 POS (operación de venta)
Interfaz del punto de venta. Corre en tablet o terminal táctil del mostrador **y en móvil** (un mesero tomando pedido en mesa desde su celular, un negocio pequeño operando solo con un teléfono).
- Táctil, rápida, optimizada para operar bajo presión.
- **Máxima prioridad de experiencia de usuario del proyecto.** UX moderna de primera clase: mobile-first, gestos táctiles, respuesta inmediata, mínimos toques para cerrar una venta, feedback visual claro. Es la cara del producto y donde se juega la percepción de calidad.
- **Única superficie que funciona offline.** Toda la complejidad de sincronización vive aquí.
- Scope de datos acotado: catálogo de su sucursal, mesas, turno de caja abierto.
- Integra hardware externo (ver sección 5.bis): lector de código de barras y ticketera térmica.

### Implicancia de arquitectura
Como las tres superficies consumen el mismo backend, **el diseño de la API y el modelo de permisos es el contrato central**. El rol de un usuario define no solo qué ve, sino a qué superficie puede entrar:
- Cajero / mesero → POS.
- Dueño → plataforma de gestión + POS.
- Operador del SaaS → backoffice.

---

## 3. Multi-tenancy

- SaaS multi-tenant con **`empresa_id` (tenant) presente en prácticamente toda tabla**.
- Enfoque para el MVP: **base de datos compartida con discriminador `empresa_id` por fila** (row-level tenancy). No schema-por-tenant ni base-por-tenant. Más simple de operar y migrar; escala bien con índices correctos.

---

## 4. Módulos del MVP

### Onboarding / configuración inicial
- Flujo guiado de primer arranque para un negocio nuevo: no puede vender hasta configurar datos de empresa, al menos una sucursal, una caja, series de comprobantes y catálogo mínimo.
- Es lo que separa un producto vendible de un demo. No necesita ser sofisticado, pero debe existir como flujo pensado (checklist o asistente), no como pantallas sueltas que el dueño debe descubrir.

### Empresa (tenant)
- RUC, razón social, nombre comercial, `regimen_tributario`, `precios_con_igv_incluido`, estado (trial/activo/suspendido), plan.
- **Capacidades del negocio** (operativo, editable por el dueño): usa mesas, usa cocina/KDS, controla inventario.

### Sucursales
- Una empresa tiene 1+ sucursales, cada una con inventario y caja propios.

### Usuarios y roles
- **Decisión — autorización por permiso, no por nombre de rol.** El código conoce un
  **vocabulario fijo de permisos** (`vender`, `aplicar_descuento`, `anular_venta`,
  `cerrar_caja`, `ver_totales`, `gestionar_catalogo`, `ajustar_inventario`,
  `gestionar_usuarios`, `acceso_pos`, `acceso_gestion`…) y **solo verifica permisos**. Los
  **roles son datos por-empresa** (`Rol` — nombre + conjunto de permisos, ver modelo de
  datos) que **cada negocio define**: son configurables, no un enum en el código. Esto
  mantiene el sistema **rubro-agnóstico** (coherente con el modelo unificado de orden): una
  bodega crea "vendedor/almacenero", un restaurante "mesero/cocina", sin ramas por rubro.
- Los roles listados (dueño, administrador, cajero, mesero, cocina) son **ejemplos/semilla**,
  no la lista cerrada.
- **Permisos granulares por rol**: quién aplica descuentos (y hasta qué %), quién autoriza anulaciones, quién ve totales de venta, quién cierra caja. (El límite `descuento_max_pct` es un atributo del rol; los permisos booleanos son el vocabulario que verifican los guards.)
- El rol también determina a qué superficie puede acceder el usuario (vía permisos `acceso_*`).

### Catálogo
- Productos, categorías, variantes, modificadores (grupos de modificadores por producto: opciones con precio, min/max/obligatorio). Rubro-agnóstico (§1): son opcionales por producto, no gated por capacidad; comunes en restaurante (término, extras) pero también aplican a bodega/cafetería (tamaño, tipo de leche) o retail (envoltura, grabado).
- Flags: `requiere_preparacion`, `controla_inventario`.
- `tipo_afectacion_igv` por producto: gravado / exonerado / inafecto.
- **SKU como identificador único** de la unidad de stock. Vive en la variante (ver modelo de datos), único por empresa. Todo producto tiene al menos una variante (una "por defecto" cuando no tiene variaciones reales), de modo que SKU, código de barras y stock siempre cuelgan de la misma entidad.
- **Ejes de variante** (crean unidades de stock distintas, cada una con su SKU): talla, color, etc. Una camiseta roja y una azul son dos variantes.
- **Características descriptivas opcionales** del producto (no crean variantes, no todas aplican a todos): peso, medidas/dimensiones, material, marca, etc. Se modelan como atributos opcionales flexibles.
- **Unidad de medida** por producto: unidad, kg, g, l, ml, m, etc. Determina cómo se vende y se inventaría.
- **`permite_cantidad_fraccionada`**: define si el producto se vende en cantidades decimales (2.5 kg de jamón) o solo en enteros (3 gaseosas). Se propaga a la línea de orden y al cálculo de precio.

### Inventario
- Stock por sucursal, movimientos, alertas de stock mínimo.

### Mesas
- Plano de mesas, estado (libre/ocupada), zona/salón, asignación a mesero.

### Órdenes (entidad unificada)
- Canal: mesa o venta directa (mostrador, para llevar, delivery).
- Descuentos y anulaciones con flujo de autorización según rol.
- **Orden abierta (flujo de mesa)**: una orden en mesa se construye por etapas — abrir mesa, agregar ítems, enviar comanda, agregar más ítems, enviar otra comanda, cerrar. "Agregar ítems a una orden abierta" es núcleo del uso en restaurante, no un extra.
- **Devoluciones con reingreso a stock**: el cliente devuelve un producto ya vendido; la mercadería regresa al inventario y se emite nota de crédito. Es distinto de anular la venta del día. Conecta con Inventario (reingreso) y Facturación (nota de crédito).

### Comandas / Cocina
- Ticket a cocina cuando el ítem requiere preparación.
- Soporta **KDS en pantalla** e **impresión física** en impresora térmica (muchos negocios pequeños en Perú no tienen tablet en cocina).

### Caja
- Apertura de turno con fondo inicial.
- Registro de ingresos/egresos durante el turno (sangrados y suministros).
- Cierre y arqueo: comparación automática de lo esperado vs. lo contado, por medio de pago.
- Turnos por cajero cuando varios comparten una caja física.

### Cobro y pagos
- Métodos: efectivo, tarjeta (POS físico del banco), Yape, Plin.
- **Pago mixto**: una orden puede dividirse en varias líneas de pago, cada una con su método.
- Cálculo de vuelto para efectivo.
- Campo opcional de `numero_operacion` por pago (para conciliación futura con estado de cuenta).

### Facturación electrónica
- Boleta / factura vía integración con **PSE** (Proveedor de Servicios Electrónicos, ej. Nubefact/Bizlinks). No se genera XML firmado desde cero.
- **Notas de crédito** para anulaciones posteriores a la emisión y para devoluciones.
- Desglose de IGV por línea (según régimen).
- **ICBPER (impuesto a las bolsas de plástico)**: cuando un negocio afecto al IGV entrega una bolsa de plástico, el comprobante debe consignar la cantidad de bolsas y el importe del ICBPER dentro de la "sumatoria de otros tributos". Se resuelve marcando el producto "bolsa" como afecto a ICBPER en catálogo. No aplica a negocios que solo realizan operaciones exoneradas del IGV (conecta con el régimen tributario).
- **Entrega del comprobante al cliente**: además del ticket térmico impreso, el comprobante electrónico se entrega en formato PDF/XML (por correo o enlace). El cliente en Perú espera su boleta/factura electrónica, no solo el ticket físico.
- Manejo de series y correlativos (ver decisiones transversales).
- Cola de contingencia para modo offline.

### Sincronización offline (transversal)
- Ventas en cola cuando no hay conexión.
- Sincronización y envío a SUNAT (vía PSE) al recuperar internet.
- IDs generados localmente (UUID) para evitar colisiones.

### Clientes
- Registro básico (tipo y número de documento, nombre), historial de compra.

### Reportes
- Ventas por sucursal, productos más vendidos, cierres de caja, descuentos y anulaciones por usuario.
- **Dominio con PRD propio** (§10), el último del MVP: es puramente aditivo sobre datos que los
  demás dominios ya capturan. Su permiso, `ver_totales`, ya existe en el vocabulario y todavía no
  lo consume ninguna ruta.

### Auditoría (transversal)
- Registro de quién hizo qué y cuándo, con foco en descuentos, anulaciones y cierres de caja.
- **Dominio con PRD propio** (§10), después de *Sincronización offline*. Es prerrequisito de dos
  cosas que hoy están fuera del MVP —soporte sobre datos e impersonación del operador—, y el
  Backoffice ya le dejó un consumidor esperando: **quién suspendió a qué tenant y cuándo** es la
  acción más sensible del producto y hoy no deja rastro.
- **Costura ya identificada (BKO-06):** los casos de uso del backoffice **no reciben al actor** —
  solo llega hasta el controlador. Enganchar el rastro va a exigir tocar las firmas de los casos de
  uso que escriben. Está nombrado para que no se descubra tarde.

---

## 4.bis Hardware externo (integración en el POS)

El MVP debe contemplar la integración con hardware físico periférico. Vive en la superficie POS.

### Lector de código de barras
- Uso principal: búsqueda rápida de producto en la venta y en la carga de inventario.
- La mayoría de lectores operan como **emulación de teclado** (HID): el código escaneado llega como una cadena de texto seguida de un Enter. Para la versión desktop/tablet esto suele no requerir integración especial, solo un campo de captura bien diseñado.
- En **mobile**, considerar además el escaneo por **cámara** del dispositivo (útil cuando no hay lector físico). Esto sí requiere una librería de lectura de códigos.
- El campo `codigo_barra` ya existe en `Variante`; la búsqueda debe resolver por ese campo.

### Ticketera térmica (impresora de tickets/comandas)
- Dos usos: comprobante/ticket de venta para el cliente y **comanda impresa a cocina** (conviviendo con el KDS en pantalla, según lo definido en el módulo de cocina).
- La impresión térmica no es "imprimir un PDF": suele usar comandos **ESC/POS** y conexión por USB, red (Ethernet/WiFi) o Bluetooth.
- Punto de diseño importante: **el mecanismo de impresión depende de la superficie**. Desde una tablet/desktop en la misma red, imprimir a una térmica de red es directo; desde un navegador móvil, el acceso a hardware es más limitado y puede requerir una app nativa, un puente local, o impresión vía Bluetooth. Definir la estrategia por plataforma en los lineamientos técnicos.
- El formato del ticket y de la comanda debe ser **configurable** (datos del negocio, logo si aplica, pie de página).

### Venta por peso (frutas, verduras, productos a granel)
- Un negocio tipo tienda puede vender productos por peso (ej. 2.3 kg de tomate). El caso base ya está cubierto por el modelo: `unidad_medida = kg`, `permite_cantidad_fraccionada = true`, y cantidad decimal en `Stock` y `OrdenItem`. El precio se calcula como precio por unidad de medida × peso.
- **En el MVP, el peso se ingresa a mano**: el producto se pesa en una balanza aparte y el cajero teclea el peso en el POS. Esto no requiere hardware adicional.
- Balanza integrada al POS y códigos de barra de peso variable → costura de extensión (ver 9.bis).

### Consideración transversal
La abstracción de impresión y de captura de código debe modelarse como un **servicio del lado POS con interfaz común**, de modo que la lógica de venta no dependa del hardware concreto ni de la plataforma. Esto mantiene el flujo de venta agnóstico al dispositivo.

---

## 5. Modelo de datos — entidades por dominio

> Lista de entidades y campos clave. El detalle completo de columnas y relaciones se define en la fase de PRD/diseño técnico.

**Núcleo tenant**
- `Empresa` — ruc, razon_social, nombre_comercial, regimen_tributario, precios_con_igv_incluido, estado, plan_id, capacidades.
- `Sucursal` — empresa_id, nombre, direccion.
- `Usuario` — empresa_id, nombre, email, password_hash, activo.
- `Rol` — empresa_id, nombre, permisos (descuento_max_pct, puede_anular, puede_ver_totales, puede_cerrar_caja…).
- `UsuarioSucursal` — puente: usuario ↔ sucursal ↔ rol.

**Catálogo**
- `Categoria` — empresa_id, nombre.
- `Producto` — empresa_id, categoria_id, nombre, precio, requiere_preparacion, controla_inventario, tipo_afectacion_igv, afecto_icbper (para bolsas de plástico), unidad_medida, permite_cantidad_fraccionada, atributos_opcionales (peso, medidas, material, marca… flexibles).
- `Variante` — producto_id, ejes (talla, color…), precio, **sku (único por empresa)**, codigo_barra. Todo producto tiene ≥1 variante (una por defecto si no tiene variaciones reales); SKU, código de barras y stock cuelgan siempre de aquí.
- `GrupoModificador`, `Modificador` — opciones y precios por producto (min/max/obligatorio). Rubro-agnóstico; restaurante es el caso más común, no el único.

> Decisión de modelado: los atributos que **definen** unidades de stock distintas (talla, color) son ejes de `Variante`; los atributos meramente **descriptivos** (peso, medidas, material) van en `atributos_opcionales` del producto y no generan variantes.

**Inventario**
- `Stock` — variante_id, sucursal_id, cantidad (decimal, según unidad de medida), stock_minimo.
- `MovimientoInventario` — tipo (venta/compra/ajuste/devolución), motivo, cantidad, referencia a orden o nota de crédito.

**Operación de venta**
- `Mesa` — sucursal_id, nombre, estado, zona.
- `Orden` — empresa_id, sucursal_id, canal, mesa_id (nullable), mesero_id (nullable), cliente_id (nullable), estado, subtotal, igv, descuento, total, uuid_local.
- `OrdenItem` — orden_id, referencia a producto/variante (solo trazabilidad) + **snapshot** de nombre, precio_unitario, unidad_medida y tipo_afectacion_igv. Cantidad decimal cuando el producto permite fracción.
- `OrdenItemModificador` — modificadores elegidos por línea.
- `Comanda` — orden_id, sucursal_id, estado (pendiente/en_preparacion/listo).

**Caja**
- `Caja` — sucursal_id, nombre.
- `TurnoCaja` — caja_id, usuario_id, fondo_inicial, apertura, cierre, monto_esperado, monto_contado, diferencia.
- `MovimientoCaja` — turno_caja_id, tipo (ingreso/egreso/sangrado/suministro), monto, motivo.

**Pago**
- `Pago` — orden_id, turno_caja_id, metodo, monto, numero_operacion (nullable), vuelto. Relación 1..n con orden (pago mixto).

**Facturación electrónica**
- `SerieComprobante` — asignada en exclusiva a una caja; tipo, serie, correlativo_actual.
- `Comprobante` — orden_id, tipo (boleta/factura), serie, correlativo, doc_cliente, subtotal, igv, otros_tributos (incluye ICBPER), total, estado_sunat, xml, cdr, entregado_a (correo/enlace, nullable). Guarda **snapshot** de sus propios totales y datos del cliente.
- `NotaCredito` — comprobante_id (el que modifica), motivo (anulación / devolución / corrección), serie, correlativo, estado_sunat.

**Soporte**
- `Cliente` — empresa_id, tipo_documento, numero_documento, nombre.
- `LogAuditoria` — empresa_id, usuario_id, accion, entidad, entidad_id, datos_antes, datos_despues, timestamp.

---

## 6. Decisiones transversales críticas

Estas cuatro definen la solidez del modelo. Mal diseñadas al inicio, son caras de corregir en producción.

### A. Snapshot vs. referencia en la línea de orden
`OrdenItem` **no referencia el precio ni el IGV vivos del producto**: los copia al momento de la venta. Un comprobante es un documento legal ante SUNAT y no puede cambiar retroactivamente porque se editó el catálogo. La FK al producto se mantiene solo para trazabilidad, no para leer datos de cobro.

### B. Correlativo sin huecos + offline: una serie por caja
- SUNAT permite múltiples series por tipo de comprobante. **Cada caja es dueña exclusiva de su propia serie** (Caja 1 → B001, Caja 2 → B002…).
- El requisito de "sin huecos" es **por serie**, no global. Como cada serie vive en un solo dispositivo, se mantiene secuencial por construcción, incluso offline por días.
- El correlativo se asigna **localmente al emitir** (número final, se imprime al instante). No hay coordinación entre cajas porque no comparten espacio de numeración.
- "Sin huecos" significa que **todo número consumido debe rendirse** ante SUNAT: si se anula, el número queda quemado y se resuelve con nota de crédito / baja, nunca se reusa ni se salta.
- La asignación exclusiva serie↔caja es una **regla de negocio crítica**, no un detalle de UI.
- El servidor mantiene el `correlativo_actual` como high-water mark reconciliado (para recuperación). Offline, el dispositivo es la fuente de verdad de su serie.

### C. IDs para sincronización
Todo lo creable offline (órdenes, pagos, movimientos de caja) usa **UUID generado en el cliente**, no autoincremental del servidor. Garantiza que dos dispositivos no colisionen y que la sincronización sea idempotente.

### D. Snapshot en el comprobante
El `Comprobante` guarda sus propios totales, desglose de IGV y datos del cliente al momento de emisión. No los recalcula leyendo la orden: una vez emitido, es inmutable.

### Ciclo de vida del comprobante (`estado_sunat`)
`generado` (local, puede ser offline) → `enviado` → `aceptado` / `rechazado`.
Un rechazo se corrige y reenvía, o se da de baja; el número nunca desaparece.

---

## 7. Los dos ejes de configuración (ortogonales)

No mezclar en un solo sistema de flags. Se modelan por separado desde el inicio.

- **Capacidades del negocio** (`Empresa.capacidades`) — operativo, editable por el dueño: usa mesas, usa cocina, controla inventario. Define cómo opera, no lo que pagó.
- **Feature gating por plan** (`Plan.features`) — comercial, editable solo por el operador: qué funciones incluye el plan contratado.

Ejemplo de por qué son ortogonales: un negocio puede tener la capacidad "mesas" activada (es un restaurante) pero estar en un plan que no incluye KDS.

Para el MVP: capacidades completas (son baratas y necesarias para el modelo unificado); feature gating en su versión más simple (posiblemente un solo plan al inicio, con la estructura lista para agregar más).

---

## 8. Decisiones confirmadas

- **Facturación SUNAT**: imprescindible en el MVP, vía PSE (no XML firmado propio).
- **Multi-sucursal**: sí, desde el inicio (`sucursal_id` como dimensión transversal en inventario, caja y reportes).
- **Ambos canales** (venta directa y mesas/comandas) desde el MVP.
- **Regímenes tributarios**: soportar Régimen General (boleta y factura con IGV desglosado) y Nuevo RUS (boleta simplificada sin desglose de IGV). La lógica de facturación se ramifica según `regimen_tributario`.
- **Pago mixto**: sí (varias líneas de pago por orden).
- **Sin pasarela de pago en el MVP**: solo se registra el método. El cobro con tarjeta lo hace el POS físico del banco (Izipay/Niubiz).
- **Yape/Plin con QR dinámico**: generado localmente con el estándar QR interoperable (EMVCo) con el monto incluido. Es generación de QR, no integración de API de pago. Confirmación de pago manual por el cajero.
- **Conciliación en cierre de caja**: automática para efectivo; manual (basada en lo registrado) para tarjeta y billeteras digitales en el MVP.

### Manejo de IGV
- En catálogo: `tipo_afectacion_igv` por producto (gravado/exonerado/inafecto).
- En empresa: flag de si los precios se ingresan con IGV incluido.
- En facturación: desglose de IGV por línea; en Nuevo RUS no se desglosa aunque el dato quede guardado para reportes internos.

### Datos del cliente al cobrar
- Boleta: DNI opcional. Factura: RUC obligatorio. El flujo de cobro captura esto según el caso.

---

## 9. Fuera del MVP (fase 2)

**Aditivas puras — se difieren sin costo de retrofit** (se construyen encima del cimiento limpio, sin tocar el modelo transversal ni la API):
- Órdenes de compra a proveedores.
- Programa de fidelización / puntos.
- Integraciones con apps de delivery externas (Rappi, PedidosYa).
- Analíticas avanzadas / dashboards predictivos.
- Reservas de mesa.
- Propinas y comisiones para meseros.
- Integración directa con pasarela de pago.
- Conciliación automática de tarjeta/billeteras contra estado de cuenta bancario.
- Importación masiva de productos (CSV/Excel).
- Búsqueda automática de RUC/DNI para autocompletar datos del cliente.
- Pantalla para el cliente (customer-facing display).
- Marcar producto como agotado del día (86ing) — trivial de agregar; puede entrar al MVP si se quiere.

**Explícitamente fuera de alcance** (se nombran para que no se cuelen):
- Mecanismos tributarios avanzados: percepción, detracción, retención (no aplican a negocios pequeños).
- Multi-moneda (ver costura en sección 9.bis — decisión activa requerida).
- Precios por horario / happy hour (ver costura en 9.bis).
- Costeo de recetas / ingredientes (restaurante avanzado).

**Funcionalidades de IA — candidatas para fase 2** (aditivas puras: se apoyan en datos que el MVP ya captura, no requieren cambiar arquitectura; ver costura de datos en 9.bis):
- Pronóstico de demanda / reabastecimiento (cuándo se agota un producto según histórico).
- Reportes en lenguaje natural para el administrador ("¿cómo me fue el fin de semana vs el anterior?").
- Detección de anomalías / fraude sobre anulaciones, descuentos y cierres de caja con diferencia (se alimenta del módulo de auditoría).
- Sugerencias de precios o de productos a promocionar según rotación.
- Búsqueda semántica en catálogo / alta de productos desde foto o descripción.
- Asistente conversacional para el administrador y para el POS.

> Nota de disciplina: la IA es donde más fácil se infla el alcance. Un primer cliente quiere vender rápido, facturar bien y cuadrar la caja, no un pronóstico predictivo. Mantener la IA fuera del MVP es la decisión correcta; es un diferenciador de fase 2.

---

## 9.bis Costuras de extensión (diseñar ahora, construir después)

Principio: *el error costoso no es dejar una funcionalidad fuera del MVP, sino tomar una decisión de arquitectura que le cierre la puerta*. Estas costuras se **diseñan** ahora (cuesta poco: es no cerrar la puerta) aunque la funcionalidad se **construya** más tarde.

- **Combos / paquetes** → dejar que un producto *pueda* estar compuesto de otros (una composición/bill-of-materials opcional en el modelo). No construir la lógica de combos ahora, solo no asumir que todo producto es atómico.
- **Precios por horario / listas de precio** → toda lectura de precio pasa por una **función de resolución de precio**, no por leer un campo crudo disperso en el código. Con eso, agregar reglas de precio después es un módulo, no una cirugía.
- **Multi-moneda** → decisión activa. Si es solo Perú/soles, se cierra la puerta con conciencia. Si hay ambición regional, la costura barata es **centralizar el manejo de dinero** (un tipo/utilidad de dinero único) para que agregar moneda luego sea un cambio localizado, no una migración de decenas de tablas.
- **Facturación offline y otros comprobantes** → el ciclo `estado_sunat` y la separación "vender" vs "emitir comprobante numerado" ya dejan la puerta abierta a notas de débito y otros documentos sin rediseño.
- **Balanza integrada y código de barras de peso variable** → la puerta ya está medio abierta (cantidad fraccionada y unidad de medida están en el modelo). Falta, para fase 2, la integración de hardware de balanza y el parseo del código de barras de peso variable (EAN-13 con prefijo 2, que codifica peso/precio en el propio código, común en supermercados). No toca el cimiento; se apoya en el servicio de captura de código ya previsto.
- **Datos e IA** → las funcionalidades de IA de fase 2 son aditivas, pero dependen de dos decisiones de cimiento que sí se toman ahora: (1) **capturar datos ricos y bien estructurados desde el MVP** — timestamps precisos, categorías consistentes, detalle fino de cada orden (no solo totales), motivos en movimientos de inventario y caja. El modelo actual ya va bien encaminado (snapshots, auditoría, movimientos con motivo); la disciplina es no degradar esa calidad. (2) **Postura de privacidad de datos multi-tenant**: definir con conciencia si los datos de un negocio pueden usarse para alimentar/entrenar modelos que beneficien a otros negocios, o si el aislamiento por tenant es estricto siempre. No se construye nada de IA ahora, pero esta postura afecta cómo se estructuran y etiquetan los datos desde el día uno.

Las decisiones de la fase 2 marcadas como "aditivas puras" **no necesitan costura**: escriben en las mismas tablas y endpoints existentes. Solo las de arriba requieren pensar el hueco desde ahora.

---

## 10. Estructura documental (PRD maestro + PRDs por dominio)

Por el tamaño del proyecto, la documentación se organiza en capas en vez de un solo PRD gigante o un PRD por módulo suelto (los módulos están demasiado acoplados para aislarlos uno a uno).

### Documento raíz / PRD maestro
Este documento (evolucionado) es la **fuente de verdad** de todo lo que cruza dominios: visión, las tres superficies, multi-tenancy, requisito mobile, hardware externo, y sobre todo las **decisiones transversales** (snapshot, correlativo por caja, UUIDs, snapshot en comprobante, los dos ejes de configuración, ciclo `estado_sunat`). Estas decisiones se escriben **una sola vez, aquí**.

### PRDs por dominio funcional
Se agrupan módulos acoplados que se diseñan juntos. Cada PRD de dominio **referencia** el documento raíz para las decisiones transversales, no las repite.

- **Ventas y operación** — la **`Order` unificada (rubro-agnóstica)** como núcleo (venta directa: mostrador/para llevar/delivery); **mesas** y **comandas/KDS** son **capas opcionales gated por capacidad** (`usesTables`/`usesKitchen`), no pilares del dominio. El código nunca ramifica por rubro/`tipo_negocio`, solo por capacidad y por el flag de producto `requiresPreparation`.
- **Cobros y caja** — pagos, pago mixto, turnos, arqueo.
- **Facturación electrónica** — comprobantes, notas de crédito, series/correlativo, integración PSE.
- **Catálogo e inventario** — productos, variantes, modificadores, stock, código de barras.
- **Plataforma y administración** — empresa, sucursales, usuarios, roles, capacidades.
- **Backoffice del operador** — tenants, planes, feature gating.
- **Sincronización offline** — PRD propio por ser transversal y complejo.
- **Auditoría** — quién hizo qué y cuándo (§4). Transversal: se engancha en las rutas de
  escritura de los demás dominios.
- **Reportes** — los agregados de §4 para el dueño (`ver_totales` ya está en el vocabulario de
  permisos y **todavía no lo usa ninguna ruta**: se reservó para este dominio).

> **Alineación §4 ↔ §10 (ago-2026).** Hasta acá el §4 nombraba **Reportes** y **Auditoría** como
> módulos del MVP, el §10 no los listaba como dominios, y el §9 tampoco los ponía fuera del MVP:
> quedaban en un limbo por el que el MVP podía darse por terminado con dos módulos declarados y sin
> construir. **Los dos son del MVP**, y no por criterio nuevo sino por lo que este mismo documento
> ya decía: el §9 difiere a fase 2 las *analíticas avanzadas* (lo que presupone reportes básicos
> adentro) y la *detección de anomalías* diciendo que «se alimenta del módulo de auditoría» (lo que
> presupone que el módulo existe). **Clientes** no entra a esta lista porque no quedó en limbo: lo
> absorbió *Facturación electrónica*, que ya modela `Customer` y lo captura al emitir.
>
> **Orden dentro del MVP: Sincronización offline → Auditoría → Reportes.** Sincro va primero
> porque reescribe *cómo se escribe* en todo el backend (operaciones encoladas, resolución de
> conflictos, escrituras diferidas respecto del acto que las originó), y Auditoría se engancha
> justo en esas rutas: construirla antes es diseñarla contra rutas que están por cambiar, y obliga
> a contestar sin datos si los registros de auditoría se sincronizan o solo se generan en el
> servidor. Reportes va último por ser puramente aditivo: lee lo que ya se captura y no cierra
> ninguna puerta.

### Regla de generación
Los PRDs de dominio **no se generan todos por adelantado**. Cada uno se genera **justo antes de entrar a implementar ese dominio**, con contexto fresco, para evitar acumular documentación que se desactualiza antes de tocarse. El documento raíz sí existe desde el inicio.

---

## 11. Pendientes de decisión (para PRD / lineamientos técnicos)

- **Stack técnico** de cada superficie y del backend (a definir en los lineamientos técnicos).
- **Billing propio del SaaS**: cómo se le cobra al negocio suscriptor. Definir si es manual al inicio o automatizado; mantenerlo separado del modelo de facturación de los clientes.
- Elección concreta del **PSE** a integrar.
- Estrategia de **resolución de conflictos** de sincronización más allá de la idempotencia por UUID (ej. ediciones concurrentes de la misma orden desde dos dispositivos).
- Alcance exacto del **QR interoperable** (validar el estándar vigente y librerías disponibles).
- **Estrategia mobile por superficie**: responsive web vs. app nativa vs. híbrida, especialmente para el POS (donde la experiencia y el acceso a hardware son críticos).
- **Estrategia de impresión térmica por plataforma**: cómo imprime cada superficie (red, USB, Bluetooth) según corra en desktop, tablet o móvil.
- **Escaneo de código en mobile**: definir si se soporta cámara además del lector físico HID, y con qué librería.
- **Patrón de "variante por defecto"**: confirmar que todo producto se modele con ≥1 variante (simplifica SKU/stock) vs. permitir productos sin variante. Recomendado: variante por defecto siempre.
- **Mecánica de `atributos_opcionales`**: definir si se guardan como JSON flexible o como estructura tipada. Para el MVP, JSON flexible suele bastar.
