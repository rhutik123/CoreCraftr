# System Architecture — CoreCraftr

**Tagline:** *Build Smarter. Build Better.*  
**Repository:** `https://github.com/rhutik123/CoreCraftr`

## 1. Architectural Pattern: Modular Django Monolith

CoreCraftr follows a clean, layered Django monolith architecture without microservices, separate SPA frameworks, or generic chatbots. Domain business logic lives inside dedicated `services/` modules so Django views, DRF API endpoints, templates, and tests share identical rules and behavior.

The outer Django configuration package is named `corecraftr` (renamed safely from the original typo package `ecomnmerce` with zero migration impact), while the modular domain apps remain `store`, `pc_builder`, and `ai_engine`.

```
CoreCraftr/
├── corecraftr/                  # Django project settings, root URL routing, Admin branding, WSGI/ASGI
├── store/                       # Core e-commerce domain (catalogue, cart, checkout, accounts, wishlist, compare)
│   ├── models.py                # Category, Brand, Product, Inventory, HardwareSpecProfile, Cart, Order...
│   ├── signals.py               # Automatic Customer profile creation on User creation
│   ├── context_processors.py    # Global navbar categories, cart item count, builder part count
│   ├── templatetags/            # Indian numbering currency formatting (|inr, |inr_whole)
│   ├── services/
│   │   ├── catalog_service.py   # Homepage sections, multi-facet filtering, sorting, category key highlights
│   │   ├── cart_service.py      # Session & user cart management, atomic stock checks, login merge
│   │   ├── cart_compatibility.py# Cart hardware compatibility bridge reusing CompatibilityEngine
│   │   ├── order_service.py     # Transactional checkout, server-side pricing, order compatibility audit
│   │   └── comparison_service.py# Side-by-side matrix construction & diff highlighting
│   └── management/commands/
│       └── seed_hardware_catalog.py # Idempotent hardware catalog + Chipset-CPU matrix seeder
├── pc_builder/                  # Dual-mode PC Builder + Compatibility Engine
│   ├── models.py                # ChipsetCPUSupport, MotherboardCPUSupport, PCBuild, BuildComponent
│   ├── services/
│   │   ├── compatibility.py     # Deterministic 4-state rule engine (compatible/incompatible/warning/unknown)
│   │   ├── alternatives.py      # Compatible cheaper / similar / higher / better-value suggestions
│   │   └── builder_service.py   # Mode switching, slot filtering, saved snapshots, build-to-cart
│   ├── views.py                 # HTML workspace, beginner recommend, slot picker, saved builds
│   └── api_views.py             # DRF JSON endpoints (/builder/api/...)
├── ai_engine/                   # Catalog-grounded AI orchestration + deterministic fallback
│   └── services/
│       └── recommender.py       # AIProviderClient, DeterministicBuildRecommender, CartCompatibilityAdvisor
├── templates/                   # Shared base template (base.html) and custom error pages (404.html, 500.html)
├── static/                      # CSS, JS, CoreCraftr SVG mark, category SVGs, product assets
└── media/                       # Uploaded product images (runtime/user media)
```

---

## 2. Database Design & Legacy Migration Strategy

### Preserving Existing Data
The repository retains full `store` schema continuity (`0001`–`0007`) and `pc_builder` migrations (`0001`):
- `store/migrations/0005_brand_category_hardwarespecprofile_inventory_and_more.py` uses `RenameField` (`Product.category` -> `Product.legacy_category`) before adding structured `Category` and `Brand` foreign keys, `Inventory`, `HardwareSpecProfile`, `ProductSpecification`, `WishlistItem`, `Cart`, and `CartItem`.
- `store/migrations/0006_migrate_legacy_data.py` safely backfills legacy products into structured categories (`CPU / Processors`, `General Hardware`), initializes `Inventory` records, marks legacy uncompleted `Order` rows cleanly, and ensures every existing `User` has a linked `Customer` profile.
- `store/migrations/0007_order_compatibility_status_and_more.py` adds `compatibility_status`, `compatibility_summary`, `incompatibility_acknowledged`, and `incompatibility_acknowledged_at` to `Order`.
- `seed_hardware_catalog` enriches legacy Ryzen 1st-gen CPUs (`AMD ryzen 5 1400`, `1600x`, `1700`, `1700x`, `2200G`, `2400G`) with verified AM4/Zen 1 specs idempotently.

