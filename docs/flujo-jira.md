# Flujo de trabajo en Jira — alpaqa-pos

> Convención de proceso para el proyecto **ALPQ** (`alpaqa.atlassian.net`). **Jira es la fuente
> de verdad del backlog y del estado**; los documentos del hub (HUs, PRDs) son snapshots de
> referencia. Esta convención evita improvisar estados al implementar.

## Jerarquía

- **Épica** agrupa un dominio o un frente de trabajo.
  - `ALPQ-1` — Catálogo e inventario (13 HUs: `ALPQ-2`..`ALPQ-14`).
  - `ALPQ-15` — Plataforma / Cimiento del backend (8 tareas de fase: `ALPQ-16`..`ALPQ-23`,
    corresponden a F0..F7 de `alpaqa-pos-backend/docs/plan-bootstrap.md`).
- **Historia** (HU): unidad vertical de valor de negocio.
- **Tarea**: trabajo técnico independiente (p. ej. fases del cimiento).

## Estados (tablero ALPQ)

`Por hacer` → `En curso` → `En revisión` → `Finalizada` (Listo)

| Estado | Cuándo se mueve aquí |
|---|---|
| **Por hacer** | Backlog. El issue está definido pero nadie lo ha empezado. |
| **En curso** | Al **empezar** a implementarlo. Se asigna a quien trabaja y se crea la rama. |
| **En revisión** | Cuando el código está listo y en PR/revisión (o auto-revisión antes de merge). |
| **Finalizada** | Cuando los **criterios de aceptación pasan** (build/lint/tests en verde) y se mergea. |

## Reglas

1. **Un issue En curso a la vez por persona** (foco). No abrir trabajo en paralelo sin cerrar.
2. **Vinculación código ↔ issue**: la rama y el PR llevan la key del issue
   (`ALPQ-3-crear-producto-simple`); el cuerpo del PR referencia la key.
   Los mensajes de commit **no** llevan coautoría de herramientas (decisión de marca).
3. **Definition of Done** = los criterios de aceptación (Gherkin) de la HU se cumplen y están
   cubiertos por tests; el cimiento afectado sigue en verde.
4. **El cimiento también se rastrea** (épica `ALPQ-15`), no solo las HUs de negocio.
5. Al cambiar el estado, dejar (si aporta) un comentario breve en el issue con el commit/PR.

## Ritual de cierre de una HU

Cada HU se cierra con la misma secuencia, y el orden importa: las auditorías corren **contra el PRD
ya reconciliado**, para que contrasten con la decisión vigente y no con la anterior.

1. **Implementar** leyendo antes `lineamientos-tecnicos.md` (§2.2 arquitectura, §2.4 privilegios,
   §2.6 pruebas) y el PRD del dominio.
2. **Mutation-testing de cada garantía nueva**: romper lo que el test dice fijar y comprobar que se
   pone rojo. No una muestra — cada garantía.
3. **Reconciliar el PRD del dominio** con lo que realmente se construyó, incluidas las desviaciones
   y por qué.
4. **Auditar** con `audit-plan` (fidelidad al plan) y `audit-arquitectura` (sanidad de capas), en
   paralelo.
5. **Cerrar los hallazgos** y volver a correr las suites.
6. **Suites vía `test-runner`**: unit + e2e, más `tsc --noEmit`.
7. **Commit sin coautoría**, push.
8. **Mover el ticket**: En curso → En revisión → Listo. **Las épicas las cierra el usuario**, no el
   flujo.

> **Dónde va cada decisión.** Si la decisión vale para un solo dominio, va a su PRD. Si vale para
> todo el backend —una regla de privilegios, un orden de ejecución, una convención de pruebas— va a
> `lineamientos-tecnicos.md`; si cruza dominios a nivel de producto, al PRD maestro. Archivar una
> regla transversal dentro del PRD de un dominio es cómo se repite un error ya corregido: nadie la
> va a buscar ahí.

## Estado inicial registrado (2026-07-22)

- `ALPQ-16` (F0 — versiones) y `ALPQ-17` (F1 — init + estructura): **Finalizada**.
- `ALPQ-18`..`ALPQ-23` (F2..F7): Por hacer.
- `ALPQ-1` y sus HUs (`ALPQ-2`..`ALPQ-14`): Por hacer (no arrancan hasta tener el cimiento).
