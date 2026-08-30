# PRD de dominio — Backoffice del operador

> PRD de dominio (hermano de `prd-plataforma-y-administracion.md`, `prd-ventas-y-operacion.md`,
> `prd-cobros-y-caja.md`, `prd-facturacion-electronica.md` y `prd-catalogo-e-inventario.md`).
> **Referencia** el PRD maestro (`alcance-mvp-pos.md`) y los lineamientos técnicos para lo
> transversal — no los repite. Cubre la superficie §2.1 **Backoffice del operador** y el eje
> comercial del §7 (`Plan.features`).
> **No** cubre la administración que el negocio hace de su propio tenant (dominio *Plataforma y
> administración*, cerrado: empresa, sucursales, usuarios, roles). Aquí el actor es **el operador
> del SaaS**, no el dueño del negocio.

## 0. Convención de nombres

Código en **inglés** + camelCase; comentarios y documentación en español.

**Físico en inglés `snake_case`** para las tablas nuevas (`operator_user`, `plan`), como en
*Ventas*, *Cobros* y *Facturación*. Las columnas que se agreguen a tablas heredadas conservan el
físico español de su tabla (`empresa.plan_id`), igual que hizo ADM-04 con `sucursal.activo`.

---

## 1. Propósito y alcance del dominio

Darle al **operador del SaaS** —nosotros— la herramienta para administrar los negocios que usan
alpaqa-pos: darlos de alta, suspenderlos, asignarles un plan y ver cómo va la plataforma. Nunca la
ve un cliente (§2.1 maestro).

**Este dominio invierte la premisa de los otros cinco.** Todo el backend está construido para que
un tenant no pueda ver a otro: filtro automático por `companyId` más RLS en Postgres, y sin
contexto de empresa las consultas fallan cerrado. El operador necesita exactamente lo contrario:
leer y escribir **a través de todos los tenants**. El diseño de este dominio es, sobre todo, la
respuesta a cómo hacer eso **sin debilitar el aislamiento del que dependen los otros cinco**.

**Estructura del dominio:**

| Bloque | Contenido | Fuente maestro |
|---|---|---|
| **Operadores** | `OperatorUser` con login propio y tokens de audiencia separada | §2.1 |
| **Tenants** | listado y ficha de empresas (metadatos), alta de estado, suspensión **con efecto** | §2.1, §4 Empresa |
| **Planes** | `Plan` (código, nombre, `features`) y su asignación a una empresa | §7, §2.1 |
| **Métricas** | agregados por tenant y globales, **derivados** | §2.1 |

**Invariante-guardrail del dominio:** el operador ve **metadatos del tenant, nunca el contenido del
negocio**. Ni órdenes, ni comprobantes, ni clientes, ni productos: cuántos hay, no cuáles son. El
día que haga falta soporte real sobre datos, entra con su propio rastro de auditoría y su propia
discusión (§7).

**Fuera de alcance (fase 2 / otros dominios):**
- **Billing propio del SaaS** (cómo se le cobra al negocio suscriptor): §9 maestro lo deja para
  definir aparte y **no se confunde** con *Facturación electrónica*, que es cómo el negocio le
  factura a sus clientes.
- **Gating efectivo por plan**: se modela y se asigna, pero todavía no bloquea funciones
  (decisión §11.3).
- **Soporte sobre datos del negocio e impersonación**: fuera del MVP (decisión §11.4).
- **RBAC interno del operador**: en el MVP todos los operadores pueden todo (§6).

---

## 2. Ubicación en la arquitectura backend

Un módulo hexagonal nuevo **`backoffice`** en `alpaqa-pos-backend` (lineamientos §2.2), que corre
como **proceso aparte** del de tenant.

**Dos desplegables, un repositorio** (decidido al construir BKO-01). `AppModule` monta los seis
dominios de tenant; `BackofficeAppModule` monta solo este módulo más config y el shared kernel — ni
`PlatformModule`, ni `AuthModule`, ni una sola ruta de negocio. El proceso de tenant **no carga** la
credencial que cruza empresas, y arranca sin siquiera tener esas variables de entorno (probado en
e2e y verificado arrancando el binario sin ellas).