### Key Entity Relationships
- `User` 1<->1 `Customer` (`store.signals.ensure_customer_profile`)
- `Category` 1->N `Product` <-N `Brand`
- `Product` 1<->1 `Inventory`, `Product` 1<->1 `HardwareSpecProfile`, `Product` 1->N `ProductSpecification`
- `Cart` (tied to `User` or guest `session_key`) 1->N `CartItem` -> `Product` (+ optional nullable FK `source_build` to `PCBuild`)
- `Customer` 1->N `Order` 1->N `OrderItem` (with price/name snapshots and compatibility acknowledgement audit) + `ShippingAddress`
- `PCBuild` (`is_active_workspace` or `is_saved` snapshot, shared by both `beginner` and `expert` modes) 1->N `BuildComponent` (`slot`, `product`, `quantity`, `selection_reason`, `tradeoffs`, `added_via_mode`)
- `ChipsetCPUSupport` `(socket, chipset, cpu_family)` and `MotherboardCPUSupport` `(motherboard, cpu)` QVL rules.

---

## 3. Unified Dual-Mode PC Builder & Non-Blocking Cart Validation

Both Beginner Mode and Expert Mode operate against the **exact same `PCBuild` record** (`is_active_workspace=True`), while `CartCompatibilityService` reuses the exact same [`CompatibilityEngine`](pc_builder/services/compatibility.py) for shopping carts:
- Switching builder modes updates only `PCBuild.mode` (and `Customer.preferred_builder_mode`) without altering or deleting components.
- Cart compatibility checks separate core internal PC parts from peripherals (`monitor`, `keyboard`, `mouse`), surface ambiguity notes when multiple SKUs share single slots, offer verified Option A / Option B replacements without disabling checkout, recalculate fresh at checkout, and persist explicit customer acknowledgement on `Order`.

---

## 4. Deterministic Compatibility Engine (`CompatibilityEngine`)

Compatibility is never inferred from missing data and never delegated to an LLM. Check groups include:
1. **CPU <-> Motherboard**: Socket match -> `MotherboardCPUSupport` QVL override -> `ChipsetCPUSupport` matrix -> `supported_cpu_families` + `min_bios_note`.
2. **Motherboard <-> RAM**: DDR generation, DIMM module count, max RAM capacity.
3. **CPU <-> RAM**: Supported DDR types, max capacity, JEDEC vs XMP/EXPO speed warning.
4. **GPU <-> Case**: GPU length vs `max_gpu_length_mm`.
5. **CPU Cooler <-> Case & CPU**: Stock cooler check, socket support list, air cooler height, radiator mounts, thermal TDP rating.
6. **Motherboard <-> Case**: Form factor fit.
7. **Storage <-> Motherboard & Case**: M.2 NVMe/SATA slot limits, SATA ports, `slot_sharing_notes`, drive bays.
8. **Power Estimation & PSU**: Estimated system peak wattage + headroom + native vs adapter 12VHPWR / 8-pin PCIe + PSU length.
9. **Display Output & Channel Advisories**: iGPU-less CPU without dedicated GPU, single-stick RAM warning.

---

## 5. Catalog-Grounded AI Orchestration & Validation Gate

Both PC Builder recommendations (`BuildRecommendationOrchestrator`) and Cart conflict advice (`CartCompatibilityAdvisor`) enforce strict database and deterministic validation gates: every AI-proposed `product_id` must exist, be active and in stock, match the requested category slot, preserve locked user picks, and pass `CompatibilityEngine`. Any unconfigured key, timeout, hallucinated ID, or incompatible AI combination triggers automatic fallback to deterministic logic with a clear UI notice.

---

## 6. Security & Session Integrity Controls

- **Zero Hardcoded Secrets**: All keys, DB credentials, debug flags, allowed hosts, SMTP settings, and AI keys are loaded from environment variables via `.env`.
- **Database Tracking Removed Going Forward**: `db.sqlite3` and `*.sqlite3` are ignored by `.gitignore` and removed from Git tracking on `feature/corecraftr-branding` so local test/demo data is not committed.
- **Pre-Login Session Capture**: Captures guest `session_key` before `login()` session rotation so guest carts and guest PC builds merge cleanly.
- **Server-Side Checkout Authority**: All prices, shipping calculation, atomic stock locks (`select_for_update`), fresh compatibility checks, and totals execute strictly server-side.
- **Hardened HTTP & Cookie Defaults**: `SESSION_COOKIE_HTTPONLY = True`, `SameSite = 'Lax'`, `X_FRAME_OPTIONS = 'DENY'`, `SECURE_CONTENT_TYPE_NOSNIFF = True`, and strict HTTPS/HSTS flags when `DJANGO_DEBUG=False`.
