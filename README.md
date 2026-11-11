# CoreCraftr

**Build Smarter. Build Better.**

CoreCraftr is a modular Django computer hardware e-commerce platform paired with an intelligent dual-mode PC Builder, deterministic hardware compatibility validation, catalog-grounded AI assistance, and a dedicated Owner & Inventory Management Portal.

Built as an evolution of a standard Django storefront (`https://github.com/rhutik123/CoreCraftr`), CoreCraftr lets hardware shoppers browse components freely without forced logins, validate multi-component shopping carts before ordering, craft complete PC builds step by step or slot by slot, and manage SKUs, specifications, stock movements, CSV batches, and staff permissions from a role-restricted management workspace.

---

## Features

### Storefront, Discovery & Accounts (`store`)
- **Hardware Catalogue & Structured Specs**: Organizes SKUs into 13 hardware categories (`Category`, `Brand`, `Product`, `HardwareSpecProfile`, `ProductSpecification`) with multi-image galleries (`ProductImage`), category-relevant spec highlights (`Unknown / Not verified` for missing values), and Indian Rupee formatting (`₹10,799.00`).
- **Search, Filtering & Comparison**: Full-text search alongside multi-facet filters (category, brand, min/max price, socket, DDR generation, in-stock status), sorting, and side-by-side comparison (`/compare/`) highlighting differing specifications across up to 4 same-category parts.
- **Shopping Cart & Non-Blocking Compatibility Check**: Session- and user-backed shopping carts that merge pre-login guest carts seamlessly on login. Multi-component carts display a **PC BUILD COMPATIBILITY CHECK** panel evaluating internal PC parts with Beginner + Expert explanations and database-verified Option A / Option B swap suggestions (`POST /cart/swap/`).
- **Checkout & Order Management**: Server-side price, shipping (free at ₹5,000+, ₹199 standard below), and tax/total calculation with row-locked inventory deductions (`select_for_update`), fresh compatibility recalculation on GET/POST, mandatory customer acknowledgement when conflicts exist (`Order.incompatibility_acknowledged`), demo checkout payment options (`COD`, `UPI Demo`, `Card Demo`, `NetBanking Demo`), and customer order confirmation/history with IDOR checks.
- **Customer Accounts & Wishlist**: Registration, login, logout, password reset workflow, profile delivery preferences, order history, and persistent wishlist (`/account/wishlist/`).

### Intelligent PC Builder & Compatibility Engine (`pc_builder`)
- **Dual-Mode Workspace (`/builder/`)**:
  - **Beginner Mode ("Help me build my first PC")**: Captures budget, primary workload, priority preference, upgradeability preference, preferred brands, and optional monitor/peripherals, explaining part fit and trade-offs.
  - **Expert Mode ("I know what I'm looking for")**: Direct slot-by-slot component picker (`/builder/select/<slot>/`) with technical filters, a compatible-only toggle, live per-item status indicators, and Smart Alternatives.
  - **Non-Destructive Mode Switching**: Beginner and Expert views operate on the same active `PCBuild`, switching cleanly without deleting existing or incompatible picks.
- **Saved Builds & One-Click Cart Transfer**: Logged-in users can save isolated `PCBuild` snapshots (`/builder/saved/`) and add complete builds to their shopping cart atomically.
- **Deterministic Compatibility Engine (`pc_builder.services.compatibility`)**: Evaluates 4 explicit states (`compatible`, `incompatible`, `warning`, `unknown`) without guessing missing specs or delegating compatibility logic to AI. Rules check:
  - CPU & Motherboard (socket, `ChipsetCPUSupport` matrix, `MotherboardCPUSupport` QVL overrides, BIOS notes)
  - Motherboard & RAM, plus CPU & RAM (DDR generation, module slots, max capacity, JEDEC vs XMP/EXPO warnings)
  - GPU & Case clearance (`gpu_length_mm` vs `max_gpu_length_mm`), Cooler & Case/CPU (stock cooler checks, socket support, height/radiator clearance, thermal TDP), Motherboard & Case form factor
  - Storage M.2 NVMe/SATA/port/bay limits & slot-sharing advisories
  - Peak PSU wattage headroom & PCIe/12VHPWR power connectors, plus missing iGPU and single-channel RAM advisories