La razón no es acoplamiento: el módulo no importa nada de los otros dominios y nada lo importa a él.
Es el **radio de daño de la credencial**: la API de tenant es la superficie grande y expuesta, y un
fallo ahí no debe entregar una conexión capaz de leer todas las empresas.

Lo que **no** se separa: repositorio, esquema y migraciones. Este dominio modifica tablas de tenant
(BKO-04 cambia `empresa.estado`, BKO-05 agrega `empresa.plan_id`), así que el historial de
migraciones tiene un solo dueño.

| Módulo | Estilo | Contenido |
|---|---|---|
| `backoffice` | **Hexagonal** | `OperatorUser`, `Plan`, y la vista de `Company` como *tenant* |

- **Consume** del kernel de seguridad: `PasswordHasher` y `TokenService` (puertos, no adapters);
  `Clock` e `IdGenerator` del shared kernel.
- **No consume** ningún módulo de dominio. Lee `Company` por su propio repositorio, con su propia
  conexión (§2.1 de este PRD). No importa `admin` ni al revés.
- **Expone** el estado del tenant para que la cadena de guards lo haga cumplir (§4.2 inv. 4).
- Estructura por módulo: `domain/` · `application/` · `infrastructure/`; dominio puro.

> Nombre de módulo (`backoffice`) y prefijo de HU (`BKO`) son **defaults** de este PRD.

### 2.1 La segunda conexión — cómo se cruza el aislamiento

**Decisión (§11.2, revisada en BKO-03): un rol de base de datos propio y un cliente Prisma
separado**, usados **solo** por este módulo. **Sin `BYPASSRLS`**: el acceso cross-tenant se abre
tabla por tabla.

```
alpaqa_app          → sin BYPASSRLS, RLS activa. Lo usan los seis módulos de tenant.
alpaqa_backoffice   → sin BYPASSRLS tampoco. Lo usa únicamente el módulo backoffice, y solo
                      alcanza las tablas que una HU le abrió explícitamente.
```

**Por qué se revisó** (confirmado con el usuario el 2026-08-29, al implementar BKO-03): `BYPASSRLS`
es un atributo del **rol entero y permanente**, así que cubriría toda tabla, hoy y en el futuro —
incluidas `order`, `comprobante`, `customer`. El invariante 6 («el operador ve metadatos, nunca
contenido») quedaría sostenido solo por qué métodos tiene el repositorio, que es un guardrail de
código. Abriendo tabla por tabla, el encierro lo sostiene Postgres.

Cada apertura son **dos llaves que giran juntas**, y se probaron por separado quitando cada una:

1. el `GRANT`, sin el cual la consulta ni siquiera corre (`permission denied`);
2. una **política RLS nominal para el rol**, sin la cual la consulta corre y devuelve **0 filas**
   —la tabla tiene RLS y la política del cimiento exige `app.current_empresa`, que el backoffice
   nunca fija—.

Efecto lateral buscado: migrar ya no exige superusuario (`ALTER ROLE ... BYPASSRLS` sí lo exige, y
en producción el rol de migración puede no serlo).

Por qué así y no de otra forma:

- **No toca lo existente.** `alpaqa_app` sigue exactamente igual de encerrado; ninguna política se
  relaja. Si mañana este módulo desaparece, el aislamiento del resto no cambió.
- **El privilegio es explícito y auditable.** Está en un `GRANT` y en una variable de entorno
  (`DATABASE_URL_BACKOFFICE`), no escondido en una bandera de código que alguien pueda activar por
  accidente desde un caso de uso de tenant.
- **La alternativa de funciones `SECURITY DEFINER`** —la que usamos para el registro y el login—
  no escala aquí: aquellas son operaciones puntuales y cerradas; el backoffice hace consultas
  variables (listar, filtrar, contar, ordenar) y terminaría en decenas de funciones o en una
  genérica tan ancha que el `SECURITY DEFINER` dejaría de ser una superficie mínima.
- **La alternativa de una bandera en el `TenantContext`** salta el filtro de Prisma pero **no la
  RLS**: seguiría siendo el mismo rol, así que habría que relajar políticas —y eso sí debilita el
  aislamiento de todos.

