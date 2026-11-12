from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from management.models import AIResearchDraft, PriceChangeLog, StockMovement
from management.services.audit_service import log_portal_action
from management.services.image_service import add_product_images
from management.spec_schemas import (
    SHARED_METADATA_FIELDS,
    coerce_spec_value,
    get_spec_fields_for_slot,
    has_complete_critical_specs,
)
from store.models import HardwareSpecProfile, Inventory, Product, ProductSpecification


def find_potential_duplicates(
    *,
    name: str = '',
    sku: str = '',
    model_number: str = '',
    brand=None,
    category=None,
    exclude_product_id: int | None = None,
) -> list[dict]:
    """
    Detect possible duplicate products by SKU, model number, or similar name + brand/category.
    Returns advisory warning entries; never auto-merges products.
    """
    qs = Product.objects.select_related('category', 'brand')
    if exclude_product_id:
        qs = qs.exclude(pk=exclude_product_id)

    matches = []
    seen_ids = set()

    clean_sku = (sku or '').strip()
    if clean_sku:
        for p in qs.filter(sku__iexact=clean_sku)[:5]:
            seen_ids.add(p.id)
            matches.append({
                'id': p.id,
                'name': p.name,
                'sku': p.sku,
                'model_number': p.model_number,
                'status': p.status,
                'reason': f'Exact SKU match ({p.sku})',
            })

    clean_model = (model_number or '').strip()
    if clean_model:
        for p in qs.filter(model_number__iexact=clean_model)[:5]:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                matches.append({
                    'id': p.id,
                    'name': p.name,
                    'sku': p.sku,
                    'model_number': p.model_number,
                    'status': p.status,
                    'reason': f'Matching model number ({p.model_number})',
                })

    clean_name = (name or '').strip()
    if len(clean_name) >= 4:
        name_q = Q(name__iexact=clean_name)
        if brand and category:
            tokens = [t for t in clean_name.split() if len(t) >= 3][:3]
            if tokens:
                token_q = Q(brand=brand, category=category)
                for tok in tokens:
                    token_q &= Q(name__icontains=tok)
                name_q |= token_q
        for p in qs.filter(name_q)[:5]:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                matches.append({
                    'id': p.id,
                    'name': p.name,
                    'sku': p.sku,
                    'model_number': p.model_number,
                    'status': p.status,
                    'reason': 'Similar product name / brand / category already exists',
                })

    return matches


def _generate_unique_slug(name: str, exclude_id: int | None = None) -> str:
    base = slugify(name or '')[:190] or 'hardware-product'
    candidate = base
    suffix = 1
    while Product.objects.filter(slug=candidate).exclude(pk=exclude_id).exists():
        candidate = f'{base}-{suffix}'
        suffix += 1
    return candidate


def _generate_unique_sku(name: str) -> str:
    base = slugify(name or '').upper().replace('-', '')[:8] or 'SKU'
    candidate = f'CC-{base}'
    suffix = 1
    while Product.objects.filter(sku__iexact=candidate).exists():
        candidate = f'CC-{base}-{suffix}'
        suffix += 1
    return candidate


