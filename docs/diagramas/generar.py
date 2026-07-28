#!/usr/bin/env python3
"""Genera los diagramas técnicos de alpaqa-pos como SVG (→ PDF con rsvg-convert).

Diagramas:
  1. topologia      — repos, superficies y API.
  2. arquitectura   — backend hexagonal + estado del cimiento (F0–F5).
  3. flujo-request  — pipeline auth + multi-tenancy de una request.
  4. modelo-datos   — ER del PRD §5 (planificado; los modelos son F6).
"""
from __future__ import annotations

FONT = "font-family=\"Inter, 'Noto Sans', 'DejaVu Sans', sans-serif\""


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.p = [f'<rect x="0" y="0" width="{w}" height="{h}" fill="#ffffff"/>']

    def rect(self, x, y, w, h, fill="#ffffff", stroke="#334155", rx=8, sw=1.4, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}{d}/>')

    def text(self, x, y, s, size=12, bold=False, fill="#0f172a", anchor="start", italic=False, mono=False):
        fw = ' font-weight="700"' if bold else ""
        fs = ' font-style="italic"' if italic else ""
        fam = 'font-family="\'DejaVu Sans Mono\', monospace"' if mono else FONT
        self.p.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{fw}{fs} {fam}>{esc(s)}</text>'
        )

    def line(self, x1, y1, x2, y2, stroke="#475569", sw=1.5, dash=None, marker="arrow"):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        m = f' marker-end="url(#{marker})"' if marker else ""
        self.p.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"{d}{m}/>')

    def label(self, x, y, s, size=10, fill="#334155"):
        # etiqueta con fondo blanco para legibilidad sobre las líneas
        w = len(s) * size * 0.60 + 8
        self.rect(x - w / 2, y - size, w, size + 6, fill="#ffffff", stroke=None, rx=3)
        self.text(x, y + 3, s, size=size, fill=fill, anchor="middle")

    def svg(self) -> str:
        defs = (
            '<defs>'
            '<marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="userSpaceOnUse">'
            '<path d="M0,0 L8,3 L0,6 Z" fill="#475569"/></marker>'
            '<marker id="arrowlt" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="userSpaceOnUse">'
            '<path d="M0,0 L8,3 L0,6 Z" fill="#94a3b8"/></marker>'
            '</defs>'
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}">{defs}{"".join(self.p)}</svg>'
        )

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.svg())


def header(cv, title, subtitle):
    cv.rect(0, 0, cv.w, 58, fill="#0f172a", stroke=None, rx=0)
    cv.text(28, 30, "alpaqa-pos", size=15, bold=True, fill="#38bdf8")
    cv.text(28, 47, title, size=17, bold=True, fill="#ffffff")
    cv.text(cv.w - 28, 36, subtitle, size=11, fill="#94a3b8", anchor="end")


# ── sides helpers ────────────────────────────────────────────────────────────
def sides(r):
    x, y, w, h = r
    return {
        "l": (x, y + h / 2), "r": (x + w, y + h / 2),
        "t": (x + w / 2, y), "b": (x + w / 2, y + h),
        "c": (x + w / 2, y + h / 2),
    }