**Contención del riesgo (obligatorio, no opcional):**
1. El cliente se inyecta con un token propio (`BACKOFFICE_PRISMA`) y **solo** el
   `BackofficeModule` lo declara, sin exportarlo. Ningún otro módulo puede alcanzarlo por
   accidente; hacerlo exige declararlo a mano.
2. Una **regla de ESLint** prohíbe importar el cliente desde fuera del módulo: la contención deja
   de depender de disciplina y pasa a fallar en el build.
3. `PrismaService` —el de siempre— no cambia: los seis módulos de tenant siguen usando el rol
   encerrado.
4. Los repositorios del backoffice **no exponen** métodos que devuelvan contenido de negocio
   (invariante-guardrail): su superficie es la que este PRD enumera y nada más.
5. **Dos procesos, no dos prefijos** (decidido durante BKO-01). El backoffice es un desplegable
   aparte (`main-backoffice.ts`), no un módulo más del proceso de tenant: la credencial que puede
   cruzar empresas no se carga en la superficie grande y expuesta. Un test enumera el router del
   proceso de tenant y exige **cero** rutas `/backoffice`.
6. **El entorno se separó junto con los procesos** (corregido en la auditoría de BKO-02). Separar
   los procesos sin separar las variables no acotaba nada: el despliegue del backoffice seguía
   obligado a llevar `DATABASE_URL` —la conexión del **owner**, que evade RLS— solo para pasar la
   validación de arranque. Ahora hay **un perfil de validación por proceso**: cada uno exige lo
   suyo y ninguno el del otro. Verificado arrancando ambos binarios con `.env` disjuntos.
7. **El privilegio crece con su uso** (corregido en la auditoría de BKO-01, extendido en BKO-03).
   El rol se crea en BKO-01 con permiso solo sobre `operator_user`. BKO-03 le suma **`SELECT`
   sobre `empresa` y nada más**: ni `UPDATE` (eso es BKO-04, con su propia política de escritura),
   ni acceso a ninguna otra tabla. BKO-06 abrirá, una línea por tabla, solo lo que necesite
   contar.

---

## 3. Modelo de datos

Dos tablas nuevas y dos cambios en `empresa`.

### 3.1 Operadores

**`OperatorUser`** (`@@map("operator_user")`) — quien administra la plataforma:

| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| name | text | |
| email | text único | único **global**; es la llave del login del operador |
| passwordHash | text | mismo `PasswordHasher` del kernel |
| active | boolean | borrado lógico |
| createdAt / updatedAt | timestamp | |

- **No tiene `companyId`, ni rol, ni sucursal.** Un operador no es "un usuario de alguna empresa":
  es de la plataforma. Por eso vive en su propia tabla y no en `usuario` con una bandera — mezclar
  dos poblaciones con reglas opuestas en la misma tabla y el mismo login es cómo un bug filtra
  super-admin a un tenant (decisión §11.1).
- **Sin RLS**: no es una tabla de tenant. Sí `GRANT` acotado: `alpaqa_backoffice` la usa;
  `alpaqa_app` **no la necesita y no la recibe**.
- Unicidad case-insensitive por índice funcional `lower(email)`, igual que `usuario` (ADM-01).

### 3.2 Planes

**`Plan`** (`@@map("plan")`) — el eje **comercial** (§7 maestro):

| Campo | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| code | text único | `basico`, `pro`… estable, apto para referenciar desde código |
| name | text | nombre comercial |
| features | text[] | banderas del plan; vocabulario abierto **por ahora** (§4.2 inv. 5) |
| active | boolean | borrado lógico; un plan retirado no se asigna pero los que lo tienen lo conservan |

- Va en `SHARED_MODELS` de `tenant-scope` (como `Company`): no es tabla de tenant y no lleva
  `empresa_id`. El código ya lo anticipaba — el comentario de `tenant-scope.ts` menciona `Plan`
  como ejemplo de tabla de plataforma futura.

### 3.3 Cambios en `empresa`

