# System Architecture — HardwareHub (Ecommerce-website Upgrade)

## 1. Architectural Pattern: Modular Django Monolith

The project follows a clean, layered Django monolith structure without microservices, Node/SPA build pipelines, or generic chatbots. Business logic is isolated in dedicated `services/` modules so Django views, DRF API endpoints, templates, and tests all share identical rules and behavior.

```
Ecommerce-website/
├── ecomnmerce/                  # Django project settings, root URL routing, WSGI/ASGI
├── store/                       # Core e-commerce domain (catalogue, cart, checkout, accounts, wishlist, compare)
│   ├── models.py                # Category, Brand, Product, Inventory, HardwareSpecProfile, Cart, Order...
│   ├── signals.py               # Automatic Customer profile creation on User creation
│   ├── context_processors.py    # Global navbar categories, cart item count, builder part count
│   ├── services/
│   │   ├── catalog_service.py   # Homepage sections, multi-facet filtering, sorting, grouped specs
│   │   ├── cart_service.py      # Session & user cart management, atomic stock checks, login merge
│   │   ├── order_service.py     # Transactional checkout, server-side pricing, inventory deduction
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
│       └── recommender.py       # AIProviderClient, DeterministicBuildRecommender, BuildRecommendationOrchestrator
├── templates/                   # Shared base template (base.html)
├── static/                      # CSS, JS, brand/product assets, category SVGs
└── media/                       # Uploaded product images (runtime/user media)
```

---

## 2. Database Design & Legacy Migration Strategy

### Preserving Existing Data
The original repository contained `store` migrations `0001`–`0004` with legacy `Customer`, `Product` (legacy AMD Ryzen 1st-gen processors), `Order`, `OrderItem`, and `ShippingAddress` rows.
- `store/migrations/0005_brand_category_hardwarespecprofile_inventory_and_more.py` uses `RenameField` (`Product.category` -> `Product.legacy_category`) before adding structured `Category` and `Brand` foreign keys, `Inventory`, `HardwareSpecProfile`, `ProductSpecification`, `WishlistItem`, `Cart`, and `CartItem`.
- `store/migrations/0006_migrate_legacy_data.py` safely backfills legacy products into structured categories (`CPU / Processors`, `General Hardware`), initializes `Inventory` records, marks legacy uncompleted `Order` rows cleanly, and ensures every existing `User` has a linked `Customer` profile.
- `seed_hardware_catalog` enriches the legacy Ryzen 1st-gen CPUs (`AMD ryzen 5 1400`, `1600x`, `1700`, `1700x`, `2200G`, `2400G`) with verified AM4/Zen 1 specs while preserving their rows and deactivating an exact duplicate legacy entry safely.

### Key Entity Relationships
- `User` 1<->1 `Customer` (`store.signals.ensure_customer_profile`)
- `Category` 1->N `Product` <-N `Brand`
- `Product` 1<->1 `Inventory`, `Product` 1<->1 `HardwareSpecProfile`, `Product` 1->N `ProductSpecification`
- `Cart` (tied to `User` or guest `session_key`) 1->N `CartItem` -> `Product` (+ optional nullable FK `source_build` to `PCBuild`)
- `Customer` 1->N `Order` 1->N `OrderItem` (with price & name snapshots at purchase time) + `ShippingAddress`
- `PCBuild` (`is_active_workspace` or `is_saved` snapshot, shared by both `beginner` and `expert` modes) 1->N `BuildComponent` (`slot`, `product`, `quantity`, `selection_reason`, `tradeoffs`, `added_via_mode`)
- `ChipsetCPUSupport` `(socket, chipset, cpu_family)` and `MotherboardCPUSupport` `(motherboard, cpu)` QVL rules.

---

## 3. Unified Dual-Mode PC Builder Architecture

Both Beginner Mode and Expert Mode operate against the **exact same `PCBuild` record** (`is_active_workspace=True`):
- Switching modes (`POST /builder/switch-mode/` or `GET /builder/?mode=beginner|expert`) updates only `PCBuild.mode` (and `Customer.preferred_builder_mode` for logged-in users). All `BuildComponent` rows remain untouched.
- When a Beginner switches to Expert Mode, they retain the recommended components and can inspect granular specs, filter compatible alternatives, or replace individual parts.
- When an Expert switches to Beginner Mode, `BuildRecommendationOrchestrator.explain_existing_build()` generates plain-English component roles, compatibility explanations, and upgrade/budget alternatives without overwriting their custom-selected parts.
- Changing any component never silently deletes conflicting components in other slots; instead, `CompatibilityEngine` flags the affected slots and `SmartAlternativesService.get_compatible_replacements()` offers one-click fixes.