def connect(cv, ra, rb, label="", dash=None, color="#475569", marker="arrow"):
    a, b = sides(ra), sides(rb)
    dx = b["c"][0] - a["c"][0]
    dy = b["c"][1] - a["c"][1]
    if abs(dx) >= abs(dy):
        pa = a["r"] if dx >= 0 else a["l"]
        pb = b["l"] if dx >= 0 else b["r"]
    else:
        pa = a["b"] if dy >= 0 else a["t"]
        pb = b["t"] if dy >= 0 else b["b"]
    cv.line(pa[0], pa[1], pb[0], pb[1], stroke=color, sw=1.3, dash=dash, marker=marker)
    if label:
        cv.label((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, label, size=9,
                 fill="#64748b" if dash else "#334155")


# ══════════════════════════════════════════════════════════════════════════════
# 1. TOPOLOGÍA
# ══════════════════════════════════════════════════════════════════════════════
def topologia(path):
    cv = Canvas(1180, 760)
    header(cv, "Topología del proyecto — 3 repos, 3 superficies, 1 API", "estado 2026-07")

    # frontend monorepo container
    cv.rect(70, 90, 620, 190, fill="#faf5ff", stroke="#7c3aed", rx=12)
    cv.text(90, 118, "alpaqa-pos-frontend", size=14, bold=True, fill="#6d28d9")
    cv.text(90, 136, "monorepo Nx · Angular + Vite + Tailwind + pnpm", size=10, fill="#7c3aed")
    apps = [("POS", "cajero / mesero", "offline (PWA)"),
            ("Gestión", "dueño + permisos", "backoffice del negocio"),
            ("Backoffice", "operador SaaS", "multi-tenant")]
    surf_rects = []
    for i, (t, who, note) in enumerate(apps):
        x = 92 + i * 196
        cv.rect(x, 150, 176, 110, fill="#ffffff", stroke="#a78bfa", rx=10)
        cv.text(x + 88, 178, t, size=14, bold=True, fill="#5b21b6", anchor="middle")
        cv.text(x + 88, 200, who, size=10, fill="#334155", anchor="middle")
        cv.text(x + 88, 220, note, size=9, fill="#64748b", anchor="middle")
        surf_rects.append((x, 150, 176, 110))

    # backend
    back = (300, 400, 560, 120)
    cv.rect(*back, fill="#eff6ff", stroke="#2563eb", rx=12)
    cv.text(580, 432, "alpaqa-pos-backend", size=15, bold=True, fill="#1d4ed8", anchor="middle")
    cv.text(580, 456, "API única · contrato central · NestJS + TypeScript", size=11, fill="#334155", anchor="middle")
    cv.text(580, 476, "monolito modular + hexagonal · JWT+RBAC · multi-tenant (2 capas)", size=10, fill="#64748b", anchor="middle")
    cv.text(580, 496, "Prisma + Prisma Migrate", size=10, fill="#64748b", anchor="middle")

    # arrows surfaces -> backend
    for r in surf_rects:
        s = sides(r)["b"]
        cv.line(s[0], s[1], 580, 400, stroke="#93c5fd", sw=1.4, marker="arrow")
    cv.label(580, 335, "HTTP / REST + OpenAPI", size=10, fill="#2563eb")

    # postgres cylinder
    cx, cy, cw = 580, 600, 200
    cv.rect(cx - cw / 2, cy, cw, 70, fill="#ecfdf5", stroke="#059669", rx=14)
    cv.text(cx, cy + 30, "PostgreSQL", size=13, bold=True, fill="#047857", anchor="middle")
    cv.text(cx, cy + 50, "row-level tenancy (empresa_id) + RLS", size=10, fill="#059669", anchor="middle")
    cv.line(580, 520, 580, 600, stroke="#6ee7b7", sw=1.6, marker="arrow")
    cv.label(580, 562, "@prisma/adapter-pg", size=9, fill="#059669")

    # hub
    cv.rect(910, 400, 210, 120, fill="#fffbeb", stroke="#d97706", rx=12)
    cv.text(1015, 430, "alpaqa-pos (hub)", size=13, bold=True, fill="#b45309", anchor="middle")
    cv.text(1015, 452, "spec / fuente de verdad", size=10, fill="#334155", anchor="middle")
    cv.text(1015, 472, "PRD maestro", size=10, fill="#64748b", anchor="middle")
    cv.text(1015, 490, "lineamientos técnicos", size=10, fill="#64748b", anchor="middle")
    cv.text(1015, 508, "HUs / diagramas", size=10, fill="#64748b", anchor="middle")
    cv.line(910, 460, 860, 460, stroke="#fcd34d", sw=1.4, marker="arrow", dash="5,4")
    cv.label(884, 448, "guía", size=9, fill="#d97706")

    cv.text(28, 730, "El negocio está en el flujo de la orden, no en el rubro: una sola entidad Orden, capacidades configurables por empresa.",
            size=11, italic=True, fill="#475569")
    cv.save(path)


# ══════════════════════════════════════════════════════════════════════════════
# 2. ARQUITECTURA BACKEND (hexagonal) + estado del cimiento
# ══════════════════════════════════════════════════════════════════════════════
def arquitectura(path):
    cv = Canvas(1280, 900)
    header(cv, "Backend — arquitectura hexagonal y estado del cimiento", "F0–F5 hechas · F6 pendiente")

    cv.rect(40, 78, 1200, 40, fill="#f1f5f9", stroke="#cbd5e1", rx=8)
    cv.text(60, 103, "AppModule  —  raíz: monta el cimiento; los dominios (catálogo, ventas, caja…) se agregan encima",
            size=12, bold=True, fill="#334155")

    mods = [
        ("Config", "#0ea5e9", "F1", True, [
            "config/", "· validación de entorno (fail-fast)", "· ConfigModule global"]),
        ("Shared Kernel", "#16a34a", "F3", True, [
            "shared/domain/", "· Money (Decimal, nunca float)", "· puertos Clock · IdGenerator",
            "shared/infrastructure/", "· SystemClock · UuidIdGenerator", "· DomainError base"]),
        ("Platform / Tenancy", "#7c3aed", "F4", True, [
            "platform/tenancy/", "· TenantContext (AsyncLocalStorage)", "· TenantInterceptor (global)",
            "· extensión Prisma $extends", "  (auto-filtro empresaId, fail-closed)",
            "platform/database/", "· PrismaService (adapter pg)", "· withTenant() → SET LOCAL"]),
        ("Auth", "#ea580c", "F5", True, [
            "auth/domain/", "· puertos: UserRepository,", "  PasswordHasher, TokenService",
            "· Permiso (RBAC por permiso)", "auth/application/", "· LoginUseCase · RefreshUseCase",
            "auth/infrastructure/", "· JWT · scrypt · guards", "· UserRepository en memoria (temporal)"]),
    ]
    x = 40
    w = 293
    gap = 12
    top = 140
    for name, color, fase, done, lines in mods:
        h = 40 + len(lines) * 17 + 16
        cv.rect(x, top, w, h, fill="#ffffff", stroke=color, rx=10, sw=1.6)
        cv.rect(x, top, w, 30, fill=color, stroke=None, rx=10)
        cv.rect(x, top + 16, w, 14, fill=color, stroke=None, rx=0)
        cv.text(x + 12, top + 20, name, size=13, bold=True, fill="#ffffff")
        cv.text(x + w - 10, top + 20, f"{fase} ✓", size=11, bold=True, fill="#ffffff", anchor="end")
        yy = top + 48
        for ln in lines:
            is_layer = ln.endswith("/")
            cv.text(x + 12, yy, ln, size=10.5,
                    bold=is_layer, fill="#1e293b" if is_layer else "#475569",
                    mono=is_layer)
            yy += 17
        x += w + gap

    # hexagonal legend band
    ly = 560
    cv.rect(40, ly, 1200, 84, fill="#f8fafc", stroke="#cbd5e1", rx=10)
    cv.text(60, ly + 26, "Regla hexagonal (desde el cimiento):", size=12, bold=True, fill="#0f172a")
    chips = [("domain/", "#16a34a", "puro: entidades, VOs, puertos (interfaces). No importa Nest ni Prisma."),
             ("application/", "#2563eb", "casos de uso que orquestan puertos."),
             ("infrastructure/", "#ea580c", "adapters: Prisma, JWT, HTTP, controllers.")]
    yy = ly + 50
    for label, color, desc in chips:
        cv.rect(60, yy - 13, 116, 20, fill=color, stroke=None, rx=5)
        cv.text(118, yy + 1, label, size=11, bold=True, fill="#ffffff", anchor="middle", mono=True)
        cv.text(186, yy + 1, desc, size=11, fill="#475569")
        yy += 26

    # cross-cutting pipeline
    py = 690
    cv.text(40, py, "Transversal (seguro por defecto): guards globales + interceptor", size=12, bold=True, fill="#0f172a")
    stages = [("JwtAuthGuard", "#ea580c"), ("PermisosGuard", "#ea580c"), ("TenantInterceptor", "#7c3aed"),
              ("Controller / UseCase", "#2563eb"), ("PrismaService.db", "#7c3aed")]
    sx = 40
    for i, (t, c) in enumerate(stages):
        w2 = 210
        cv.rect(sx, py + 14, w2, 40, fill="#ffffff", stroke=c, rx=8)
        cv.text(sx + w2 / 2, py + 39, t, size=11, bold=True, fill=c, anchor="middle")
        if i < len(stages) - 1:
            cv.line(sx + w2, py + 34, sx + w2 + 20, py + 34, stroke="#94a3b8", sw=1.5, marker="arrow")
        sx += w2 + 20

    # pending F6
    cv.rect(40, py + 82, 1200, 70, fill="#fef2f2", stroke="#dc2626", rx=10, dash="6,4")
    cv.text(60, py + 108, "F6 — pendiente (cierra el cimiento):", size=12, bold=True, fill="#b91c1c")
    cv.text(60, py + 130, "modelos Prisma del núcleo tenant (empresaId @map) · migración inicial · políticas RLS + rol de app sin BYPASSRLS · "
            "seed empresa/usuario demo · PrismaUserRepository (reemplaza el adapter en memoria de auth)",
            size=10.5, fill="#991b1b")
    cv.save(path)


# ══════════════════════════════════════════════════════════════════════════════
# 3. FLUJO DE REQUEST (auth + multi-tenancy)
# ══════════════════════════════════════════════════════════════════════════════
def flujo(path):
    cv = Canvas(1200, 820)
    header(cv, "Flujo de una request — autenticación + multi-tenancy", "cadena del cimiento")

    steps = [
        ("1. HTTP request", "#334155", ["Authorization: Bearer <access>", "cuerpo validado con ValidationPipe"]),
        ("2. JwtAuthGuard (global)", "#ea580c", ["verifica el JWT (secreto access)", "adjunta AuthenticatedUser:", "{ id, empresaId, email, permisos }", "@Public() exime (login/refresh)"]),
        ("3. PermisosGuard (global)", "#ea580c", ["@RequierePermiso('anular_venta'…)", "exige permisos del usuario", "por permiso, nunca por rol"]),
        ("4. TenantInterceptor (global)", "#7c3aed", ["lee req.user.empresaId", "TenantContext.run(empresaId)", "AsyncLocalStorage por request"]),
        ("5. Controller → UseCase", "#2563eb", ["orquesta puertos del dominio", "dominio puro (sin Nest/Prisma)"]),
        ("6. PrismaService.db", "#7c3aed", ["extensión $extends lee el ALS", "inyecta where empresaId / lo fija", "sin contexto → fail-closed", "withTenant(): SET LOCAL", "app.current_empresa"]),
        ("7. PostgreSQL", "#059669", ["capa 1: filtro Prisma (empresaId)", "capa 2: RLS por sesión (F6)", "un WHERE olvidado no filtra datos"]),
    ]
    x = 40
    boxw = 250
    y = 100
    rects = []
    col_h = [0, 1, 0, 1, 0, 1, 0]  # vertical zig-zag offset
    for i, (title, color, lines) in enumerate(steps):
        yy = y + (150 if i % 2 else 0)
        h = 44 + len(lines) * 17 + 8
        cv.rect(x, yy, boxw, h, fill="#ffffff", stroke=color, rx=10, sw=1.6)
        cv.rect(x, yy, boxw, 30, fill=color, stroke=None, rx=10)
        cv.rect(x, yy + 16, boxw, 14, fill=color, stroke=None)
        cv.text(x + 12, yy + 20, title, size=12, bold=True, fill="#ffffff")
        ry = yy + 48
        for ln in lines:
            cv.text(x + 12, ry, ln, size=10, fill="#475569")
            ry += 17
        rects.append((x, yy, boxw, h))
        x += boxw + 40
        if i in (2, 5) and False:
            pass
    # this layout is too wide; overridden below by vertical layout
    cv.save(path)


def flujo_v(path):
    cv = Canvas(1180, 1000)
    header(cv, "Flujo de una request — autenticación + multi-tenancy", "cadena del cimiento (seguro por defecto)")

    steps = [
        ("1  ·  HTTP request", "#334155",
         "Authorization: Bearer <access token>   ·   cuerpo validado con ValidationPipe (whitelist)"),
        ("2  ·  JwtAuthGuard  (guard global)", "#ea580c",
         "Verifica la firma/expiración del JWT (secreto de access). Adjunta AuthenticatedUser { id, empresaId, email, permisos }.  @Public() exime login y refresh."),
        ("3  ·  PermisosGuard  (guard global)", "#ea580c",
         "@RequierePermiso('anular_venta', …) exige que el usuario tenga esos permisos. Autorización por permiso, nunca por nombre de rol."),
        ("4  ·  TenantInterceptor  (interceptor global)", "#7c3aed",
         "Lee req.user.empresaId y ejecuta el handler dentro de TenantContext.run(empresaId) — AsyncLocalStorage, propagado a todo lo async."),
        ("5  ·  Controller → Caso de uso", "#2563eb",
         "Orquesta los puertos del dominio. El dominio es puro (no importa Nest ni Prisma)."),
        ("6  ·  PrismaService.db  (extensión $extends)", "#7c3aed",
         "En cada query lee el empresaId del ALS: inyecta where empresaId en lecturas/updates/deletes y lo fija en creaciones. Sin contexto → fail-closed. withTenant() abre transacción con SET LOCAL app.current_empresa."),
        ("7  ·  PostgreSQL", "#059669",
         "Capa 1 = filtro Prisma automático (empresaId).  Capa 2 = Row-Level Security por variable de sesión (F6). Un WHERE olvidado no puede cruzar datos entre negocios."),
    ]
    x = 150
    w = 880
    y = 90
    prev = None
    for title, color, desc in steps:
        # wrap desc
        words = desc.split()
        lines, cur = [], ""
        for wd in words:
            if len(cur) + len(wd) + 1 > 92:
                lines.append(cur)
                cur = wd
            else:
                cur = (cur + " " + wd).strip()
        if cur:
            lines.append(cur)
        h = 34 + len(lines) * 16 + 12
        cv.rect(x, y, w, h, fill="#ffffff", stroke=color, rx=10, sw=1.6)
        cv.rect(x, y, 8, h, fill=color, stroke=None, rx=0)
        cv.text(x + 22, y + 24, title, size=13, bold=True, fill=color)
        ry = y + 44
        for ln in lines:
            cv.text(x + 22, ry, ln, size=10.5, fill="#475569")
            ry += 16
        if prev is not None:
            cv.line(x + w / 2, prev, x + w / 2, y, stroke="#94a3b8", sw=1.7, marker="arrow")
        prev = y + h
        y = y + h + 34
    cv.save(path)


# ══════════════════════════════════════════════════════════════════════════════
# 4. MODELO DE DATOS (ER) — PRD §5
# ══════════════════════════════════════════════════════════════════════════════
def modelo_datos(path):
    cv = Canvas(1720, 1180)
    header(cv, "Modelo de datos (ER) — PRD §5 · planificado (los modelos son F6)", "multi-tenant: empresa_id en (casi) toda tabla")

    boxes = {}

    def entity(col_x, col_w, y, name, color, tenant, fields):
        x = col_x + 8
        w = col_w - 16
        h = 26 + len(fields) * 15 + 8
        cv.rect(x, y, w, h, fill="#ffffff", stroke=color, rx=8, sw=1.4)
        cv.rect(x, y, w, 24, fill=color, stroke=None, rx=8)
        cv.rect(x, y + 12, w, 12, fill=color, stroke=None)
        cv.text(x + 10, y + 17, name, size=11.5, bold=True, fill="#ffffff")
        if tenant:
            cv.text(x + w - 8, y + 17, "[T]", size=9.5, bold=True, fill="#e2e8f0", anchor="end")
        fy = y + 39
        for f in fields:
            fk = "(FK)" in f or "(ref)" in f
            cv.text(x + 10, fy, f, size=9, fill="#334155" if fk else "#64748b")
            fy += 15
        boxes[name] = (x, y, w, h)
        return y + h + 16

    COLS = [
        ("#2563eb", 40, 320),    # tenant / soporte
        ("#7c3aed", 380, 340),   # catálogo
        ("#0891b2", 740, 300),   # inventario + venta
        ("#16a34a", 1060, 300),  # caja + pago
        ("#dc2626", 1380, 320),  # facturación
    ]

    # Column 1 — Núcleo tenant + Soporte
    cx, cw = 40, 320
    cv.text(cx + 8, 80, "Núcleo tenant", size=12, bold=True, fill="#2563eb")
    y = 90
    y = entity(cx, cw, y, "Empresa", "#2563eb", False, ["ruc · razon_social", "regimen_tributario", "estado · plan_id", "capacidades (usa mesas/cocina/inv.)"])
    y = entity(cx, cw, y, "Sucursal", "#2563eb", True, ["empresa_id (FK)", "nombre · direccion"])
    y = entity(cx, cw, y, "Usuario", "#2563eb", True, ["empresa_id (FK)", "nombre · email", "password_hash · activo"])
    y = entity(cx, cw, y, "Rol", "#2563eb", True, ["empresa_id (FK)", "nombre", "permisos { descuento_max_pct,", "  puede_anular, puede_ver_totales… }"])
    y = entity(cx, cw, y, "UsuarioSucursal", "#2563eb", False, ["usuario_id (FK)", "sucursal_id (FK)", "rol_id (FK)"])
    cv.text(cx + 8, y + 6, "Soporte", size=12, bold=True, fill="#64748b")
    y += 16
    y = entity(cx, cw, y, "Cliente", "#64748b", True, ["empresa_id (FK)", "tipo_doc · numero_doc", "nombre"])
    y = entity(cx, cw, y, "LogAuditoria", "#64748b", True, ["empresa_id (FK) · usuario_id (FK)", "accion · entidad · entidad_id", "datos_antes/despues · timestamp"])

    # Column 2 — Catálogo
    cx, cw = 380, 340
    cv.text(cx + 8, 80, "Catálogo", size=12, bold=True, fill="#7c3aed")
    y = 90
    y = entity(cx, cw, y, "Categoria", "#7c3aed", True, ["empresa_id (FK)", "nombre"])
    y = entity(cx, cw, y, "Producto", "#7c3aed", True, ["empresa_id (FK) · categoria_id (FK)", "nombre · precio", "requiere_preparacion", "controla_inventario", "tipo_afectacion_igv · afecto_icbper", "unidad_medida · fraccionada"])
    y = entity(cx, cw, y, "Variante", "#7c3aed", True, ["producto_id (FK)", "ejes (talla, color…)", "precio", "sku (único por empresa)", "codigo_barra"])
    y = entity(cx, cw, y, "GrupoModificador", "#7c3aed", False, ["producto_id (FK)", "nombre"])
    y = entity(cx, cw, y, "Modificador", "#7c3aed", False, ["grupo_id (FK)", "nombre · precio"])

    # Column 3 — Inventario + Venta
    cx, cw = 740, 300
    cv.text(cx + 8, 80, "Inventario", size=12, bold=True, fill="#0891b2")
    y = 90
    y = entity(cx, cw, y, "Stock", "#0891b2", False, ["variante_id (FK)", "sucursal_id (FK)", "cantidad · stock_minimo"])
    y = entity(cx, cw, y, "MovimientoInventario", "#0891b2", False, ["variante_id (FK)", "tipo · motivo · cantidad", "ref: orden / nota_credito"])
    cv.text(cx + 8, y + 6, "Operación de venta", size=12, bold=True, fill="#ea580c")
    y += 16
    y = entity(cx, cw, y, "Mesa", "#ea580c", False, ["sucursal_id (FK)", "nombre · estado · zona"])
    y = entity(cx, cw, y, "Orden", "#ea580c", True, ["empresa_id · sucursal_id (FK)", "canal · mesa_id? · mesero_id?", "cliente_id? · estado", "subtotal · igv · desc · total", "uuid_local (offline)"])
    y = entity(cx, cw, y, "OrdenItem", "#ea580c", False, ["orden_id (FK) · variante_id (ref)", "snapshot: nombre, precio_unit,", "  unidad, tipo_afectacion_igv", "cantidad (decimal)"])
    y = entity(cx, cw, y, "OrdenItemModificador", "#ea580c", False, ["orden_item_id (FK)", "modificador_id (ref)"])
    y = entity(cx, cw, y, "Comanda", "#ea580c", False, ["orden_id (FK) · sucursal_id (FK)", "estado (pend/prep/listo)"])

    # Column 4 — Caja + Pago
    cx, cw = 1060, 300
    cv.text(cx + 8, 80, "Caja", size=12, bold=True, fill="#16a34a")
    y = 90
    y = entity(cx, cw, y, "Caja", "#16a34a", False, ["sucursal_id (FK)", "nombre"])
    y = entity(cx, cw, y, "TurnoCaja", "#16a34a", False, ["caja_id (FK) · usuario_id (FK)", "fondo_inicial · apertura · cierre", "monto_esperado/contado · dif."])
    y = entity(cx, cw, y, "MovimientoCaja", "#16a34a", False, ["turno_caja_id (FK)", "tipo (ingreso/egreso/sangrado…)", "monto · motivo"])
    cv.text(cx + 8, y + 6, "Pago", size=12, bold=True, fill="#ca8a04")
    y += 16
    y = entity(cx, cw, y, "Pago", "#ca8a04", False, ["orden_id (FK)", "turno_caja_id (FK)", "metodo · monto · vuelto", "numero_operacion?"])

    # Column 5 — Facturación
    cx, cw = 1380, 320
    cv.text(cx + 8, 80, "Facturación electrónica", size=12, bold=True, fill="#dc2626")
    y = 90
    y = entity(cx, cw, y, "SerieComprobante", "#dc2626", False, ["caja_id (FK) — exclusiva", "tipo · serie", "correlativo_actual (sin huecos)"])
    y = entity(cx, cw, y, "Comprobante", "#dc2626", False, ["orden_id (FK)", "serie_id (FK)", "tipo (boleta/factura)", "serie · correlativo · doc_cliente", "subtotal · igv · otros_tributos", "total · estado_sunat · xml · cdr", "snapshot de totales y cliente"])
    y = entity(cx, cw, y, "NotaCredito", "#dc2626", False, ["comprobante_id (FK)", "motivo (anula/devuelve/corrige)", "serie · correlativo · estado_sunat"])

    # ── relationships ────────────────────────────────────────────────────────
    R = boxes
    def rel(a, b, lbl, dash=None, color="#64748b"):
        if a in R and b in R:
            connect(cv, R[a], R[b], lbl, dash=dash, color=color)

    # tenant core
    rel("Empresa", "Sucursal", "1..N")
    rel("Empresa", "Usuario", "1..N")
    rel("Empresa", "Rol", "1..N")
    rel("Usuario", "UsuarioSucursal", "1..N")
    rel("Rol", "UsuarioSucursal", "1..N")
    rel("Sucursal", "UsuarioSucursal", "1..N")
    # catálogo
    rel("Categoria", "Producto", "1..N")
    rel("Producto", "Variante", "1..N")
    rel("Producto", "GrupoModificador", "1..N")
    rel("GrupoModificador", "Modificador", "1..N")
    # inventario
    rel("Variante", "Stock", "1..N")
    rel("Variante", "OrdenItem", "ref", dash="4,4", color="#94a3b8")
    # venta
    rel("Mesa", "Orden", "0..N")
    rel("Orden", "OrdenItem", "1..N")
    rel("OrdenItem", "OrdenItemModificador", "1..N")
    rel("Modificador", "OrdenItemModificador", "ref", dash="4,4", color="#94a3b8")
    rel("Orden", "Comanda", "1..0..1")
    # caja
    rel("Caja", "TurnoCaja", "1..N")
    rel("TurnoCaja", "MovimientoCaja", "1..N")
    # pago
    rel("Orden", "Pago", "1..N")
    rel("TurnoCaja", "Pago", "1..N")
    # facturación
    rel("Caja", "SerieComprobante", "1..1")
    rel("SerieComprobante", "Comprobante", "1..N")
    rel("Orden", "Comprobante", "1..0..1")
    rel("Comprobante", "NotaCredito", "1..N")

    # legend
    ly = 1095
    cv.rect(40, ly, 1640, 66, fill="#f8fafc", stroke="#cbd5e1", rx=10)
    cv.text(60, ly + 24, "Leyenda:", size=12, bold=True, fill="#0f172a")
    cv.text(140, ly + 24, "[T] = tabla con empresa_id (aislada por tenant vía RLS)   ·   línea sólida = pertenencia (FK dueña)   ·   "
            "línea punteada = referencia / snapshot   ·   FK a sucursal/usuario/cliente no se dibujan (ver campos)", size=11, fill="#475569")
    cv.text(60, ly + 48, "Invariantes: OrdenItem y Comprobante guardan snapshot (precio/IGV) al emitir · correlativo sin huecos, una serie por caja · "
            "uuid_local para creación offline · dinero en Decimal, nunca float.", size=11, italic=True, fill="#475569")
    cv.save(path)


if __name__ == "__main__":
    import os
    d = os.path.dirname(os.path.abspath(__file__))
    topologia(os.path.join(d, "1-topologia.svg"))
    arquitectura(os.path.join(d, "2-arquitectura-backend.svg"))
    flujo_v(os.path.join(d, "3-flujo-request.svg"))
    modelo_datos(os.path.join(d, "4-modelo-datos.svg"))
    print("SVGs generados en", d)
