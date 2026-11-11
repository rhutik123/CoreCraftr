# CoreCraftr — Build Smarter. Build Better.

**CoreCraftr** is a computer hardware marketplace with an intelligent PC Builder that helps beginners and experienced enthusiasts select, compare, and purchase compatible PC components.

Built as a modular Django monolith (originating from `rhutik123/Ecommerce-website` and now hosted at `https://github.com/rhutik123/CoreCraftr`), CoreCraftr combines a modern hardware storefront, deterministic compatibility verification across both the PC Builder and shopping cart, and catalog-grounded AI assistance with automatic fallback.

---

## Main Features

### 1. Hardware Storefront & Checkout (`store`)
- **Guest-Friendly Catalogue**: Browse all hardware categories without forced login (CPUs, GPUs, Motherboards, RAM, SSDs/HDDs, Power Supplies, PC Cases, CPU Coolers, Case Fans, Monitors, Keyboards, Mice, and Accessories).
- **Search, Multi-Facet Filtering & Sorting**: Filter by category, brand, price range (formatted in Indian numbering, `₹10,799.00`), socket, DDR generation, stock availability, and sort by featured, price, rating, newest, or name.
- **Structured Hardware Specifications & Verification**: Dedicated `HardwareSpecProfile` + grouped `ProductSpecification` tables with category-tailored spec highlights that mark missing attributes explicitly as `Unknown / Not verified`.
- **Side-by-Side Comparison**: Compare up to 4 products in the same hardware category (`/compare/`).
- **Non-Blocking Cart Compatibility Check (`PC BUILD COMPATIBILITY CHECK`)**: Automatically checks multi-component shopping carts using the shared deterministic compatibility engine, shows Beginner + Expert explanations and Option A / Option B database-verified swaps (`POST /cart/swap/`), never blocks checkout, recalculates freshly at checkout, requires explicit customer acknowledgement on serious conflicts, and records compatibility results on `Order`.
- **Account & Transactional Safety**: Persistent wishlist, delivery preferences, order history, demo checkout (`COD`, `UPI Demo`, `Card Demo`, `NetBanking Demo` — no real payment gateway), atomic stock locks (`select_for_update`), and pre-login session merging for carts and guest builds.

### 2. Dual-Mode Intelligent PC Builder (`pc_builder`)
- **Beginner Mode ("Help me build my first PC")**: Captures budget, primary use (Gaming, Programming, Video Editing, Office, Streaming, Mixed), priority preference, upgradeability preference, preferred brands, and optional monitor/peripherals. Explains why each part fits, trade-offs, and verified alternatives.
- **Expert Mode ("I know what I'm looking for")**: Slot-by-slot component picker with technical filters, "Compatible with Current Build Only" toggle, live per-item compatibility status badges, and performance/price sorting.
- **Non-Destructive Mode Switching**: Switch freely between Beginner and Expert modes on the same active `PCBuild` without losing components or silently deleting incompatible choices.
- **Saved Builds & Build-to-Cart**: Save builds per user with strict ownership isolation and add complete builds to the cart in one click.

### 3. Deterministic Hardware Compatibility Engine (`pc_builder.services.compatibility`)
Compatibility decisions are **always evaluated by deterministic backend rules**, never decided by AI. Every rule reports one of four explicit statuses:
- `compatible` — Verified compatible
- `incompatible` — Known physical, electrical, or platform conflict
- `warning` — Possible limitation (e.g., BIOS update required, XMP/EXPO above JEDEC, 12VHPWR adapter needed, tight case clearance, missing stock cooler, CPU without integrated graphics)
- `unknown` — Insufficient verified specification data (never assumed compatible)

Checks cover CPU <-> Motherboard (socket, `ChipsetCPUSupport` matrix, `MotherboardCPUSupport` QVL overrides, BIOS notes), Motherboard <-> RAM, CPU <-> RAM, GPU <-> Case clearance, CPU Cooler <-> Case & CPU TDP/sockets, Motherboard <-> Case form factor, Storage M.2/SATA slots & bay limits, and PSU peak wattage + power connectors.

### 4. Catalog-Grounded AI Recommendations (`ai_engine`)
- Structured build and conflict-resolution guidance only (no generic chatbot).
- Optional OpenAI or Gemini integration configured purely via `.env` (`AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL`).
- **Strict Grounding Gate**: Every AI-suggested `product_id` must match an active, in-stock, spec-verified database product in the target slot and pass `CompatibilityEngine` cleanly.
- **Graceful Fallback**: When `AI_PROVIDER=none`, an API key is missing, or the AI proposes invalid/incompatible hardware, `DeterministicBuildRecommender` and deterministic alternatives run seamlessly with transparent status notices.

---

## Technology Stack
- **Backend**: Python, Django 5.2 (`corecraftr` project package; modular apps `store`, `pc_builder`, `ai_engine`), Django REST Framework, `django-filter`, `python-dotenv`, WhiteNoise, Pillow
- **Database**: PostgreSQL target via `psycopg` (`psycopg3`), with automatic local SQLite fallback when PostgreSQL credentials are not configured in development/testing
- **Frontend**: Django Templates, Bootstrap 5.3, Bootstrap Icons, Vanilla JavaScript, custom CSS & SVG hardware marks
- **Testing**: `pytest` + `pytest-django`

---

## Installation & Quick Start

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for full PostgreSQL configuration and security remediation notes.

```powershell
# 1. Clone CoreCraftr
git clone https://github.com/rhutik123/CoreCraftr.git
cd CoreCraftr
git checkout feature/corecraftr-branding

# 2. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables (placeholders only in .env.example)
Copy-Item .env.example .env
# Edit .env with your DJANGO_SECRET_KEY and PostgreSQL DB_PASSWORD
# (Leave DB_PASSWORD blank or set DB_ENGINE=sqlite to use local SQLite fallback)

# 5. Apply migrations and seed verified computer hardware catalogue
python manage.py migrate
python manage.py seed_hardware_catalog

# 6. Collect static files and start the development server
python manage.py collectstatic --noinput
python manage.py runserver
```

### Verification & Tests
```powershell
# Run automated test suite
pytest

# Verify Django system health and migration consistency
python manage.py check
python manage.py makemigrations --check --dry-run
```
