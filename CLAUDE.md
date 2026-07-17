# CLAUDE.md — alpaqa-pos (hub de especificación)

Este repo es el **hub de especificación** del SaaS POS unificado alpaqa-pos. **No contiene
código de aplicación**: es la fuente de la verdad del producto y las decisiones técnicas.

## Qué vive aquí

- `docs/alcance-mvp-pos.md` — **PRD maestro**. Fuente de la verdad de todo lo que cruza
  dominios (visión, tres superficies, multi-tenancy, decisiones transversales).
- `docs/lineamientos-tecnicos.md` — decisiones de stack y arquitectura (hermano del PRD).
- `docs/` — PRDs por dominio (se generan **justo antes** de implementar cada dominio, no
  todos por adelantado; ver PRD §10).
- `ui/` — referencias de diseño y paleta de marca.

## Repos hermanos (el código)

- `alpaqa-pos-backend` — API / contrato central (NestJS + Prisma + Postgres).
- `alpaqa-pos-frontend` — monorepo Nx de las tres superficies (Angular).

## Reglas al trabajar aquí

- Las **decisiones transversales** se escriben **una sola vez**, en el PRD o los
  lineamientos. Los PRDs de dominio las **referencian**, no las repiten.
- No generar todos los PRDs de dominio por adelantado.
- No se elige stack ni se scaffoldea desde aquí; eso vive en los repos de código.
- Convertir fechas relativas a absolutas en la documentación.

## Decisiones ya tomadas (no re-litigar sin motivo)

- Topología: 3 repos (hub + backend + frontend). Frontend es monorepo con 3 apps.
- Backend: NestJS + TypeScript + Prisma + PostgreSQL; **monolito modular + hexagonal
  pragmático**.
- Frontend: Angular + Vite + Tailwind + Nx + pnpm; UI = **CDK + Tailwind (base) +
  PrimeNG unstyled**.

## Idioma

Documentación y comunicación en **español**.
