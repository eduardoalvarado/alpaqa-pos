# PRD — Óptica (vertical vendible)

> **Fase 3** del frente de verticales vendibles (maestro §7). Vertical **nuevo**: módulo
> `optics` sobre el núcleo de ventas, detrás del feature-gating (Fase 1). Directiva del
> usuario (2026-09-07): **funcionalmente completa** para operar una óptica de verdad
> —ficha clínica incluida—, benchmarkeada contra software de mercado. Referencias: maestro
> §7/§10, `docs/prd-verticales-feature-gating.md`, lineamientos §2.2/§2.4/§2.6.

## 0. Convención de nombres
- Épica **`ALPQ-94`**; HUs con prefijo **`OPT`**: `OPT-01..06` = `ALPQ-95..100`. La clave
  Jira `ALPQ-N` es el id.
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
por un puerto propio.

**Molde de reúso cross-context, fijado en OPT-01** (vale para OPT-02..06): todo lo que Óptica
necesite de otro dominio va por un **puerto propio nombrado por la necesidad**
(`CustomerReader`, y mañana `CatalogReader`), nunca colgado del puerto de persistencia del
agregado propio — eso le daría dos razones para cambiar y obligaría a su doble en memoria a
fingir un contexto ajeno. El adapter vive en `optics/infrastructure/<contexto>/` y **puede
leer las tablas del otro dominio** (mismo desplegable, misma tenancy) mientras la pregunta sea
de *existencia*; cuando Óptica necesite **datos** del otro dominio —nombre y documento del
cliente en la receta o la dispensación, OPT-04/05— sube a un **caso de uso exportado** por el
módulo dueño, que es lo único que esos módulos exportan. Tablas nuevas = **tablas de tenant** con RLS + GRANT (invariante 4).
Enganche de auditoría: una línea `@Audit` por ruta (mecanismo ya existente).

---

## 4. Modelo de datos (tablas de tenant nuevas)
- **`Patient` (paciente)** — nombre, documento, contacto, fecha de nacimiento, notas. Opcionalmente
  vinculado a un `Customer` (identidad fiscal) cuando compra. La ficha clínica cuelga de acá.
  **Construido (OPT-01):** `first_name`/`last_name`, `doc_type`/`doc_number` **nullables** (un
  menor puede no tener documento; en Postgres los NULL no colisionan, así que el único
  `(company, doc_type, doc_number)` deduplica solo a quienes sí lo tienen), `birth_date` como
  **fecha civil** (`DATE`, sin hora ni zona), `phone`/`email`/`address`/`notes`, y
  `customer_id` nullable con FK `ON DELETE SET NULL` — borrar la identidad fiscal no puede
  llevarse puesta la ficha clínica. El vocabulario de documento del paciente es **más chico**
  que el fiscal: `DNI`/`CE`/`PASAPORTE`; `RUC` no entra (una empresa no tiene graduación) y la
  ausencia se modela con `null`, no con el centinela `SIN_DOCUMENTO`. La columna **reusa el
  enum físico de facturación** (`document_type`, que es más ancho) y un **`CHECK`** angosta el
  vocabulario **en la base** — sin él, "sin RUC" sería una promesa del repositorio (§12.1).
- **`ClinicalRecord` / `OptometricExam`** — visita: fecha, profesional, agudeza visual, refracción,
  observaciones. Append-only en la práctica (historia). Uno-a-muchos con `Patient`.
- **`Prescription` (receta/Rx)** — por ojo: `sphere`, `cylinder`, `axis`, `add`, `pd/dip`, `prism`;
  tipo, vigencia, profesional. Cuelga del paciente; opcionalmente del examen que la originó.
  **Construido (OPT-02):** tipo (`DISTANCE`/`NEAR`/`PROGRESSIVE`/`OCCUPATIONAL`), los dos ojos en
  **columnas** `od_*`/`os_*` (una receta tiene exactamente dos ojos, siempre: una tabla hija
  admitiría cero, uno o tres y obligaría a un join para leer lo que nunca se lee por separado),
  `pupillary_distance` en mm, `issued_at`/`expires_at` como **fechas civiles**, `notes`, y
  `professional_id` → `usuario` con `RESTRICT` (quien firmó no se borra dejando la receta sin
  firma). Dioptrías en `Decimal(4,2)`, nunca float. **Es append-only**: se emite y se supersede,
  nunca se edita — sin `updated_at`, sin rutas de edición/borrado, y `GRANT SELECT, INSERT` con
  `REVOKE UPDATE, DELETE` explícito. El vínculo al examen **se difiere a OPT-03**, que es cuando
  la tabla `OptometricExam` existe y la FK puede ser real (§12.5).
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
- Pacientes **(hecho, OPT-01)**: `POST /patients`, `GET /patients` (búsqueda por nombre/
  apellido/documento, con techo de página), `GET /patients/:id`, `PATCH /patients/:id`
  (parche parcial: ausente conserva, `null` explícito borra, y la ficha se **re-valida
  entera**). Todas con `@RequireFeature('optica')` a nivel de clase + `gestionar_optica` +
  `@Audit` en las de escritura.