@transaction.atomic
def create_or_update_product(
    *,
    product: Product | None = None,
    product_data: dict,
    spec_data: dict | None = None,
    custom_specs: list[dict] | None = None,
    initial_quantity: int | None = None,
    low_stock_threshold: int | None = None,
    restock_date=None,
    uploaded_files=None,
    price_change_reason: str = '',
    ai_draft_id: int | None = None,
    actor=None,
    request=None,
) -> Product:
    """
    Create or update a Product along with Inventory, HardwareSpecProfile,
    ProductSpecification custom entries, gallery images, PriceChangeLog, and AuditLog.
    """
    is_create = product is None
    before_snapshot = {}

    if not is_create:
        before_snapshot = {
            'name': product.name,
            'sku': product.sku,
            'model_number': product.model_number,
            'price': str(product.price),
            'cost_price': str(product.cost_price) if product.cost_price is not None else None,
            'status': product.status,
            'category_id': product.category_id,
            'brand_id': product.brand_id,
        }
        prev_price = product.price
        prev_cost_price = product.cost_price
    else:
        product = Product()
        prev_price = None
        prev_cost_price = None

    name = (product_data.get('name') or '').strip()
    if not name:
        raise ValidationError('Product name is required.')

    sku = (product_data.get('sku') or '').strip().upper()
    if not sku:
        sku = _generate_unique_sku(name)

    if Product.objects.filter(sku__iexact=sku).exclude(pk=product.pk).exists():
        raise ValidationError(f'SKU "{sku}" already exists on another product. SKUs must be unique.')

    category = product_data.get('category')
    if not category:
        raise ValidationError('Product category is required.')

    try:
        price = Decimal(str(product_data.get('price')))
    except Exception as exc:
        raise ValidationError('Price must be a valid decimal amount.') from exc
    if price < Decimal('0.00'):
        raise ValidationError('Price cannot be negative.')

    raw_cost = product_data.get('cost_price')
    cost_price = None
    if raw_cost not in (None, ''):
        try:
            cost_price = Decimal(str(raw_cost))
        except Exception as exc:
            raise ValidationError('Cost price must be a valid decimal amount.') from exc
        if cost_price < Decimal('0.00'):
            raise ValidationError('Cost price cannot be negative.')

    status_val = (product_data.get('status') or Product.STATUS_DRAFT).strip()
    valid_statuses = {choice[0] for choice in Product.STATUS_CHOICES}
    if status_val not in valid_statuses:
        raise ValidationError('Invalid product lifecycle status.')

    product.name = name
    product.sku = sku
    product.model_number = (product_data.get('model_number') or '').strip()
    product.category = category
    product.brand = product_data.get('brand')
    product.price = price
    product.cost_price = cost_price
    product.status = status_val
    product.is_active = status_val == Product.STATUS_PUBLISHED
    product.short_description = (product_data.get('short_description') or '').strip()
    product.description = (product_data.get('description') or '').strip()
    product.warranty_months = int(product_data.get('warranty_months') or 12)
    product.is_featured = bool(product_data.get('is_featured', False))
    product.digital = bool(product_data.get('digital', False))
    if not product.slug:
        product.slug = _generate_unique_slug(name, exclude_id=product.pk)

    actor_user = actor if actor and getattr(actor, 'is_authenticated', False) else None
    if is_create and actor_user and not product.created_by_id:
        product.created_by = actor_user
    if actor_user:
        product.last_edited_by = actor_user

    product.save()

    # Track price & cost history
    if is_create or prev_price != product.price or prev_cost_price != product.cost_price:
        PriceChangeLog.objects.create(
            product=product,
            previous_price=prev_price,
            new_price=product.price,
            previous_cost_price=prev_cost_price,
            new_cost_price=product.cost_price,
            reason=price_change_reason or ('Initial catalog entry' if is_create else 'Product price updated'),
            changed_by=actor_user,
        )

    # Ensure Inventory exists & handle initial stock on create
    inv, inv_created = Inventory.objects.select_for_update().get_or_create(product=product)
    if is_create and initial_quantity is not None:
        init_qty = max(0, int(initial_quantity))
        inv.quantity = init_qty
        if low_stock_threshold is not None:
            inv.low_stock_threshold = max(0, int(low_stock_threshold))
        inv.restock_date = restock_date
        inv.save()
        if init_qty > 0:
            StockMovement.objects.create(
                product=product,
                previous_quantity=0,
                change_amount=init_qty,
                new_quantity=init_qty,
                reason=StockMovement.REASON_INITIAL_STOCK,
                notes='Initial stock set during product creation',
                performed_by=actor_user,
            )
    elif inv_created or low_stock_threshold is not None or restock_date is not None:
        if low_stock_threshold is not None:
            inv.low_stock_threshold = max(0, int(low_stock_threshold))
        if restock_date is not None:
            inv.restock_date = restock_date
        inv.save()

    # Apply typed category hardware specifications
    profile, _ = HardwareSpecProfile.objects.get_or_create(product=product)
    if spec_data is not None:
        slot_fields = get_spec_fields_for_slot(category.component_slot)
        errors = []
        for fdef in slot_fields + SHARED_METADATA_FIELDS:
            fname = fdef['name']
            if fname in spec_data:
                coerced, err = coerce_spec_value(fdef, spec_data[fname])
                if err:
                    errors.append(err)
                else:
                    if fname == 'performance_tier' and not coerced:
                        coerced = 'midrange'
                    setattr(profile, fname, coerced)
        if errors:
            raise ValidationError(errors)
        profile.save()

    verified_complete = has_complete_critical_specs(profile, category)
    update_fields = []
    if (is_create or spec_data is not None) and product.spec_verified != verified_complete:
        product.spec_verified = verified_complete
        update_fields.append('spec_verified')
    elif not product.spec_verified and verified_complete:
        product.spec_verified = True
        update_fields.append('spec_verified')
    if update_fields:
        product.save(update_fields=update_fields)

    # Replace custom display specifications when provided
    if custom_specs is not None:
        ProductSpecification.objects.filter(product=product).delete()
        for idx, row in enumerate(custom_specs):
            key = (row.get('spec_key') or '').strip()
            val = (row.get('spec_value') or '').strip()
            if not key or not val:
                continue
            ProductSpecification.objects.create(
                product=product,
                spec_group=(row.get('spec_group') or 'Additional').strip()[:80],
                spec_key=key[:120],
                spec_value=val[:255],
                unit=(row.get('unit') or '').strip()[:30],
                is_highlight=bool(row.get('is_highlight', False)),
                is_verified=bool(row.get('is_verified', True)),
                display_order=idx,
            )

    if uploaded_files:
        add_product_images(product, uploaded_files, actor=actor_user, request=request)

    if ai_draft_id:
        draft = AIResearchDraft.objects.filter(pk=ai_draft_id).first()
        if draft and draft.status != AIResearchDraft.STATUS_APPROVED:
            draft.status = AIResearchDraft.STATUS_APPROVED
            draft.product = product
            draft.approved_by = actor_user
            draft.approved_at = timezone.now()
            draft.save(update_fields=['status', 'product', 'approved_by', 'approved_at'])
            if not product.spec_source and isinstance(draft.sources, list) and draft.sources:
                primary = draft.sources[0]
                src_url = primary.get('url', '') if isinstance(primary, dict) else ''
                if src_url:
                    product.spec_source = src_url[:255]
                    product.save(update_fields=['spec_source'])
            log_portal_action(
                actor=actor_user,
                action='ai.draft_approved',
                target_type='ai_research_draft',
                target_id=draft.id,
                target_label=f'{draft.product_name} -> {product.sku}',
                after_data={'product_id': product.id, 'sku': product.sku},
                summary=f'Approved AI research draft #{draft.id} onto product {product.sku}.',
                request=request,
            )

    after_snapshot = {
        'name': product.name,
        'sku': product.sku,
        'model_number': product.model_number,
        'price': str(product.price),
        'cost_price': str(product.cost_price) if product.cost_price is not None else None,
        'status': product.status,
        'category_id': product.category_id,
        'brand_id': product.brand_id,
    }
    log_portal_action(
        actor=actor_user,
        action='product.created' if is_create else 'product.updated',
        target_type='product',
        target_id=product.id,
        target_label=f'{product.sku} - {product.name}',
        before_data=before_snapshot,
        after_data=after_snapshot,
        summary=(
            f'Created product {product.sku} ({product.name}) as {product.status}.'
            if is_create
            else f'Updated product {product.sku} ({product.name}).'
        ),
        request=request,
    )
    return product


@transaction.atomic
def change_product_status(*, product_id: int, new_status: str, actor=None, request=None) -> Product:
    """Safely transition product visibility status (draft / published / archived)."""
    valid = {choice[0] for choice in Product.STATUS_CHOICES}
    if new_status not in valid:
        raise ValidationError('Invalid target status.')

    product = Product.objects.select_for_update().filter(pk=product_id).first()
    if not product:
        raise ValidationError('Product not found.')

    prev_status = product.status
    if prev_status == new_status:
        return product

    actor_user = actor if actor and getattr(actor, 'is_authenticated', False) else None
    product.status = new_status
    product.is_active = new_status == Product.STATUS_PUBLISHED
    if actor_user:
        product.last_edited_by = actor_user
    product.save()

    log_portal_action(
        actor=actor_user,
        action='product.status_changed',
        target_type='product',
        target_id=product.id,
        target_label=f'{product.sku} - {product.name}',
        before_data={'status': prev_status, 'is_active': prev_status == Product.STATUS_PUBLISHED},
        after_data={'status': product.status, 'is_active': product.is_active},
        summary=f'Changed status of {product.sku} from {prev_status} to {new_status}.',
        request=request,
    )
    return product
