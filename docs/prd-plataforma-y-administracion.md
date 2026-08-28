# PRD de dominio — Plataforma y administración

> PRD de dominio (hermano de `prd-ventas-y-operacion.md`, `prd-cobros-y-caja.md`,
> `prd-facturacion-electronica.md` y `prd-catalogo-e-inventario.md`). **Referencia** el PRD maestro
> (`alcance-mvp-pos.md`) y los lineamientos técnicos para lo transversal — no los repite. Cubre los
> módulos §4 **Onboarding / configuración inicial**, **Empresa (tenant)**, **Sucursales** y
> **Usuarios y roles**.
> **No** cubre la mecánica de autenticación ya construida (login/refresh/guards/hasher, épica
> `ALPQ-15` del cimiento) ni la administración de **tenants, planes y feature gating** por parte del
> operador del SaaS (dominio *Backoffice del operador*): este dominio es la **capa de administración
> que el propio negocio ejerce sobre su tenant**.

## 0. Convención de nombres

Código en **inglés** + camelCase (modelos, campos, funciones, rutas, `code` de error), comentarios y
documentación en español — como todo el backend tras `ALPQ-24`.

**Caveat propio de este dominio:** sus tablas **no son nuevas**. `empresa`, `sucursal`, `usuario`,
`rol` y `usuario_sucursal` nacieron en el cimiento y conservan su **físico en español** vía `@map`
(`Company` → `@@map("empresa")`, `companyId` → `@map("empresa_id")`). La convención de físico inglés
aplica a **tablas nuevas**, y este dominio no crea ninguna: las columnas que agregue siguen el
físico español de su tabla (p. ej. `Branch.active` → `@map("activo")`, como ya hace `User.active`).
Cambiar ese físico sería un rename masivo con RLS de por medio, sin ganancia funcional.

---

## 1. Propósito y alcance del dominio

Dar al negocio **el control de su propio tenant**: registrarse, crear su empresa, configurar sus
datos fiscales y sus **capacidades operativas**, abrir sucursales, definir **roles** con permisos y
dar de alta a sus **usuarios** — y saber, en todo momento, **qué le falta para poder vender**.

Es el dominio que convierte al backend en un producto usable sin `seed.ts`. Hoy una empresa solo
existe si alguien la inserta a mano en la base de datos: no hay forma de crear una sucursal, un
usuario ni un rol desde la API. Todos los dominios ya construidos (catálogo, inventario, ventas,
cobros, facturación) **asumen** que ese núcleo existe y lo usan para tenancy, RLS y RBAC.

**Estructura del dominio:**

| Bloque | Contenido | Fuente maestro |
|---|---|---|
| **Registro y alta de empresa** | `POST /auth/register` (persona) → `POST /companies` (su negocio, con sucursal y rol dueño) | §4 Onboarding, §4 Empresa |
| **Empresa** | datos fiscales, régimen, `preciosConIgvIncluido`, **capacidades** (`usaMesas`/`usaCocina`/`controlaInventario`) | §4 Empresa, §7 |
| **Sucursales** | alta/edición/desactivación; cada una con inventario y caja propios | §4 Sucursales |
| **Roles y usuarios** | `Role` (permisos + `maxDiscountPct`) como **dato por-empresa**; `User` + asignación a sucursal con rol (`UserBranch`) | §4 Usuarios y roles, §5 |
| **Onboarding** | checklist **derivado** de lo que ya existe (sucursal, caja, serie, catálogo, usuarios) | §4 Onboarding |

**Invariante-guardrail del dominio:** **la autorización se verifica por permiso, nunca por nombre de
rol** (§4 maestro). Los roles son datos que cada negocio define; el código solo conoce el
**vocabulario fijo de 14 permisos** ya cerrado en `permission.ts`. Este dominio **administra** ese
vocabulario, no lo amplía por rubro. Corolario operativo: ninguna operación puede dejar a la empresa
**sin acceso a sí misma** (invariante anti-lockout, §4.2).

**Fuera de alcance (otros dominios / fase 2):**
- **Backoffice del operador**: alta/suspensión de tenants, `Plan`, `features`, facturación del SaaS
  al negocio suscriptor. `Company.estado` (trial/activo/suspendido) **se lee** aquí pero lo gobierna
  ese dominio (§7 maestro; PRD propio).
- **Feature gating por plan** (§7): este dominio construye el eje **operativo** (capacidades); el eje
  **comercial** (`Plan.features`) queda como costura, deliberadamente separado (decisión §11.4).
- **Reportes** (`ver_totales` es su permiso, ya en el vocabulario) y **Auditoría** transversal.
- Recuperación de contraseña por correo, verificación de email, 2FA, invitaciones con token: fase 2
  (§7); el MVP usa **contraseña temporal** (decisión §11.3).

---

## 2. Ubicación en la arquitectura backend