- Historia: `POST /patients/:id/exams`, `GET /patients/:id/exams`.
- Recetas **(hecho, OPT-02)**: `POST /patients/:patientId/prescriptions` (`gestionar_optica`),
  `GET /patients/:patientId/prescriptions` (historial, de la más reciente a la más antigua) y
  `GET /prescriptions/:id`, ambas de lectura con **`ver_receta`**. No hay PATCH ni DELETE: la
  receta se supersede. El **profesional que firma sale del token**, nunca del cuerpo.
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

## 8. Permisos y capacidades (resuelto en OPT-01)
- Permisos nuevos en `PERMISSIONS`: **`gestionar_optica`** (ficha/receta/laboratorio) y
  **`ver_receta`** (lectura clínica; empieza a gatear en OPT-02). No se reusan
  `gestionar_catalogo`/`vender`: un vendedor que puede facturar no debería por eso poder
  editar una historia clínica.
- Capacidad operativa nueva: **`usesInternalLab`** (`empresa.usa_laboratorio_interno`), y
  `VERTICALS.optica = ['usesInternalLab']`. Su toggle queda gateado por la feature `optica`
  (FGT-02, ya construido): el dueño solo la prende si el operador le vendió el vertical.
  **Ojo de despliegue:** los grants de `empresa` son **por columna** (BKO-04/05c), así que la
  columna nueva necesitó `GRANT UPDATE` *y* `GRANT INSERT` explícitos — Prisma materializa el
  `@default` del lado del cliente y la columna viaja nombrada en el INSERT del alta de empresa.

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
| `OPT-01` **(hecha, `ALPQ-95`)** | Cimiento del módulo `optics` + feature `optica` operativa: `Patient` (ficha) + `VERTICALS.optica` + capacidad `usesInternalLab`; todo detrás de `@RequireFeature('optica')`; RLS+GRANT (con `REVOKE DELETE`, §12.1); auditoría |
| `OPT-02` **(hecha, `ALPQ-96`)** | **Receta/graduación** (`Prescription`) ligada al paciente y al profesional, con las invariantes clínicas sostenidas por `CHECK` en la base |
| `OPT-03` | **Historia clínica / examen** (`OptometricExam`) del paciente — **set optométrico completo** (decisión §9.4), campos a fijar con el benchmark. **Incluye agregar `prescription.exam_id` con su FK compuesta por tenant** (diferido de OPT-02, §13.7) |
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

---

## 12. Desviaciones y hallazgos al construir

### 12.1 El `GRANT` de tres verbos no deja el cuarto afuera
La migración de OPT-01 concedía `SELECT, INSERT, UPDATE` sobre `patient` y afirmaba, en su
comentario, que la ficha por lo tanto **no se puede borrar**. Era falso: el cimiento corrió
`ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO
alpaqa_app`, así que **toda tabla nueva nace con los cuatro verbos** y enumerar tres no quita
el cuarto. Se descubrió con mutation-testing, consultando `information_schema.role_table_grants`
sobre la tabla ya creada. Corregido con un `REVOKE DELETE` explícito y un e2e que lo fija
contra una conexión real del rol de la app (no leyendo el catálogo).

> **Deuda detectada fuera de esta HU:** por el mismo motivo, `audit_event` (AUD-01) tiene hoy
> `UPDATE` y `DELETE` concedidos a `alpaqa_app`, pese a que su migración declara append-only
> «y aunque lo hubiera, Postgres lo rechaza». Hoy Postgres **no** lo rechaza. Cerrarlo es una
> HU nueva bajo la épica de Auditoría (precedente FAC-07/AUD-09).

### 12.2 El pre-chequeo de duplicado no es la garantía
El caso de uso pre-chequea el documento para dar un 409 legible, pero dos altas simultáneas lo
pasan las dos. La garantía es el índice único de BD, y para que llegue al cliente como 409 (y
no como 500) el adapter traduce `P2002` **en el alta y en la edición**, con el `catch` acotado
a la sentencia que puede chocar. Verificado quitando el pre-chequeo: el e2e sigue devolviendo
409. (FAC-02 tiene la misma forma sin la traducción en el alta — deuda propia de ese dominio.)