- **HECHO (BKO-04): `estado` pasó de texto libre a enum** `CompanyStatus {TRIAL, ACTIVE,
  SUSPENDED}` (físico `estado`, valores migrados desde `'trial' | 'activo' | 'suspendido'`).
  Era una cadena que nadie validaba; desde que un guard **depende** de ella, un `'Suspendido'` con
  mayúscula habría sido un tenant suspendido que sigue operando. La migración convierte con
  `lower(trim(...))` y deja el default en `TRIAL`.

  **La migración frena si encuentra un valor que no sabe traducir**, en vez de caer en un
  `ELSE 'TRIAL'`. Un valor sucio que significaba "suspendido" se habría vuelto un tenant operativo
  en silencio y sin forma de detectarlo después; es preferible que falle y que alguien mire.
- **CAMBIO (BKO-05): `planId` uuid NULL FK → `Plan`** (`@map("plan_id")`). Nullable a propósito: un
  tenant en `TRIAL` puede no tener plan, y un plan no puede ser obligatorio antes de que exista el
  primero.

### 3.4 Sin tablas de métricas

Las métricas son **derivadas**, no persistidas (misma decisión que el onboarding en ADM-08): se
cuentan al consultarlas. Un contador materializado se desincroniza y hay que mantenerlo; para el
volumen del MVP, `count` por tenant alcanza. Si el costo aparece, la costura es una vista
materializada, no un rediseño (§7).

---

## 4. Puertos y reglas de dominio

### 4.1 Puertos que este dominio usa/implementa (lineamientos §2.3)

| Puerto | Uso |
|---|---|
| **`PasswordHasher`** (kernel) | hash de la contraseña del operador. Mismo algoritmo que los usuarios de tenant. |
| **`TokenService`** (kernel) | emite el par de tokens del operador. **Con secreto propio** — ver §4.2 inv. 2. |
| **`Clock`** / **`IdGenerator`** | timestamps e ids. |
| **`OperatorUserRepository`** (nuevo) | alta y búsqueda de operadores; login. |
| **`TenantRepository`** (nuevo) | lista y ficha de empresas **a través de tenants**; cambia estado y plan. Es el puerto que justifica la segunda conexión. |
| **`PlanRepository`** (nuevo) | CRUD de planes. |
| **`TenantMetricsReader`** (nuevo) | agregados por tenant y globales. **Solo cuenta**, no devuelve filas de negocio. |
| **`CompanyStatusReader`** (BKO-04, del lado del tenant) | lo consume la cadena de guards para cortar a un tenant suspendido. Vive en `platform/tenancy`, no en este módulo: quien lo usa es la infraestructura transversal, y `platform` no puede depender de un módulo de dominio. **Lee por una función `SECURITY DEFINER`** (`company_status`), no por el modelo Prisma: los guards corren **antes** que el `TenantInterceptor`, así que todavía no existe `app.current_empresa` y la RLS de `empresa` devolvería 0 filas. Es la misma situación del login, resuelta igual y con la misma superficie mínima: una columna de una fila, y `EXECUTE` para el rol de app. **Requisito de despliegue (ver §7)**: el dueño de esa función debe ser superusuario o tener `BYPASSRLS`. |

### 4.2 Invariantes del dominio

1. **El operador no pertenece a ninguna empresa.** `OperatorUser` no tiene `companyId`; sus tokens
   no llevan claim de empresa y sus rutas nunca abren contexto de tenant.
2. **Los dos mundos de tokens no se cruzan.** El token de operador se firma con un **secreto
   distinto** (`JWT_OPERATOR_SECRET`) del de los usuarios de tenant. No es cosmético: si
   compartieran secreto, un token de operador —que no lleva empresa— sería indistinguible de un
   usuario recién registrado sin empresa, y entraría por las rutas marcadas `@AllowsNoCompany()`.
   Con secretos distintos, cada guard **no puede** verificar los tokens del otro mundo.
   **Verificado al arrancar (BKO-01):** la validación de entorno exige que los cuatro secretos de
   firma sean distintos entre sí y la app no levanta si dos coinciden. El invariante dependía de
   que nadie copiara y pegara una variable; ahora falla ruidoso.
3. **La conexión que cruza empresas es exclusiva de este módulo** (§2.1) — y **no** usa `BYPASSRLS`:
   alcanza solo las tablas que una HU le abrió, con `GRANT` + política nominal. Ningún caso de uso
   de tenant la alcanza: el token de inyección no se exporta, una regla de ESLint prohíbe importar
   el cliente desde fuera del módulo, y el proceso de tenant ni siquiera lo carga.
