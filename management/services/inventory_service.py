from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from management.models import StockMovement
from management.services.audit_service import log_portal_action
from store.models import Category, Inventory, Product

ALLOWED_MANUAL_STOCK_REASONS = {
    StockMovement.REASON_RESTOCK,
    StockMovement.REASON_CUSTOMER_RETURN,
    StockMovement.REASON_DAMAGED,
    StockMovement.REASON_MANUAL_CORRECTION,
    StockMovement.REASON_SUPPLIER_ADJUSTMENT,
    StockMovement.REASON_OTHER,
}


def inventory_version_token(inventory: Inventory) -> str:
    """Stable microsecond concurrency token for optimistic stock update checking."""
    if not inventory or not inventory.updated_at:
        return ''
    return str(int(inventory.updated_at.timestamp() * 1_000_000))


@transaction.atomic
def adjust_stock(
    *,
    product_id: int,
    adjustment_mode: str,
    quantity_value: int,
    reason: str,
    notes: str = '',
    actor=None,
    request=None,
    expected_version_token: str | None = None,
) -> StockMovement | None:
    """
    Atomically update product inventory inside select_for_update(), enforce
    non-negative / >= reserved stock bounds, record StockMovement and AuditLog.
    """
    product = Product.objects.filter(pk=product_id).first()
    if not product:
        raise ValidationError('Product not found.')

    inv, _ = Inventory.objects.select_for_update().get_or_create(product=product)

    if expected_version_token is not None and str(expected_version_token).strip() != '':
        current_token = inventory_version_token(inv)
        if str(expected_version_token).strip() != current_token:
            raise ValidationError(
                f'Stock for {product.sku} was modified concurrently by another user. Refresh the page and retry.'
            )

    if reason not in ALLOWED_MANUAL_STOCK_REASONS:
        raise ValidationError('Select a valid stock adjustment reason.')

    try:
        qty_input = int(quantity_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError('Quantity value must be a whole integer.') from exc

    mode = (adjustment_mode or '').strip().lower()
    previous_qty = inv.quantity

    if mode == 'add':
        if qty_input < 0:
            raise ValidationError('Addition quantity cannot be negative.')
        new_qty = previous_qty + qty_input
    elif mode == 'subtract':
        if qty_input < 0:
            raise ValidationError('Deduction quantity cannot be negative.')
        new_qty = previous_qty - qty_input
    elif mode == 'set':
        new_qty = qty_input
    else:
        raise ValidationError('Invalid adjustment mode. Choose add, subtract, or set.')

    if new_qty < 0:
        raise ValidationError(
            f'Cannot adjust stock below 0 (current stock: {previous_qty}, attempted result: {new_qty}).'
        )
    if new_qty < inv.reserved_quantity:
        raise ValidationError(
            f'Cannot reduce physical stock ({new_qty}) below reserved units ({inv.reserved_quantity}).'
        )

    change_amount = new_qty - previous_qty
    inv.quantity = new_qty
    inv.save()

    movement = StockMovement.objects.create(
        product=product,
        previous_quantity=previous_qty,
        change_amount=change_amount,
        new_quantity=new_qty,
        reason=reason,
        notes=(notes or '').strip(),
        performed_by=actor if actor and getattr(actor, 'is_authenticated', False) else None,
    )

    log_portal_action(
        actor=actor,
        action='inventory.adjusted',
        target_type='product',
        target_id=product.id,
        target_label=f'{product.sku} - {product.name}',
        before_data={'quantity': previous_qty},
        after_data={'quantity': new_qty, 'change_amount': change_amount, 'reason': reason},
        summary=f'Stock adjusted for {product.sku}: {previous_qty} -> {new_qty} ({reason}).',
        request=request,
    )
    return movement


@transaction.atomic
def update_inventory_settings(
    *,
    product_id: int,
    low_stock_threshold: int,
    restock_date=None,
    actor=None,
    request=None,
) -> Inventory:
    """Update low-stock threshold and restock date for a product atomically."""
    product = Product.objects.filter(pk=product_id).first()
    if not product:
        raise ValidationError('Product not found.')

    inv, _ = Inventory.objects.select_for_update().get_or_create(product=product)
    try:
        threshold = int(low_stock_threshold)
    except (TypeError, ValueError) as exc:
        raise ValidationError('Low-stock threshold must be a whole integer.') from exc
    if threshold < 0:
        raise ValidationError('Low-stock threshold cannot be negative.')

    before = {
        'low_stock_threshold': inv.low_stock_threshold,
        'restock_date': str(inv.restock_date) if inv.restock_date else None,
    }
    inv.low_stock_threshold = threshold
    inv.restock_date = restock_date
    inv.save()

    after = {
        'low_stock_threshold': inv.low_stock_threshold,
        'restock_date': str(inv.restock_date) if inv.restock_date else None,
    }
    log_portal_action(
        actor=actor,
        action='inventory.settings_updated',
        target_type='product',
        target_id=product.id,
        target_label=f'{product.sku} - {product.name}',
        before_data=before,
        after_data=after,
        summary=f'Updated low-stock threshold ({threshold}) for {product.sku}.',
        request=request,
    )
    return inv


def get_verified_inventory_metrics() -> dict:
    """
    Compute live database metrics for dashboard & reports without fabricating values.
    Cost valuation is computed strictly over SKUs that have cost_price set.
    """
    products = list(
        Product.objects.select_related('inventory', 'category', 'brand').all()
    )

    active_skus = [p for p in products if p.status == Product.STATUS_PUBLISHED]
    draft_skus = [p for p in products if p.status == Product.STATUS_DRAFT]
    archived_skus = [p for p in products if p.status == Product.STATUS_ARCHIVED]

    low_stock_items = []
    out_of_stock_items = []
    in_stock_count = 0

    retail_value_total = Decimal('0.00')
    cost_valuation_total = Decimal('0.00')
    valued_sku_count = 0
    missing_cost_count = 0
    total_units_on_hand = 0

    for prod in products:
        inv = getattr(prod, 'inventory', None)
        avail = inv.available_quantity if inv else 0
        qty = inv.quantity if inv else 0
        threshold = inv.low_stock_threshold if inv else 3

        if prod.status != Product.STATUS_ARCHIVED:
            total_units_on_hand += qty
            retail_value_total += (prod.price or Decimal('0.00')) * qty

            if prod.cost_price is not None:
                valued_sku_count += 1
                cost_valuation_total += prod.cost_price * qty
            else:
                missing_cost_count += 1

        if prod.status == Product.STATUS_PUBLISHED:
            if avail <= 0:
                out_of_stock_items.append(prod)
            elif avail <= threshold:
                low_stock_items.append(prod)
            else:
                in_stock_count += 1

    active_categories_count = Category.objects.filter(is_active=True).count()

    non_archived_count = len(active_skus) + len(draft_skus)

    return {
        'total_skus': len(products),
        'published_count': len(active_skus),
        'draft_count': len(draft_skus),
        'archived_count': len(archived_skus),
        'active_categories_count': active_categories_count,
        'total_categories_count': Category.objects.count(),
        'in_stock_count': in_stock_count,
        'low_stock_count': len(low_stock_items),
        'out_of_stock_count': len(out_of_stock_items),
        'low_stock_items': low_stock_items,
        'out_of_stock_items': out_of_stock_items,
        'total_units_on_hand': total_units_on_hand,
        'retail_value_total': retail_value_total,
        'cost_valuation_total': cost_valuation_total,
        'valued_sku_count': valued_sku_count,
        'missing_cost_count': missing_cost_count,
        'non_archived_count': non_archived_count,
        'has_complete_cost_coverage': missing_cost_count == 0 and non_archived_count > 0,
    }
