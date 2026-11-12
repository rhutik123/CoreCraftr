import csv
import io
import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from management.models import CSVImportBatch, PriceChangeLog, StockMovement
from management.services.audit_service import log_portal_action
from management.spec_schemas import (
    CATEGORY_SPEC_FIELDS,
    coerce_spec_value,
    format_spec_for_input,
    has_complete_critical_specs,
)
from store.models import Brand, Category, HardwareSpecProfile, Inventory, Product

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 2000

CSV_SPEC_COLUMNS = [
    'socket',
    'chipset',
    'form_factor',
    'memory_type',
    'tdp_watts',
    'wattage',
    'vram_gb',
    'capacity_gb',
    'ram_capacity_gb',
    'ram_modules',
    'ram_speed_mhz',
    'memory_slots',
    'gpu_length_mm',
    'cooler_height_mm',
    'radiator_size_mm',
    'max_gpu_length_mm',
    'max_cooler_height_mm',
    'max_psu_length_mm',
    'psu_form_factor',
    'psu_length_mm',
    'storage_type',
    'storage_form_factor',
    'recommended_psu_watts',
    'supported_sockets',
    'supported_form_factors',
    'supported_memory_types',
    'supported_cpu_families',
    'supported_radiator_sizes_mm',
    'm2_nvme_slots',
    'm2_sata_slots',
    'sata_ports',
    'performance_tier',
    'benchmark_score',
]

EXPORT_COLUMNS = [
    'sku',
    'name',
    'category_slug',
    'brand_name',
    'model_number',
    'status',
    'price',
    'cost_price',
    'stock_quantity',
    'low_stock_threshold',
    'warranty_months',
    'short_description',
    'description',
] + CSV_SPEC_COLUMNS


def _all_spec_defs_by_name() -> dict:
    by_name = {}
    for fields in CATEGORY_SPEC_FIELDS.values():
        for fdef in fields:
            by_name.setdefault(fdef['name'], fdef)
    by_name['performance_tier'] = {
        'name': 'performance_tier', 'label': 'Performance Tier', 'type': 'str', 'unit': '',
    }
    by_name['benchmark_score'] = {
        'name': 'benchmark_score', 'label': 'Benchmark Score', 'type': 'int', 'unit': '',
    }
    return by_name


SPEC_DEFS_BY_NAME = _all_spec_defs_by_name()


def _safe_csv_cell(value: str) -> str:
    """Neutralize spreadsheet formula-injection prefixes on descriptive text fields."""
    if value and value[0] in ('=', '+', '@'):
        return "'" + value
    return value


def export_products_csv(queryset=None) -> str:
    """Serialize matching products and their specs into a UTF-8 BOM CSV string."""
    if queryset is None:
        queryset = Product.objects.select_related(
            'category', 'brand', 'inventory', 'spec_profile'
        ).order_by('category__display_order', 'sku')

    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)

    for prod in queryset:
        inv = getattr(prod, 'inventory', None)
        profile = getattr(prod, 'spec_profile', None)
        row = [
            prod.sku,
            _safe_csv_cell(prod.name),
            prod.category.slug if prod.category_id else '',
            _safe_csv_cell(prod.brand.name) if prod.brand_id else '',
            _safe_csv_cell(prod.model_number or ''),
            prod.status,
            str(prod.price),
            str(prod.cost_price) if prod.cost_price is not None else '',
            str(inv.quantity) if inv else '0',
            str(inv.low_stock_threshold) if inv else '3',
            str(prod.warranty_months),
            _safe_csv_cell(prod.short_description or ''),
            _safe_csv_cell(prod.description or ''),
        ]
        for col in CSV_SPEC_COLUMNS:
            val = getattr(profile, col, None) if profile else None
            fdef = SPEC_DEFS_BY_NAME.get(col, {'type': 'str', 'label': col})
            formatted = format_spec_for_input(fdef, val)
            if fdef['type'] in ('str', 'text'):
                formatted = _safe_csv_cell(formatted)
            row.append(formatted)
        writer.writerow(row)

    return buf.getvalue()


