from decimal import Decimal
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from store.models import Product
from ai_engine.services.recommender import BuildRecommendationOrchestrator, BuildRequirements
from pc_builder.models import BuildComponent
from pc_builder.services.alternatives import SmartAlternativesService
from pc_builder.services.builder_service import PCBuilderService
from pc_builder.services.compatibility import CompatibilityEngine


class BuildStateAPIView(APIView):
    """GET current active workspace build summary, prices, and deterministic compatibility report."""

    def get(self, request):
        builder = PCBuilderService()
        build = builder.get_or_create_active_build(request)
        report = builder.compat_engine.evaluate_build(build)
        components = []
        for comp in build.components.select_related('product', 'product__brand', 'product__category'):
            components.append({
                'slot': comp.slot,
                'product_id': comp.product.id,
                'name': comp.product.name,
                'brand': comp.product.brand.name if comp.product.brand else '',
                'price': str(comp.product.price),
                'quantity': comp.quantity,
                'line_total': str(comp.line_total),
            })

        return Response({
            'build_uuid': str(build.uuid),
            'name': build.name,
            'mode': build.mode,
            'total_price': str(build.total_price),
            'component_count': build.component_count,
            'components': components,
            'compatibility': report.to_dict(),
        })


class CompatibilityCheckAPIView(APIView):
    """POST {slots: {slot: product_id}} to evaluate deterministic compatibility."""

    def post(self, request):
        slots = request.data.get('slots') or {}
        if not isinstance(slots, dict):
            return Response({'detail': 'slots must be an object.'}, status=status.HTTP_400_BAD_REQUEST)

        slot_items = {}
        for slot, pid in slots.items():
            if slot not in BuildComponent.ALL_SLOTS or not pid:
                continue
            prod = Product.objects.filter(id=pid, is_active=True).select_related('spec_profile').first()
            if prod:
                slot_items[slot] = (prod, 1)

        report = CompatibilityEngine().evaluate_products(slot_items)
        return Response(report.to_dict())


class BeginnerRecommendAPIView(APIView):
    """POST questionnaire parameters to get a compatibility-verified AI/fallback recommendation."""

    def post(self, request):
        data = request.data or {}
        try:
            budget = Decimal(str(data.get('budget', 65000)))
        except Exception:
            return Response({'detail': 'Invalid budget value.'}, status=status.HTTP_400_BAD_REQUEST)

        req = BuildRequirements(
            budget=budget,
            primary_use=data.get('primary_use', 'gaming'),
            preferred_brands=list(data.get('preferred_brands') or []),
            include_monitor=bool(data.get('include_monitor', False)),
            include_peripherals=bool(data.get('include_peripherals', False)),
            priority_preference=data.get('priority_preference', 'balanced'),
            upgradeability_preference=data.get('upgradeability_preference', 'moderate'),
        )
        outcome = BuildRecommendationOrchestrator().generate_recommendation(req)
        return Response({
            'success': outcome.success,
            'is_fallback': outcome.is_fallback,
            'source_label': outcome.source_label,
            'notice_message': outcome.notice_message,
            'summary': outcome.summary,
            'total_price': str(outcome.total_price),
            'compatibility': outcome.compatibility_report.to_dict(),
            'recommendations': [
                {
                    'slot': rec.slot,
                    'product_id': rec.product.id,
                    'product_name': rec.product.name,
                    'price': str(rec.product.price),
                    'why_selected': rec.why_selected,
                    'what_it_does': rec.what_it_does,
                    'suits_user': rec.suits_user,
                    'tradeoffs': rec.tradeoffs,
                }
                for rec in outcome.recommendations
            ],
        })


class SlotAlternativesAPIView(APIView):
    """GET smart alternatives for a selected slot in the active workspace build."""

    def get(self, request, slot):
        if slot not in BuildComponent.ALL_SLOTS:
            return Response({'detail': 'Invalid slot.'}, status=status.HTTP_400_BAD_REQUEST)
        builder = PCBuilderService()
        build = builder.get_or_create_active_build(request)
        slot_map = build.get_slot_map()
        comp = slot_map.get(slot)
        if not comp:
            return Response({'alternatives': {}})
        slot_items = {s: (c.product, c.quantity) for s, c in slot_map.items()}
        alts = SmartAlternativesService(builder.compat_engine).get_slot_alternatives(slot_items, slot, comp.product)
        serialized = {
            k: {
                'label': v['label'],
                'product_id': v['product'].id,
                'product_name': v['product'].name,
                'price': str(v['product'].price),
                'price_diff': str(v['price_diff']),
                'compat_status': v['compat_status'],
                'tradeoff': v['tradeoff'],
            }
            for k, v in alts.items()
        }
        return Response({'slot': slot, 'alternatives': serialized})