Un módulo hexagonal nuevo **`admin`** en `alpaqa-pos-backend` (lineamientos §2.2). Dominio de reglas
más que de cálculo: sus invariantes son de **consistencia organizativa** (un rol válido, un usuario
siempre alcanzable, capacidades coherentes con la operación en curso), no de dinero.

| Módulo | Estilo | Contenido |
|---|---|---|
| `admin` | **Hexagonal** | `Company`, `Branch`, `User` (administración), `Role`, `UserBranch`, onboarding |

- **Ojo con el nombre:** `src/platform/` **ya existe** y es infraestructura transversal (tenancy:
  `TenantContext`, `TenantInterceptor`, `tenant-scope`), no un módulo de dominio. Por eso el módulo
  se llama `admin` y no `platform`. Tampoco es `backoffice`, que será el dominio del **operador**.
- **Relación con `auth`:** `auth` conserva la **mecánica** (login, refresh, guards, `PasswordHasher`,
  `TokenService`, vocabulario `Permission`). `admin` es la **administración** de las mismas
  entidades. Comparten tablas, así que la frontera se traza por comportamiento: `auth` **autentica**,
  `admin` **administra**. `admin` reusa `PasswordHasher` y `TokenService` **por puerto** (ya existen
  como puertos de `auth`), sin duplicar hashing ni firma de tokens.
- **Consume** del shared kernel: `Clock`, `IdGenerator`. No usa `Money` (el único decimal es
  `maxDiscountPct`, que es porcentaje, no importe).
- **Lee** otros dominios **solo para el onboarding**, por puertos de solo lectura confinados a
  infraestructura (patrón `SalesReader` de PAY-03): cuántas cajas, series y productos hay.
- Estructura por módulo: `domain/` · `application/` · `infrastructure/`; dominio puro.

> Nombre de módulo (`admin`) y prefijo de HU (`ADM`) son **defaults** de este PRD, renombrables
> antes de scaffoldear.

---

## 3. Modelo de datos

**Este dominio casi no crea tablas: administra las que ya existen.** El núcleo tenant
(`Company`/`Branch`/`User`/`Role`/`UserBranch`) nació en la migración `init_nucleo_tenant` y ya
está en producción de todos los dominios. Aquí se documenta **lo que ya hay** y, marcado como
**CAMBIO**, lo poco que hace falta agregar.

### 3.1 Empresa (existente)

**`Company`** (`@@map("empresa")`) — la raíz del tenant:

| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | RLS: se aísla **por su propio id**, no por `empresa_id` |
| ruc | text único | único **global** (una empresa por RUC en la plataforma) |
| razonSocial / nombreComercial | text / text NULL | |
| regimenTributario | text | RER, RUS, General… (hoy texto libre) |
| preciosConIgvIncluido | boolean | default `true`; lo consume Facturación (§8 maestro) |
| estado | text | `trial` \| `activo` \| `suspendido` — **lo gobierna Backoffice** |
| usaMesas / usaCocina / controlaInventario | boolean | **capacidades** (eje operativo, §7) |

- `Company` es un **modelo compartido** en `tenant-scope.ts` (`SHARED_MODELS`): no se filtra por
  `companyId` sino por su propio `id`, y su política RLS es `id = current_setting(...)`. Cualquier
  escritura sobre la empresa vive dentro del contexto de tenant.
- Las capacidades **no** se mezclan con `Plan.features` (invariante 6 del maestro §7). Son dos ejes.

### 3.2 Sucursal (existente + CAMBIO)

**`Branch`** (`@@map("sucursal")`) — `companyId`, `name`, `address`.

- **CAMBIO (ADM-04): agregar `active` boolean** (`@map("activo")`, default `true`) para **borrado
  lógico**, el mismo patrón de catálogo y `CashRegister`. Hoy una sucursal no se puede dar de baja, y
  borrarla físicamente arrastraría en cascada stock, órdenes, cajas y comprobantes — inaceptable.
  Migración `adm04`: una columna con default seguro; `sucursal` ya tiene RLS desde el cimiento.
- **Alcance real de `active` (verificado al implementar, ADM-04):** hoy **ningún otro dominio lo
  consulta**. Ventas, Cobros, Inventario y Facturación no preguntan si la sucursal está activa
  antes de operar sobre ella, así que desactivarla la saca de los listados de administración pero
  **no bloquea la operación** en curso. Es deliberado —esta HU no toca otros módulos— pero conviene
  no llamarlo "cerrar una sucursal" hasta que esos dominios lo respeten. Costura registrada en §7.
- **CAMBIO extra (ADM-04): único `(companyId, name)`.** No estaba en el plan; se agregó por analogía
  con `rol(empresa_id, nombre)` y `caja(sucursal_id, nombre)`. La razón concreta es que el propio
  ADM-04 busca por nombre para detectar duplicados (`findByName`), y sin unicidad esa búsqueda es
  ambigua. *(La versión anterior de este párrafo decía que también afectaba «la búsqueda que usa el
  alta de empresa»; es falso: el alta **crea** la sucursal, no la busca.)* El índice es además el
  backstop real de la carrera: el adapter traduce su `P2002` a `409 BRANCH_DUPLICATE`, no a un 500.
  **Ojo con el deploy:** la migración crea el índice sin desduplicar, así que en una base con
  nombres repetidos **falla ruidosamente**, a propósito — preferible a renombrar filas en silencio.

