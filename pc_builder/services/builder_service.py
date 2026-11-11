from dataclasses import dataclass
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from store.models import Brand, Cart, Product
from store.services import cart_service
from pc_builder.models import BuildComponent, PCBuild
from pc_builder.services.alternatives import SmartAlternativesService, slot_to_category_slot
from pc_builder.services.compatibility import CompatibilityEngine, STATUS_PRIORITY


SLOT_METADATA = [
    {'slot': 'cpu', 'label': 'CPU / Processor', 'required': True, 'icon': 'cpu'},
    {'slot': 'motherboard', 'label': 'Motherboard', 'required': True, 'icon': 'circuit-board'},
    {'slot': 'ram', 'label': 'Memory (RAM)', 'required': True, 'icon': 'memory-stick'},
    {'slot': 'gpu', 'label': 'Graphics Card (GPU)', 'required': False, 'icon': 'microchip'},
    {'slot': 'storage', 'label': 'Primary Storage', 'required': True, 'icon': 'hard-drive'},
    {'slot': 'storage_secondary', 'label': 'Secondary Storage', 'required': False, 'icon': 'database'},
    {'slot': 'psu', 'label': 'Power Supply (PSU)', 'required': True, 'icon': 'zap'},
    {'slot': 'case', 'label': 'PC Case / Cabinet', 'required': True, 'icon': 'pc-case'},
    {'slot': 'cooler', 'label': 'CPU Cooler', 'required': False, 'icon': 'fan'},
    {'slot': 'case_fan', 'label': 'Additional Cooling / Fans', 'required': False, 'icon': 'wind'},
    {'slot': 'monitor', 'label': 'Monitor', 'required': False, 'icon': 'monitor'},
    {'slot': 'keyboard', 'label': 'Keyboard', 'required': False, 'icon': 'keyboard'},
    {'slot': 'mouse', 'label': 'Mouse', 'required': False, 'icon': 'mouse'},
]


@dataclass
class BuildToCartResult:
    success: bool
    message: str
    added_count: int = 0
    errors: list[str] | None = None