- **DRF Builder Endpoints (`/builder/api/`)**: Session-authenticated JSON views (`BuildStateAPIView`, `CompatibilityCheckAPIView`, `BeginnerRecommendAPIView`, `SlotAlternativesAPIView`).

### Catalog-Grounded AI Engine (`ai_engine`)
- **Build Recommendations (`BuildRecommendationOrchestrator`)**: Optional OpenAI or Gemini recommendations strictly gated against active, in-stock catalog SKUs and validated through `CompatibilityEngine`.
- **Cart Conflict Advisory (`CartCompatibilityAdvisor`)**: Explains cart incompatibilities and evaluates verified replacement pairs cleanly.
- **Product Specification Research (`ProductSpecResearchService`)**: Assists portal staff by drafting schema-aligned technical specs with manufacturer vs third-party source tagging, conflict warnings, forbidden commercial key stripping, and mandatory human approval before saving.
- **Automatic Deterministic Fallback**: Every AI entry point falls back seamlessly to deterministic logic or manual workflows when `AI_PROVIDER=none`, keys are absent, or AI output fails validation.

### Owner & Inventory Management Portal (`management`)
- **Role-Based Staff Portal (`/management/`)**: Completely isolated from customer navigation. **Owners** (Django superusers) control everything including staff provisioning/revocation (`/management/users/`) and read-only audit logs (`/management/audit/`), while **Inventory Managers** (synced `Inventory Manager` group) manage products, media, specs, stock, CSVs, and valuation reports without access to `/management/users/`, `/management/audit/`, or `/admin/`.
- **Product, Media & Spec Studio**: Enforces unique SKUs, surfaces advisory duplicate warnings, synchronizes `draft` / `published` / `archived` visibility cleanly without erasing order history, validates gallery image binaries (`JPEG`, `PNG`, `WEBP` via Pillow, configurable max byte size), and renders dynamic category-specific compatibility spec fields (`management.spec_schemas`).
- **Atomic Stock Control & Audit Trail**: Row-locked stock adjustments (`add`, `subtract`, `set`) with optimistic version tokens, negative/reserved guards, `StockMovement` logs (including automatic `order_deduction` records at checkout), `PriceChangeLog`, and append-only immutable `AuditLog`.
- **Two-Step CSV Import / Export & Reports (`/management/import-export/`, `/management/reports/`)**: Validates up to 2,000 rows (`5 MB` max) in a preview batch (`CSVImportBatch`) before confirming updates, exports catalog + spec columns cleanly, and computes inventory valuation strictly across SKUs with verified `cost_price`.

### Modern Adaptive UI
- **Dark, Light & System Themes**: Dark-first hardware workbench palette with Light daylight mode and OS `System` auto-switching stored in `localStorage` (`corecraftr-theme`) with an inline pre-paint `<head>` script to prevent white flash.
- **Self-Contained Styles & Icons**: Built locally using Tailwind CSS v4 and bundled Lucide icons with zero Bootstrap CSS/JS or external Tailwind CDN dependencies (see [FRONTEND_DESIGN.md](FRONTEND_DESIGN.md)).

---

## Technology Stack

Verified versions installed and used in this repository:
- **Language & Runtime**: Python (`3.11+` target; verified on Python `3.15.0rc3`)
- **Web Framework**: Django `5.2.19` (`Django>=5.2,<6.0`)
- **APIs & Filtering**: Django REST Framework `3.18.3`, `django-filter` `26.2`
- **Database Drivers**: PostgreSQL via `psycopg[binary]` `3.3.8`, with automatic local SQLite fallback
- **Frontend Styling & UI**: Django Templates, Tailwind CSS `v4.3.5` (compiled via `pytailwindcss` `0.4.2`), Vanilla JavaScript (`theme.js`, `cart.js`, `management.js`), local Lucide Icons `v0.475.0` (`static/vendor/lucide.min.js`)
- **Media, Static Serving & Env**: Pillow `13.0.0`, WhiteNoise `6.12.0`, `python-dotenv` `1.2.4`
- **Testing**: `pytest` `9.2.0`, `pytest-django` `4.14.0`