### 3.3 Usuario (existente + CAMBIO estructural)

**`User`** (`@@map("usuario")`) — `companyId`, `name`, `email` (**único global**, es el login),
`passwordHash`, `active`.

- **CAMBIO (ADM-01): `companyId` pasa a NULLABLE.** Es la consecuencia directa de la decisión §11.1
  (registro de persona primero, empresa después): entre `POST /auth/register` y `POST /companies`
  existe un usuario **sin tenant**. Implicaciones, todas acotadas:
  - **RLS:** la política de `usuario` es `empresa_id = current_setting('app.current_empresa')`. Una
    fila con `empresa_id IS NULL` **no es visible para ningún tenant**, que es exactamente lo
    correcto: un usuario sin empresa no pertenece a nadie. No hay que relajar la política.
  - **Escritura del registro:** es una ruta **pública** y sin contexto de tenant, así que no puede
    pasar por el cliente extendido (fallaría fail-closed con `MissingTenantContextError`).
    **Corregido al implementar (ADM-01):** el camino `unscoped` de `tenant-scope` **no alcanza** —
    solo salta el filtro de Prisma, y la RLS es una capa aparte: la política de `usuario` tiene
    `WITH CHECK` y `FORCE`, así que Postgres rechaza igual un `INSERT` con `empresa_id NULL` (la
    comparación con NULL nunca es verdadera). Se resuelve como el login: una función
    **`SECURITY DEFINER`** propia de superficie mínima, `auth_register_user(name, email, hash)`,
    con `empresa_id NULL` y `activo` **fijos en el SQL** (no parametrizables), `REVOKE ALL FROM
    PUBLIC` y `GRANT EXECUTE` solo al rol de app, que sigue **sin `BYPASSRLS`**.
  - **Dueño de la función y `FORCE RLS`:** `FORCE ROW LEVEL SECURITY` aplica la política **también
    al dueño de la tabla**, salvo que sea superusuario — cierto en desarrollo, no garantizable en
    un despliegue. Para que el registro no dependa de eso, `adm01` agrega una política
    `registration_orphan_rows` acotada a `CURRENT_USER` (el rol que corre las migraciones) que
    permite insertar y releer **solo** filas con `empresa_id IS NULL` (`FOR ALL`, porque el
    `RETURNING` del `INSERT` pasa por la política de `SELECT`). El rol de app **no** la recibe:
    para un tenant las filas huérfanas siguen siendo invisibles, y eso está **probado** en el e2e
    consultando con el rol de app y una empresa activa.
  - **Cómo escribe el alta de la empresa (ADM-02):** el id se genera **antes** (`IdGenerator`),
    así la transacción puede abrir `app.current_empresa` con el tenant que está naciendo y la RLS
    aprueba cada INSERT sola (`empresa.id = current_setting(...)` y `empresa_id = ...` en las
    hijas). La primitiva vive en plataforma (`PrismaService.withNewTenant`) y **falla si ya hay
    un tenant activo**: abrir uno nuevo encima sería sombrear la empresa de la request. Por eso
    quien ya tiene empresa se rechaza en el caso de uso, antes de llegar a la persistencia.
    Vincular al usuario va por una segunda función `SECURITY DEFINER`
    (`auth_attach_user_to_company`) llamada **dentro de esa misma transacción**: su fila sigue
    huérfana y para el rol de app es invisible. Su `WHERE empresa_id IS NULL` es, además, el
    **candado atómico** del invariante «un usuario, una empresa».
  - **Unicidad de email case-insensitive:** `adm01` agrega el índice funcional
    `usuario_email_lower_key` sobre `lower(email)` — el índice de Prisma es sobre el valor crudo.
    Es la garantía dura del invariante 9 y, además, el *conflict target* del alta: el
    `ON CONFLICT DO NOTHING` devuelve cero filas en vez de lanzar `23505`, así que el email tomado
    se resuelve **atómicamente en la base**, sin carrera entre comprobar y crear.
  - **Login:** `auth_lookup_by_email` ya devuelve `empresa_id` tal cual; para este usuario vendrá
    `NULL` y **no hay que tocar la función**.
  - **Token:** `AuthenticatedUser.companyId` y los claims JWT pasan a `string | null`. El
    `TenantInterceptor` **ya** maneja ese caso: si no hay `companyId`, no abre contexto y tocar
    cualquier modelo de tenant falla fail-closed.
    **Corregido al implementar (ADM-01):** eso no basta para responder `403 NO_COMPANY`. Los
    interceptores corren **después** de los guards, y un usuario sin empresa tampoco tiene
    permisos, así que el `PermissionsGuard` lo cortaba antes con un genérico "permisos
    insuficientes" — cierto pero inútil: lo que le falta no es un permiso, es crear su negocio. El
    corte vive en un guard propio, `CompanyContextGuard`, registrado en `AuthModule` **entre**
    `JwtAuthGuard` y `PermissionsGuard` (el orden dentro del arreglo de providers de un módulo sí
    es determinista; entre módulos dependería del orden de importación).
  - Migración `adm01`: `ALTER COLUMN empresa_id DROP NOT NULL` (+ el FK sigue igual).

