# PROJECT PROGRESS — Computer Hardware E-Commerce + Intelligent PC Builder

Repository: `Ecommerce-website` (upgraded from `https://github.com/rhutik123/Ecommerce-website`)  
Branch: `feature/pc-builder-upgrade`  
Original Branch Preserved: `master`

---

## Phase 0 — Audit and Preparation
**Status:** Completed

### Completed Tasks
- Cloned source repository from GitHub (`https://github.com/rhutik123/Ecommerce-website.git`).
- Inspected existing code (`ecomnmerce/`, `store/`, `static/`, `db.sqlite3`, `requirements.txt`, templates, migrations `0001`–`0004`, Git log `d44f34f`, `fed3650`).
- Created backup of original `db.sqlite3` outside the workspace and checked out dedicated feature branch `feature/pc-builder-upgrade`.
- Untracked legacy `__pycache__/*.pyc` artifacts from Git index and added `.gitignore` and `.env.example` (placeholders only).
- Logged security findings from initial audit: hardcoded `SECRET_KEY` and SMTP credentials in original `settings.py`/history, `DEBUG=True`, `ALLOWED_HOSTS=[]`, `@login_required` blocking guest storefront browsing, client-trusted float order total in `processOrder`, and unsafe `User.objects.get` / `request.user.customer` lookups.

---

## Phase 1 — Modern Django Foundation
**Status:** Completed

### Completed Tasks
- Created Python `.venv` and updated `requirements.txt` with `Django>=5.2,<6.0`, `djangorestframework>=3.16,<4.0`, `django-filter>=25.1`, `psycopg[binary]>=3.2`, `Pillow>=11.0`, `python-dotenv>=1.0`, `whitenoise>=6.8`, `pytest>=8.0`, and `pytest-django>=4.9`.
- Upgraded `ecomnmerce/settings.py` to load `.env`, enforce env-driven `DJANGO_SECRET_KEY`/`DJANGO_DEBUG`/`DJANGO_ALLOWED_HOSTS`/email/AI configuration, target PostgreSQL via `DB_*` env vars with automatic SQLite dev/test fallback (`DATABASE_MODE='sqlite_fallback'`), enable WhiteNoise, configure DRF, and harden HTTP/session/CSRF security settings.
- Added modular apps `pc_builder` and `ai_engine`, created `pytest.ini`, shared `templates/base.html`, and responsive Bootstrap 5 UI styles/scripts (`static/css/main.css`, `static/js/cart.js`).

---

## Phase 2 — Hardware Product Catalogue & Verified Data
**Status:** Completed

### Completed Tasks
- Upgraded `store/models.py` (`Category`, `Brand`, `Customer`, `Product`, `Inventory`, `ProductImage`, `HardwareSpecProfile`, `ProductSpecification`, `WishlistItem`, `Cart`, `CartItem`, `Order`, `OrderItem`, `ShippingAddress`), `store/signals.py`, and `store/admin.py`.
- Authored reversible schema & data migrations `store/migrations/0005_brand_category_hardwarespecprofile_inventory_and_more.py` and `store/migrations/0006_migrate_legacy_data.py`.
- Created `store/services/catalog_service.py` for curated homepage sections, multi-facet filtering (search, category, brand, min/max price, socket, DDR generation, in-stock), sorting, and grouped product specifications.
- Generated 13 category SVG graphics (`static/images/categories/*.svg`) and built idempotent `store/management/commands/seed_hardware_catalog.py` (75 curated products across 13 categories + enrichment of legacy Ryzen AM4 CPUs = 83 active products in `db.sqlite3`, plus `ChipsetCPUSupport` platform matrix).

---

## Phase 3 — Storefront E-Commerce, Checkout & Accounts
**Status:** Completed

### Completed Tasks
- Implemented `store/services/cart_service.py` and `store/services/order_service.py` cleanly separating `Cart`/`CartItem` from confirmed `Order`s.
- Fixed guest checkout/browse access (removed guest-blocking `@login_required` on homepage/catalogue/detail/compare/cart) while protecting account views (`@login_required`) and state mutations (`@require_POST`).
- Hardened `checkout` and `processOrder` with atomic inventory row locks (`select_for_update`), server-side price/shipping/total calculation (free shipping >= Rs. 5,000, Rs. 199 standard below), simulated demo payment methods, and IDOR checks on order confirmation.
- Fixed `loginPage` pre-login `session_key` capture prior to Django's `login()` session key rotation so guest carts and guest PC builds merge reliably upon sign-in.
- Built responsive Bootstrap 5 templates across all store, cart, checkout, order, comparison, wishlist, profile, login, register, and password-reset flows.

---

## Phase 4 — Dual-Mode PC Builder & Deterministic Compatibility Engine
**Status:** Completed

### Completed Tasks
- Implemented `pc_builder/models.py` (`ChipsetCPUSupport`, `MotherboardCPUSupport`, `PCBuild`, `BuildComponent`) and `pc_builder/migrations/0001_initial.py`.
- Built `CompatibilityEngine` in `pc_builder/services/compatibility.py` with 4 explicit statuses (`compatible`, `incompatible`, `warning`, `unknown`) covering CPU+Motherboard (socket, chipset matrix, QVL, BIOS), Motherboard+RAM, CPU+RAM, GPU+Case, Cooler+Case & CPU, Motherboard+Case form factor, Storage+Motherboard & Case bays/slot sharing, PSU wattage & PCIe/12VHPWR power connectors, and display output/single-channel advisories.
- Implemented `PCBuilderService` (`pc_builder/services/builder_service.py`), `SmartAlternativesService` (`pc_builder/services/alternatives.py`), `pc_builder/forms.py`, `pc_builder/views.py`, `pc_builder/api_views.py`, and templates (`workspace.html`, `select_component.html`, `saved_builds.html`).
- Verified non-destructive mode switching (`beginner` <-> `expert`), incompatible part retention (no silent deletion), saved build ownership enforcement, and one-click build-to-cart.

