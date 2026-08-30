# Lineamientos técnicos — alpaqa-pos

> Documento raíz de decisiones técnicas, hermano del PRD (`alcance-mvp-pos.md`). Define el
> stack, la arquitectura y las convenciones transversales de los tres repos. El PRD dice
> **qué** se construye; este documento dice **con qué** y **cómo**.

## Principio rector de versiones

Se usan versiones **estables / LTS**, maduras y probadas en producción. **Nada
experimental, beta, RC ni en preview.** Al momento de scaffolding se verifica la LTS
vigente de cada pieza. Las funcionalidades marcadas como experimentales por sus propios
mantenedores (p. ej. zoneless en Angular) no se adoptan hasta ser estables.

---

## 1. Topología de repos

| Repo | Rol |
|---|---|
| `alpaqa-pos` | Hub de especificación (PRD, lineamientos, PRDs por dominio, `ui/`). Sin código. |
| `alpaqa-pos-backend` | API única, contrato central, multi-tenant. |
| `alpaqa-pos-frontend` | Monorepo Nx: `apps/{pos,gestion,backoffice}` + `packages/{design-system,api-client,shared}`. |

Repos independientes, hermanos en `~/Projects/`.

---

## 2. Backend

### 2.1 Stack

| Pieza | Elección |
|---|---|
| Runtime | Node LTS |
| Framework | NestJS (estable) |
| Lenguaje | TypeScript, `strict: true` |
| ORM | Prisma + Prisma Migrate |
| Base de datos | PostgreSQL 16/17 |
| API | REST + OpenAPI (Swagger) |
| Auth | JWT (access + refresh) + RBAC |
| Validación | class-validator/DTOs en el borde |
| Dinero | Postgres `numeric` / Decimal — **nunca float** |
| Testing | Jest (unit + e2e con supertest) |

### 2.2 Arquitectura: monolito modular + hexagonal pragmático

Módulos por **bounded context**, sin microservicios en el MVP.

**Dos desplegables, un solo repositorio** (ago-2026, al construir el backoffice). El monolito
modular sigue siendo la regla para los dominios de negocio: comparten proceso, esquema y
despliegue. La excepción es el **backoffice del operador**, que corre como un proceso aparte
(`main-backoffice.ts` + `BackofficeAppModule`) desde el mismo código.

La razón **no** es acoplamiento —el módulo no importa nada de los demás— sino el **radio de daño
de una credencial**: el backoffice usa un rol de base de datos capaz de cruzar tenants, y la API de
tenant es la superficie grande y expuesta a todos los clientes. Con un solo proceso, un fallo ahí
entrega esa conexión; con dos, la credencial no está cargada en el proceso vulnerable. Es un límite
de privilegio, no de dominio, y por eso no contradice "sin microservicios".

Separar los procesos **obliga a separar el entorno**, o el límite es decorativo: si el proceso de
backoffice tuviera que cargar las variables del de tenant —`DATABASE_URL`, la conexión del *owner*,
que evade RLS— solo para pasar la validación de arranque, el radio de daño seguiría abierto en la
otra dirección. Por eso hay **un perfil de validación de entorno por proceso**: cada uno exige
únicamente sus variables. La regla para cualquier desplegable futuro es la misma — un proceso
aparte que igual carga las credenciales del otro no acota nada.

Lo que **no** se separa, a propósito: repositorio, `schema.prisma` y migraciones. El backoffice
modifica tablas de tenant (estado y plan de la empresa), así que el historial de migraciones tiene
un solo dueño; dos escritores sobre una misma base es la forma clásica de romperla.

**Hexagonal (ports & adapters) en los dominios ricos** — facturación, órdenes/ventas,
caja, inventario, sincronización:

```
src/modules/<contexto>/
  domain/            entidades, value objects, invariantes, puertos (interfaces)
  application/       casos de uso / command handlers
  infrastructure/    adapters: repositorios Prisma, clientes externos, controllers
```

- El **dominio es puro**: no importa Prisma, Nest ni nada de infraestructura.
- **Prisma vive en infraestructura**, detrás de puertos de repositorio que mapean
  modelo Prisma ↔ entidad de dominio. El mapeo es el precio de mantener el core puro.
- **CRUD ligero** (módulo Nest + servicio sobre Prisma) en módulos simples de
  configuración, sin ceremonia hexagonal.

**Regla de dependencias — apuntan hacia adentro** (`infrastructure → application → domain`):