### 12.3 Lo que las auditorías corrigieron
Las dos auditorías (plan y arquitectura) dieron **fiel** y **sana**, con reservas que se
cerraron antes del commit:
- **Puerto propio para el cliente fiscal.** `customerExists()` colgaba de `PatientRepository`.
  Se extrajo a `CustomerReader` (§3). Importa porque este módulo es el molde de OPT-02..06:
  sin esto, cada agregado nuevo duplicaría el chequeo o inyectaría el repositorio de pacientes
  para preguntar por un cliente.
- **Dos aserciones que no podían fallar.** (a) La "prueba" de RLS afirmaba en un comentario
  que sin contexto de tenant la lectura da cero filas, pero solo aseveraba que la promesa
  resolviera — con la tabla llena habría pasado igual. Ahora siembra fichas y exige `count = 0`
  desde el rol de la app. (b) El cruce de tenants del vínculo fiscal mandaba un UUID
  **inexistente**: pasaba aunque el lookup no estuviera acotado por empresa. Ahora manda el id
  de un `Customer` **real de otra empresa** — que es la única defensa, porque las FK de
  Postgres no aplican RLS. Ambas verificadas por mutación (apagar la RLS, desacotar el lector).
- **El contrato de error del puerto.** `update` lanza `PatientNotFoundError` y ahora el puerto
  lo declara, que es lo que obliga al doble en memoria a comportarse igual.

### 12.4 Alcance de `ver_receta`
El permiso entró al vocabulario en OPT-01 —el dueño necesita verlo para armar sus roles— y
**empieza a gatear en OPT-02**: emitir es `gestionar_optica` (acto clínico, alguien firma una
graduación) y **leer** es `ver_receta`. La separación existe para que quien despacha —el
mostrador que arma el pedido y elige el armazón— consulte la receta sin poder emitir ni tocar la
historia; sin ella, dispensar exigiría dar permiso de escritura clínica a media tienda.

---

## 13. Decisiones y desviaciones de OPT-02 (receta)

### 13.1 Las invariantes clínicas viven en el dominio **y** en la base
El dominio valida con errores legibles (paso de fabricación de 0.25 dioptrías, rango clínico,
cilindro↔eje, prisma↔base, adición↔tipo, vigencia posterior a emisión). Además, las que se pueden
expresar en SQL van como `CHECK`: son el techo que queda puesto cuando mañana alguien escriba por
otro camino. Las dos capas se probaron por separado —el dominio con unit tests, los `CHECK`
insertando con el owner para saltear la aplicación— y **cada una se verificó por mutación**.

Por qué estas reglas y no otras: una graduación fuera del paso de 0.25 **no se puede tallar**, así
que dejarla entrar convierte un error de tipeo del mostrador en un pedido rechazado por el
laboratorio días después. Un cilindro sin eje es lo mismo: el cilindro dice *cuánto* astigmatismo
hay, el eje *en qué orientación*, y sin las dos cosas no hay lente. El eje se acota a 0–180 porque
una elipse a 190° es la misma que a 10°: aceptar 190 guarda un dato que después nadie sabe si
estaba mal escrito.

**Los números** (fijados acá porque rechazan peticiones con 422, así que no pueden vivir solo
como constantes en el código): paso **0.25 D** para esfera, cilindro, adición y prisma; esfera
**±30**, cilindro **±15**, adición **0.25 a 6**, prisma **0 a 20**; distancia interpupilar **40 a
85 mm** en pasos de **0.5**; eje **entero de 0 a 180**; notas hasta 500 caracteres. Los rangos son
generosos a propósito: no pretenden ser el criterio clínico del profesional, sino atajar el tipeo
(el récord de miopía documentado ronda −28 D).

### 13.2 La adición ata el tipo con los ojos
`DISTANCE` **rechaza** adición (con adición sería de cerca o progresiva); `PROGRESSIVE` y
`OCCUPATIONAL` la **exigen** (se definen por ella); `NEAR` la deja opcional a propósito, porque una
receta de cerca se escribe tanto como potencia absoluta —sin adición— como derivada de la de lejos,
y las dos formas se usan.

