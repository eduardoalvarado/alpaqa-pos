# PRD — Verticales y feature-gating (prerrequisito del frente de verticales)

> **Fase 1** del frente de verticales vendibles (maestro §7 "Evolución — verticales vendibles",
> 2026-09-07). Este PRD **referencia** las decisiones transversales del maestro y los lineamientos;
> no las repite. Lectura previa: `docs/alcance-mvp-pos.md` §7 y §10, y `docs/lineamientos-tecnicos.md`
> §2.2 (cadena de guards) / §2.4 (privilegios, `SECURITY DEFINER`) / §2.6 (pruebas).

## 0. Convención de nombres

- Épica nueva propuesta; HUs con prefijo **`FGT`** (feature-gating). El id/referencia es la clave
  Jira `ALPQ-N` (ver `docs/flujo-jira.md`). Los verticales concretos van en sus propios PRDs con
  prefijos propios (restaurante = Fase 2, óptica = Fase 3).
- **No es un dominio de negocio ni un módulo hexagonal nuevo.** Es **infra comercial transversal**:
  extiende plataforma (borde HTTP + tenancy) y se apoya en lo que Backoffice (BKO-05) ya construyó.

---

## 1. Propósito

Construir el **eje comercial de verdad**: que el candado que decide *qué compró un tenant* exista y se
**haga cumplir**. Hoy el operador puede asignar un `Plan` con features (`Plan.features`, BKO-05), pero
**nada las hace valer** — asignar un plan no habilita ni bloquea nada. Esta fase cierra esa costura.

Define además el **patrón único** que seguirán todos los verticales (restaurante, óptica, futuros): un
vertical se vende metiendo su feature en el plan del tenant, y el sistema desbloquea sus capacidades y
rutas en consecuencia. Es la inversión que habilita las Fases 2 y 3.

### Lo que construye
- El **enforcement** de `Plan.features`: lectura de las features efectivas del tenant **por request** y
  el corte cuando falta la feature que una ruta o capacidad exige.
- El **vocabulario de features** conocido por el código (catálogo cerrado, como `PERMISSIONS`) y un
  **registro de verticales** (qué capacidad/rutas desbloquea cada feature).
- El **gate del toggle de capacidad** (el comercial habilita el operativo, maestro §7).
- La exposición de las **features efectivas** al frontend (gate de superficie: la UI muestra/oculta
  el vertical; el backend lo hace cumplir).

### Lo que NO construye
- Los verticales en sí (restaurante = Fase 2 reclasificación; óptica = Fase 3 módulo nuevo).
- Comercialización fina: precios de plan, límites/cupos, trials por feature, upgrades self-service.
  BKO-05 modela `Plan`; esto solo agrega el enforcement de sus `features`.

---

## 2. Qué ya existe (no reconstruir)

De **BKO-05** (Backoffice): `Plan` (CRUD, `features String[]`, `code` inmutable), asignación de plan a
un tenant (`Company.planId`, `PUT /backoffice/tenants/:id/plan`), y el cliente `alpaqa_backoffice`.
Lo modelado quedó explícitamente **sin gating**: *"asignar un plan no habilita ni bloquea nada; cuando
exista, el guard leerá `features`."* Esta fase es ese guard.

Precedente técnico calcado: **BKO-04** (suspensión de tenant) ya lee `Empresa.estado` **por request**
en la cadena de guards (`TenantStatusGuard`) vía la función `SECURITY DEFINER` `company_status(id)`
—porque el guard corre antes de que exista contexto de tenant y la RLS devolvería 0 filas—. El
feature-gate es el mismo problema con otra columna.

---

## 3. Modelo

- **Features efectivas de un tenant** = las `features` del `Plan` asignado (`Company.planId →
  Plan.features`). Sin plan → sin features de vertical: el tenant tiene **solo el núcleo**.
- **Vocabulario de features** (`FEATURES`, catálogo cerrado tipo `PERMISSIONS`, en el kernel
  compartido): hoy `['restaurante', 'optica']`; crece con cada vertical. Un string fuera del
  vocabulario en un `Plan.features` es dato inválido (se valida al escribir el plan, BKO-05).
- **Registro de verticales** (`VERTICALS`): mapa feature → { capacidades operativas que desbloquea }.
  Ej.: `restaurante → [usaMesas, usaCocina]`; `optica → [usaLaboratorioInterno, …]`. Empieza como
  constante; el gate del toggle lo consulta. Las **capacidades base** (`controlaInventario`) **no**
  pertenecen a ningún vertical y nunca se gatean.