def create_csv_import_preview(uploaded_file, *, actor=None, request=None) -> CSVImportBatch:
    """
    Parse and validate an uploaded CSV file without writing catalog changes yet.
    Returns a persisted CSVImportBatch with row-by-row action, warnings, and errors.
    """
    if not uploaded_file:
        raise ValidationError('Select a CSV file to preview.')
    if getattr(uploaded_file, 'size', 0) > MAX_CSV_BYTES:
        raise ValidationError('CSV file exceeds the 5 MB limit.')

    raw = uploaded_file.read()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValidationError('CSV file must be UTF-8 encoded.') from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationError('CSV file has no header row.')

    headers = {h.strip().lower() for h in reader.fieldnames if h}
    missing_req = [col for col in ('sku', 'name', 'price') if col not in headers]
    if missing_req:
        raise ValidationError(f'Missing required CSV column(s): {", ".join(missing_req)}.')

    categories_by_slug = {c.slug.lower(): c for c in Category.objects.all()}
    categories_by_name = {c.name.lower(): c for c in Category.objects.all()}
    existing_by_sku = {
        p.sku.upper(): p
        for p in Product.objects.select_related('inventory', 'category', 'brand').all()
    }

    rows_preview = []
    seen_skus = {}
    valid_count = 0
    error_count = 0

    for idx, raw_row in enumerate(reader, start=2):
        if idx - 1 > MAX_CSV_ROWS:
            raise ValidationError(f'CSV file exceeds the maximum {MAX_CSV_ROWS} data rows per import.')

        norm = {(k.strip().lower() if k else ''): (v.strip() if v else '') for k, v in raw_row.items()}
        errors = []
        warnings = []

        sku = (norm.get('sku') or '').upper()
        name = norm.get('name') or ''

        if not sku:
            errors.append('SKU is required.')
        elif sku in seen_skus:
            errors.append(f'Duplicate SKU "{sku}" inside CSV (first seen at row {seen_skus[sku]}).')
        else:
            seen_skus[sku] = idx

        if not name:
            errors.append('Product name is required.')

        existing_prod = existing_by_sku.get(sku) if sku else None
        action = 'update' if existing_prod else 'create'

        cat_ref = (norm.get('category_slug') or norm.get('category') or '').lower()
        category = categories_by_slug.get(cat_ref) or categories_by_name.get(cat_ref)
        if not category:
            if existing_prod and not cat_ref:
                category = existing_prod.category
            else:
                errors.append(f'Unknown category "{norm.get("category_slug") or norm.get("category") or ""}".')

        price_val = None
        if not norm.get('price'):
            errors.append('Price is required.')
        else:
            try:
                price_val = Decimal(norm['price'])
                if price_val < Decimal('0.00'):
                    errors.append('Price cannot be negative.')
            except InvalidOperation:
                errors.append(f'Invalid decimal price "{norm["price"]}".')

        cost_val = None
        if norm.get('cost_price'):
            try:
                cost_val = Decimal(norm['cost_price'])
                if cost_val < Decimal('0.00'):
                    errors.append('Cost price cannot be negative.')
            except InvalidOperation:
                errors.append(f'Invalid decimal cost_price "{norm["cost_price"]}".')

        stock_qty = None
        if (norm.get('stock_quantity') or '') != '':
            try:
                stock_qty = int(norm['stock_quantity'])
                if stock_qty < 0:
                    errors.append('stock_quantity cannot be negative.')
                elif existing_prod and hasattr(existing_prod, 'inventory'):
                    reserved = existing_prod.inventory.reserved_quantity
                    if stock_qty < reserved:
                        errors.append(f'stock_quantity ({stock_qty}) cannot be below reserved units ({reserved}).')
            except ValueError:
                errors.append(f'Invalid integer stock_quantity "{norm["stock_quantity"]}".')

        threshold_val = None
        if (norm.get('low_stock_threshold') or '') != '':
            try:
                threshold_val = int(norm['low_stock_threshold'])
                if threshold_val < 0:
                    errors.append('low_stock_threshold cannot be negative.')
            except ValueError:
                errors.append(f'Invalid integer low_stock_threshold "{norm["low_stock_threshold"]}".')

        warranty_val = 12
        if (norm.get('warranty_months') or '') != '':
            try:
                warranty_val = int(norm['warranty_months'])
                if warranty_val < 0:
                    errors.append('warranty_months cannot be negative.')
            except ValueError:
                errors.append(f'Invalid integer warranty_months "{norm["warranty_months"]}".')

        status_val = (norm.get('status') or (existing_prod.status if existing_prod else Product.STATUS_DRAFT)).lower()
        if status_val not in {c[0] for c in Product.STATUS_CHOICES}:
            errors.append(f'Invalid status "{status_val}". Allowed: draft, published, archived.')

        specs_clean = {}
        for col in CSV_SPEC_COLUMNS:
            if col in norm and norm[col] != '':
                fdef = SPEC_DEFS_BY_NAME[col]
                coerced, err = coerce_spec_value(fdef, norm[col])
                if err:
                    errors.append(err)
                else:
                    specs_clean[col] = str(coerced) if fdef['type'] == 'decimal' and coerced is not None else coerced

        if existing_prod and action == 'update':
            warnings.append(f'Matches existing product #{existing_prod.id} ({existing_prod.name}) — will update.')

        if errors:
            error_count += 1
        else:
            valid_count += 1

        rows_preview.append({
            'row_number': idx,
            'sku': sku,
            'name': name,
            'action': action,
            'existing_product_id': existing_prod.id if existing_prod else None,
            'category_id': category.id if category else None,
            'category_name': category.name if category else '',
            'brand_name': norm.get('brand_name', ''),
            'model_number': norm.get('model_number', ''),
            'status': status_val,
            'price': str(price_val) if price_val is not None else '',
            'cost_price': str(cost_val) if cost_val is not None else None,
            'stock_quantity': stock_qty,
            'low_stock_threshold': threshold_val,
            'warranty_months': warranty_val,
            'short_description': norm.get('short_description', ''),
            'description': norm.get('description', ''),
            'specs': specs_clean,
            'errors': errors,
            'warnings': warnings,
        })

    batch = CSVImportBatch.objects.create(
        uploaded_by=actor if actor and getattr(actor, 'is_authenticated', False) else None,
        filename=(getattr(uploaded_file, 'name', 'catalog.csv') or 'catalog.csv')[:255],
        status=CSVImportBatch.STATUS_PREVIEW,
        total_rows=len(rows_preview),
        valid_rows=valid_count,
        error_rows=error_count,
        preview_payload={'rows': rows_preview},
    )

    log_portal_action(
        actor=actor,
        action='csv.import_previewed',
        target_type='csv_import_batch',
        target_id=batch.id,
        target_label=batch.filename,
        after_data={'total_rows': batch.total_rows, 'valid_rows': valid_count, 'error_rows': error_count},
        summary=f'Uploaded CSV "{batch.filename}" for preview ({valid_count} valid, {error_count} error rows).',
        request=request,
    )
    return batch