- `domain/` — entidades, value objects, invariantes, **puertos** (`ports/*.port.ts`:
  interfaz + token `Symbol`) y **errores** (`errors/`). Cero imports de Nest, Prisma o HTTP.
  No conoce a nadie hacia afuera.
- `application/` — casos de uso (`*.use-case.ts`) que orquestan el dominio **a través de
  puertos**. **Excepción pragmática:** pueden usar los decoradores de DI de Nest
  (`@Injectable`, `@Inject(TOKEN)`) — ese es el *único* acople a framework permitido aquí;
  nada de Prisma, HTTP ni adapters. No importan de `infrastructure/`.
- `infrastructure/` — adapters intercambiables que **implementan** los puertos del dominio:
  `persistence/` (repos `prisma-*` + un `in-memory-*` para tests), `http/`
  (`*.controller.ts` + `*.dto.ts` con class-validator en el borde), clientes externos.
  El dinero cruza siempre como `Money`, nunca `number`.

**Los guards corren ANTES que los interceptores** (Nest). Consecuencia práctica y no obvia: cuando
un guard se ejecuta, el `TenantInterceptor` **todavía no fijó** `app.current_empresa`, así que la
RLS devuelve 0 filas para cualquier tabla de tenant. **Un guard que necesite leer la base no puede
usar el modelo Prisma**: va por una función `SECURITY DEFINER` de superficie mínima, como hace el
login. Se descubrió construyendo el guard de suspensión (BKO-04) y volverá a aparecer cada vez que
un dominio agregue un guard con lectura.

**El orden de los `APP_GUARD` es portante y se fija con un test.** La cadena vigente es: autenticar
→ exigir empresa → cortar si el tenant está suspendido → autorizar por permiso. Cada eslabón existe
para que el rechazo **diga la verdad**: a un suspendido le sobran los permisos, así que dejarlo
llegar al guard de permisos le daría un 403 por el motivo equivocado. Registrar un eslabón en el
módulo equivocado lo puede dejar corriendo antes de que exista `request.user`, o sea muerto y en
silencio.

### 2.3 Puertos (seams) obligatorios desde el día uno

El PRD los exige; se modelan como interfaces del dominio con adapters intercambiables:

| Puerto | Para qué | Referencia PRD |
|---|---|---|
| `PsePort` | Emisión SUNAT (Nubefact/Bizlinks intercambiable) | §4 Facturación |
| `PriceResolver` | Toda lectura de precio pasa por aquí (precios por horario a futuro) | §9.bis |
| `Money` | Tipo/utilidad de dinero único (costura multi-moneda) | §9.bis |
| `IdGenerator` | UUID generado en cliente/servidor para sync | §6.C |
| `Clock` | Tiempo inyectable (timestamps, testabilidad) | §9.bis (datos ricos) |
| `PrinterPort` | Abstracción de impresión ESC/POS (vive del lado POS) | §4.bis |

### 2.4 Multi-tenancy y modelo de privilegios (crítico — maneja dinero)

Aislamiento por tenant en **dos capas**:
1. Filtro `empresa_id` automático vía extensión/middleware de Prisma (nunca a mano).
2. **Postgres Row-Level Security (RLS)** como defensa en profundidad: un `WHERE`
   olvidado no puede filtrar datos entre negocios.

Lo que sigue se aprendió construyendo, y varias de estas reglas se descubrieron **repitiendo el
error**. Se consultan **antes de escribir una migración o un guard**, no después.

#### El privilegio crece con su uso

Un rol recibe **solo lo que la HU en curso necesita**, y se amplía en la HU que lo justifica. Nunca
"por simetría" ni "ya que estamos". Concederle a un rol acceso a tablas que ningún repositorio lee
convierte una garantía de la base en una promesa sobre la buena conducta del código.

- **`GRANT` por columna cuando la columna tiene dueño.** Si una columna la gobierna otro actor —el
  estado comercial de una empresa lo fija el operador, no el dueño—, el grant se acota a las
  columnas correspondientes y se revoca el de tabla. Un `GRANT UPDATE` de tabla hace que "el
  repositorio escribe campo por campo" sea la única defensa, y un `data: { ...patch }` futuro la
  borra en silencio.
- **Políticas RLS nominales (`TO <rol>`) en vez de `BYPASSRLS`.** `BYPASSRLS` es un atributo del
  rol **entero y permanente**: cubre toda tabla, hoy y futura. Una política nominal abre exactamente
  una tabla para exactamente un rol. Se necesitan **dos llaves**: el `GRANT` (sin él la consulta no
  corre) y la política (sin ella corre y devuelve 0 filas). Conviene probar **cada una por
  separado**: quitar una y ver la suite en rojo es lo que distingue una garantía de una suposición.
