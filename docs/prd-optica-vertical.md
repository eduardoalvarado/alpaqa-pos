# PRD — Óptica (vertical vendible)

> **Fase 3** del frente de verticales vendibles (maestro §7). Vertical **nuevo**: módulo
> `optics` sobre el núcleo de ventas, detrás del feature-gating (Fase 1). Directiva del
> usuario (2026-09-07): **funcionalmente completa** para operar una óptica de verdad
> —ficha clínica incluida—, benchmarkeada contra software de mercado. Referencias: maestro
> §7/§10, `docs/prd-verticales-feature-gating.md`, lineamientos §2.2/§2.4/§2.6.

## 0. Convención de nombres
- Épica nueva; HUs con prefijo **`OPT`**. La clave Jira `ALPQ-N` es el id.
- **Módulo hexagonal nuevo `optics`** (físico inglés, `@map`). Feature comercial **`optica`**
  (ya en el vocabulario `FEATURES` desde FGT-01). Todo el módulo va detrás de
  `@RequireFeature('optica')`.

---

## 1. Propósito y alcance
Que una óptica **opere completa** sobre el POS: atender al paciente, registrar su historia
optométrica, emitir/registrar la receta, vender armazón + lunas a medida, mandar a tallar
(laboratorio interno o externo) y entregar con garantía — **cobrando y facturando por el
núcleo** que ya existe. No es un mínimo; es el vertical que justifica venderlo.

**Lo que construye:** paciente/ficha clínica, receta (Rx), dispensación (venta óptica ligada
a la receta), orden de laboratorio con canal interno/externo, entrega y garantía.
**Lo que reúsa (no reconstruye):** `Order`/cobro/caja/facturación/inventario/sincronización/
auditoría. Un armazón o una luna son **productos** del catálogo; la venta es una `Order`; el
cobro y el comprobante, los de siempre.

---

## 2. Benchmark de mercado (para no dejar huecos)
Referencia: suites de **gestión óptica / optometría** (p. ej. Ocuco/Acuitas, MaximEyes,
RevolutionEHR, CrystalPM, Eye Cloud Pro, Optix). Todas comparten el mismo **flujo canónico**,
que es el que este PRD cubre:

1. **Paciente** — ficha con datos personales y de contacto (distinta del cliente fiscal).
2. **Historia clínica / examen optométrico** — visitas con agudeza visual, refracción,
   antecedentes; se acumulan en el tiempo.
3. **Receta (Rx)** — graduación por ojo (esfera, cilindro, eje, adición, DIP, prisma), tipo
   (lejos/cerca/progresivo/ocupacional), vigencia, profesional que la firma.
4. **Dispensación** — armazón (del catálogo) + lunas (material + tratamientos) según la receta;
   se convierte en una **venta** (`Order`).
5. **Orden de laboratorio** — mandar a tallar: **interno** (cola/ticketera propia) o **externo**
   (documento impreso/transmitido a un laboratorio tercero, con seguimiento).
6. **Entrega y garantía** — retiro por el paciente, control de garantías/reprocesos.

Lo que **queda fuera** del MVP del vertical (fase 2 del vertical): agenda de citas, seguro
médico/convenios, telemedicina, integración con equipos de diagnóstico (autorefractómetros).

---

## 3. Ubicación en la arquitectura
Módulo `optics` con `domain/ application/ infrastructure/`, hexagonal, detrás de
`@RequireFeature('optica')`. Reúsa el núcleo por sus **casos de uso/puertos**, no tocándolo:
la dispensación crea la venta por el caso de uso de `sales` (como hace `sync`), y lee catálogo
por un puerto propio. Tablas nuevas = **tablas de tenant** con RLS + GRANT (invariante 4).
Enganche de auditoría: una línea `@Audit` por ruta (mecanismo ya existente).

---

## 4. Modelo de datos (tablas de tenant nuevas)
- **`Patient` (paciente)** — nombre, documento, contacto, fecha de nacimiento, notas. Opcionalmente
  vinculado a un `Customer` (identidad fiscal) cuando compra. La ficha clínica cuelga de acá.
- **`ClinicalRecord` / `OptometricExam`** — visita: fecha, profesional, agudeza visual, refracción,
  observaciones. Append-only en la práctica (historia). Uno-a-muchos con `Patient`.
- **`Prescription` (receta/Rx)** — por ojo: `sphere`, `cylinder`, `axis`, `add`, `pd/dip`, `prism`;
  tipo, vigencia, profesional. Cuelga del paciente; opcionalmente del examen que la originó.
- **`OpticalDispense` (dispensación)** — liga una `Order` (o una `OrderItem`) a una `Prescription`
  + la especificación de la luna (material, tratamientos) + el armazón elegido. Es el puente entre
  lo clínico y la venta.
- **`LabOrder` (orden de laboratorio / WorkOrder)** — de una dispensación: canal (interno/externo),
  estado (`PENDING → IN_LAB/SENT → READY → DELIVERED`), fecha prometida, laboratorio destino,
  notas, y el rastro de impresión/transmisión. **Append-only en transición** (estados solo avanzan),
  patrón calcado de las comandas pero entidad propia (§5).
- **`Delivery`/garantía** — entrega al paciente y control de garantía (puede modelarse como estado
  terminal de `LabOrder` + un registro de garantía; se decide en su HU).

Todas: RLS + GRANT (patrón invariante 4). `id` sin default de BD (IdGenerator). Físico inglés.

---

