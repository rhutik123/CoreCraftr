from store.models import Product


def build_comparison_matrix(products: list[Product]) -> dict:
    """
    Build a structured side-by-side comparison matrix for products of the same category,
    highlighting differing rows.
    """
    if not products:
        return {'products': [], 'rows': [], 'same_category': True}

    category_ids = {p.category_id for p in products}
    same_category = len(category_ids) <= 1

    # Gather all spec keys across selected products preserving order
    spec_keys_ordered = []
    seen_keys = set()
    product_spec_maps = {}

    for p in products:
        smap = {}
        for spec in p.specifications.all():
            label = spec.spec_key
            smap[label] = spec.formatted_value
            if label not in seen_keys:
                seen_keys.add(label)
                spec_keys_ordered.append((spec.spec_group, label))
        product_spec_maps[p.id] = smap

    rows = []

    # Core summary rows first
    core_rows = [
        ('Overview', 'Brand', [p.brand.name if p.brand else '—' for p in products]),
        ('Overview', 'Price', [f'Rs. {p.price:,.2f}' for p in products]),
        ('Overview', 'Availability', [p.inventory.stock_status_label if hasattr(p, 'inventory') else 'Check Stock' for p in products]),
        ('Overview', 'Warranty', [f'{p.warranty_months} months' for p in products]),
        ('Overview', 'Spec Verified', ['Verified' if p.spec_verified else 'Incomplete / Unverified' for p in products]),
    ]
    for group, label, vals in core_rows:
        rows.append({
            'group': group,
            'label': label,
            'values': vals,
            'differs': len(set(vals)) > 1,
        })

    for group, key in spec_keys_ordered:
        vals = [product_spec_maps[p.id].get(key, 'Unknown / Not Listed') for p in products]
        rows.append({
            'group': group,
            'label': key,
            'values': vals,
            'differs': len(set(vals)) > 1,
        })

    return {
        'products': products,
        'rows': rows,
        'same_category': same_category,
    }