Sin tablas nuevas: `Plan.features` y `Company.planId` ya existen. A lo sumo, una **función SQL**
(§4). Migración solo si esa función lo requiere.

---

## 4. Mecanismo (la decisión de diseño)

Dos capas, **defensa en profundidad** (decisión, ver §8):

### 4.1 Gate del **toggle de capacidad** — el candado principal
El caso de uso que prende capacidades del dueño (`UpdateCompanyCapabilitiesUseCase`, admin) verifica,
**antes de permitir activar** una capacidad de vertical, que la feature correspondiente esté en el plan
del tenant. Sin `restaurante` en el plan → **`403 CAPABILITY_REQUIRES_FEATURE`** al intentar prender
`usaMesas` (reconciliado FGT-02: **403**, no 409 —no es conflicto de estado sino falta de
entitlement—, y código propio del toggle, distinto del `FEATURE_NOT_IN_PLAN` del guard de ruta).
Esto materializa literalmente "el comercial habilita el operativo": el dueño no puede activar lo que no
compró. Las capacidades base (`controlaInventario`) pasan sin gate.

### 4.2 Gate de **ruta** — el backstop
Un decorador **`@RequireFeature('restaurante')`** (borde HTTP compartido, junto a `@RequirePermission`)
+ un **`FeatureGuard`** en la cadena de guards. Aunque una capacidad ya estuviera activa, si el tenant
pierde la feature (cambio/retiro de plan), sus rutas del vertical cortan con `403 FEATURE_NOT_IN_PLAN`
**en el acto** (por request). Es el mismo rol que el `TenantStatusGuard` de suspensión.

**Lectura por request**: `FeatureGuard` corre en la cadena de guards, antes del `TenantInterceptor`, así
que no puede usar el ORM (RLS = 0 filas). Lee las features vía función **`SECURITY DEFINER`**
`tenant_features(company_id) → text[]` (join `empresa → plan`), con el **requisito de dueño exento**
(lineamientos §2.4) y superficie mínima. `EXECUTE` solo al rol de app.

