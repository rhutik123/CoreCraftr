from decimal import Decimal
from store.models import Product
from pc_builder.services.compatibility import (
    CompatibilityEngine,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_PRIORITY,
    STATUS_UNKNOWN,
)


def slot_to_category_slot(slot: str) -> str:
    if slot == 'storage_secondary':
        return 'storage'
    return slot


def _product_score(product: Product) -> int:
    profile = product.spec_profile_safe
    if profile and profile.benchmark_score:
        return profile.benchmark_score
    return 40


def _describe_tradeoff(current: Product, alt: Product, kind: str) -> str:
    diff = alt.price - current.price
    cur_score = _product_score(current)
    alt_score = _product_score(alt)
    score_diff = alt_score - cur_score

    if diff < Decimal('0.00'):
        price_phrase = f'Saves Rs. {abs(diff):,.0f}'
    elif diff > Decimal('0.00'):
        price_phrase = f'Costs Rs. {diff:,.0f} more'
    else:
        price_phrase = 'Same price'

    cur_spec = current.spec_profile_safe
    alt_spec = alt.spec_profile_safe
    spec_notes = []
    if cur_spec and alt_spec:
        if cur_spec.cores and alt_spec.cores and cur_spec.cores != alt_spec.cores:
            spec_notes.append(f'{alt_spec.cores} cores vs {cur_spec.cores} cores')
        if cur_spec.vram_gb and alt_spec.vram_gb and cur_spec.vram_gb != alt_spec.vram_gb:
            spec_notes.append(f'{alt_spec.vram_gb}GB VRAM vs {cur_spec.vram_gb}GB')
        if cur_spec.ram_capacity_gb and alt_spec.ram_capacity_gb and cur_spec.ram_capacity_gb != alt_spec.ram_capacity_gb:
            spec_notes.append(f'{alt_spec.ram_capacity_gb}GB vs {cur_spec.ram_capacity_gb}GB RAM')
        if cur_spec.capacity_gb and alt_spec.capacity_gb and cur_spec.capacity_gb != alt_spec.capacity_gb:
            spec_notes.append(f'{alt_spec.capacity_gb}GB vs {cur_spec.capacity_gb}GB')
        if cur_spec.wattage and alt_spec.wattage and cur_spec.wattage != alt_spec.wattage:
            spec_notes.append(f'{alt_spec.wattage}W vs {cur_spec.wattage}W')

    if kind == 'cheaper':
        perf_note = 'slightly lower performance tier' if score_diff < -5 else 'comparable capability'
        extra = f' ({"; ".join(spec_notes)})' if spec_notes else ''
        return f'{price_phrase} with {perf_note}{extra}.'
    if kind == 'similar':
        extra = f' ({"; ".join(spec_notes)})' if spec_notes else ''
        return f'{price_phrase}; comparable performance tier{extra}.'
    if kind == 'higher':
        extra = f' ({"; ".join(spec_notes)})' if spec_notes else ''
        return f'{price_phrase} for a meaningful step up in capability{extra}.'
    if kind == 'value':
        extra = f' ({"; ".join(spec_notes)})' if spec_notes else ''
        return f'{price_phrase}; strong performance-per-rupee in this slot{extra}.'
    return price_phrase