4. **Suspender tiene efecto** (BKO-04, construido). Un tenant en `SUSPENDED` no opera: la cadena de
   guards corta sus requests con `403 TENANT_SUSPENDED`. Se verifica **por request contra la base**,
   no desde el token: una suspensión que tarda lo que tarda en expirar un access token (15 min) no
   es una suspensión. Excepción deliberada, marcada con `@AllowsSuspended()` y con lista corta:
   `GET /auth/me`, `GET /me` y `POST /me/password`, para que el dueño no quede encerrado fuera de su
   propia cuenta mientras negocia con nosotros. El login sigue abierto por ser ruta pública.

   **El orden en la cadena es portante**: el `TenantStatusGuard` va entre `CompanyContextGuard` y
   `PermissionsGuard`. Un suspendido tiene permisos perfectamente válidos, así que dejarlo llegar al
   guard de permisos le daría un 403 por el motivo equivocado. Hay un test que fija ese orden —se
   pone rojo si el guard se registra después—, y tres mutaciones verificadas: sacar el guard, moverlo
   de lugar y leer el estado de una constante en vez de la base ponen roja una prueba distinta cada
   una.

   **La lista de excepciones está cerrada por test**, no por disciplina: un e2e descubre los
   handlers reales de la app y exige que el conjunto marcado sea exactamente esos tres. Marcar una
   cuarta ruta pone la suite en rojo — verificado marcando una ruta de negocio.
5. **El plan se asigna pero todavía no bloquea** (decisión §11.3). `features` es hoy un vocabulario
   **abierto**: se guarda lo que el operador escriba. Cuando el gating se active, ese vocabulario
   pasa a ser cerrado y verificado —como `Permission`—, y esa es exactamente la HU que lo cierra.
6. **El operador ve metadatos, no contenido.** Los puertos de este módulo no exponen ni una fila de
   `order`, `comprobante`, `customer` o `product`: solo conteos.
7. **El primer operador no se autoservi­cia.** No hay registro público: se siembra por seed/CLI, y
   desde ahí un operador da de alta a los demás (§6).
8. **Dinero:** este dominio no mueve importes en el MVP (el precio del plan es del billing propio
   del SaaS, fuera de alcance). Si entra, va por `Money`.

### 4.3 Relación con otros dominios (costuras — se **respetan**, no se implementan aquí)

- **Plataforma y administración:** gobierna lo que el negocio decide de sí mismo (datos fiscales,
  capacidades, sucursales, usuarios, roles). Este dominio gobierna lo que **nosotros** decidimos
  sobre él (estado, plan). Los dos ejes del §7 maestro quedan finalmente completos: capacidades =
  operativo del dueño, `Plan.features` = comercial del operador. `Company.estado` deja de ser un
  campo decorativo y pasa a tener dueño.
- **Todos los dominios de tenant:** el guard de suspensión los afecta a todos por igual, y por eso
  vive en la cadena de guards y no en cada módulo.
- **Auditoría (transversal):** quién suspendió a quién y cuándo es el caso de auditoría más nítido
  de todo el producto. Este dominio **no** lo construye (no existe el dominio de Auditoría todavía),
  pero deja el actor disponible en cada caso de uso para engancharlo sin rediseñar (§7).

---

## 5. Contrato de API (REST + OpenAPI, lineamientos §2.1/§5)

Todas bajo el prefijo **`/backoffice`**, con el guard de operador. Ninguna acepta tokens de tenant.

**El default del borde importa** (corregido en la auditoría de BKO-01): una ruta bajo `/backoffice`
sin decorar **no** queda denegada. Al separar los procesos, además, el modo de fallo cambió y
empeoró: el proceso de backoffice no monta `AuthModule`, que es quien registra el guard global, así
que una ruta sin decorar hoy queda **anónima** —antes la habría alcanzado un token de empresa
válido—. Por eso las rutas autenticadas viven en controladores con `@OperatorRoute()` **a nivel de
clase** (el decorador compuesto: separar `SkipTenantAuth` del guard permite copiar la mitad
peligrosa), las dos anónimas (`auth/login`, `auth/refresh`) están aisladas en el suyo, y un test
enumera las rutas del router en tiempo de ejecución para exigir que ninguna quede expuesta. Los
endpoints de BKO-02..06 quedan cubiertos sin tocar ese test.