- **Para leer agregados cross-tenant, función que devuelve el agregado — no `GRANT` sobre la
  tabla.** Contar filas no requiere poder leerlas. Una función `SECURITY DEFINER` que devuelve solo
  `count(*)` deja el techo puesto por Postgres; un `GRANT SELECT` lo deja puesto por qué métodos
  tiene el repositorio.

#### Funciones `SECURITY DEFINER`: el requisito de despliegue que no es obvio

Se usan cuando hace falta leer **antes de que exista contexto de tenant** (el login, un guard) o
para exponer un agregado sin conceder la tabla. Reglas:

- **Superficie mínima**: devuelven las columnas justas, nunca `SELECT *` de una tabla de negocio.
- `SET search_path = public, pg_temp` — **con `pg_temp` explícito**: si no se nombra, Postgres lo
  busca *antes* que los esquemas listados y un caller con privilegio `TEMP` puede anteponer una
  tabla suya.
- `REVOKE ALL ... FROM PUBLIC` **siempre**: Postgres concede `EXECUTE` a `PUBLIC` por defecto.
- **El dueño de la función debe ser superusuario o tener `BYPASSRLS`.** Las tablas del cimiento
  tienen `FORCE ROW LEVEL SECURITY`, y con `FORCE` la RLS alcanza **también al dueño de la tabla**:
  ser owner **no** basta. Si el dueño no es exento, las funciones **no fallan: devuelven vacío** —
  nadie puede iniciar sesión, sin decir por qué, y los agregados dan ceros verosímiles. En
  desarrollo no se nota porque el owner del contenedor es superusuario. Los dos procesos verifican
  esto **al arrancar** y se niegan a levantar si no se cumple.

#### Trampas verificadas

- **Prisma materializa los defaults del esquema del lado del cliente.** Un `@default(...)` de
  `schema.prisma` viaja **nombrado** en el `INSERT`. Consecuencia: un `GRANT INSERT (columnas)` debe
  incluir toda columna con default declarado en el esquema, o la escritura falla con `permission
  denied`. (Postgres, por su parte, **no** pide privilegio sobre una columna realmente *omitida*.)
  Si lo que se quiere es que el cliente no **elija** el valor, la herramienta correcta no es el
  grant sino una política `AS RESTRICTIVE ... WITH CHECK`.
- **El conjunto de modelos legibles sin acotar por tenant no es "los que no tienen `empresa_id`".**
  Es **"los que el lado del tenant tiene que leer"**. Son preguntas distintas: hay tablas de
  plataforma sin `empresa_id` que el tenant no debe tocar, y dejarlas fuera hace que el cliente
  falle cerrado si alguien las consulta. Agregar una "por simetría" abre esa puerta.
- **Discriminar `P2002` por `meta.target` no es confiable** con el driver adapter: vuelve
  `undefined`. Acotar el `try/catch` a la sentencia que puede chocar, en vez de inferir del mensaje.

### 2.5 Invariantes del cimiento (del PRD §6) que el código debe garantizar

- **Snapshot en `OrdenItem` y `Comprobante`**: copian precio/IGV/datos al emitir; no leen
  datos vivos del catálogo. Inmutables tras emisión.
- **Correlativo sin huecos, una serie por caja**: correlativo asignado localmente al
  emitir; número consumido siempre se rinde (anulación → nota de crédito, nunca se reusa).
- **UUID cliente** para todo lo creable offline (órdenes, pagos, movimientos de caja).
- **Dos ejes ortogonales**: `Empresa.capacidades` (operativo) vs. `Plan.features`
  (comercial). Sistemas de flags separados.

---

### 2.6 Disciplina de pruebas del backend

- **Unit y e2e separados.** Unit sin base; e2e contra Postgres real. Las suites se corren
  delegando en el sub-agente `test-runner`, con reintento para distinguir fallo real de flaky.
- **`nest build` no compila los specs.** Un error de tipos en un `.spec.ts` pasa desapercibido con
  Jest en verde: **correr `tsc --noEmit` antes de cerrar una HU**.
- **Aislamiento entre suites e2e.** Jest corre los archivos **en paralelo contra la misma base**:
  - Cada suite usa **sus propios RUC**. `createCompany` hace `upsert` por RUC y varias suites borran
    su empresa en `afterAll`, así que compartir uno hace que una le arranque la fila a otra a mitad
    de corrida. El síntoma aparece en una suite **sin relación** con la culpable, y es facilísimo
    archivarlo como flaky. Lo fija `ruc-unico.e2e-spec`.
  - Una regla que abarca **toda una tabla global** (p. ej. "no dejar cero operadores activos") no se
    puede aislar por datos: exige un **lock consultivo de Postgres** (`lockOperatorTable`), que
    serializa solo a las suites que la tocan.
  - **Antes de archivar un e2e como flaky, buscar fixtures compartidos entre archivos.**
