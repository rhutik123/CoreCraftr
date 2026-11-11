"""
Shopping Cart Hardware Compatibility Service.

Reuses pc_builder.services.compatibility.CompatibilityEngine,
pc_builder.services.alternatives.SmartAlternativesService, and
ai_engine.services.recommender.CartCompatibilityAdvisor so cart/checkout
compatibility never duplicates rules or lets AI decide compatibility.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from store.models import Cart, Product
from store.templatetags.store_extras import format_inr
from pc_builder.services.alternatives import SmartAlternativesService
from pc_builder.services.compatibility import (
    CompatibilityEngine,
    CompatibilityIssue,
    CompatibilityReport,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_UNKNOWN,
    STATUS_WARNING,
)
from ai_engine.services.recommender import CartCompatibilityAdvisor

CORE_PC_SLOTS = {
    'cpu',
    'motherboard',
    'ram',
    'gpu',
    'storage',
    'psu',
    'case',
    'cooler',
    'case_fan',
}
PERIPHERAL_SLOTS = {'monitor', 'keyboard', 'mouse'}

SLOT_LABELS = {
    'cpu': 'CPU / Processor',
    'motherboard': 'Motherboard',
    'ram': 'Memory (RAM)',
    'gpu': 'Graphics Card (GPU)',
    'storage': 'Primary Storage',
    'storage_secondary': 'Secondary Storage',
    'psu': 'Power Supply (PSU)',
    'case': 'PC Case / Cabinet',
    'cooler': 'CPU Cooler',
    'case_fan': 'Case Fans',
    'monitor': 'Monitor',
    'keyboard': 'Keyboard',
    'mouse': 'Mouse',
}

OVERALL_STATUS_META = {
    STATUS_COMPATIBLE: {
        'headline': 'All verified components are compatible.',
        'badge_class': 'success',
        'alert_class': 'success',
        'icon': 'bi-check-circle-fill',
    },
    STATUS_INCOMPATIBLE: {
        'headline': 'Incompatible components detected.',
        'badge_class': 'danger',
        'alert_class': 'danger',
        'icon': 'bi-exclamation-octagon-fill',
    },
    STATUS_WARNING: {
        'headline': 'Compatibility warning.',
        'badge_class': 'warning',
        'alert_class': 'warning',
        'icon': 'bi-exclamation-triangle-fill',
    },
    STATUS_UNKNOWN: {
        'headline': 'Some specifications are unknown.',
        'badge_class': 'secondary',
        'alert_class': 'secondary',
        'icon': 'bi-question-circle-fill',
    },
}


@dataclass
class ComponentSpecSummary:
    slot: str
    slot_label: str
    product: Product
    spec_bullets: list[str] = field(default_factory=list)


@dataclass
class ReplacementSuggestion:
    product: Product
    price_inr: str
    price_diff_inr: str
    spec_summary: str
    compat_status: str
    reason: str = ''


@dataclass
class FixDirection:
    direction_key: str
    title: str
    action_type: str  # 'swap' or 'add'
    keep_slot: str
    keep_product: Product | None
    target_slot: str
    remove_product: Product | None
    tip: str = ''
    replacements: list[ReplacementSuggestion] = field(default_factory=list)


@dataclass
class DetailedCartIssue:
    rule_code: str
    status: str
    category: str
    heading: str
    title: str
    message: str
    beginner_explanation: str
    expert_explanation: str
    suggestion: str
    involved_components: list[ComponentSpecSummary] = field(default_factory=list)
    fix_directions: list[FixDirection] = field(default_factory=list)


@dataclass
class CartCompatibilityContext:
    is_applicable: bool
    status: str  # compatible | incompatible | warning | unknown | not_applicable
    headline: str
    badge_class: str
    alert_class: str
    icon: str
    has_incompatibility: bool
    has_warning: bool
    has_unknown: bool
    is_all_compatible: bool
    evaluated_components: list[ComponentSpecSummary] = field(default_factory=list)
    detailed_issues: list[DetailedCartIssue] = field(default_factory=list)
    ambiguity_notes: list[str] = field(default_factory=list)
    selection_scope_note: str = ''
    estimated_wattage: int = 0
    recommended_psu_wattage: int = 0
    advisor_source_label: str = ''
    advisor_notice: str = ''
    advisor_summary: str = ''
    is_ai_fallback: bool = True
    report: CompatibilityReport | None = None

    def to_order_snapshot(self) -> dict:
        if not self.is_applicable:
            return {'status': 'not_applicable', 'checked': False}
        return {
            'status': self.status,
            'headline': self.headline,
            'checked': True,
            'evaluated_components': [
                {'slot': c.slot, 'product_id': c.product.id, 'name': c.product.name}
                for c in self.evaluated_components
            ],
            'issues': [
                {
                    'rule_code': issue.rule_code,
                    'status': issue.status,
                    'title': issue.title,
                    'message': issue.message,
                }
                for issue in self.detailed_issues
                if issue.status != STATUS_COMPATIBLE
            ],
        }


def extract_component_bullets(product: Product, slot: str) -> list[str]:
    """Return concise verified specification bullets for a product without fabricating missing specs."""
    spec = product.spec_profile_safe
    if not spec:
        return ['Specifications: Unknown / Not verified']

    bullets = []
    if slot == 'cpu':
        if spec.socket:
            bullets.append(f'{spec.socket} socket')
        if spec.cpu_family:
            bullets.append(spec.cpu_family)
        if spec.cores and spec.threads:
            bullets.append(f'{spec.cores}C / {spec.threads}T')
        if spec.supported_memory_types:
            bullets.append(f'Supports {", ".join(spec.supported_memory_types)}')
        if spec.tdp_watts:
            bullets.append(f'{spec.tdp_watts}W TDP')
    elif slot == 'motherboard':
        if spec.socket:
            bullets.append(f'{spec.socket} socket')
        if spec.chipset:
            bullets.append(f'{spec.chipset} chipset')
        if spec.memory_type:
            cap = f' (max {spec.max_memory_gb}GB)' if spec.max_memory_gb else ''
            bullets.append(f'{spec.memory_type} memory{cap}')
        if spec.form_factor:
            bullets.append(f'{spec.form_factor} form factor')
        if spec.min_bios_note:
            bullets.append(spec.min_bios_note)
    elif slot == 'ram':
        if spec.memory_type:
            bullets.append(spec.memory_type)
        if spec.ram_capacity_gb:
            mods = f' ({spec.ram_modules}x stick)' if spec.ram_modules else ''
            bullets.append(f'{spec.ram_capacity_gb}GB{mods}')
        if spec.ram_speed_mhz:
            bullets.append(f'{spec.ram_speed_mhz} MT/s')
    elif slot == 'gpu':
        if spec.vram_gb:
            bullets.append(f'{spec.vram_gb}GB VRAM')
        if spec.gpu_length_mm:
            bullets.append(f'{spec.gpu_length_mm} mm length')
        if spec.recommended_psu_watts:
            bullets.append(f'{spec.recommended_psu_watts}W PSU rec.')
    elif slot == 'psu':
        if spec.wattage:
            bullets.append(f'{spec.wattage}W')
        if spec.efficiency_rating:
            bullets.append(spec.efficiency_rating)
        if spec.psu_connectors and spec.psu_connectors.get('pcie_16pin_12vhpwr'):
            bullets.append('Native 12VHPWR')
    elif slot == 'case':
        if spec.supported_form_factors:
            bullets.append(', '.join(spec.supported_form_factors))
        if spec.max_gpu_length_mm:
            bullets.append(f'Max GPU {spec.max_gpu_length_mm} mm')
        if spec.max_cooler_height_mm:
            bullets.append(f'Max Cooler {spec.max_cooler_height_mm} mm')
    elif slot == 'cooler':
        if spec.cooler_type:
            bullets.append(spec.cooler_type)
        if spec.cooler_height_mm:
            bullets.append(f'{spec.cooler_height_mm} mm height')
        if spec.radiator_size_mm:
            bullets.append(f'{spec.radiator_size_mm} mm radiator')
        if spec.supported_sockets:
            bullets.append(f'Sockets: {", ".join(spec.supported_sockets[:4])}')
    elif slot in ('storage', 'storage_secondary'):
        if spec.storage_type:
            bullets.append(spec.storage_type)
        if spec.capacity_gb:
            bullets.append(f'{spec.capacity_gb}GB')

    if not bullets:
        return ['Partial specifications recorded']
    return bullets


def _build_dual_level_explanations(issue: CompatibilityIssue, involved: list[ComponentSpecSummary]) -> tuple[str, str, str]:
    """Return (heading, beginner_explanation, expert_explanation) tailored for the conflict."""
    code = issue.rule_code
    by_slot = {c.slot: c for c in involved}

    if code == 'CPU_MOBO_SOCKET_MISMATCH' and 'cpu' in by_slot and 'motherboard' in by_slot:
        cpu_spec = by_slot['cpu'].product.spec_profile_safe
        mobo_spec = by_slot['motherboard'].product.spec_profile_safe
        cpu_sock = cpu_spec.socket if cpu_spec else 'unknown'
        mobo_sock = mobo_spec.socket if mobo_spec else 'unknown'
        return (
            'Your CPU and motherboard are incompatible.',
            'Your processor and motherboard use different connection types. They physically cannot be installed together.',
            f'CPU socket {cpu_sock} does not match the motherboard\'s {mobo_sock} socket.',
        )

    if code in ('CPU_MOBO_CHIPSET_INCOMPATIBLE', 'CPU_MOBO_FAMILY_UNSUPPORTED', 'CPU_MOBO_QVL_UNSUPPORTED'):
        return (
            'Your CPU and motherboard chipset are incompatible.',
            'Even when connectors look similar, this motherboard chipset does not support this processor generation and the PC will not boot.',
            issue.message,
        )

    if code in ('CPU_MOBO_CHIPSET_BIOS_WARNING', 'CPU_MOBO_BIOS_REQUIRED', 'CPU_MOBO_BIOS_NOTE'):
        return (
            issue.title,
            'These parts can work together, but you may need a motherboard BIOS software update before installing this CPU.',
            issue.message,
        )

    if code in ('MOBO_RAM_DDR_MISMATCH', 'CPU_RAM_TYPE_MISMATCH'):
        return (
            'Your memory (RAM) generation is incompatible.',
            'DDR4 and DDR5 memory sticks have different slot notches and voltage designs, so they will not fit or work on a mismatched board.',
            issue.message,
        )

    if code in ('MOBO_RAM_SLOTS_EXCEEDED', 'MOBO_RAM_CAPACITY_EXCEEDED', 'CPU_RAM_CAPACITY_EXCEEDED'):
        return (
            'Your memory configuration exceeds motherboard or CPU limits.',
            'You selected more RAM sticks or higher memory capacity than this motherboard or CPU supports.',
            issue.message,
        )

    if code == 'GPU_CASE_TOO_LONG':
        return (
            'Your graphics card is too long for this PC case.',
            'The graphics card physically cannot fit inside the selected cabinet length clearance.',
            issue.message,
        )

    if code in ('COOLER_CASE_TOO_TALL', 'COOLER_CASE_RAD_UNSUPPORTED', 'CPU_COOLER_SOCKET_MISMATCH'):
        return (
            'Your CPU cooler does not fit this build.',
            'This cooler either lacks mounting brackets for your processor or is too large for your PC case.',
            issue.message,
        )

    if code == 'MOBO_CASE_FORM_FACTOR_MISMATCH':
        return (
            'Your motherboard is too large for this PC case.',
            'The selected cabinet does not have mounting standoffs or space for a motherboard of this size.',
            issue.message,
        )

    if code in ('PSU_WATTAGE_INSUFFICIENT', 'PSU_12VHPWR_CONNECTORS_MISSING', 'PSU_PCIE_8PIN_INSUFFICIENT'):
        return (
            'Your power supply cannot safely power this build.',
            'The selected power supply either provides too little wattage or lacks the required graphics card power cables.',
            issue.message,
        )

    if code == 'DISPLAY_NO_GPU':
        return (
            'No graphics output detected in cart.',
            'This processor has no built-in graphics. If you do not already own a graphics card, you will need a dedicated GPU for display output.',
            issue.message,
        )

    if issue.status == STATUS_UNKNOWN:
        return (
            issue.title,
            'Verified specification data is missing for one or more parts, so full compatibility cannot be guaranteed automatically.',
            issue.message,
        )

    return (issue.title, issue.message, issue.message)


class CartCompatibilityService:
    """Evaluates shopping cart items using the deterministic PC Builder CompatibilityEngine."""

    def __init__(self):
        self.engine = CompatibilityEngine()
        self.alt_service = SmartAlternativesService(self.engine)
        self.advisor = CartCompatibilityAdvisor(self.engine)

    def evaluate_cart(self, cart: Cart | None, include_ai: bool = True) -> CartCompatibilityContext:
        if not cart:
            return self._not_applicable_context()

        items = list(
            cart.items.select_related(
                'product',
                'product__category',
                'product__brand',
                'product__inventory',
                'product__spec_profile',
            ).order_by('added_at', 'id')
        )
        return self.evaluate_cart_items(items, include_ai=include_ai)

    def evaluate_cart_items(self, items: list, include_ai: bool = True) -> CartCompatibilityContext:
        core_items = []
        peripheral_items = []
        unrelated_items = []

        for item in items:
            prod = item.product
            slot = prod.category.component_slot if prod.category else 'other'
            if slot in CORE_PC_SLOTS:
                core_items.append((slot, prod, item.quantity))
            elif slot in PERIPHERAL_SLOTS:
                peripheral_items.append((slot, prod, item.quantity))
            else:
                unrelated_items.append(prod)

        # Require at least 2 core internal PC hardware items (e.g. CPU + Motherboard, RAM + Motherboard, GPU + Case, Storage + Motherboard)
        if len(core_items) < 2:
            return self._not_applicable_context()

        slot_items: dict[str, tuple[Product, int]] = {}
        competing_slots: list[str] = []
        storage_assigned = 0

        for slot, prod, qty in core_items:
            if slot == 'storage':
                if storage_assigned == 0:
                    slot_items['storage'] = (prod, qty)
                    storage_assigned += 1
                elif storage_assigned == 1:
                    slot_items['storage_secondary'] = (prod, qty)
                    storage_assigned += 1
                else:
                    competing_slots.append('storage')
                continue

            if slot in slot_items:
                if 'motherboard' if slot == 'motherboard' else slot not in competing_slots:
                    competing_slots.append(slot)
                continue

            # Keep RAM quantity so CompatibilityEngine enforces DIMM count & max capacity;
            # single-part slots with qty > 1 also indicate multi-PC / competing quantity ambiguity.
            if slot in ('cpu', 'motherboard', 'gpu', 'psu', 'case', 'cooler') and qty > 1:
                if slot not in competing_slots:
                    competing_slots.append(slot)
            slot_items[slot] = (prod, qty if slot in ('ram', 'storage', 'case_fan') else 1)

        report = self.engine.evaluate_products(slot_items)

        ambiguity_notes = []
        if competing_slots:
            labels = ', '.join(SLOT_LABELS.get(s, s.title()) for s in dict.fromkeys(competing_slots))
            ambiguity_notes.append(
                f'Your cart contains multiple items or quantities for {labels}. '
                'This check evaluates the primary hardware combination listed below rather than assuming all items go into one PC.'
            )
        if unrelated_items or peripheral_items:
            extra_count = len(unrelated_items) + len(peripheral_items)
            ambiguity_notes.append(
                f'Compatibility check is based on the {len(slot_items)} core internal PC component(s) in your cart '
                f'({extra_count} accessory/peripheral item(s) excluded from internal fit checks).'
            )

        evaluated_components = [
            ComponentSpecSummary(
                slot=s,
                slot_label=SLOT_LABELS.get(s, s.title()),
                product=prod,
                spec_bullets=extract_component_bullets(prod, s),
            )
            for s, (prod, _) in slot_items.items()
        ]
        comp_by_slot = {c.slot: c for c in evaluated_components}

        detailed_issues: list[DetailedCartIssue] = []
        for idx, chk in enumerate(report.checks):
            # Keep cart focused: show non-compatible issues prominently, or verified checks in summary
            involved = [comp_by_slot[s] for s in chk.affected_slots if s in comp_by_slot]
            heading, beg_exp, exp_exp = _build_dual_level_explanations(chk, involved)
            directions = self._build_fix_directions(chk, slot_items, idx) if chk.status == STATUS_INCOMPATIBLE else []
            detailed_issues.append(
                DetailedCartIssue(
                    rule_code=chk.rule_code,
                    status=chk.status,
                    category=chk.category,
                    heading=heading,
                    title=chk.title,
                    message=chk.message,
                    beginner_explanation=beg_exp,
                    expert_explanation=exp_exp,
                    suggestion=chk.suggestion,
                    involved_components=involved,
                    fix_directions=directions,
                )
            )

        advice = self.advisor.advise_on_conflicts(
            detailed_issues=detailed_issues,
            slot_items=slot_items,
            allow_ai_call=include_ai,
        )

        # Apply validated AI ranking / reasons to replacement suggestions without changing verified pool
        if advice.direction_suggestions:
            for issue in detailed_issues:
                for direction in issue.fix_directions:
                    d_advice = advice.direction_suggestions.get(direction.direction_key)
                    if not d_advice:
                        continue
                    if d_advice.get('tip'):
                        direction.tip = d_advice['tip']
                    reasons = d_advice.get('reasons') or {}
                    rec_order = d_advice.get('recommended_ids') or []
                    for rep in direction.replacements:
                        if rep.product.id in reasons:
                            rep.reason = reasons[rep.product.id]
                    if rec_order:
                        rank_idx = {pid: i for i, pid in enumerate(rec_order)}
                        direction.replacements.sort(key=lambda r: rank_idx.get(r.product.id, 999))

        meta = OVERALL_STATUS_META.get(report.overall_status, OVERALL_STATUS_META[STATUS_UNKNOWN])
        part_names = ', '.join(f'{c.slot_label}: {c.product.name}' for c in evaluated_components)
        scope_note = f'Based on selected cart hardware ({part_names}).'

        return CartCompatibilityContext(
            is_applicable=True,
            status=report.overall_status,
            headline=meta['headline'],
            badge_class=meta['badge_class'],
            alert_class=meta['alert_class'],
            icon=meta['icon'],
            has_incompatibility=len(report.incompatibilities) > 0,
            has_warning=len(report.warnings) > 0,
            has_unknown=len(report.unknowns) > 0,
            is_all_compatible=(report.overall_status == STATUS_COMPATIBLE),
            evaluated_components=evaluated_components,
            detailed_issues=detailed_issues,
            ambiguity_notes=ambiguity_notes,
            selection_scope_note=scope_note,
            estimated_wattage=report.estimated_wattage,
            recommended_psu_wattage=report.recommended_psu_wattage,
            advisor_source_label=advice.source_label,
            advisor_notice=advice.notice_message,
            advisor_summary=advice.summary,
            is_ai_fallback=advice.is_fallback,
            report=report,
        )

    def _build_fix_directions(self, chk: CompatibilityIssue, slot_items: dict, issue_idx: int) -> list[FixDirection]:
        """Generate grounded Direction A & Direction B swap choices (or add choices) verified by CompatibilityEngine."""
        present_slots = [s for s in chk.affected_slots if s in slot_items]
        directions: list[FixDirection] = []

        if len(present_slots) >= 2:
            # Build Direction A (keep first slot, replace second) and Direction B (keep second slot, replace first)
            pairs = [(present_slots[0], present_slots[1], 'A'), (present_slots[1], present_slots[0], 'B')]
            for keep_slot, replace_slot, letter in pairs:
                keep_prod = slot_items[keep_slot][0]
                remove_prod = slot_items[replace_slot][0]
                raw_fixes = self.alt_service.get_compatible_replacements(slot_items, replace_slot, limit=3)
                suggestions = self._format_replacements(raw_fixes, replace_slot, remove_prod)
                replace_label = SLOT_LABELS.get(replace_slot, replace_slot.title())
                directions.append(
                    FixDirection(
                        direction_key=f'issue_{issue_idx}_{letter}_{keep_slot}_replace_{replace_slot}',
                        title=f'Option {letter}: Keep {keep_prod.name} — choose a compatible {replace_label}',
                        action_type='swap',
                        keep_slot=keep_slot,
                        keep_product=keep_prod,
                        target_slot=replace_slot,
                        remove_product=remove_prod,
                        tip=f'Verified in-stock {replace_label} options compatible with {keep_prod.name}.',
                        replacements=suggestions,
                    )
                )
        elif len(present_slots) == 1:
            slot = present_slots[0]
            remove_prod = slot_items[slot][0]
            raw_fixes = self.alt_service.get_compatible_replacements(slot_items, slot, limit=3)
            if raw_fixes:
                slot_label = SLOT_LABELS.get(slot, slot.title())
                directions.append(
                    FixDirection(
                        direction_key=f'issue_{issue_idx}_replace_{slot}',
                        title=f'Compatible {slot_label} alternatives',
                        action_type='swap',
                        keep_slot='',
                        keep_product=None,
                        target_slot=slot,
                        remove_product=remove_prod,
                        tip=f'Replace {remove_prod.name} with one of these verified compatible options.',
                        replacements=self._format_replacements(raw_fixes, slot, remove_prod),
                    )
                )
        return directions

    @staticmethod
    def _format_replacements(raw_fixes: list[dict], target_slot: str, current_prod: Product | None) -> list[ReplacementSuggestion]:
        suggestions = []
        for entry in raw_fixes:
            cand = entry['product']
            bullets = extract_component_bullets(cand, target_slot)
            diff_label = ''
            if current_prod is not None:
                diff = cand.price - current_prod.price
                if diff < Decimal('0.00'):
                    diff_label = f'Saves {format_inr(abs(diff))}'
                elif diff > Decimal('0.00'):
                    diff_label = f'+{format_inr(diff)}'
                else:
                    diff_label = 'Same price'
            suggestions.append(
                ReplacementSuggestion(
                    product=cand,
                    price_inr=format_inr(cand.price),
                    price_diff_inr=diff_label,
                    spec_summary=' • '.join(bullets[:3]),
                    compat_status=entry['status'],
                )
            )
        return suggestions

    @staticmethod
    def _not_applicable_context() -> CartCompatibilityContext:
        return CartCompatibilityContext(
            is_applicable=False,
            status='not_applicable',
            headline='Add 2 or more PC hardware components to check build compatibility.',
            badge_class='light',
            alert_class='light',
            icon='bi-pc-display',
            has_incompatibility=False,
            has_warning=False,
            has_unknown=False,
            is_all_compatible=False,
        )
