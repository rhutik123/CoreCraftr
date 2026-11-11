# CoreCraftr — Frontend Architecture & Design System

**Brand:** CoreCraftr — *Build Smarter. Build Better.*  
**Stack:** Django 5.2 Templates, Tailwind CSS v4 (`tailwindcss v4.3.5` via `pytailwindcss`), CSS Custom Properties, Vanilla JavaScript, Local Lucide Icons (`v0.475.0`)  

---

## 1. Design Direction & Goals

CoreCraftr's UI is engineered specifically for serious PC hardware shoppers, first-time builders, and inventory staff:
- **Zero-Runtime-Framework / Zero-CDN-CSS Complexity:** Replaces Bootstrap 5.3 and Bootstrap Icons with a locally compiled, minified **Tailwind CSS v4** stylesheet (`static/css/app.min.css`) built cleanly via `pytailwindcss` (zero Node.js runtime required).
- **Hardware Precision Aesthetic:** Combines `Plus Jakarta Sans` for clean editorial readability with `JetBrains Mono` (`cc-mono`) for SKUs, technical specifications, wattage figures, and Indian Rupee (`₹`) prices.
- **Dark-First + Light + System Adaptive Theme:** Defaults to an obsidian slate hardware workbench palette (`dark`), supports high-clarity daylight (`light`), and dynamically follows OS preferences (`system`), persisted in `localStorage` without white flash on load.
- **Backend & Domain Preservation:** Keeps 100% of Django routes, form field names, compatibility statuses (`compatible`, `warning`, `incompatible`, `unknown`), cart replacement flows, RBAC guards, and AI specification safeguards intact.

---

## 2. Color Tokens & Typography

Design tokens live in `frontend_src/tailwind.css` under `@theme`, `:root` (dark default), and `html.light`.

### Dark Mode (Default — `:root` / `html.dark`)
| Token | CSS Variable | Hex / Value | Usage |
| :--- | :--- | :--- | :--- |
| Canvas | `--cc-bg` | `#10141B` | Primary page canvas |
| Surface | `--cc-surface` | `#191F29` | Cards, navbar, sidebar, panels |
| Elevated | `--cc-elevated` | `#252E3B` | Inputs, nested spec boxes, product frames |
| Hover | `--cc-hover` | `#2E3949` | Interactive hover states |
| Border | `--cc-border` | `#2F3A4A` | Structural 1px borders |
| Primary Text | `--cc-text` | `#E7EDF5` | Headings and primary copy |
| Muted Text | `--cc-text-muted` | `#98A6B8` | Labels, metadata, secondary text |
| Primary Accent | `--cc-accent` / `--cc-accent-ink` | `#F47738` / `#FF945C` | Primary CTAs, CoreCraftr highlight, links |
| Tech Secondary | `--cc-secondary` / `--cc-secondary-ink` | `#62A6F8` / `#7DB6FA` | Tech specs, info cues, builder metrics |

### Light Mode (`html.light`)
| Token | CSS Variable | Hex / Value | Usage |
| :--- | :--- | :--- | :--- |
| Canvas | `--cc-bg` | `#F6F7F9` | Page canvas |
| Surface | `--cc-surface` | `#FFFFFF` | Cards, navbar, sidebar, tables |
| Elevated | `--cc-elevated` | `#E9EDF2` | Inputs, secondary badges, sub-panels |
| Hover | `--cc-hover` | `#DFE5EE` | Hover fills |
| Border | `--cc-border` | `#D2DAE5` | Structural 1px borders |
| Primary Text | `--cc-text` | `#202733` | Headings and body text |
| Muted Text | `--cc-text-muted` | `#556173` | Captions and secondary labels |
| Primary Accent | `--cc-accent` / `--cc-accent-ink` | `#E9672C` / `#C24510` | Primary CTAs and brand links |
| Tech Secondary | `--cc-secondary` / `--cc-secondary-ink` | `#287DD6` / `#1D63AF` | Compatibility & technical badges |

### Compatibility & Semantic Status Tokens
Status styling is shared uniformly across the PC Builder, Shopping Cart compatibility panel, Checkout warnings, and Management Inventory badges:
- **Compatible (`compatible`)**: Green tint (`--cc-success-bg` / `--cc-success-border` / `--cc-success-text`)
- **Warning / Advisory (`warning`)**: Amber tint (`--cc-warning-bg` / `--cc-warning-border` / `--cc-warning-text`)
- **Incompatible / Critical (`incompatible`)**: Red tint (`--cc-danger-bg` / `--cc-danger-border` / `--cc-danger-text`)
- **Unknown / Unverified (`unknown`)**: Neutral slate tint (`--cc-unknown-bg` / `--cc-unknown-border` / `--cc-unknown-text`)

---

## 3. Tailwind CSS v4 Build Workflow

The source stylesheet is [frontend_src/tailwind.css](frontend_src/tailwind.css), which declares Tailwind v4 `@custom-variant dark`, `@custom-variant light`, and explicit `@source` globs covering:
- `templates/**/*.html`
- `store/templates/**/*.html`
- `pc_builder/templates/**/*.html`
- `management/templates/**/*.html`
- `store/forms.py`, `pc_builder/forms.py`, `management/forms.py`
- `static/js/**/*.js`