**Orden en la cadena** (portante, fijado por test): autenticar → exigir empresa → **suspensión** →
**feature** → permiso. La feature va después de suspensión (un suspendido no debe recibir "te falta la
feature") y antes de permiso (a definir con el mismo criterio de "el rechazo dice la verdad").

### 4.3 Alternativa considerada
Un puerto `PlanFeatureReader` chequeado **dentro de cada caso de uso** del vertical (como
`CompanyCapabilityReader`). Más explícito pero disperso (una llamada por caso de uso). Se prefiere el
guard de ruta (una línea por ruta, transversal) + el gate del toggle; el puerto queda disponible si un
caso de uso necesita lógica fina de features.

---

## 5. Contrato de API

- **No hay endpoint de tenant nuevo**: el gating es transversal e implícito (decorás la ruta o el
  toggle lo verifica). Igual que la auditoría no tiene `POST /audit`.
- **Superficie (frontend)**: `GET /auth/me` (o `/onboarding/status`) expone las **features efectivas**
  del tenant, para que la UI muestre/oculte el vertical. Es gate de superficie —la UI lo aplica
  leyendo la respuesta—, el backend es el que **hace cumplir** (igual que `acceso_pos`/`acceso_gestion`).
- **Backoffice**: ya asigna planes (BKO-05); opcionalmente la ficha del tenant expone sus features
  efectivas (read). El operador es quien vende/retira el vertical cambiando el plan.

---

## 6. Invariantes

1. **Sin feature en el plan, no hay vertical.** Su capacidad no se puede activar (**403** en el toggle,
   `CAPABILITY_REQUIRES_FEATURE`) y sus rutas cortan (**403**, `FEATURE_NOT_IN_PLAN`). Las capacidades
   **base** nunca se gatean.
2. **El candado se evalúa por request**, no del token: cambiar/retirar el plan surte efecto en el acto,
   sin re-login (mismo patrón que la suspensión BKO-04).
3. **Retirar una feature apaga el acceso, no borra los datos.** Un tenant que pierde `restaurante` deja
   de operar mesas, pero sus mesas/órdenes históricas quedan (coherente con BKO-05: "retirar cierra la
   puerta de entrada, no expulsa"). Reactivar la feature restaura el acceso.
4. **Ortogonal a RBAC y a la tenancy.** El feature-gate no relaja permisos ni aislamiento; es una capa
   más de la cadena. Un usuario con permiso pero sin la feature del vertical: 403 por feature, no por
   permiso.
5. **Compatibilidad hacia atrás (crítico).** Esta fase construye el **mecanismo** y **no cambia el
   comportamiento de ninguna ruta existente**. Aplicar el candado a restaurante (y migrar los tenants
   que hoy usan mesas/cocina) es **Fase 2**. Fase 1 no debe dejar a ningún tenant actual sin su
   operación.

---

## 7. Costuras dejadas abiertas
- **Registro de verticales** como constante; si la relación feature↔capacidades↔rutas crece, se
  modela (tabla/config). Hoy alcanza una constante.
- **Comercialización fina** (precios, límites por feature, trials, upgrade self-service, cupos por
  sucursal/usuario) — fase posterior; el enforcement de esta fase es el cimiento.
- **Features finas dentro de un vertical** (ej. `kds` separado de `mesas`): §8 decide la granularidad
  inicial; partir una feature en varias después es agregar entradas al vocabulario, no cirugía.

---

## 8. Decisiones a confirmar (recomendación primero)

1. **Granularidad de la feature de restaurante:** **una** feature `restaurante` que agrupa mesas+cocina
   *(recomendado: simple; el dueño elige qué capacidades prende dentro)* vs. features finas (`mesas`,
   `kds`). — El maestro §7 asume vertical *coarse*.
2. **Doble gate (toggle + ruta):** hacer **ambos** *(recomendado, defensa en profundidad)* vs. solo el
   toggle. El toggle es la puerta; la ruta es el backstop ante cambio de plan por request.
3. **Lectura por request vía `SECURITY DEFINER` `tenant_features`** *(recomendado, calca BKO-04)*.
4. **Exponer features efectivas en `/auth/me`** para el gate de superficie *(recomendado)*.
5. **Retirar feature = apaga acceso, conserva datos** *(recomendado, coherente con BKO-05)*.
6. **Prefijo/épica `FGT`** *(a confirmar el nombre)*.

---

## 9. Mapa HU → entregable técnico

| HU | Entregable |
|---|---|
| `FGT-01` | **Mecanismo de enforcement**: vocabulario `FEATURES` + registro `VERTICALS`; función `tenant_features(company_id)` (`SECURITY DEFINER`, dueño exento); `FeatureReader` (puerto + adapter); decorador `@RequireFeature` + `FeatureGuard` en la cadena (orden fijado por test). **Sin aplicar a ninguna ruta real todavía** (probado con una feature de prueba), para no romper compatibilidad (invariante 5) |
| `FGT-02` | **Gate del toggle de capacidad** en `UpdateCompanyCapabilitiesUseCase`: prender una capacidad de vertical exige su feature en el plan. Con el registro `VERTICALS` (capacidades base pasan). **Hecho 2026-09-07** (`ALPQ-89`): solo al **encender** (false→true) y solo las de vertical; helper `featureForCapability`; lee features vía `FeatureReader` **una sola vez y solo si hace falta** (mutation-tested); error propio `CAPABILITY_REQUIRES_FEATURE`→**403** (distinto del guard de ruta). e2e por la ruta real (sin plan→403, base pasa, con `restaurante`→200). **Nota de compat:** al gatear mesas/cocina, un fixture que las prendía por API sin plan (`company.e2e`) pasó a necesitar un plan `restaurante` — la migración de datos reales es Fase 2 |
| `FGT-03` | **Gate de superficie**: `GET /auth/me` expone las features efectivas del tenant. **Hecho 2026-09-07** (`ALPQ-90`): se agregó `features: string[]` a `AuthenticatedUserResponse`; el handler las lee **en vivo** con `FeatureReader` (por request, no del token — un token viejo ya refleja el plan actual), `[]` sin empresa (ADM-01). e2e: con `restaurante` en el plan, `/auth/me` lo expone (mutation-tested). No hubo rutas de escritura nuevas que auditar |

> La **aplicación real a restaurante** (`@RequireFeature('restaurante')` en las rutas de mesas/cocina +
> el gate efectivo del toggle + la **migración** de los tenants que hoy las usan) es la **Fase 2**, en
> el PRD "Restaurante (vertical)". Fase 1 entrega el mecanismo probado y desactivado sobre lo existente.

---

## 10. Prerrequisitos y orden

**Prerrequisito duro (cumplido):** BKO-05 (`Plan` + `features` + asignación). **Riesgo a vigilar:**
`FGT-01` toca la **cadena de guards**, transversal a los seis módulos (como BKO-04) — auditar con
cuidado y fijar el orden con test. **Compatibilidad hacia atrás** (invariante 5) es la restricción que
gobierna la fase: el mecanismo entra "en frío", sin cambiar rutas vivas; recién la Fase 2 lo activa
sobre restaurante con su migración.