---

## Project Architecture

CoreCraftr uses a modular monolith layered by domain (`models` -> `services` -> `views` / `api_views` -> `templates`). Detailed schema continuity, compatibility rule groups, and portal workflows live in [ARCHITECTURE.md](ARCHITECTURE.md), and the CSS token / component system lives in [FRONTEND_DESIGN.md](FRONTEND_DESIGN.md).

- **`corecraftr/`**: Django project configuration package (`settings.py`, `urls.py`, `wsgi.py`, `asgi.py`, Admin branding).
- **`store/`**: Hardware catalogue (`Product`, `Category`, `Brand`, `HardwareSpecProfile`, `ProductImage`), search/filtering, comparison, session-merged cart & cart compatibility bridge (`cart_compatibility.py`), transactional checkout/orders, wishlist, customer accounts, and `seed_hardware_catalog`.
- **`pc_builder/`**: `PCBuild` & `BuildComponent` persistence, platform support rules (`ChipsetCPUSupport`, `MotherboardCPUSupport`), `CompatibilityEngine`, `SmartAlternativesService`, Beginner/Expert workflows, and DRF API views.
- **`ai_engine/`**: `AIProviderClient`, `DeterministicBuildRecommender`, `BuildRecommendationOrchestrator`, `CartCompatibilityAdvisor`, and `ProductSpecResearchService` + `WebSearchClient`.
- **`management/`**: Portal RBAC (`PortalPermission`, `permissions.py`), stock/price/audit/AI-draft models, category spec schemas (`spec_schemas.py`), CSV preview importer/exporter, valuation reporting, portal templates/JS, and `seed_portal_demo`.

```text
CoreCraftr/
├── corecraftr/                  # Project settings, URLs, WSGI/ASGI, Admin setup
├── store/                       # Storefront, catalogue, cart, checkout, accounts
│   ├── management/commands/     # seed_hardware_catalog
│   ├── migrations/              # 0001–0008 schema & legacy data backfill
│   ├── services/                # catalog, cart, cart_compatibility, comparison, order
│   ├── templatetags/            # |inr, |inr_whole, |lucide_icon filters
│   └── templates/store/         # Storefront, detail, compare, cart, checkout, auth
├── pc_builder/                  # Dual-mode PC Builder & deterministic engine
│   ├── migrations/              # 0001_initial
│   ├── services/                # compatibility, alternatives, builder_service
│   └── templates/pc_builder/    # workspace, select_component, saved_builds
├── ai_engine/                   # Catalog-grounded AI orchestrator & spec research
│   └── services/                # recommender, spec_researcher
├── management/                  # Owner & Inventory Manager workspace (/management/)
│   ├── management/commands/     # seed_portal_demo
│   ├── migrations/              # 0001_initial
│   ├── services/                # product, image, inventory, csv, report, user, audit, ai_spec
│   └── templates/management/    # Dashboard, product form, inventory, import/export, reports, users, audit
├── frontend_src/                # Tailwind CSS v4 input & theme variables (tailwind.css)
├── templates/                   # Shared base.html, error pages (403/404/500), UI partials
├── static/                      # Compiled app.min.css, JS, Lucide vendor bundle, SVG category marks
├── .env.example                 # Safe environment variable template
├── pytest.ini                   # Pytest Django settings configuration
├── requirements.txt             # Python dependencies
├── ARCHITECTURE.md              # Detailed system & database architecture
└── FRONTEND_DESIGN.md           # Theme tokens, Tailwind CSS build & JS primitives
```

---

## Installation and Setup (Windows)

