# Setup & Developer Operations Guide

## 1. Prerequisites
- Python 3.11+ (verified in this workspace on Python 3.15 with Django 5.2)
- PostgreSQL 14+ (optional for quick local SQLite demo fallback; recommended for full production/staging parity)
- Git

---

## 2. Repository & Environment Setup

### Step 1: Enter the Project Directory and Checkout Branch
```powershell
git clone https://github.com/rhutik123/Ecommerce-website.git
cd Ecommerce-website
git checkout feature/pc-builder-upgrade
```

### Step 2: Create and Activate Virtual Environment
Windows PowerShell:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Linux / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Create `.env` Configuration
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```

Edit `.env`:
```dotenv
DJANGO_SECRET_KEY=<generate-a-long-random-50+-char-string>
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000

# Option A: PostgreSQL (Primary Production Target)
DB_ENGINE=postgresql
DB_NAME=hardwarehub_db
DB_USER=postgres
DB_PASSWORD=<your-postgres-password>
DB_HOST=127.0.0.1
DB_PORT=5432

# Option B: SQLite Local Fallback (if PostgreSQL is not configured yet)
# Leave DB_PASSWORD unset or set DB_ENGINE=sqlite
```

> **Note on Automatic Fallback:** When `DB_PASSWORD` is left blank or set to a `replace-with-*` placeholder in development (`DJANGO_ALLOW_SQLITE_FALLBACK=True`), `ecomnmerce/settings.py` automatically falls back to `db.sqlite3` (`DATABASE_MODE='sqlite_fallback'`) so developers and CI/test runners can execute immediately. Set `DJANGO_ALLOW_SQLITE_FALLBACK=False` in production to enforce PostgreSQL strictly.

---

## 3. PostgreSQL Database Creation (When Using PostgreSQL)

Create the database and user using `psql`:
```sql
CREATE DATABASE hardwarehub_db;
-- Optionally create a dedicated role:
-- CREATE USER hardwarehub_user WITH PASSWORD 'your-strong-password';
-- GRANT ALL PRIVILEGES ON DATABASE hardwarehub_db TO hardwarehub_user;
```
Update `DB_NAME`, `DB_USER`, and `DB_PASSWORD` in `.env`, then run migrations and seed data.

---

## 4. Database Migrations & Curated Catalog Seeding

Run migrations and populate the hardware catalogue (13 categories, verified specs across CPUs, GPUs, Motherboards, RAM, Storage, PSUs, Cases, Coolers, Case Fans, Monitors, Keyboards, Mice, Accessories, plus `ChipsetCPUSupport` platform rules):

```powershell
python manage.py migrate
python manage.py seed_hardware_catalog
```

`seed_hardware_catalog` is **idempotent** — running it multiple times safely updates/upserts curated SKUs (`is_demo_data=True`), enriches legacy AM4 processors without deleting existing database rows, and refreshes `ChipsetCPUSupport` entries.

Create an admin superuser for Django Admin access (`/admin/`):
```powershell
python manage.py createsuperuser
```

---

## 5. Optional AI Provider Configuration

The PC Builder works out of the box with `AI_PROVIDER=none` using the deterministic `DeterministicBuildRecommender`.

To enable AI-assisted ranking and natural-language explanations (still strictly grounded to real DB products and checked by `CompatibilityEngine`):

For OpenAI:
```dotenv
AI_PROVIDER=openai
AI_API_KEY=sk-...
AI_MODEL=gpt-4o-mini
AI_TIMEOUT_SECONDS=15
```

For Google Gemini:
```dotenv
AI_PROVIDER=gemini
AI_API_KEY=AIza...
AI_MODEL=gemini-2.0-flash
AI_TIMEOUT_SECONDS=15
```

If an API key is missing, expired, rate-limited, unreachable, or suggests invalid/incompatible components, the system automatically falls back to `DeterministicBuildRecommender` and displays an explicit status notice.

---

## 6. Collecting Static Files & Running the Server

```powershell
python manage.py collectstatic --noinput
python manage.py runserver
```

Key application URLs:
- Storefront Homepage: `http://127.0.0.1:8000/`
- Hardware Catalogue: `http://127.0.0.1:8000/store/`
- Product Comparison: `http://127.0.0.1:8000/compare/`
- Intelligent PC Builder (Beginner & Expert Modes): `http://127.0.0.1:8000/builder/`
- PC Builder JSON APIs: `http://127.0.0.1:8000/builder/api/build/`
- Django Admin: `http://127.0.0.1:8000/admin/`

---

## 7. Running Tests & Verification Checks

```powershell
# Run full pytest suite (store, compatibility engine, builder workflows, AI grounding)
pytest

# Django system checks & migration consistency checks
python manage.py check
python manage.py makemigrations --check --dry-run
```

---

## 8. Security Remediation Checklist for Original Repository Owners

During the initial audit of the upstream repository history (`master` commits `fed3650` and `d44f34f`), plaintext credentials were found in historical versions of `ecomnmerce/settings.py`:
- A hardcoded Django `SECRET_KEY`
- Hardcoded Gmail SMTP credentials (`EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`)

While `feature/pc-builder-upgrade` removes all hardcoded secrets from source files and moves them to `.env`:
1. **Rotate/Revoke Exposed Credentials Immediately**: Revoke the Google App Password / account password and rotate Django's `SECRET_KEY` on any deployed environment.
2. **Optional Git History Purge**: Because those values remain visible in commits on `master`, consider rewriting Git history (`git filter-repo` or BFG Repo-Cleaner) before making the repository public or sharing Git history further, then coordinate a clean force-push with collaborators.
3. **Production Deployment Check**: Before deploying with `DJANGO_DEBUG=False`, configure real `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, HTTPS (`SECURE_SSL_REDIRECT`), SMTP credentials (or transactional email provider), and `DB_ENGINE=postgresql`.