**`Role`** (`@@map("rol")`) — `companyId`, `name`, `permissions` (`text[]`), `maxDiscountPct`
(`numeric(5,2)` NULL). Único `(companyId, name)`.

**`UserBranch`** (`@@map("usuario_sucursal")`) — puente `userId` ↔ `branchId` ↔ `roleId`, único
`(userId, branchId)`: **un usuario tiene un rol por sucursal**, y puede tener roles distintos en
sucursales distintas. Los permisos efectivos de un login son la **unión** de los permisos de sus
roles (así lo agrega hoy `auth_lookup_by_email`).

### 3.4 Sin tablas nuevas

No hay entidad `Onboarding` (decisión §11.2: estado **derivado**) ni `Plan` (§11.4: Backoffice).
El dominio completo se implementa con **dos migraciones sin tablas nuevas** (`adm01`, `adm04`).
`adm04` sí es de una sola columna (`sucursal.activo`); `adm01` resultó más ancha de lo previsto —
además del `DROP NOT NULL` lleva el índice funcional de email, la política acotada al owner y la
función `SECURITY DEFINER` del alta (§3.3).

---

## 4. Puertos y reglas de dominio

### 4.1 Puertos que este dominio usa/implementa (lineamientos §2.3)

| Puerto | Uso |
|---|---|
| **`PasswordHasher`** (existente, de `auth`) | hash de la contraseña al registrar (ADM-01), al crear un empleado con contraseña temporal (ADM-06) y al cambiarla (ADM-07). **No se duplica** el hasher. |
| **`TokenService`** (existente, de `auth`) | reemitir el par de tokens al crear la empresa (ADM-02), cuando el `companyId` del usuario cambia de `null` a real. |
| **`Clock`** / **`IdGenerator`** | timestamps e ids. **Nota (ADM-01):** el registro **no** los usa — el id y los timestamps de la fila los pone el SQL de `auth_register_user` (`gen_random_uuid()`/`now()`), porque el alta va por función. Entran cuando el dominio cree filas por el ORM (ADM-02 en adelante). |
| **`TemporaryPasswordGenerator`** (nuevo) | genera la contraseña temporal legible del alta de empleado (ADM-06). Puerto propio y estrecho para poder fijarla en los tests. |
| **`OnboardingProbe`** (nuevo, ×3) | lectura de otros dominios para el checklist (ADM-08): ¿hay al menos una **caja** (cashbox)? ¿una **serie** por caja (billing)? ¿un **producto vendible** (catalog)? Solo lectura, confinado a infraestructura (patrón `SalesReader`/`OrderReader`). Se prefieren tres puertos pequeños y explícitos a uno genérico que se vuelva un cajón de sastre. |

### 4.2 Invariantes del dominio

1. **Autorización por permiso, nunca por nombre de rol** (§4 maestro). El código no conoce "dueño"
   ni "cajero": conoce `gestionar_usuarios`, `vender`, `cerrar_caja`… Los roles semilla son
   **ejemplos**, no un enum.
2. **Anti-lockout:** ninguna operación puede dejar a la empresa sin **al menos un usuario activo con
   `gestionar_usuarios`** en alguna sucursal. Cubre desactivar un usuario, quitarle el rol, editar el
   rol para sacarle el permiso y borrar el rol. Es la regla más importante del dominio: violarla deja
   al negocio fuera de su propia cuenta sin recuperación posible en el MVP. → `409 LAST_ADMIN`.
   **Implementado en ADM-05** para la única superficie que existe hoy (editar el rol): la cuenta es
   `countAdminsOutsideRole`, que cuenta **usuarios activos**, no asignaciones — alguien con dos roles
   en dos sucursales sigue siendo administrador por el otro, y un usuario desactivado no cuenta
   porque no puede entrar a devolverle permisos a nadie. **ADM-06 debe extender la misma regla** a
   desactivar un usuario y a reasignar sus roles: son los otros dos caminos al lockout, y hoy no
   existen como endpoint.
   **Límite conocido (precisado en la auditoría):** no hay una unidad de trabajo que abarque la
   comprobación y la escritura. Cada llamada al repositorio abre **su propia transacción**
   (`PrismaService.withTenant` → `$transaction`), así que leer el rol, contar administradores y
   escribir son tres transacciones distintas: no es que falte serializar una, es que todavía no
   existe. Dos ediciones simultáneas que quiten el permiso a dos roles administradores distintos
   podrían ver, cada una, que "queda otro" y dejar la empresa en cero. La base tampoco puede
   expresar "al menos una fila con este permiso" como constraint. Se acepta el riesgo (dos
   administradores renunciando en el mismo instante) y se deja registrado.
   **Sobre-bloqueo conocido, del lado seguro:** si el único rol con el permiso lo tienen solo
   usuarios **inactivos**, la empresa ya está sin administrador y aun así se rechaza quitárselo.