@transaction.atomic
def confirm_csv_import_batch(batch_id: int, *, actor=None, skip_error_rows: bool = False, request=None) -> CSVImportBatch:
    """Apply a previewed CSV import batch atomically and audit every created/updated SKU."""
    batch = CSVImportBatch.objects.select_for_update().filter(pk=batch_id).first()
    if not batch:
        raise ValidationError('CSV import batch not found.')
    if batch.status != CSVImportBatch.STATUS_PREVIEW:
        raise ValidationError('This CSV import batch has already been processed or cancelled.')

    rows = batch.preview_payload.get('rows', [])
    if batch.error_rows > 0 and not skip_error_rows:
        raise ValidationError(
            f'This batch has {batch.error_rows} row error(s). Fix the CSV or choose "Apply Valid Rows Only".'
        )

    actor_user = actor if actor and getattr(actor, 'is_authenticated', False) else None
    created_count = 0
    updated_count = 0
    skipped_count = 0

    for row in rows:
        if row.get('errors'):
            skipped_count += 1
            continue

        sku = row['sku']
        existing = Product.objects.select_for_update().filter(sku__iexact=sku).first()
        is_create = existing is None
        prod = existing or Product()

        prev_price = prod.price if not is_create else None
        prev_cost = prod.cost_price if not is_create else None

        brand = None
        if row.get('brand_name'):
            brand_name = row['brand_name'].strip()
            brand = Brand.objects.filter(name__iexact=brand_name).first()
            if not brand:
                brand, _ = Brand.objects.get_or_create(
                    slug=slugify(brand_name)[:140] or 'brand',
                    defaults={'name': brand_name[:120]},
                )

        prod.sku = sku
        prod.name = row['name']
        prod.category_id = row['category_id']
        if brand:
            prod.brand = brand
        prod.model_number = row.get('model_number', '')
        prod.status = row['status']
        prod.is_active = row['status'] == Product.STATUS_PUBLISHED
        prod.price = Decimal(row['price'])
        prod.cost_price = Decimal(row['cost_price']) if row.get('cost_price') is not None else None
        prod.warranty_months = int(row.get('warranty_months') or 12)
        if row.get('short_description'):
            prod.short_description = row['short_description']
        if row.get('description'):
            prod.description = row['description']
        if not prod.slug:
            base = slugify(prod.name)[:190] or 'hardware-product'
            cand = base
            n = 1
            while Product.objects.filter(slug=cand).exclude(pk=prod.pk).exists():
                cand = f'{base}-{n}'
                n += 1
            prod.slug = cand
        if is_create and actor_user:
            prod.created_by = actor_user
        if actor_user:
            prod.last_edited_by = actor_user
        prod.save()

        if is_create or prev_price != prod.price or prev_cost != prod.cost_price:
            PriceChangeLog.objects.create(
                product=prod,
                previous_price=prev_price,
                new_price=prod.price,
                previous_cost_price=prev_cost,
                new_cost_price=prod.cost_price,
                reason=f'CSV import batch #{batch.id}',
                changed_by=actor_user,
            )

        inv, _ = Inventory.objects.select_for_update().get_or_create(product=prod)
        prev_qty = inv.quantity
        if row.get('stock_quantity') is not None:
            new_qty = int(row['stock_quantity'])
            if new_qty < inv.reserved_quantity:
                raise ValidationError(
                    f'SKU {sku}: stock ({new_qty}) cannot be less than reserved units ({inv.reserved_quantity}).'
                )
            inv.quantity = new_qty
            if is_create or new_qty != prev_qty:
                StockMovement.objects.create(
                    product=prod,
                    previous_quantity=0 if is_create else prev_qty,
                    change_amount=new_qty - (0 if is_create else prev_qty),
                    new_quantity=new_qty,
                    reason=StockMovement.REASON_CSV_IMPORT,
                    notes=f'CSV import batch #{batch.id} ({batch.filename})',
                    performed_by=actor_user,
                )
        if row.get('low_stock_threshold') is not None:
            inv.low_stock_threshold = int(row['low_stock_threshold'])
        inv.save()

        if row.get('specs'):
            profile, _ = HardwareSpecProfile.objects.get_or_create(product=prod)
            for fname, val in row['specs'].items():
                if fname == 'performance_tier' and not val:
                    val = 'midrange'
                setattr(profile, fname, val)
            profile.save()
            verified_complete = has_complete_critical_specs(profile, prod.category)
            if verified_complete != prod.spec_verified:
                prod.spec_verified = verified_complete
                prod.save(update_fields=['spec_verified'])

        if is_create:
            created_count += 1
        else:
            updated_count += 1

    batch.status = CSVImportBatch.STATUS_APPLIED
    batch.applied_summary = {
        'created': created_count,
        'updated': updated_count,
        'skipped_errors': skipped_count,
    }
    batch.applied_at = timezone.now()
    batch.save(update_fields=['status', 'applied_summary', 'applied_at'])

    log_portal_action(
        actor=actor_user,
        action='csv.import_applied',
        target_type='csv_import_batch',
        target_id=batch.id,
        target_label=batch.filename,
        after_data=batch.applied_summary,
        summary=(
            f'Applied CSV batch #{batch.id} ({batch.filename}): '
            f'{created_count} created, {updated_count} updated, {skipped_count} skipped.'
        ),
        request=request,
    )
    return batch


@transaction.atomic
def cancel_csv_import_batch(batch_id: int, *, actor=None, request=None) -> CSVImportBatch:
    batch = CSVImportBatch.objects.select_for_update().filter(pk=batch_id).first()
    if not batch:
        raise ValidationError('CSV import batch not found.')
    if batch.status != CSVImportBatch.STATUS_PREVIEW:
        raise ValidationError('Only pending preview batches can be cancelled.')
    batch.status = CSVImportBatch.STATUS_CANCELLED
    batch.save(update_fields=['status'])

    log_portal_action(
        actor=actor,
        action='csv.import_cancelled',
        target_type='csv_import_batch',
        target_id=batch.id,
        target_label=batch.filename,
        summary=f'Cancelled CSV preview batch #{batch.id} ({batch.filename}).',
        request=request,
    )
    return batch