- **Acceso** — `POST /backoffice/auth/login` (público), `POST /backoffice/auth/refresh` (público),
  `GET /backoffice/me`.
- **Operadores** — `GET /backoffice/operators`, `POST /backoffice/operators` (alta con contraseña
  temporal, mismo patrón que ADM-06), `PATCH /backoffice/operators/:id` (nombre, `active`).
  **Anti-lockout `LAST_OPERATOR`** (evaluado y construido en BKO-02): desactivar al último operador
  activo devuelve 409. Es el análogo de `LAST_ADMIN` y aquí es más caro, porque no hay registro
  público de operadores ni administrador por encima: recuperarse exige tocar la base con el rol
  owner. No es la sobre-construcción que sí fue `LAST_ACTIVE_BRANCH` en ADM-04 —aquella se retiró
  porque nadie leía el flag—; `active` aquí lo leen el guard y el login en cada request.
- **Tenants** — `GET /backoffice/tenants` (listado con filtro por estado y búsqueda por RUC o razón
  social), `GET /backoffice/tenants/:id` (ficha: metadatos + plan + métricas del tenant; **BKO-03
  entrega los metadatos** —datos fiscales, estado, capacidades y fecha de alta—, el plan se suma en
  BKO-05 y las métricas en BKO-06),
  `PATCH /backoffice/tenants/:id/status` (`{ status }` → **`ACTIVE` o `SUSPENDED`**; `TRIAL` no es
  asignable: es el estado con el que un tenant nace, no un destino al que devolverlo),
  `PUT /backoffice/tenants/:id/plan` (`{ planId | null }`).
- **Planes** — `GET /backoffice/plans`, `POST /backoffice/plans`, `PATCH /backoffice/plans/:id`
  (nombre, `features`, `active`).
- **Métricas** — `GET /backoffice/metrics` (agregados globales: tenants por estado, altas por
  período, totales de la plataforma).

**Permisos RBAC:** ninguno del vocabulario de tenant aplica aquí. La autorización del backoffice es
**binaria**: se es operador o no se es, y lo resuelve el guard propio (§6).

---

## 6. Decisiones de diseño del dominio

- **Dos poblaciones, dos tablas, dos secretos.** Un operador y un cajero no comparten nada salvo
  que ambos se loguean. Separarlos en tabla, login y secreto de firma hace que "filtrar super-admin
  a un tenant" no sea un bug posible, sino un imposible estructural.
- **Acceso cross-tenant acotado a una conexión y abierto tabla por tabla** en vez de un privilegio
  de rol: queda en `GRANT`s y políticas nominales, no en una bandera de código ni en un atributo
  que cubra lo que todavía no existe (§2.1).
- **Suspender bloquea de verdad, y se lee por request.** El costo es una consulta indexada por PK
  por request; el beneficio es que la suspensión es inmediata. Cachearla es una optimización
  posterior, con invalidación explícita al cambiar el estado.
- **La cuenta propia sobrevive a la suspensión.** Un dueño suspendido puede entrar y cambiar su
  contraseña, pero no operar. Encerrarlo fuera de su cuenta no aporta nada y complica el soporte.
- **Sin RBAC interno del operador en el MVP:** todos pueden todo. Somos pocos y conocidos. El día
  que exista "soporte que solo lee", entra un rol — y el modelo no cambia, se agrega.
- **El primer operador se siembra.** No hay registro público de operadores por la misma razón por
  la que no hay "crear super-admin" en ningún producto serio: el bootstrap es un acto de
  despliegue, no una ruta HTTP.
- **La contraseña temporal es una capacidad de plataforma, no de un dominio.** Al ser el
  backoffice su segundo consumidor (el primero fue ADM-06), el generador y la política de
  contraseña se promovieron al kernel compartido en vez de duplicarse. Mismo criterio que se usó
  con `PasswordHasher` y `TokenService`.
- **Métricas derivadas** (§3.4), como el onboarding: se cuentan al preguntar.

---