3. **Un usuario pertenece a una sola empresa** (MVP). `POST /companies` con un usuario que ya tiene
   empresa → `409 USER_ALREADY_HAS_COMPANY`. Multi-empresa por usuario es costura (§7).
4. **Sin empresa no hay operación:** un usuario autenticado con `companyId = null` solo puede usar
   `POST /companies`, `GET /auth/me` y `POST /me/password`. Cualquier otra ruta → `403 NO_COMPANY`
   (hoy fallaría con `MissingTenantContextError`; se traduce a un error de negocio legible).
5. **Permisos válidos:** `Role.permissions ⊆` vocabulario de `permission.ts` (hoy en el **kernel de
   seguridad**, `shared/domain/security/permission.ts`). Un permiso inventado → `422 ROLE_INVALID`.
   `maxDiscountPct ∈ [0, 100]` o `null`.
5.bis ~~Una sucursal activa como mínimo~~ — **regla RETIRADA en la auditoría de ADM-04.** Se había
   implementado un `409 LAST_ACTIVE_BRANCH` justificado en que desactivar la última sucursal sería
   irreversible. **Es falso:** `?includeInactive=true` existe y reactivar es libre, así que la
   operación es reversible por API en ambos sentidos. Sin esa razón queda solo la política, que
   contradice §6 («el gate "no puede vender" es de UI, no del backend; un candado adicional sería
   redundante y frágil») y que además no protege nada: **ningún dominio consulta `active`** (§3.2),
   así que desactivar todas las sucursales no impide operar — solo vacía un listado de
   administración. Cuando Ventas y Cobros respeten el flag, la regla vuelve a discutirse con un
   invariante real que proteger.
5.ter **Borrar un rol exige que nadie lo tenga** (`409 ROLE_IN_USE`, ADM-05): borrarlo con gente
   dentro les quitaría todos sus permisos de golpe y el puente `UserBranch` no sobrevive sin rol.
   Con esa regla, **borrar no puede provocar lockout**: si nadie lo tiene, nadie pierde
   `gestionar_usuarios` al borrarlo. El anti-lockout, entonces, solo hace falta al **editar**.
6. **El rol se asigna siempre junto a una sucursal** (`UserBranch`): no existe "rol global". Asignar
   un usuario a una sucursal de otra empresa, o a un rol de otra empresa → `404`.
7. **Capacidades coherentes con la operación en curso:** apagar `usaMesas` con mesas ocupadas o
   `usaCocina` con comandas pendientes → `409 CAPABILITY_IN_USE`. Encenderlas es siempre libre.
   Apagar `controlaInventario` **no** borra stock: deja de exigirlo (§4 maestro, flag por producto).
   **Precisado al implementar (ADM-03):** «comanda pendiente» = comanda **sin servir de una orden
   todavía `OPEN`**. El matiz es necesario, no cosmético: anular o cerrar una orden **no**
   transiciona sus comandas (SAL-04/05 no las tocan), así que la lectura literal —cualquier
   comanda que no llegó a `SERVED`— dejaría la cocina trabada para siempre por una comanda
   histórica, sin forma de destrabarla por API. «Mesa ocupada» no necesita ese matiz: `OCCUPIED`
   ya es un estado vivo.
8. **La empresa no se borra** desde este dominio (ni lógica ni físicamente): suspender un tenant es
   competencia de Backoffice vía `Company.estado`.
9. **Email único global y case-insensitive** (el login ya compara con `lower(email)`). Duplicado →
   `409 EMAIL_TAKEN`.
10. **La contraseña temporal se muestra una sola vez** y nunca se persiste en claro: se devuelve en
    la respuesta del alta y solo queda su hash. No hay endpoint para volver a leerla (se regenera).
11. **Multi-tenancy en dos capas** (filtro + RLS) y escrituras tenant-scoped (`updateMany`), como
    todo el backend — con la excepción **explícita y acotada** del registro público (§3.3).

### 4.3 Relación con otros dominios (costuras — se **respetan**, no se implementan aquí)

- **Todos los dominios ya construidos** dependen de este núcleo para tenancy (`companyId`), scoping
  por sucursal (`branchId`) y RBAC. Este dominio **no cambia** ese contrato: solo permite crear y
  editar los datos que ya consumen.
- **Cobros y caja / Facturación / Catálogo:** el onboarding los **lee** (¿hay caja? ¿serie?
  ¿producto?) por puerto de solo lectura. Nunca los escribe: crear la caja es PAY-01, la serie
  FAC-01 y el producto ALPQ-3. El checklist **orquesta la vista, no la creación**.