class PCBuilderService:
    """Core orchestration service for Beginner & Expert PC Builder workflows."""

    def __init__(self):
        self.compat_engine = CompatibilityEngine()
        self.alt_service = SmartAlternativesService(self.compat_engine)

    @staticmethod
    def _ensure_session_key(request) -> str:
        if not request.session.session_key:
            request.session.create()
        return request.session.session_key

    def get_or_create_active_build(self, request) -> PCBuild:
        if request.user.is_authenticated:
            build = (
                PCBuild.objects.filter(user=request.user, is_active_workspace=True)
                .order_by('-updated_at')
                .first()
            )
            if build:
                return build

            # Check if guest workspace build exists for this session and claim it
            if request.session.session_key:
                guest_build = (
                    PCBuild.objects.filter(
                        session_key=request.session.session_key,
                        user__isnull=True,
                        is_active_workspace=True,
                    )
                    .order_by('-updated_at')
                    .first()
                )
                if guest_build:
                    guest_build.user = request.user
                    guest_build.save(update_fields=['user', 'updated_at'])
                    return guest_build

            default_mode = 'beginner'
            if hasattr(request.user, 'customer'):
                default_mode = request.user.customer.preferred_builder_mode or 'beginner'
            return PCBuild.objects.create(
                user=request.user,
                mode=default_mode,
                is_active_workspace=True,
            )

        session_key = self._ensure_session_key(request)
        build = (
            PCBuild.objects.filter(session_key=session_key, user__isnull=True, is_active_workspace=True)
            .order_by('-updated_at')
            .first()
        )
        if not build:
            build = PCBuild.objects.create(
                session_key=session_key,
                mode='beginner',
                is_active_workspace=True,
            )
        return build

    def merge_guest_build_on_login(self, request, user, session_key: str | None = None) -> None:
        session_key = session_key or request.session.session_key
        if not session_key:
            return
        guest_build = (
            PCBuild.objects.filter(session_key=session_key, user__isnull=True, is_active_workspace=True)
            .order_by('-updated_at')
            .first()
        )
        if not guest_build:
            return

        user_build = PCBuild.objects.filter(user=user, is_active_workspace=True).first()
        if not user_build:
            guest_build.user = user
            guest_build.save(update_fields=['user', 'updated_at'])
            return

        # If user's workspace build is empty and guest build has components, copy them over
        if user_build.components.count() == 0 and guest_build.components.count() > 0:
            self._copy_build_contents(source=guest_build, target=user_build)
            guest_build.delete()

    def switch_mode(self, build: PCBuild, target_mode: str, user=None) -> PCBuild:
        """
        Switch between Beginner Mode and Expert Mode WITHOUT erasing any selected
        components or preferences.
        """
        if target_mode not in ('beginner', 'expert'):
            raise ValueError(f'Unsupported builder mode: {target_mode}')
        if build.mode != target_mode:
            build.mode = target_mode
            build.save(update_fields=['mode', 'updated_at'])
        if user and user.is_authenticated and hasattr(user, 'customer'):
            if user.customer.preferred_builder_mode != target_mode:
                user.customer.preferred_builder_mode = target_mode
                user.customer.save(update_fields=['preferred_builder_mode', 'updated_at'])
        return build

    @transaction.atomic
    def set_component(
        self,
        build: PCBuild,
        slot: str,
        product: Product,
        quantity: int = 1,
        mode: str | None = None,
        selection_reason: str = '',
        tradeoffs: str = '',
    ):
        """
        Add or replace a component in `slot` without silently deleting any other
        components (even if an incompatibility arises).
        """
        if slot not in BuildComponent.ALL_SLOTS:
            raise ValueError(f'Invalid PC Builder slot: {slot}')
        expected_cat_slot = slot_to_category_slot(slot)
        if product.category and product.category.component_slot != expected_cat_slot:
            raise ValueError(
                f'{product.name} belongs to {product.category.name}, not the {slot} slot.'
            )

        qty = max(1, int(quantity))
        comp, _ = BuildComponent.objects.update_or_create(
            build=build,
            slot=slot,
            defaults={
                'product': product,
                'quantity': qty,
                'added_via_mode': mode or build.mode,
                'selection_reason': selection_reason,
                'tradeoffs': tradeoffs,
            },
        )
        build.save(update_fields=['updated_at'])
        report = self.compat_engine.evaluate_build(build)
        return comp, report

    @transaction.atomic
    def remove_component(self, build: PCBuild, slot: str):
        BuildComponent.objects.filter(build=build, slot=slot).delete()
        build.save(update_fields=['updated_at'])
        return self.compat_engine.evaluate_build(build)

    @transaction.atomic
    def clear_build_components(self, build: PCBuild):
        build.components.all().delete()
        build.ai_summary = ''
        build.ai_source = ''
        build.save(update_fields=['ai_summary', 'ai_source', 'updated_at'])
        return self.compat_engine.evaluate_build(build)

    def get_build_context(self, build: PCBuild) -> dict:
        """Assemble full build context: slots, compatibility report, replacement hints, totals."""
        slot_map = build.get_slot_map()
        slot_items = {slot: (comp.product, comp.quantity) for slot, comp in slot_map.items()}
        report = self.compat_engine.evaluate_products(slot_items)

        # Map incompatibilities by affected slot to offer targeted replacement suggestions
        incompatible_slots = set()
        for issue in report.incompatibilities:
            for s in issue.affected_slots:
                incompatible_slots.add(s)

        slots_display = []
        for meta in SLOT_METADATA:
            slot_key = meta['slot']
            comp = slot_map.get(slot_key)
            replacements = []
            alternatives = {}
            if comp:
                if slot_key in incompatible_slots:
                    replacements = self.alt_service.get_compatible_replacements(slot_items, slot_key, limit=3)
                alternatives = self.alt_service.get_slot_alternatives(slot_items, slot_key, comp.product)

            slots_display.append({
                'slot': slot_key,
                'label': meta['label'],
                'required': meta['required'],
                'icon': meta['icon'],
                'component': comp,
                'has_conflict': slot_key in incompatible_slots,
                'replacements': replacements,
                'alternatives': alternatives,
            })

        return {
            'build': build,
            'slots': slots_display,
            'slot_map': slot_map,
            'compatibility': report,
            'total_price': build.total_price,
            'component_count': build.component_count,
        }

    def get_slot_candidates(self, build: PCBuild, slot: str, params: dict | None = None) -> dict:
        """
        Return filtered catalog candidates for Expert Mode component selection,
        annotated with live compatibility against the user's current build.
        """
        params = params or {}
        cat_slot = slot_to_category_slot(slot)
        qs = (
            Product.objects.filter(is_active=True, category__component_slot=cat_slot)
            .select_related('category', 'brand', 'inventory', 'spec_profile')
        )

        q = (params.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(brand__name__icontains=q)
                | Q(short_description__icontains=q)
                | Q(spec_profile__socket__icontains=q)
                | Q(spec_profile__chipset__icontains=q)
                | Q(spec_profile__memory_type__icontains=q)
            )

        brand_slug = (params.get('brand') or '').strip()
        if brand_slug:
            qs = qs.filter(brand__slug=brand_slug)

        socket_filter = (params.get('socket') or '').strip()
        if socket_filter:
            qs = qs.filter(spec_profile__socket__iexact=socket_filter)

        memory_filter = (params.get('memory_type') or '').strip()
        if memory_filter:
            qs = qs.filter(spec_profile__memory_type__iexact=memory_filter)

        max_price = params.get('max_price')
        if max_price:
            try:
                qs = qs.filter(price__lte=Decimal(str(max_price)))
            except Exception:
                pass

        in_stock_only = str(params.get('in_stock') or '').lower() in ('1', 'true', 'yes', 'on')
        if in_stock_only:
            qs = qs.filter(inventory__quantity__gt=0)

        only_compatible = str(params.get('only_compatible') or '').lower() in ('1', 'true', 'yes', 'on')

        current_map = {
            comp.slot: (comp.product, comp.quantity)
            for comp in build.components.select_related('product', 'product__spec_profile')
        }

        annotated = []
        for product in qs:
            test_map = dict(current_map)
            test_map[slot] = (product, 1)
            report = self.compat_engine.evaluate_products(test_map)
            if only_compatible and not report.is_build_valid_compatible:
                continue

            # Find issues most relevant to this slot
            slot_issues = [
                issue for issue in report.issues if slot in issue.affected_slots
            ]
            primary_issue = slot_issues[0] if slot_issues else (report.issues[0] if report.issues else None)
            annotated.append({
                'product': product,
                'compat_status': report.overall_status,
                'compat_priority': STATUS_PRIORITY[report.overall_status],
                'primary_issue': primary_issue,
                'slot_issues': slot_issues,
                'is_selected': (slot in current_map and current_map[slot][0].id == product.id),
            })

        sort = (params.get('sort') or 'recommended').strip()
        if sort == 'price_asc':
            annotated.sort(key=lambda x: (x['product'].price, x['compat_priority']))
        elif sort == 'price_desc':
            annotated.sort(key=lambda x: (-x['product'].price, x['compat_priority']))
        elif sort == 'performance':
            annotated.sort(
                key=lambda x: (
                    x['compat_priority'],
                    -(x['product'].spec_profile_safe.benchmark_score or 0 if x['product'].spec_profile_safe else 0),
                    x['product'].price,
                )
            )
        else:
            annotated.sort(
                key=lambda x: (
                    x['compat_priority'],
                    -(x['product'].spec_profile_safe.benchmark_score or 0 if x['product'].spec_profile_safe else 0),
                    x['product'].price,
                )
            )

        available_brands = Brand.objects.filter(
            products__is_active=True,
            products__category__component_slot=cat_slot,
        ).distinct().order_by('name')

        return {
            'candidates': annotated,
            'brands': available_brands,
        }

    @transaction.atomic
    def save_build_snapshot(self, build: PCBuild, user, name: str) -> PCBuild:
        """Save a named immutable snapshot of the current build for a logged-in user."""
        clean_name = (name or '').strip() or f'{build.get_primary_use_display()} Build'
        snapshot = PCBuild.objects.create(
            user=user,
            name=clean_name,
            mode=build.mode,
            is_active_workspace=False,
            is_saved=True,
            budget=build.budget,
            primary_use=build.primary_use,
            preferred_brands=list(build.preferred_brands or []),
            include_monitor=build.include_monitor,
            include_peripherals=build.include_peripherals,
            priority_preference=build.priority_preference,
            upgradeability_preference=build.upgradeability_preference,
            notes=build.notes,
            ai_summary=build.ai_summary,
            ai_source=build.ai_source,
        )
        for comp in build.components.all():
            BuildComponent.objects.create(
                build=snapshot,
                slot=comp.slot,
                product=comp.product,
                quantity=comp.quantity,
                selection_reason=comp.selection_reason,
                tradeoffs=comp.tradeoffs,
                added_via_mode=comp.added_via_mode,
            )
        return snapshot

    @transaction.atomic
    def load_saved_build(self, workspace_build: PCBuild, saved_build: PCBuild) -> PCBuild:
        """Load a saved build into the user's active workspace build."""
        self._copy_build_contents(source=saved_build, target=workspace_build)
        return workspace_build

    @staticmethod
    def _copy_build_contents(source: PCBuild, target: PCBuild):
        target.name = source.name
        target.budget = source.budget
        target.primary_use = source.primary_use
        target.preferred_brands = list(source.preferred_brands or [])
        target.include_monitor = source.include_monitor
        target.include_peripherals = source.include_peripherals
        target.priority_preference = source.priority_preference
        target.upgradeability_preference = source.upgradeability_preference
        target.notes = source.notes
        target.ai_summary = source.ai_summary
        target.ai_source = source.ai_source
        target.save()

        target.components.all().delete()
        for comp in source.components.all():
            BuildComponent.objects.create(
                build=target,
                slot=comp.slot,
                product=comp.product,
                quantity=comp.quantity,
                selection_reason=comp.selection_reason,
                tradeoffs=comp.tradeoffs,
                added_via_mode=comp.added_via_mode,
            )

    @transaction.atomic
    def add_build_to_cart(self, build: PCBuild, cart: Cart) -> BuildToCartResult:
        components = list(build.components.select_related('product', 'product__inventory'))
        if not components:
            return BuildToCartResult(
                success=False,
                message='Your PC build has no components selected yet.',
                errors=['Select at least one component before adding the build to cart.'],
            )

        stock_errors = []
        for comp in components:
            avail = comp.product.stock_quantity
            if not comp.product.is_active:
                stock_errors.append(f'{comp.product.name} is currently unavailable.')
            elif avail < comp.quantity:
                stock_errors.append(
                    f'{comp.product.name}: build needs {comp.quantity}, but only {avail} left in stock.'
                )

        if stock_errors:
            return BuildToCartResult(
                success=False,
                message='Unable to add complete build to cart due to stock limits.',
                errors=stock_errors,
            )

        added = 0
        for comp in components:
            res = cart_service.update_cart_item(
                cart=cart,
                product=comp.product,
                action='add',
                quantity=comp.quantity,
                source_build=build,
            )
            if not res.success:
                return BuildToCartResult(
                    success=False,
                    message=res.message,
                    added_count=added,
                    errors=[res.message],
                )
            added += 1

        return BuildToCartResult(
            success=True,
            message=f'Added all {added} component(s) from "{build.name}" to your shopping cart!',
            added_count=added,
        )