```powershell
# 1. Clone the repository
git clone https://github.com/rhutik123/CoreCraftr.git

# 2. Open the project directory
cd CoreCraftr

# 3. Create a Python virtual environment
python -m venv .venv

# 4. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 5. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 6. Configure environment variables (edit .env locally after copying)
Copy-Item .env.example .env

# 7. Configure the database
#    - Option A (PostgreSQL): Create your database and set DB_ENGINE=postgresql and DB_PASSWORD in .env
#    - Option B (Local SQLite fallback): Leave DB_PASSWORD unset or set DB_ENGINE=sqlite

# 8. Run database migrations and seed starter hardware catalog
python manage.py migrate
python manage.py seed_hardware_catalog
# Optional: seed portal demo SKUs, stock ledger movements, demo order & staff/customer accounts:
python manage.py seed_portal_demo

# 9. Build frontend CSS assets and collect static files
tailwindcss -i frontend_src/tailwind.css -o static/css/app.min.css --minify
python manage.py collectstatic --noinput

# 10. Create an Owner (superuser) account for /management/ and /admin/
python manage.py createsuperuser

# 11. Run the development server
python manage.py runserver
```

Key local URLs:
- **Storefront & Catalogue**: `http://127.0.0.1:8000/` & `http://127.0.0.1:8000/store/`
- **Product Comparison**: `http://127.0.0.1:8000/compare/`
- **Intelligent PC Builder & API**: `http://127.0.0.1:8000/builder/` & `http://127.0.0.1:8000/builder/api/build/`
- **Management Portal & Django Admin**: `http://127.0.0.1:8000/management/` & `http://127.0.0.1:8000/admin/`

---

## Environment Configuration

Settings load via `python-dotenv` from `.env` (see [.env.example](.env.example)). Ensure `.env` remains untracked in Git and never commit live keys or passwords.