- **Mutation-testing de cada garantía nueva.** Un test verde no prueba nada por sí solo: hay que
  saber **qué habría que romper para ponerlo rojo** — y romperlo. Vale sobre todo para lo que se
  verifica contra la base (quitar un `GRANT`, una política, el filtro por empresa) y para cualquier
  aserción que "fija" un invariante. En este proyecto ese ejercicio encontró varias pruebas que
  **no podían fallar** por el motivo que declaraban.
- **Verificar una justificación ejecutándola, no leyéndola.** Antes de escribir "esto se recupera
  con X", correr X.

---

## 3. Frontend

### 3.1 Stack

| Pieza | Elección |
|---|---|
| Framework | Angular estable (standalone components, signals, nuevo control flow) |
| Build | Vite/esbuild (application builder de Angular) |
| Monorepo | Nx + pnpm |
| Estilos | Tailwind CSS (estable) — capa de design tokens |
| Componentes | **Angular CDK + Tailwind** (base headless) + **PrimeNG** en modo unstyled |
| Estado | Angular Signals + NgRx SignalStore (estado complejo: carrito POS, cola offline) |
| Datos servidor | Cliente tipado generado del OpenAPI + TanStack Query (Angular) |
| Formularios | Reactive Forms tipados |
| Testing | Vitest/Jest (unit) + Playwright (e2e) |

### 3.2 UI: base headless + PrimeNG

- **Fundamento**: Angular CDK + Tailwind en `packages/design-system`, para la UX bespoke
  del POS (referencias CosyPOS/Vita) con control total sobre la marca.
- **PrimeNG en modo unstyled + Tailwind**: componentes con pilas para pantallas densas de
  gestión/backoffice (DataTable avanzado, formularios). Su theming pasa por los tokens de
  Tailwind, no por su tema propio.

### 3.3 Arquitectura: taxonomía de librerías Nx

Por app, separación tipo clean architecture:

| Tipo | Rol |
|---|---|
| `feature` | Componentes inteligentes (orquestan casos de uso) |
| `ui` | Componentes presentacionales puros |
| `data-access` | Stores y acceso a API (el "puerto" hacia el backend) |
| `util` | Helpers puros |

Packages compartidos: `design-system` = `ui` + tokens; `api-client` = base de
`data-access`; `shared` = `util` (dinero, permisos, formato).

### 3.4 Tema claro/oscuro

Resuelto por **design tokens** en `packages/design-system` (variables Tailwind), no por
pantalla. Preferencia recordada por usuario. Paleta de marca en `alpaqa-pos/ui/colors.jpeg`.

---

## 4. POS offline y hardware (transversal, vive en `apps/pos`)

- **PWA** (Angular service worker) instalable, mobile-first.
- **IndexedDB (Dexie)** + motor de sync con **patrón outbox** y UUIDs locales; envío a
  SUNAT vía PSE al reconectar. Idempotencia por UUID.
- **Capacitor-ready**: si se necesita acceso nativo a hardware, se envuelve la PWA en
  Capacitor sin reescribir.
- **Hardware**: Web Bluetooth / WebUSB / WebHID donde el navegador lo permita; puente o
  Capacitor como fallback. Todo detrás del servicio de impresión/captura (interfaz común).
- El detalle fino de la estrategia de sync y resolución de conflictos se define en el
  **PRD de dominio de Sincronización offline** (se genera antes de implementarlo).

---

## 5. Contrato API y cliente tipado

- Backend expone **OpenAPI** (Swagger) desde los DTOs.
- Se **genera el cliente tipado** (openapi-typescript / orval) hacia
  `packages/api-client`. Un cambio de contrato se refleja atómicamente en las tres apps.

---

## 6. Pendientes de decisión (se resuelven en su momento)

- Elección concreta del **PSE** a integrar (detrás de `PsePort`, no bloquea).
- Gestor exacto de generación de cliente OpenAPI (openapi-typescript vs orval).
- Estrategia detallada de **resolución de conflictos** de sync (PRD de offline).
- Herramienta de CI/CD y hosting por superficie.
- Billing propio del SaaS (separado del modelo de facturación de clientes).