- **Ventas:** las capacidades `usaMesas`/`usaCocina` que aquí se editan son las que gatean SAL-07/08
  y SAL-09 (409 `TABLES_DISABLED`/`KITCHEN_DISABLED`). Este dominio es el **único** que las escribe.
- **Backoffice del operador:** gobierna `Company.estado` y el futuro `Plan`. La separación de los dos
  ejes (§7 maestro) se respeta desde el modelo: capacidades aquí, features allá.
- **Auditoría (transversal):** alta/baja de usuarios, cambios de rol y de capacidades son focos de
  auditoría; se registran con `Clock`/usuario desde el día uno.

---

## 5. Contrato de API (REST + OpenAPI, lineamientos §2.1/§5)

Recursos bajo el tenant autenticado (JWT + RBAC), salvo las dos rutas públicas marcadas. DTOs con
class-validator en el borde.

- **Registro (público)** — `POST /auth/register` (`{ name, email, password }`) → crea el usuario sin
  empresa y devuelve tokens (con `companyId = null`). Junto a `POST /auth/login` y
  `POST /auth/refresh` (existentes), son las **únicas** rutas públicas del backend.
- **Crear mi empresa** — `POST /companies` (autenticado, **sin permiso**: lo único que exige es no
  tener empresa todavía). Body: datos fiscales + nombre de la primera sucursal. En **una
  transacción** crea `Company` + `Branch` inicial + `Role` "dueño" (con el vocabulario completo y
  `maxDiscountPct = 100`) + `UserBranch`, y vincula al usuario. Devuelve la empresa **y un par de
  tokens nuevos** (el anterior no tiene `companyId`).
- **Empresa** — `GET /company`, `PATCH /company` (datos fiscales **salvo el RUC**),
  `PATCH /company/capabilities` (`usaMesas`/`usaCocina`/`controlaInventario`, merge parcial).
  Permiso `gestionar_configuracion`.
  **Decidido al implementar (ADM-03): el RUC no se edita.** No porque el comprobante lo
  snapshotee —no lo hace: `Comprobante` copia los datos del **cliente**, no los del emisor
  (§6.D maestro)— sino **precisamente porque no lo hace**: cambiarlo reescribiría
  retroactivamente al emisor de todo lo ya emitido ante SUNAT. Además es la identidad única
  **global** del tenant y su unicidad no se puede verificar desde dentro del tenant (la RLS
  hace invisible cualquier otra empresa, misma razón por la que el alta detecta el duplicado
  por índice). Corregir un RUC mal tipeado es competencia de *Backoffice*. La `razonSocial` sí
  es editable: es descriptiva, no la identidad fiscal.
- **Sucursales** — `GET /branches` (`?includeInactive`), `POST /branches`, `PATCH /branches/:id`
  (renombrar / dirección / `active`). Permiso `gestionar_configuracion`.
- **Roles** — `GET /roles`, `POST /roles`, `PATCH /roles/:id` (nombre, permisos, `maxDiscountPct`;
  **es un parche**: lo que no se envía se conserva, igual que en empresa y sucursales — renombrar un
  rol no puede borrarle el tope de descuento de refilón; para quitarlo se manda `null` explícito),
  `DELETE /roles/:id` (rechazado si hay usuarios asignados o si viola anti-lockout). Permiso
  `gestionar_usuarios`. `GET /permissions` devuelve el vocabulario para que la UI arme el selector.
- **Usuarios** — `GET /users`, `POST /users` (`{ name, email, branchId, roleId }` → responde
  `temporaryPassword` **una sola vez**), `PATCH /users/:id` (nombre, `active`),
  `PUT /users/:id/assignments` (reemplaza sus `UserBranch`: pares sucursal+rol),
  `POST /users/:id/reset-password` (regenera la temporal). Permiso `gestionar_usuarios`.
- **Mi cuenta** — `GET /auth/me` (existente; pasa a incluir empresa, sucursales y permisos
  efectivos), `POST /me/password` (`{ currentPassword, newPassword }`). Solo autenticación.
- **Onboarding** — `GET /onboarding/status` → pasos derivados con `done: boolean` y la ruta que los
  resuelve: empresa, ≥1 sucursal, ≥1 usuario, ≥1 caja, ≥1 serie de comprobante, ≥1 producto
  vendible. Permiso `gestionar_configuracion`.

**Permisos RBAC:** este dominio **no agrega ninguno** — estrena los que ya estaban en el vocabulario
sin usarse: `gestionar_usuarios` (usuarios y roles) y `gestionar_configuracion` (empresa, sucursales,
capacidades, onboarding). `acceso_pos` / `acceso_gestion` siguen sin verificarse en el backend: son
**gate de superficie** que la UI aplica leyendo los permisos efectivos de `/auth/me` (decisión §6).
`ver_totales` queda para Reportes.

---

## 6. Decisiones de diseño del dominio