## 7. Costuras dejadas abiertas (diseñar ahora, construir después — §9.bis)

- **Gating efectivo por plan:** `Plan.features` ya se asigna; falta el guard que lo verifique y
  cerrar el vocabulario de features. Es la continuación natural de este dominio.
- **Billing propio del SaaS** (§9 maestro): cobrarle al negocio suscriptor. `Plan` es el ancla
  natural, pero el modelo de cobro es otra discusión.
- **Soporte sobre datos e impersonación** (§11.4): hoy el operador ve metadatos. Habilitar lectura
  de negocio exige rastro de auditoría **antes**, no después.
- **Rastro de auditoría** de las acciones del operador: suspender es la acción más sensible del
  producto. Lo construye el dominio de Auditoría; aquí el actor ya está disponible en cada caso de
  uso.
- **Requisito de despliegue de las funciones `SECURITY DEFINER`.** `empresa` tiene `FORCE ROW
  LEVEL SECURITY`, y con `FORCE` la RLS alcanza **también al dueño de la tabla**: ser owner **no**
  basta para evadirla. El dueño de `company_status` —y de `auth_lookup_by_email`, que depende de lo
  mismo desde el cimiento— tiene que ser superusuario o tener `BYPASSRLS`. Si no lo es, la función
  devuelve `NULL` y la cadena de guards rechaza **toda** request autenticada, culpando al token.
  Verificado a mano cambiándole el dueño a la función. No es nuevo de BKO-04 —sin esto tampoco se
  puede iniciar sesión—, pero BKO-04 lo pone en el camino de cada request, así que hay un smoke que
  lo detecta (`tenant-suspension.e2e-spec`). **Matiza lo dicho en §2.1**: lo que BKO-03 dejó de
  exigir es superusuario para *migrar*; las funciones `SECURITY DEFINER` sí necesitan un dueño
  exento.
- **Paginación del listado de tenants.** `GET /backoffice/tenants` no pagina (BKO-03): es el único
  listado del producto cuyo tamaño crece con **toda la plataforma** y no con un tenant. Con decenas
  de empresas no molesta; conviene resolverlo antes de que esa sea la pantalla de entrada del
  backoffice, y a más tardar junto con BKO-06.
- **El `GRANT` de *lectura* es por tabla, no por columna.** BKO-04 saldó las dos mitades de
  escritura: el operador solo puede escribir `("estado", "updated_at")`, y el **dueño** perdió el
  `UPDATE` de tabla entera sobre `empresa` —se re-otorgó columna por columna, sin `estado`—, así
  que "el tenant no se auto-reactiva" dejó de depender de que el repositorio escriba campo por
  campo. El `SELECT` del operador, en cambio, sigue siendo de tabla entera: lo que ve lo recortan
  el `select` del repositorio y el DTO, no Postgres. A tener presente al agregarle columnas a
  `empresa` (BKO-05 le suma `plan_id`).
- **Métricas materializadas** si el `count` por tenant deja de alcanzar (§3.4).
- **RBAC interno del operador** cuando haya más de un tipo de operador (§6).

---

## 8. Decisiones del dominio cerradas

- Módulo hexagonal **`backoffice`**, prefijo de HU **`BKO`**, físico inglés en las tablas nuevas.
- **`OperatorUser` en tabla propia**, con login y **secreto de firma propios**.
- **Rol de BD `alpaqa_backoffice` y cliente Prisma separado**, exclusivo del módulo, **sin
  `BYPASSRLS`**: el acceso se concede por tabla (revisión de BKO-03).
- **`Company.estado` pasa a enum** y **suspender corta el acceso** por guard, leído por request.
- **`Plan` se modela y se asigna; el gating no bloquea todavía.**
- **El operador ve metadatos, nunca contenido del negocio.** Sin impersonación.
- **Sin RBAC interno**; el primer operador se siembra.

---

## 9. Mapa HU → entregable técnico

**Acceso del operador:**
| HU (código) | Entregable principal |
|---|---|
| `BKO-01` | `OperatorUser` + login/refresh propios (secreto separado, guard de operador, tabla nueva sin RLS). **Funda el módulo**, crea el rol `alpaqa_backoffice` **acotado a `operator_user`** y siembra el primer operador |
| `BKO-02` | Alta y administración de operadores (contraseña temporal, activar/desactivar) |