class SmartAlternativesService:
    """Finds compatible catalog alternatives and incompatibility fixes for any build slot."""

    def __init__(self, compatibility_engine: CompatibilityEngine | None = None):
        self.engine = compatibility_engine or CompatibilityEngine()

    def get_slot_alternatives(self, slot_items: dict, target_slot: str, current_product: Product) -> dict:
        """
        Return categorized real-catalog alternatives for `current_product` in `target_slot`:
        cheaper, similar, higher, better_value.
        """
        cat_slot = slot_to_category_slot(target_slot)
        candidates = (
            Product.objects.filter(
                is_active=True,
                category__component_slot=cat_slot,
                inventory__quantity__gt=0,
            )
            .exclude(pk=current_product.pk)
            .select_related('category', 'brand', 'inventory', 'spec_profile')
        )

        cur_score = _product_score(current_product)
        cur_price = current_product.price

        evaluated = []
        for cand in candidates:
            test_map = dict(slot_items)
            test_map[target_slot] = (cand, 1)
            report = self.engine.evaluate_products(test_map)
            if not report.is_build_valid_compatible:
                continue
            cand_score = _product_score(cand)
            value_ratio = cand_score / max(float(cand.price), 1.0)
            evaluated.append({
                'product': cand,
                'score': cand_score,
                'price': cand.price,
                'value_ratio': value_ratio,
                'compat_status': report.overall_status,
                'compat_priority': STATUS_PRIORITY[report.overall_status],
            })

        # Prefer fully verified compatible over warning/unknown
        evaluated.sort(key=lambda x: (x['compat_priority'], x['price']))
        used_ids = set()
        result = {}

        # 1. Cheaper alternative
        cheaper_pool = [e for e in evaluated if e['price'] < cur_price]
        cheaper_pool.sort(key=lambda x: (x['compat_priority'], -x['score'], x['price']))
        if cheaper_pool:
            pick = cheaper_pool[0]
            used_ids.add(pick['product'].id)
            result['cheaper'] = self._format_alt(pick, current_product, 'cheaper', 'Cheaper Alternative')

        # 2. Similar-performance alternative
        similar_pool = [
            e for e in evaluated
            if e['product'].id not in used_ids and abs(e['score'] - cur_score) <= 12
        ]
        similar_pool.sort(key=lambda x: (x['compat_priority'], abs(x['score'] - cur_score), x['price']))
        if similar_pool:
            pick = similar_pool[0]
            used_ids.add(pick['product'].id)
            result['similar'] = self._format_alt(pick, current_product, 'similar', 'Similar Performance')

        # 3. Higher-performance alternative
        higher_pool = [
            e for e in evaluated
            if e['product'].id not in used_ids and (e['score'] > cur_score or e['price'] > cur_price)
        ]
        higher_pool.sort(key=lambda x: (x['compat_priority'], -x['score'], x['price']))
        if higher_pool:
            pick = higher_pool[0]
            used_ids.add(pick['product'].id)
            result['higher'] = self._format_alt(pick, current_product, 'higher', 'Performance Upgrade')

        # 4. Better-value alternative
        value_pool = [e for e in evaluated if e['product'].id not in used_ids]
        value_pool.sort(key=lambda x: (x['compat_priority'], -x['value_ratio'], x['price']))
        if value_pool:
            pick = value_pool[0]
            result['better_value'] = self._format_alt(pick, current_product, 'value', 'Best Value Option')

        return result

    def get_compatible_replacements(self, slot_items: dict, target_slot: str, limit: int = 4) -> list[dict]:
        """Return compatible in-stock replacements when a slot causes a conflict."""
        cat_slot = slot_to_category_slot(target_slot)
        current = slot_items.get(target_slot)
        current_id = current[0].id if isinstance(current, tuple) else (current.id if current else None)

        candidates = (
            Product.objects.filter(
                is_active=True,
                category__component_slot=cat_slot,
                inventory__quantity__gt=0,
            )
            .exclude(pk=current_id)
            .select_related('category', 'brand', 'inventory', 'spec_profile')
        )

        fixes = []
        for cand in candidates:
            if not cand.spec_verified or cand.spec_profile_safe is None:
                continue
            test_map = dict(slot_items)
            test_map[target_slot] = (cand, 1)
            report = self.engine.evaluate_products(test_map)
            if not report.is_build_valid_compatible:
                continue
            # Do not recommend a replacement whose compatibility with existing parts is still unknown
            has_slot_unknown = any(
                chk.status == STATUS_UNKNOWN and target_slot in chk.affected_slots
                for chk in report.checks
            )
            if has_slot_unknown:
                continue
            fixes.append({
                'product': cand,
                'status': report.overall_status,
                'priority': STATUS_PRIORITY[report.overall_status],
                'score': _product_score(cand),
                'report': report,
            })

        fixes.sort(key=lambda x: (x['priority'], -x['score'], x['product'].price))
        return fixes[:limit]

    @staticmethod
    def _format_alt(entry: dict, current_product: Product, kind: str, label: str) -> dict:
        prod = entry['product']
        return {
            'kind': kind,
            'label': label,
            'product': prod,
            'price_diff': prod.price - current_product.price,
            'compat_status': entry['compat_status'],
            'tradeoff': _describe_tradeoff(current_product, prod, kind),
        }