- **Registro de persona, luego empresa** (§11.1). El alta no es un formulario monolítico: primero
  existe la persona (puede iniciar sesión, ver su estado), después crea su negocio. Es más
  personalizable y separa dos actos distintos. El costo es exactamente uno: `User.companyId`
  nullable — y el `TenantInterceptor` **ya** estaba escrito para tolerarlo.
- **Onboarding derivado, sin tabla** (§11.2). El checklist pregunta por el estado real (¿hay caja?
  ¿serie? ¿producto?) en vez de guardar banderas que pueden mentir. Cero desincronización, cero
  migraciones, y el paso se "completa" solo cuando la cosa existe de verdad.
- **El gate «no puede vender» es de UI, no del backend.** El maestro §4 lo pide como *flujo*; el
  backend ya lo hace cumplir por construcción: sin caja no hay turno (`NO_OPEN_SHIFT`), sin serie no
  hay comprobante (`NO_SERIES_FOR_REGISTER`), sin producto no hay orden. Un candado adicional sería
  redundante y frágil.
- **Contraseña temporal, no invitación por correo** (§11.3). Realista para el caso peruano —el dueño
  da de alta al cajero que tiene al lado— y evita un puerto `Mailer` con tokens de expiración que el
  MVP no necesita. La invitación por correo queda como costura.
- **`admin` reusa los puertos de `auth`, no los reimplementa.** Hashing y firma de tokens tienen un
  solo dueño. La frontera es de comportamiento (autenticar vs administrar), no de tabla.
- **Contraseña mínima de 8 caracteres (ADM-01).** Ni el PRD maestro ni los lineamientos fijaban
  política de contraseñas; se adopta ese piso como default razonable, declarado en el dominio
  (`MIN_PASSWORD_LENGTH`) y reusado por el DTO, de modo que el borde y la regla no se contradigan.
  En la práctica el `ValidationPipe` responde **400** antes de llegar al dominio; la validación de
  dominio queda como defensa en profundidad para quien llame al caso de uso sin pasar por HTTP.
  Endurecerla (longitud, complejidad, contraseñas filtradas) es fase 2.
- **Anti-lockout como invariante de dominio, no como validación de UI.** Se verifica en el use-case,
  con test propio, porque es el único error del dominio que **no tiene recuperación** para el usuario.
- **Con qué nace una empresa (ADM-02):** **sin capas opcionales y controlando inventario**
  (`usesTables: false`, `usesKitchen: false`, `tracksInventory: true`). Es el caso más común
  (bodega/tienda) y el que menos sorprende: mesas y cocina se encienden a mano cuando el rubro
  las pide. Ojo: el default **de la columna** en la base es `controla_inventario = false`
  (cimiento); el alta lo fija explícitamente, no lo hereda.
- **El rol dueño descuenta sin tope** (`maxDiscountPct = 100`). Es política de negocio —viaja
  por el puerto como dato, junto al nombre del rol y sus permisos—, no un default de
  persistencia.
- **Los roles semilla se crean, no se hardcodean.** `POST /companies` crea el rol "dueño" como
  **dato**; el negocio puede renombrarlo o crear los suyos. El código nunca lo busca por nombre.

---

## 7. Costuras dejadas abiertas (diseñar ahora, construir después — §9.bis)

- **Invitación por correo** con token de activación y **recuperación de contraseña**: requieren un
  puerto `Mailer` (patrón `ComprobanteDelivery` de FAC-06, con adapter stub). El modelo no cambia.
- **Un usuario en varias empresas** (contador que atiende a varios negocios): hoy `User.companyId` es
  uno solo; el puente `UserBranch` ya soporta múltiples sucursales, así que la generalización es
  mover la pertenencia al puente. No en el MVP (§4.2 inv. 3).
- **`Plan` y feature gating** (§7 maestro): el eje comercial completo, incluido `Company.planId`,
  lo construye *Backoffice del operador*. Las capacidades ya están separadas para que enchufe sin
  rediseño.
- **`regimenTributario` como enum** (hoy texto libre) y el flag de **Nuevo RUS** que Facturación
  necesita para no desglosar IGV en el documento (deuda registrada en `prd-facturacion-electronica.md`
  §12).
- **Que los dominios operativos respeten `Branch.active`**: hoy solo filtra listados de
  administración (§3.2). Cuando Ventas/Cobros/Inventario lo consulten, desactivar una sucursal
  pasará de ser una señal a ser un candado — y ahí conviene revisar qué pasa con turnos y órdenes
  abiertas de esa sucursal, igual que se hizo con las capacidades en ADM-03.
- **Auditoría de cambios administrativos** (quién cambió qué rol y cuándo): el dominio transversal de
  Auditoría; aquí ya se registran `Clock` y usuario.
- **2FA / verificación de email**: fase 2 (§9 maestro).

---

## 8. Decisiones del dominio cerradas