### Rebuilding Production CSS
Whenever template utility classes, form widget classes, or component tokens change, recompile the minified bundle:

```powershell
.\.venv\Scripts\tailwindcss.exe -i frontend_src/tailwind.css -o static/css/app.min.css --minify
```

When preparing static assets for deployment:

```powershell
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

---

## 4. Local Iconography & Brand Assets

- **Icons:** Bundled locally at `static/vendor/lucide.min.js` (`Lucide v0.475.0`). No external icon font CDN is required.
- **Template Filter (`lucide_icon`):** Defined in [store/templatetags/store_extras.py](store/templatetags/store_extras.py), translating legacy database `Category.icon_class` (`bi-*`) values and hardware slot slugs into verified Lucide icon identifiers (for example `microchip` for GPUs, `circuit-board` for motherboards, `memory-stick` for RAM, `pc-case` for PC cases).
- **SVG Brand Mark:** Updated [static/images/corecraftr-mark.svg](static/images/corecraftr-mark.svg) to align with the CoreCraftr obsidian + copper-orange (`#F47738`) + tech-blue (`#62A6F8`) palette alongside the 13 category vector badges in `static/images/categories/`.

---

## 5. JavaScript Modules & Interactive Primitives

1. **`<head>` Zero-Flash Theme Script (`templates/base.html`, `management/templates/management/base_portal.html`, error pages):**
   Reads `localStorage.getItem('corecraftr-theme')` synchronously before paint, resolves `'system'` via `prefers-color-scheme: light`, applies `.dark` or `.light` on `<html>`, and defaults to `'dark'`.
2. **`static/js/theme.js` (`window.CoreCraftrTheme`):**
   - Synchronizes segmented `Dark | Light | System` controls (`[data-theme-choice]`) with `aria-pressed` states and listens for OS theme changes when set to `system`.
   - Implements accessible vanilla JS UI primitives (zero Bootstrap JS dependency):
     - Dropdown menus (`[data-dropdown-toggle]` / `[data-dropdown-panel]`, click-outside & Escape close)
     - Slide-over mobile navigation drawers (`[data-drawer-open]` / `[data-drawer-close]` / `[data-drawer]`)
     - Dialog modals (`[data-modal-open]` / `[data-modal-close]` / `[data-modal]`)
     - Inline accordions/collapsibles (`[data-collapse-toggle]`) and dismissible flash messages (`[data-dismiss-alert]`)
     - Automatic `lucide.createIcons()` initialization and refresh.
3. **`static/js/cart.js`:**
   Handles async cart quantity/add updates via `/update_item/`, updates the header `#cart-total` counter immediately, supports full-reload flows where specified (`data-reload="true"`), and displays floating `.cc-toast` notifications with Lucide icons.
4. **`static/js/management.js`:**
   Powers Management Portal dynamic behaviors including category-driven specification schema loading (`/management/api/spec-schema/<id>/`), live product duplicate SKU/name checks (`/management/api/duplicate-check/`), and schema-constrained AI spec research triggers/draft review (`/management/api/ai-research/`, `/management/api/ai-draft/<id>/discard/`).

---

## 6. Redesigned Surface Architecture

- **Global Storefront Shell (`templates/base.html` + `templates/components/`):** Sticky translucent header with category mega-dropdown, search pill, Theme Switcher, Cart/Account triggers, mobile drawer navigation, and multi-column footer (`templates/components/{theme_switcher,messages,pagination}.html`).
- **Storefront Pages (`store/templates/store/`):** Hero showcase with hardware-category quick links, sidebar-filtered catalog (`store.html`) with live search/sort/compatibility spec filters, unified `.cc-product-frame` thumbnails (`partials/product_card.html`), interactive multi-image gallery & grouped specs (`detail.html`), side-by-side spec comparator (`compare.html`), **PC BUILD COMPATIBILITY CHECK** panel with Option A/B replacements (`cart.html`), non-blocking compatibility acknowledgement checkout (`checkout.html`), order tracking, wishlist, profile, and auth flows.
- **Intelligent PC Builder (`pc_builder/templates/pc_builder/`):** Step-by-step Beginner Mode assistant + full slot-table Expert Mode switcher on the same active build, wattage/status gauges, expandable Smart Alternatives, slot component picker (`select_component.html`), and saved build manager (`saved_builds.html`).
- **Owner & Inventory Portal (`management/templates/management/`):** Isolated staff layout (`base_portal.html`) with sticky desktop sidebar and mobile drawer, strict customer exclusion, KPI dashboard cards, inline inventory controls, ledger tables, two-step CSV import preview, valuation reports, staff role management, and immutable audit viewer.
- **Error Templates (`templates/403.html`, `404.html`, `500.html`):** Theme-aware error pages (`500.html` intentionally self-contained with CSS + inline theme resolver only).
