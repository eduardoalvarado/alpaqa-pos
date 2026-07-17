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

Un solo desplegable, módulos por **bounded context**. No microservicios en el MVP.

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

### 2.4 Multi-tenancy (crítico — maneja dinero)

Aislamiento por tenant en **dos capas**:
1. Filtro `empresa_id` automático vía extensión/middleware de Prisma (nunca a mano).
2. **Postgres Row-Level Security (RLS)** como defensa en profundidad: un `WHERE`
   olvidado no puede filtrar datos entre negocios.

### 2.5 Invariantes del cimiento (del PRD §6) que el código debe garantizar

- **Snapshot en `OrdenItem` y `Comprobante`**: copian precio/IGV/datos al emitir; no leen
  datos vivos del catálogo. Inmutables tras emisión.
- **Correlativo sin huecos, una serie por caja**: correlativo asignado localmente al
  emitir; número consumido siempre se rinde (anulación → nota de crédito, nunca se reusa).
- **UUID cliente** para todo lo creable offline (órdenes, pagos, movimientos de caja).
- **Dos ejes ortogonales**: `Empresa.capacidades` (operativo) vs. `Plan.features`
  (comercial). Sistemas de flags separados.

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