- Módulo hexagonal **`admin`** (no `platform`, que ya es la infra de tenancy), prefijo de HU **`ADM`**.
- **Registro público de persona → creación de empresa** por el propio usuario, en dos actos.
- **`User.companyId` nullable** como única concesión estructural; RLS **sin relajar**.
- **Onboarding derivado**, sin tabla ni estado persistido.
- **Contraseña temporal** devuelta una vez; sin correo en el MVP.
- **Anti-lockout** como invariante duro del dominio.
- **`Branch.active`** para borrado lógico (nunca borrado físico).
- **Sin permisos nuevos**: estrena `gestionar_usuarios` y `gestionar_configuracion`.
- **Físico en español** en estas tablas (heredado, `ALPQ-24`); las columnas nuevas lo respetan.
- **Plan / feature gating diferido** entero a *Backoffice del operador*.

---

## 9. Mapa HU → entregable técnico

**Registro y alta:**
| HU (código) | Entregable principal |
|---|---|
| `ADM-01` | Registro público (`POST /auth/register`): `User.companyId` nullable (migración `adm01`), camino unscoped, token sin `companyId`, `403 NO_COMPANY` en rutas de tenant |
| `ADM-02` | `POST /companies`: empresa + sucursal inicial + rol dueño + `UserBranch` en una transacción; reemisión de tokens; un usuario, una empresa |

**Configuración del negocio:**
| HU | Entregable |
|---|---|
| `ADM-03` | `GET/PATCH /company` + `PATCH /company/capabilities` (merge parcial, VO de capacidades; `409 CAPABILITY_IN_USE`) |
| `ADM-04` | Sucursales CRUD + `Branch.active` (migración `adm04`, borrado lógico) |

**Personas y accesos:**
| HU | Entregable |
|---|---|
| `ADM-05` | Roles CRUD + `GET /permissions`; validación `permissions ⊆` vocabulario y `maxDiscountPct ∈ [0,100]`; anti-lockout al editar/borrar |
| `ADM-06` | Usuarios CRUD + contraseña temporal (`TemporaryPasswordGenerator`) + asignaciones sucursal/rol; anti-lockout al desactivar/reasignar |
| `ADM-07` | Mi cuenta: `POST /me/password` y `GET /auth/me` enriquecido (empresa, sucursales, permisos efectivos) |

**Cierre del dominio:**
| HU | Entregable |
|---|---|
| `ADM-08` | `GET /onboarding/status` derivado, con los tres puertos `OnboardingProbe` (caja, serie, producto) |

> Códigos `ADM-0x` = etiqueta de orden que reinicia por segmento (convención vigente); el
> id/referencia de cada HU es su clave Jira `ALPQ-N` (se asigna al crear la épica).

---

## 10. Prerrequisitos y orden de implementación

**Prerrequisito duro (ya cumplido):** el cimiento (`ALPQ-15`..`ALPQ-23`) dejó el núcleo tenant
modelado con RLS en dos capas, el vocabulario de permisos, los guards, `PasswordHasher` y
`TokenService`. Los cuatro dominios funcionales ya construidos definen qué se consulta en el
onboarding (caja PAY-01, serie FAC-01, producto ALPQ-3).

**Orden sugerido (entrar por la puerta, salir por el checklist):**
`ADM-01 → ADM-02` (una persona real puede crear su negocio y dejar de depender del seed) →
`ADM-03 → ADM-04` (configura su empresa y sus sucursales) → `ADM-05 → ADM-06` (define roles y suma a
su gente) → `ADM-07` (cada quien administra su acceso) → `ADM-08` (el checklist que amarra todo).
Cada HU con el ritual de cierre (auditoría `audit-plan` + `audit-arquitectura` → suites vía
`test-runner` → commit sin coautoría → push → mover el ticket en Jira).

**Riesgo a vigilar:** `ADM-01` toca `tenant-scope`/`AuthenticatedUser`/JWT, que son **transversales**
— los usan los seis módulos. Es la HU de mayor radio de impacto del dominio; conviene auditarla con
especial cuidado y correr la suite completa (unit + e2e) antes de seguir.

---

## 11. Decisiones confirmadas con el usuario (ago-2026)

1. **La empresa la crea el usuario, previo registro.** Primero se registra la persona en la
   plataforma; ya autenticada, **ella** crea su empresa, "para que sea más personalizado". No es alta
   por el operador ni un signup monolítico. Consecuencia asumida: `User.companyId` nullable (§3.3).
2. **Onboarding con estado derivado, sin tabla.** `GET /onboarding/status` calcula los pasos leyendo
   el estado real; el gate «no puede vender» se documenta como regla de UI (§6).
3. **Contraseña temporal + cambio propio.** El admin da de alta al empleado y la API devuelve la
   contraseña temporal **una sola vez**; `POST /me/password` para cambiarla. Sin puerto de correo.
4. **`Plan` / feature gating: diferido entero a Backoffice.** Este dominio solo modela el eje
   operativo (capacidades, ya existentes) y deja `Plan.features` como costura documentada.
