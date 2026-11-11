# HardwareHub — Computer Hardware E-Commerce & Intelligent PC Builder

An upgraded modular Django monolith transforming the original `rhutik123/Ecommerce-website` repository into a full-featured computer hardware storefront and intelligent **Beginner + Expert PC Builder** powered by a deterministic hardware compatibility engine and catalog-grounded AI assistance.

---

## Key Features

### 1. Modern Hardware E-Commerce Storefront (`store`)
- **Guest-Friendly Catalogue**: Browse all hardware categories without forced login (CPUs, GPUs, Motherboards, RAM, SSDs/HDDs, Power Supplies, PC Cases, CPU Coolers, Case Fans, Monitors, Keyboards, Mice, and Accessories).
- **Search, Multi-Facet Filtering & Sorting**: Filter by category, brand, price range, socket, DDR generation, stock availability, and sort by featured, price, rating, newest, or name.
- **Structured Hardware Specifications & Verification Status**: Dedicated `HardwareSpecProfile` + grouped `ProductSpecification` tables with clear spec verification indicators.
- **Side-by-Side Product Comparison**: Compare up to 4 products in the same hardware category with automatic highlight of differing specifications (`/compare/`).
- **Wishlist, Profile & Order History**: Persistent user wishlists, default delivery preferences, preferred builder mode, and full order history for signed-in users.
- **Separated Cart, Stock Validation & Simulated Checkout**:
  - Guest session carts and authenticated user carts (`Cart`, `CartItem`) cleanly separated from completed `Order` records.
  - Strict atomic stock checks on cart updates and transactional order creation (`transaction.atomic` + `select_for_update`).
  - Server-side price, shipping (free above Rs. 5,000), and total computation (never trusting client-submitted totals).
  - Clearly labeled simulated checkout methods (`COD`, `UPI Demo`, `Card Demo`, `NetBanking Demo`) — no real payment credentials are processed or stored.
  - Guest cart & active guest PC build automatically merge when logging in.

### 2. Dual-Mode Intelligent PC Builder (`pc_builder`)
- **Beginner Mode ("Help me build my first PC")**:
  - Captures budget, primary workload (Gaming, Programming, Video Editing, Office, Streaming, Mixed), performance-vs-value priority, upgradeability preference, preferred brands, and optional monitor/peripherals.
  - Recommends a balanced, compatibility-verified build from real catalog items.
  - Explains in plain language *why* each component was chosen, *what* it does, *who* it suits, *trade-offs*, and compatible cheaper / similar / higher / better-value alternatives, with expandable technical specs.
- **Expert Mode ("I know what I'm looking for")**:
  - Slot-by-slot component picker (`cpu`, `motherboard`, `ram`, `gpu`, `storage`, `storage_secondary`, `psu`, `case`, `cooler`, `case_fan`, `monitor`, `keyboard`, `mouse`).
  - Full technical spec inspection, socket/DDR/brand/stock/price filters, "Compatible with Current Build Only" toggle, live per-candidate compatibility badges, and performance/price sorting.
- **Non-Destructive Mode Switching**: Switch freely between Beginner and Expert modes at any time without losing any selected component. Beginners can inspect specs manually or replace a GPU in Expert mode, and Experts can switch to Beginner mode for explanations and alternatives on their current build.
- **Saved Builds & One-Click Build-to-Cart**: Save named snapshots, reload into the workspace with strict user ownership isolation, or add all selected build parts to the shopping cart in one click.

### 3. Deterministic Rule-Based Hardware Compatibility Engine (`pc_builder.services.compatibility`)
Compatibility decisions are **always computed by deterministic backend rules**, never delegated to an AI model. Every rule check outputs one of four explicit statuses:
- `compatible` — Verified compatible
- `incompatible` — Known physical, electrical, or platform conflict
- `warning` — Possible limitation (e.g., BIOS update, XMP/EXPO above JEDEC, 12VHPWR adapter, tight clearance, missing stock cooler, no iGPU without GPU)
- `unknown` — Insufficient verified specification data (never assumed compatible)

Checks include:
- CPU <-> Motherboard (socket match, `MotherboardCPUSupport` QVL overrides, `ChipsetCPUSupport` matrix e.g. B550 rejecting Ryzen 1000/2000G despite sharing AM4, BIOS warnings on B450/B660)
- Motherboard <-> RAM (DDR4 vs DDR5 keying, DIMM slot count, max RAM capacity, supported speeds)
- CPU <-> RAM (supported DDR types, max capacity, JEDEC vs XMP/EXPO speed)
- GPU <-> Case (length vs max GPU clearance & tight clearance margin)
- CPU Cooler <-> Case & CPU (air height vs clearance, liquid radiator size vs supported mounts, socket mounting support, missing stock cooler alert, thermal TDP warning)
- Motherboard <-> Case (ATX / Micro-ATX / Mini-ITX form factor support)
- Storage <-> Motherboard & Case (M.2 NVMe vs M.2 SATA slots, SATA port counts, bandwidth/slot-sharing notes, 2.5"/3.5" drive bays)
- PSU <-> System (estimated system peak wattage, recommended headroom, native 12VHPWR vs 8-pin PCIe cable checks, PSU length clearance)

### 4. Catalog-Grounded AI Service + Graceful Fallback (`ai_engine`)
- No generic chatbot — structured build recommendations & trade-off guidance only.
- Optional integration with OpenAI or Gemini configured solely via environment variables (`AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL`).
- **Strict Grounding & Compatibility Gate**: Every AI-suggested `product_id` is verified against active, in-stock database records in the correct category slot, prices and specs are sourced strictly from Django models, and the full build must pass `CompatibilityEngine` with zero incompatibilities.
- **Seamless Deterministic Fallback**: When no AI API key is configured, when the provider errors/times out, or if AI returns invalid/incompatible products, `DeterministicBuildRecommender` executes automatically and notifies the user transparently.

---

## Technology Stack
- **Backend**: Python, Django 5.2, Django REST Framework, `django-filter`, `python-dotenv`, WhiteNoise, Pillow
- **Database**: PostgreSQL target via `psycopg` (`psycopg3`), with automatic local SQLite fallback when PostgreSQL credentials are not configured in development/testing
- **Frontend**: Django Templates, Bootstrap 5.3, Bootstrap Icons, Vanilla JavaScript, custom CSS
- **Testing**: `pytest` + `pytest-django`

---

## Quick Start Summary

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for full instructions and PostgreSQL setup.

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
Copy-Item .env.example .env
# Edit .env with your DJANGO_SECRET_KEY and PostgreSQL password (or set DB_ENGINE=sqlite for quick demo)

# 4. Run migrations and seed curated computer hardware catalog
python manage.py migrate
python manage.py seed_hardware_catalog

# 5. Collect static files and start development server
python manage.py collectstatic --noinput
python manage.py runserver
```

Run automated tests:
```powershell
pytest
```
