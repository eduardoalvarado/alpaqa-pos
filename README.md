# alpaqa-pos

SaaS de punto de venta **unificado** para tiendas y restaurantes en Perú.

La idea central: el negocio real está en el **flujo de la orden**, no en el rubro. Una
venta al mostrador y un "para llevar" son, en el fondo, la misma transacción. El sistema
es **un solo producto** que cada negocio configura según cómo opera —no dos productos
distintos para tienda y restaurante.

## Fuente de la verdad

El alcance, la visión y las decisiones transversales viven en el PRD:

- [`docs/alcance-mvp-pos.md`](docs/alcance-mvp-pos.md) — documento raíz / PRD maestro.

Todo lo que cruza dominios (multi-tenancy, las tres superficies, las decisiones
transversales críticas) se escribe **una sola vez, ahí**.

## Las tres superficies

Tres frontends sobre un mismo backend/API. La API y el modelo de permisos son el
contrato central.

| Superficie | Público | Notas |
|---|---|---|
| **Backoffice** | Operador del SaaS | Gestión de tenants, planes, feature gating. |
| **Plataforma de gestión** | Dueño + empleados con permiso | Config, catálogo, inventario, reportes. |
| **POS** | Cajero / mesero / dueño | Operación de venta. Máxima prioridad UX. Única superficie **offline**. |

Requisitos transversales de las tres: **mobile-first** y **tema claro/oscuro** (resuelto
por design tokens, no por pantalla).

## Decisiones transversales críticas (cimiento)

1. **Snapshot vs. referencia** — la línea de orden y el comprobante copian precio/IGV al
   momento de la venta; no leen datos vivos del catálogo.
2. **Correlativo sin huecos + offline** — una serie por caja; el correlativo se asigna
   localmente al emitir.
3. **IDs para sync** — todo lo creable offline usa UUID generado en el cliente.
4. **Dos ejes ortogonales** — capacidades del negocio (operativo) vs. feature gating por
   plan (comercial).

## Estado

MVP en fase de arranque. El **stack técnico** aún no está decidido (ver §11 del PRD): se
define en los lineamientos técnicos antes de scaffolding.

## Documentación

La documentación se organiza en capas (ver §10 del PRD): PRD maestro + PRDs por dominio
que se generan **justo antes** de implementar cada dominio, no todos por adelantado.