### 13.3 El rastro de auditoría no es una puerta de atrás a lo clínico
AUD-07 devuelve `dataAfter` y `metadata.payload` a quien tenga `ver_auditoria`. Sin redactar, ese
permiso leería esfera, cilindro, eje, adición, DIP y notas de cada receta emitida, **sorteando el
`ver_receta`** que esta misma HU introduce. Por eso la emisión declara `redactBody`/`redactResponse`
sobre los campos clínicos: el rastro responde *quién emitió qué receta y cuándo* —le basta el
`entityId`— y los valores se leen de la receta, que exige el permiso. Como la receta es inmutable,
el rastro no pierde nada.

**Asimetría deliberada con OPT-01:** la ficha del paciente **no** se redacta. Ahí el rastro sirve
para saber *qué cambió* en un dato que sí se edita, y ese es justamente su valor; en la receta, que
no se edita nunca, el documento entero sigue disponible para quien tenga `ver_receta`.

### 13.4 La firma sale del token, no del cuerpo
Dejar que la request diga quién firmó permitiría emitir una receta a nombre de otro profesional,
que es justo la accountability que el vertical necesita conservar (§9.1). La garantía es de dos
capas: el DTO no declara el campo (y `whitelist: true` lo descarta) y el controller pasa el usuario
autenticado sin mirar el cuerpo.

### 13.5 Una receta no se edita
Se emite y se supersede; corregirla es emitir otra, que es lo que deja el rastro clínico honesto.
Lo dicen el puerto (no ofrece `update`), el módulo (no expone ruta) y —lo único que lo garantiza—
el privilegio: `REVOKE UPDATE, DELETE`, por la lección de §12.1.

### 13.6 Qué queda fuera: DIP monocular
La distancia interpupilar se guarda **binocular** (una sola medida). El estándar para progresivos
es la **monocular** (una por ojo, porque la nariz rara vez está centrada). Es una costura conocida,
no un olvido: se agrega cuando OPT-04/05 lo pidan, y son dos columnas más.

### 13.7 El vínculo receta↔examen se difiere a OPT-03
La HU lo mencionaba como columna nullable "hasta OPT-03". Se difirió: una columna que referencia
una tabla que todavía no existe no puede tener FK, no la puede poblar nadie, y hay que acordarse de
cerrarla después. OPT-03 la agrega **con** su FK, cuando `OptometricExam` exista.

### 13.8 FK compuesta por tenant (nueva regla del vertical)
La RLS de una tabla verifica **de quién es la fila**, no **a qué apunta**, y las FK de Postgres no
aplican RLS. Con una FK simple `patient_id`, nada en la base impedía una receta con `company_id`
mío y `patient_id` de otro tenant: lo atajaba el caso de uso, o sea **una sola capa**, cuando los
lineamientos §2.4 piden dos. `prescription` estrena por eso la **primera FK compuesta del repo**,
`(company_id, patient_id) → patient(company_id, id)`, con el único que Postgres exige como destino.

**Es molde para OPT-03..06**: todos cuelgan del mismo paciente, y con la FK simple cada agregado
nuevo repetiría el chequeo por convención hasta que uno se olvide y la base no avise.

### 13.9 Lo que las auditorías corrigieron
Ambas dieron **fiel** y **sana**; las reservas se cerraron antes del commit:
- **El paso de 0.25 no estaba en la base**, pese a que este PRD lo ponía de bandera. Ahora es un
  `CHECK` (`x*4 = trunc(x*4)` sobre columnas `DECIMAL`: exacto, sin aritmética flotante).
- **Tres decoradores sin cobertura:** `@RequireFeature('optica')` y `@Audit` se podían borrar con la
  suite en verde. Ahora tienen e2e que muerden.
- **La FK del profesional decía `RESTRICT` en el comentario y quedaba en `NO ACTION`** (el default
  de Postgres no es `RESTRICT`), con drift contra `schema.prisma`. Escrita explícita; `migrate diff`
  vuelve limpio.
- **El contrato mentía:** el OpenAPI declaraba los ojos obligatorios y `@ValidateNested` no valida
  lo ausente. Se agregó `@IsDefined`/`@IsObject`.
- **`isExpired` se quitó**: era código de OPT-04. La semántica que fijaba —una receta vence **al día
  siguiente** de su vigencia, y sin `expiresAt` no vence nunca— queda registrada acá para que OPT-04
  la implemente deliberadamente.
- **Un comentario afirmaba de más:** decía que `entityIdFromResponse` evitaba etiquetar el evento
  con el id del paciente. Es falso —el param se llama `:patientId`, no `:id`, así que el interceptor
  ya cae al `id` de la respuesta—; se verificó por mutación y el comentario ahora dice lo que es:
  intención explícita, no mecanismo necesario.