---

## Phase 5 — Catalog-Grounded AI Engine & Deterministic Fallback
**Status:** Completed

### Completed Tasks
- Implemented `AIProviderClient`, `DeterministicBuildRecommender`, and `BuildRecommendationOrchestrator` in `ai_engine/services/recommender.py`.
- Enforced strict catalog grounding and deterministic compatibility gate validation before returning any AI recommendation (`_validate_and_ground_ai_output`), rejecting fake IDs, wrong categories, out-of-stock SKUs, and incompatible hardware combinations.
- Verified automatic fallback to `DeterministicBuildRecommender` when no external AI key is configured (`AI_PROVIDER=none`) or when AI proposals fail validation.

---

## Phase 6 & 7 — Additional Features, Testing, Security Review & Documentation
**Status:** Completed

### Files Created / Modified
- **Project / Config**: `.gitignore`, `.env.example`, `pytest.ini`, `requirements.txt`, `ecomnmerce/settings.py`, `ecomnmerce/urls.py`, `templates/base.html`
- **Store App**: `store/models.py`, `store/signals.py`, `store/apps.py`, `store/context_processors.py`, `store/admin.py`, `store/forms.py`, `store/views.py`, `store/urls.py`, `store/tests.py`, `store/services/{catalog_service,cart_service,order_service,comparison_service}.py`, `store/migrations/{0005_*,0006_*}.py`, `store/management/commands/seed_hardware_catalog.py`, `store/templates/store/{main,home,store,detail,compare,cart,checkout,order_confirmation,order_history,profile,wishlist,login,register,reset_password,reset_sent,change_password,reset_complete}.html`, `store/templates/store/partials/product_card.html`
- **PC Builder App**: `pc_builder/models.py`, `pc_builder/admin.py`, `pc_builder/forms.py`, `pc_builder/views.py`, `pc_builder/api_views.py`, `pc_builder/urls.py`, `pc_builder/migrations/0001_initial.py`, `pc_builder/services/{compatibility,alternatives,builder_service}.py`, `pc_builder/templates/pc_builder/{workspace,select_component,saved_builds}.html`, `pc_builder/test_compatibility.py`, `pc_builder/test_builder_workflows.py`
- **AI Engine App**: `ai_engine/apps.py`, `ai_engine/models.py`, `ai_engine/services/recommender.py`, `ai_engine/tests.py`
- **Static & Docs**: `static/css/main.css`, `static/js/cart.js`, `static/images/categories/*.svg`, `README.md`, `ARCHITECTURE.md`, `SETUP_GUIDE.md`, `PROJECT_PROGRESS.md`

### Tests Executed & Results
- **Command**: `.\.venv\Scripts\pytest.exe` -> **31 passed in 8.50s (0 failed, 0 skipped)** covering:
  - `ai_engine/tests.py` (6 tests: no-key deterministic fallback, locked component preservation, hallucinated ID rejection, AM5+DDR4 incompatible AI rejection, wrong-category rejection, valid mocked AI acceptance & DB-grounded pricing)
  - `pc_builder/test_builder_workflows.py` (6 tests: Beginner recommendation + Beginner/Expert mode switching build preservation, non-silent deletion of incompatible selections & slot filtering, compatible smart alternatives, saved build ownership isolation & load/delete, build-to-cart & stock failure atomicity, DRF API endpoints)
  - `pc_builder/test_compatibility.py` (12 tests: socket mismatch, AM4 B550 rejecting Ryzen 1000 via chipset matrix, B450 + Ryzen 5000 BIOS warning, QVL override, AM5 + DDR4 mismatch, RAM slot/capacity limits + XMP warning, GPU/cooler clearance & form factor, cooler socket mismatch + missing stock cooler, PSU wattage + 12VHPWR native/adapter/missing, storage M.2 limit + slot sharing warning, unknown status on missing specs, seeded catalog check)
  - `store/tests.py` (7 tests: guest browsing, search/filters/sorting, side-by-side comparison, stock validation + session merge across real login rotation, server-side checkout pricing + atomic inventory deduction + IDOR 404 check, insufficient stock rejection at checkout, registration/wishlist/account/password-reset page rendering)
- **Django Verification Checks**:
  - `python manage.py check` -> `System check identified no issues (0 silenced).`
  - `python manage.py collectstatic --noinput` -> `187 static files copied` (clears WhiteNoise missing-dir warning)
  - `python manage.py makemigrations --check --dry-run` -> `No changes detected.`

### Known Issues & Environment Limitations
- **PostgreSQL Live Execution**: PostgreSQL 18.6 (`127.0.0.1:5432`, SCRAM-SHA-256 auth) is installed locally without pre-configured credentials in the environment, so live migrations, seeding, and tests ran using the automatic SQLite fallback (`DATABASE_MODE='sqlite_fallback'`). PostgreSQL target settings are ready and documented in `.env.example` and `SETUP_GUIDE.md`.
- **Live External LLM Calls**: No `OPENAI_API_KEY` or `GEMINI_API_KEY` is configured in environment; external AI REST paths were verified with deterministic fallback execution plus unit tests using mocked `AIProviderClient` responses.
- **Git History Secrets**: Historical commits on untouched `master` still retain the original repository's hardcoded secrets; remediation steps (credential rotation and optional history rewrite) are documented in `SETUP_GUIDE.md`.
