# CoreCraftr — Setup & Developer Operations Guide

**Tagline:** *Build Smarter. Build Better.*  
**Repository:** `https://github.com/rhutik123/CoreCraftr`

## 1. Prerequisites
- Python 3.11+ (verified in this workspace on Python 3.15 with Django 5.2)
- PostgreSQL 14+ (optional for quick local SQLite fallback; recommended for production/staging parity)
- Git

---

## 2. Repository & Environment Setup

### Step 1: Clone the Repository and Select Branch
```powershell
git clone https://github.com/rhutik123/CoreCraftr.git
cd CoreCraftr
git checkout feature/corecraftr-branding
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
DB_NAME=corecraftr_db
DB_USER=postgres
DB_PASSWORD=<your-postgres-password>
DB_HOST=127.0.0.1
DB_PORT=5432

# Option B: SQLite Local Fallback (if PostgreSQL is not configured yet)
# Leave DB_PASSWORD unset or set DB_ENGINE=sqlite
```

> **Note on Automatic Fallback:** When `DB_PASSWORD` is left blank or set to a `replace-with-*` placeholder in development (`DJANGO_ALLOW_SQLITE_FALLBACK=True`), `corecraftr/settings.py` automatically falls back to a local `db.sqlite3` file (`DATABASE_MODE='sqlite_fallback'`) so developers and tests can run immediately. Set `DJANGO_ALLOW_SQLITE_FALLBACK=False` in production to enforce PostgreSQL strictly.

---

## 3. PostgreSQL Database Creation (When Using PostgreSQL)

Create the database and user using `psql`:
```sql
CREATE DATABASE corecraftr_db;
-- Optionally create a dedicated role:
-- CREATE USER corecraftr_user WITH PASSWORD 'your-strong-password';
-- GRANT ALL PRIVILEGES ON DATABASE corecraftr_db TO corecraftr_user;
```
Update `DB_NAME`, `DB_USER`, and `DB_PASSWORD` in `.env`, then run migrations and seed data.

---

## 4. Database Migrations & Curated Catalog Seeding

Run migrations and populate the hardware catalogue (13 categories, verified specs across CPUs, GPUs, Motherboards, RAM, Storage, PSUs, Cases, Coolers, Case Fans, Monitors, Keyboards, Mice, Accessories, plus `ChipsetCPUSupport` platform rules):

```powershell
python manage.py migrate
python manage.py seed_hardware_catalog
```

`seed_hardware_catalog` is **idempotent** — running it multiple times safely upserts curated SKUs (`is_demo_data=True`), enriches legacy AM4 processors without deleting existing database rows, and refreshes `ChipsetCPUSupport` entries.

Create an admin superuser for CoreCraftr Admin (`/admin/`):
```powershell
python manage.py createsuperuser
```

---

## 5. Optional AI Provider Configuration

CoreCraftr works out of the box with `AI_PROVIDER=none` using deterministic recommendation and compatibility logic.

To enable AI-assisted ranking and natural-language explanations (always strictly grounded to verified DB products and validated by `CompatibilityEngine`):

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
- CoreCraftr Django Admin: `http://127.0.0.1:8000/admin/`

---

## 7. Running Tests & Verification Checks

```powershell
# Run full pytest suite
pytest

# Django system checks & migration consistency checks
python manage.py check
python manage.py makemigrations --check --dry-run
```

---

## 8. Security Remediation Checklist (Historical Commits)

During the initial audit of the upstream repository history (`master` commits `d44f34f` and `fed3650`, and tracked `db.sqlite3` up through commit `767fb3f`), the following sensitive artifacts existed in historical Git snapshots:
- Historical `ecomnmerce/settings.py` contained a hardcoded Django `SECRET_KEY` and hardcoded Gmail SMTP credentials (`EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`).
- Historical commits also tracked `db.sqlite3`, which contains legacy user/customer/order rows.

While current source code removes all hardcoded secrets into `.env` and `feature/corecraftr-branding` ignores/untracks `*.sqlite3`:
1. **Rotate/Revoke Exposed Credentials Immediately**: Revoke the historical Gmail App Password / SMTP credentials and rotate any `SECRET_KEY` used in past deployments.
2. **Preserve vs Purge Git History**: Because `master` (`fed3650`) and `feature/pc-builder-upgrade` (`767fb3f`) already exist on the renamed `rhutik123/CoreCraftr` repository and non-force pushes cannot rewrite existing commits, keep this in mind if making the repository public—run `git filter-repo` (or create a fresh orphan baseline commit on a clean repo) *only* after rotating credentials and coordinating with collaborators.
3. **Production Deployment Check**: Before deploying with `DJANGO_DEBUG=False`, configure real `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, HTTPS (`SECURE_SSL_REDIRECT`), SMTP credentials (or transactional email provider), and `DB_ENGINE=postgresql`.