| Variable | Purpose | Example / Default |
| :--- | :--- | :--- |
| `DJANGO_SECRET_KEY` | Django cryptographic signing key (required if `DJANGO_DEBUG=False`) | `replace-with-a-long-random-secret-key` |
| `DJANGO_DEBUG` | Enables debug mode (`False` enforces HTTPS/HSTS and secret checks) | `True` (set `False` in production) |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated permitted hostnames | `127.0.0.1,localhost` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated CSRF-trusted origins | `http://127.0.0.1:8000,http://localhost:8000` |
| `DJANGO_TIME_ZONE` | Application timezone | `Asia/Kolkata` |
| `DB_ENGINE` | Database backend selector (`postgresql` or `sqlite`) | `postgresql` |
| `DB_NAME` | PostgreSQL database name | `corecraftr_db` |
| `DB_USER` | PostgreSQL username | `postgres` |
| `DB_PASSWORD` | PostgreSQL password | `replace-with-your-postgres-password` |
| `DB_HOST` | PostgreSQL host | `127.0.0.1` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DJANGO_ALLOW_SQLITE_FALLBACK` | Falls back to SQLite when PG password is empty/placeholder | `True` (`False` recommended in prod) |
| `EMAIL_BACKEND` | Django mail backend (console backend by default locally) | `django.core.mail.backends.console.EmailBackend` |
| `EMAIL_HOST` | SMTP server host | `smtp.gmail.com` |
| `EMAIL_PORT` | SMTP server port | `587` |
| `EMAIL_USE_TLS` | Enable STARTTLS for SMTP | `True` |
| `EMAIL_HOST_USER` | SMTP login email | `your-email@example.com` |
| `EMAIL_HOST_PASSWORD` | SMTP password / app password | `replace-with-app-password` |
| `DEFAULT_FROM_EMAIL` | Sender address for transactional/reset emails | `noreply@corecraftr.local` |
| `AI_PROVIDER` | AI backend (`none`, `openai`, or `gemini`) | `none` |
| `AI_API_KEY` | Provider API key | `replace-with-your-ai-api-key` |
| `AI_MODEL` | Target model identifier | `gpt-4o-mini` |
| `AI_TIMEOUT_SECONDS` | HTTP timeout for AI requests (seconds) | `15` |
| `AI_SEARCH_PROVIDER` | Portal spec search provider (`none`, `tavily`, `serper`, `google_cse`) | `none` |
| `AI_SEARCH_API_KEY` | Optional search API key | `replace-with-your-search-api-key` |
| `AI_SEARCH_ENGINE_ID` | Google CSE engine ID (only for `google_cse`) | `replace-with-google-cse-id` |
| `AI_RESEARCH_RATE_LIMIT_PER_HOUR` | Per-staff hourly spec research request limit | `20` |
| `PRODUCT_IMAGE_MAX_BYTES` | Maximum upload size for product images in bytes | `5242880` (5 MB) |

---

## Database Configuration

`corecraftr/settings.py` supports both **PostgreSQL** (`django.db.backends.postgresql`) and automatic local **SQLite fallback** (`django.db.backends.sqlite3`):
- **PostgreSQL Mode**: Activated when `DB_ENGINE=postgresql` (or `postgres`) and either a real non-placeholder `DB_PASSWORD` is configured or `DJANGO_ALLOW_SQLITE_FALLBACK=False`.
- **SQLite Fallback Mode**: Activated when `DB_ENGINE=sqlite` or when `DB_PASSWORD` is blank or set to a `replace-with-*` placeholder while `DJANGO_ALLOW_SQLITE_FALLBACK=True`. Reads/writes `db.sqlite3` at the repository root (or `SQLITE_DB_PATH`).

> **Verification Scope Note**: All local migrations, catalog seeding, and automated tests in this repository were executed against the SQLite fallback backend because a live PostgreSQL instance/credentials were not configured in the local environment. Test migrations and workflows against your target PostgreSQL server before production deployment.

---

## AI Configuration

- **Configuration**: Set `AI_PROVIDER` (`openai` or `gemini`), `AI_API_KEY`, and `AI_MODEL` in `.env` (plus optional `AI_SEARCH_PROVIDER` / `AI_SEARCH_API_KEY` for Portal Spec Research). Keep `AI_PROVIDER=none` to operate completely offline.
- **Recommendations (`BuildRecommendationOrchestrator` & `CartCompatibilityAdvisor`)**: Prompts request structured JSON component picks/advice, then verify every proposed `product_id` against active, in-stock DB products in the target category slot and validate the resulting build through `CompatibilityEngine`. Locked user parts are preserved; hallucinated IDs or incompatible combinations are rejected.
- **Specification Research (`ProductSpecResearchService`)**: Constrains proposed fields to category schemas (`management.spec_schemas`), strips forbidden commercial keys (`sku`, `price`, `cost_price`, `quantity`, `status`), tags `manufacturer` vs `third_party` URLs with SSRF guardrails, surfaces conflicting or missing fields instead of guessing values, stores results in `AIResearchDraft`, and requires explicit staff approval before saving specs.
- **Fallback Behaviour**: Whenever `AI_PROVIDER=none`, an API key is missing, a timeout occurs, or validation rejects an AI response, CoreCraftr falls back transparently to `DeterministicBuildRecommender`, deterministic cart swaps, or manual portal specification entry.

---

## Running Tests & Verification Commands

```powershell
# 1. Build minified Tailwind CSS bundle
tailwindcss -i frontend_src/tailwind.css -o static/css/app.min.css --minify

# 2. Collect static files cleanly (WhiteNoise-ready)
python manage.py collectstatic --noinput

# 3. Django system and migration consistency checks
python manage.py check
python manage.py makemigrations --check --dry-run