**Tenants:**
| HU | Entregable |
|---|---|
| `BKO-03` | Listado y ficha de tenants (metadatos). **Abre el acceso cross-tenant: `GRANT SELECT` sobre `empresa` + política RLS nominal para el rol** — el rol y el cliente ya existen desde BKO-01, pero sin privilegio. **Sin `BYPASSRLS`** (revisión de §11.2) |
| `BKO-04` | `Company.estado` a enum + suspender/activar **con efecto**: `TenantStatusGuard` en la cadena (entre empresa y permisos), lector vía `SECURITY DEFINER`, excepción `@AllowsSuspended()` para la cuenta propia. Abre además el `GRANT UPDATE ("estado", "updated_at")` **por columna** y su política de escritura |

**Planes y métricas:**
| HU | Entregable |
|---|---|
| `BKO-05` | `Plan` CRUD + `Company.planId`: asignar y quitar plan (sin gating) |
| `BKO-06` | Métricas derivadas: por tenant y globales |

> Códigos `BKO-0x` = etiqueta de orden que reinicia por segmento; el id/referencia de cada HU es su
> clave Jira `ALPQ-N`.

---

## 10. Prerrequisitos y orden de implementación

**Prerrequisito duro (ya cumplido):** *Plataforma y administración* completo — `Company` con sus
datos y su `estado`, el kernel de seguridad con `PasswordHasher`/`TokenService`, el borde HTTP
compartido y la cadena de guards donde enganchar el de suspensión.

**Orden sugerido (entrar, mirar, actuar):**
`BKO-01` (el operador puede entrar; aquí ya aparece la segunda conexión, porque el cimiento concede
toda tabla nueva al rol de tenant por default y las credenciales de operador no pueden quedar a su
alcance) → `BKO-02` (hay más de uno) → `BKO-03` (ve a los tenants; aquí el rol **gana el privilegio**
de cruzar, que es el cambio más delicado del dominio) → `BKO-04`
(puede actuar sobre ellos, y la suspensión pasa a tener efecto) → `BKO-05` (planes) → `BKO-06`
(métricas). Cada HU con el ritual de cierre: auditoría `audit-plan` + `audit-arquitectura` → suites
vía `test-runner` → commit sin coautoría → push → mover el ticket en Jira.

**Riesgos a vigilar:**
- **BKO-01** introduce un segundo mundo de autenticación. El test que importa no es que el operador
  entre: es que un token de operador **no** sirva en las rutas de tenant, y viceversa.
- **BKO-03** abre el acceso cross-tenant. Hay que probar que ningún módulo de tenant alcanza esa
  conexión, que la de siempre sigue fallando cerrado, y —lo que se agregó al construirla— que
  **cada una de las dos llaves es portante**: quitando el `GRANT` o la política, la suite se pone
  roja por separado.
- **BKO-04** toca la cadena de guards, que afecta a los seis módulos: la suite completa manda.

---

## 11. Decisiones confirmadas con el usuario (ago-2026)

1. **Operadores con tabla y login propios:** `OperatorUser` aparte, tokens de audiencia distinta.
   Un operador no es un usuario de alguna empresa; separarlos hace imposible que un bug filtre
   super-admin a un tenant.
2. **Rol de base de datos propio y conexión aparte**, exclusivo del módulo `backoffice`.
   `alpaqa_app` no cambia y ninguna política suya se relaja. **Revisado el 2026-08-29 (BKO-03):
   sin `BYPASSRLS`** — el acceso cross-tenant se abre tabla por tabla, con `GRANT` + política
   nominal, para que el invariante 6 lo sostenga la base y no el repositorio (§2.1).
3. **La suspensión se aplica; el plan solo se modela.** Coherente con el maestro §7 («gating en su
   versión más simple, con la estructura lista»). Una suspensión que no suspende sería peor que no
   tenerla — y hoy `estado` no bloquea nada.
4. **El operador ve solo metadatos del tenant** (empresa, estado, plan, fechas, métricas agregadas).
   Nunca órdenes, ventas ni clientes. Sin impersonación en el MVP.