## 5. El laboratorio: interno vs. externo (la decisión de diseño del vertical)
`LabOrder` **no es la comanda de cocina** (comparte la forma, no la naturaleza). Tiene un
**canal de cumplimiento** (puerto), decidido por ruteo sobre la misma entidad:
- **Externo:** el sistema **produce el documento** (imprime en la ticketera / exporta/transmite a un
  laboratorio tercero, vía un puerto tipo `LabOrderDelivery`, best-effort) y **trackea el ciclo desde
  el lado de la óptica**: enviado → fecha esperada → recibido → entregado. No modela el proceso interno
  del laboratorio.
- **Interno:** la misma orden se **rutea a una cola/estación propia** (una pantalla tipo KDS de
  laboratorio, o directo a la ticketera) — reusa el **patrón** de cola de trabajo con estados que
  avanzan, como consumidor separado (no las comandas de cocina).
El interno/externo es **config operativa** del vertical ya vendido (capacidad `usaLaboratorioInterno`,
nivel dueño), no el candado de venta (ese es la feature `optica`, nivel operador).

---

## 6. Contrato de API (todo detrás de `@RequireFeature('optica')`)
- Pacientes: `POST/GET/PATCH /patients`, `GET /patients/:id`.
- Historia: `POST /patients/:id/exams`, `GET /patients/:id/exams`.
- Recetas: `POST /patients/:id/prescriptions`, `GET /patients/:id/prescriptions`, `GET
  /prescriptions/:id`.
- Dispensación: `POST /orders/:orderId/optical-dispense` (liga la venta a la receta + spec de luna).
- Laboratorio: `POST /lab-orders`, `GET /lab-orders` (cola), `PATCH /lab-orders/:id` (avance de
  estado), `POST /lab-orders/:id/print` (documento). Entrega: `POST /lab-orders/:id/deliver`.
Cada ruta lleva su permiso (§8) + `@RequireFeature('optica')` + `@Audit(...)`.

---

## 7. Reúso del núcleo (no se reconstruye)
- **Armazones/lunas/accesorios** = productos con variantes/atributos/inventario/código de barras.
- **La venta** = `Order` (canal COUNTER); el **cobro** = caja/pagos; el **comprobante** = facturación
  (boleta/factura). La dispensación **liga** la receta a esa venta, no la reimplementa.
- **Auditoría, sincronización, admin, backoffice** aplican sin cambios.

---

## 8. Permisos y capacidades (a confirmar)
- Permisos nuevos probables: `gestionar_optica` (ficha/receta/laboratorio) y quizás `ver_receta`.
  Alternativa: reusar `gestionar_catalogo`/`vender`. **Decisión en §9.**
- Capacidad operativa nueva: `usaLaboratorioInterno` (`Company.capacidades`), y `VERTICALS.optica`
  pasa a mapear las capacidades del vertical (hoy `[]`). Su toggle queda gateado por la feature
  `optica` (FGT-02, ya construido).

---

## 9. Decisiones confirmadas con el usuario (2026-09-07)
1. **Profesional/optometrista = `User` con permiso** (sin entidad nueva).
2. **`Patient` es entidad separada** del `Customer` (fiscal), con **vínculo opcional** al `Customer`
   al facturar. La ficha clínica cuelga del `Patient`.
3. **Permisos nuevos** para el vertical (`gestionar_optica`, `ver_receta`) — no se reusan los
   existentes.
4. **Historia clínica = set optométrico COMPLETO** (no el mínimo que alimenta la receta). ⇒ `OPT-03`
   crece: el examen modela el set completo (agudeza, refracción, biomicroscopía, presión, fondo de
   ojo, antecedentes, etc.), a fijar en su HU con el benchmark.
5. **Laboratorio: EXTERNO primero** (imprimir/transmitir el documento + seguimiento); el **interno**
   (cola/ticketera propia) llega después. ⇒ `OPT-05` arranca por el canal externo; el interno es una
   HU/costura posterior.
6. **Sin sincronización offline** en el MVP del vertical (receta/laboratorio son de mostrador con
   conexión). Costura si se necesita.

---

## 10. Costuras (fuera del MVP del vertical)
Agenda de citas, convenios/seguros, telemedicina, integración con equipos de diagnóstico, historia
clínica rica (más allá de lo que alimenta la receta), sincronización offline del vertical.

---

## 11. Mapa HU → entregable (propuesta, se afina al implementar)
| HU | Entregable |
|---|---|
| `OPT-01` | Cimiento del módulo `optics` + feature `optica` operativa: `Patient` (ficha) + `VERTICALS.optica` + capacidad `usaLaboratorioInterno`; todo detrás de `@RequireFeature('optica')`; RLS+GRANT; auditoría |
| `OPT-02` | **Receta/graduación** (`Prescription`) ligada al paciente y al profesional |
| `OPT-03` | **Historia clínica / examen** (`OptometricExam`) del paciente — **set optométrico completo** (decisión §9.4), campos a fijar con el benchmark |
| `OPT-04` | **Dispensación**: liga la `Order` a la receta + spec de luna/armazón (reúsa el caso de uso de venta) |
| `OPT-05` | **Orden de laboratorio** — **canal externo primero** (imprimir/transmitir + seguimiento) + estados + puerto de impresión/transmisión. El canal **interno** (cola/ticketera) es HU posterior (decisión §9.5) |
| `OPT-06` | **Entrega y garantía** |

Orden: OPT-01 (cimiento) → OPT-02/03 (clínico) → OPT-04 (dispensación) → OPT-05 (laboratorio) →
OPT-06 (entrega). Frontend (pantallas de óptica) es trabajo aparte del backend.

---

## 12. Prerrequisitos y orden
Fases 1 y 2 completas. La feature `optica` ya existe en el vocabulario; falta que `VERTICALS.optica`
mapee sus capacidades (OPT-01) y que el módulo se construya detrás del gate. Es **aditivo**: no toca
los dominios existentes salvo por el reúso vía puertos.