# 4. Run full automated pytest suite (68 tests across all apps)
pytest -v
```

### Bulk CSV Portal Columns Reference
CSV imports in `/management/import-export/` enforce a `5 MB` / `2,000`-row limit and generate a preview batch prior to committing changes:
- **Required columns**: `sku`, `name`, `price` (plus `category_slug` when creating new SKUs)
- **Optional catalog columns**: `brand_name`, `model_number`, `status` (`draft`/`published`/`archived`), `cost_price`, `stock_quantity`, `low_stock_threshold`, `warranty_months`, `short_description`, `description`
- **Supported typed spec columns**: `socket`, `chipset`, `form_factor`, `memory_type`, `tdp_watts`, `wattage`, `vram_gb`, `capacity_gb`, `ram_capacity_gb`, `ram_modules`, `ram_speed_mhz`, `memory_slots`, `gpu_length_mm`, `cooler_height_mm`, `radiator_size_mm`, `max_gpu_length_mm`, `max_cooler_height_mm`, `max_psu_length_mm`, `psu_form_factor`, `psu_length_mm`, `storage_type`, `storage_form_factor`, `recommended_psu_watts`, `supported_sockets`, `supported_form_factors`, `supported_memory_types`, `supported_cpu_families`, `supported_radiator_sizes_mm`, `m2_nvme_slots`, `m2_sata_slots`, `sata_ports`, `performance_tier`, `benchmark_score`

---

## Security Considerations

- **Environment & Secret Hygiene**: No live credentials, `.env` files, private keys, or `*.sqlite3` databases are tracked on active feature branches; `.gitignore` blocks `.env`, `.env.*` (except `.env.example`), `*.pem`, `*.key`, and database files. Setting `DJANGO_DEBUG=False` forbids insecure fallback secret keys and activates `SECURE_SSL_REDIRECT`, secure cookies, and 1-year `SECURE_HSTS_SECONDS`.
- **Authentication & Staff RBAC**: Storefront customers use isolated accounts with pre-login session merging; staff portal views enforce `Owner` vs `Inventory Manager` group permissions server-side, protect against deactivating the last active Owner, return `403` across unauthorized portal routes, and hide staff links from customer navbars.
- **Server-Side Checkout & Inventory Locks**: Product prices, shipping charges, compatibility checks, and totals are computed strictly on the server. Order creation and stock adjustments acquire row-level locks (`select_for_update`), block negative or below-reserved stock deductions, preserve order item snapshots independently of catalog price edits, and log immutable `AuditLog` entries.
- **Upload & AI Input Hardening**: Product images undergo Pillow binary inspection (`JPEG`/`PNG`/`WEBP`, max size enforced). AI spec research applies per-user hourly cache rate limiting (`429`), SSRF protections, commercial-key stripping, and mandatory staff approval.
- **Historical Git Commits Notice**: Earlier upstream repository snapshots (`master` commits `d44f34f` / `fed3650` and historical `db.sqlite3` tracked up through `767fb3f`) previously contained a hardcoded development key, SMTP password, and local SQLite data before remediation. Those historical commits remain in upstream Git history because history rewriting was avoided—**rotate any previously exposed credentials** before production use, and coordinate `git filter-repo` history purging only if repository history must be scrubbed publicly.

---

## Limitations

- **Simulated Payment Gateway**: Checkout uses simulated demo payment options (`COD`, `UPI Demo`, `Card Demo`, `NetBanking Demo`) rather than a live merchant payment gateway (no real payment processing or webhook verification).
- **Live External AI / Search**: External LLM (`OpenAI`/`Gemini`) and web search (`Tavily`/`Serper`/`Google CSE`) endpoints require user-supplied credentials and network access; without live keys configured in this workspace, verification covered deterministic fallback paths and mocked client unit tests rather than live external API calls.
- **Local Database Verification**: Automated tests and local verification executed on SQLite fallback; live PostgreSQL deployment should be verified directly against the target PostgreSQL instance.
- **Browser E2E Testing**: Frontend redesign checks verified static builds, rendered HTML responses across routes, asset integrity, and icon resolution via `pytest` rather than an automated headless browser runner.

---

## Future Improvements

*(These items represent potential future enhancements and are not currently implemented.)*
- Live payment gateway integration (e.g., Razorpay / Stripe with signed webhook confirmation and refund workflows).
- Live PostgreSQL + Nginx/Gunicorn CI/CD deployment pipeline with automated container health checks.
- Background task queue (e.g., Celery) for asynchronous bulk AI specification research and large CSV imports.
- Automated Playwright / headless browser visual regression tests covering Light/Dark theme toggling and responsive viewports.
- Customer shipment tracking numbers, invoice PDF generation, and order cancellation/return flows.

---

## License

No `LICENSE` file is currently present in this repository. All rights and licensing permissions remain unspecified until an explicit license file is added by the repository owner.