---

## 4. Deterministic Compatibility Engine (`CompatibilityEngine`)

Compatibility is never inferred from missing data and never delegated to an LLM.
For a given build mapping `{slot: (Product, quantity)}`, `CompatibilityEngine.evaluate_products()` runs independent check groups:
1. **CPU <-> Motherboard**: Socket check -> `MotherboardCPUSupport` QVL override -> `ChipsetCPUSupport` matrix -> motherboard `supported_cpu_families` + `min_bios_note`. Missing fields emit `unknown`.
2. **Motherboard <-> RAM**: DDR generation check -> total DIMM module count vs `memory_slots` -> total GB vs `max_memory_gb`.
3. **CPU <-> RAM**: CPU `supported_memory_types` -> CPU `max_memory_gb` -> `ram_speed_mhz` vs CPU JEDEC `max_memory_speed_mhz` (emitting XMP/EXPO warning).
4. **GPU <-> Case**: `gpu_length_mm` vs `max_gpu_length_mm` (tight clearance warning when <= 10mm margin).
5. **CPU Cooler <-> Case & CPU**: Stock cooler check (`CPU_NEEDS_COOLER` if `includes_stock_cooler=False` and no cooler selected), cooler socket support list, air cooler height vs `max_cooler_height_mm`, liquid radiator size vs `supported_radiator_sizes_mm`, thermal capacity TDP check.
6. **Motherboard <-> Case**: Motherboard `form_factor` vs Case `supported_form_factors`.
7. **Storage <-> Motherboard & Case**: M.2 NVMe/SATA slot counts, M.2 SATA support, SATA ports, motherboard `slot_sharing_notes` warning (when multiple M.2 or M.2 + SATA drives are present), and 2.5"/3.5" case drive bays.
8. **Power Estimation & PSU**: Computes system draw (base overhead + CPU peak/TDP + GPU TDP + RAM + storage + fans), applies 25% headroom + GPU manufacturer PSU recommendation, verifies PSU wattage, native vs adapter 12VHPWR / 8-pin PCIe connectors, and PSU length clearance.
9. **Display Output & Channel Advisories**: Warns when a CPU lacks integrated graphics (`integrated_graphics=False`) and no dedicated GPU is selected, or when single-stick RAM is chosen.

---

## 5. Catalog-Grounded AI Orchestration & Validation Gate

```
User Requirements (+ Optional Locked Existing Parts)
        │
        ▼
[AIProviderClient configured?]
   ├── No / Error ──────────────────────────────────────────┐
   └── Yes -> Request JSON product IDs from real catalog    │
                 │                                          │
                 ▼                                          │
   [_validate_and_ground_ai_output]                         │
     - Verify every product_id exists in DB                 │
     - Verify is_active=True & inventory.quantity > 0       │
     - Verify category matches requested slot               │
     - Preserve locked user components                      │
     - Run CompatibilityEngine (must have 0 errors)         │
                 │                                          │
         ┌───────┴────────┐                                 │
       Valid         Invalid / Incompatible                 │
         │                └────────────► [DeterministicBuildRecommender]
         ▼                                                  │
   Ground names/prices/specs directly from Django ORM ◄─────┘
         │
         ▼
   Return RecommendationOutcome (with explicit source label & user notice)
```

---

## 6. Security & Session Integrity Controls

- **Zero Hardcoded Secrets**: All keys, DB passwords, debug flags, allowed hosts, SMTP credentials, and AI keys are loaded from environment variables via `.env`.
- **Pre-Login Session Capture**: Before `django.contrib.auth.login()` rotates the session key via `cycle_key()`, `loginPage` captures the pre-login guest `session_key` so guest shopping cart items and guest PC builds merge reliably into the user's account.
- **Server-Side Checkout Authority**: All prices, shipping calculation, stock locks (`select_for_update`), and order totals are computed exclusively on the server; client-supplied totals are ignored.
- **Object Ownership Enforcement**: Saved build load/delete endpoints filter strictly by `user=request.user`; order confirmation verifies order customer ownership or checkout session membership; wishlist, profile, and order history require authentication (`@login_required`); state-changing endpoints require `@require_POST` + CSRF validation.
- **Hardened HTTP & Cookie Defaults**: `SESSION_COOKIE_HTTPONLY = True`, `SameSite = 'Lax'`, `X_FRAME_OPTIONS = 'DENY'`, `SECURE_CONTENT_TYPE_NOSNIFF = True`, and strict SSL/HSTS flags automatically enabled when `DJANGO_DEBUG=False`.
