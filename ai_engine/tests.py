from decimal import Decimal
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase
from store.models import Product
from ai_engine.services.recommender import (
    AIProviderClient,
    BuildRecommendationOrchestrator,
    BuildRequirements,
)


class AIRecommendationGroundingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_hardware_catalog')

    def test_deterministic_fallback_when_no_ai_key_configured(self):
        orchestrator = BuildRecommendationOrchestrator()
        req = BuildRequirements(
            budget=Decimal('75000'),
            primary_use='gaming',
            include_monitor=True,
            include_peripherals=True,
            priority_preference='balanced',
            upgradeability_preference='high',
        )
        outcome = orchestrator.generate_recommendation(req)
        self.assertTrue(outcome.success)
        self.assertTrue(outcome.is_fallback)
        self.assertIn('fallback', outcome.source_label.lower())
        self.assertTrue(outcome.compatibility_report.is_build_valid_compatible)

        slots = {r.slot for r in outcome.recommendations}
        for expected in ('cpu', 'motherboard', 'ram', 'storage', 'psu', 'case', 'monitor', 'keyboard', 'mouse'):
            self.assertIn(expected, slots)

    def test_existing_locked_component_preserved_in_recommendations(self):
        am5_cpu = Product.objects.filter(category__component_slot='cpu', spec_profile__socket='AM5', is_active=True).first()
        self.assertIsNotNone(am5_cpu)
        req = BuildRequirements(budget=Decimal('90000'), primary_use='programming')
        outcome = BuildRecommendationOrchestrator().generate_recommendation(req, existing_components={'cpu': am5_cpu})

        self.assertTrue(outcome.compatibility_report.is_build_valid_compatible)
        rec_by_slot = {r.slot: r.product for r in outcome.recommendations}
        self.assertEqual(rec_by_slot['cpu'].id, am5_cpu.id)
        self.assertEqual(rec_by_slot['motherboard'].spec_profile.socket, 'AM5')
        self.assertEqual(rec_by_slot['ram'].spec_profile.memory_type, 'DDR5')

    def test_ai_hallucinated_product_id_is_rejected_and_falls_back(self):
        orchestrator = BuildRecommendationOrchestrator()
        req = BuildRequirements(budget=Decimal('65000'), primary_use='gaming')

        fake_hallucinated = {
            'summary': 'Super fake PC',
            'selections': {
                'cpu': {'product_id': 9999999, 'why_selected': 'Fake CPU'},
            },
        }
        with patch.object(AIProviderClient, 'is_configured', True), patch.object(
            AIProviderClient, 'request_structured_build', return_value=fake_hallucinated
        ):
            outcome = orchestrator.generate_recommendation(req)

        self.assertTrue(outcome.success)
        self.assertTrue(outcome.is_fallback)
        self.assertIn('rejected', outcome.notice_message.lower())
        self.assertTrue(outcome.compatibility_report.is_build_valid_compatible)

    def test_ai_incompatible_build_am5_plus_ddr4_is_rejected_by_compatibility_gate(self):
        am5_cpu = Product.objects.filter(category__component_slot='cpu', spec_profile__socket='AM5', is_active=True, inventory__quantity__gt=0).first()
        am5_mobo = Product.objects.filter(category__component_slot='motherboard', spec_profile__socket='AM5', is_active=True, inventory__quantity__gt=0).first()
        ddr4_ram = Product.objects.filter(category__component_slot='ram', spec_profile__memory_type='DDR4', is_active=True, inventory__quantity__gt=0).first()

        # Real in-stock product IDs, matching categories, yet physically incompatible (AM5 + DDR4)!
        bad_ai_proposal = {
            'summary': 'Broken AI proposal mixing AM5 and DDR4.',
            'selections': {
                'cpu': {'product_id': am5_cpu.id, 'why_selected': 'Good CPU'},
                'motherboard': {'product_id': am5_mobo.id, 'why_selected': 'AM5 board'},
                'ram': {'product_id': ddr4_ram.id, 'why_selected': 'Cheap RAM'},
            },
        }
        with patch.object(AIProviderClient, 'is_configured', True), patch.object(
            AIProviderClient, 'request_structured_build', return_value=bad_ai_proposal
        ):
            outcome = BuildRecommendationOrchestrator().generate_recommendation(
                BuildRequirements(budget=Decimal('80000'), primary_use='gaming')
            )

        self.assertTrue(outcome.is_fallback)
        self.assertIn('rejected', outcome.notice_message.lower())
        self.assertTrue(outcome.compatibility_report.is_build_valid_compatible)

    def test_ai_wrong_category_or_out_of_stock_rejected(self):
        psu = Product.objects.filter(category__component_slot='psu', is_active=True, inventory__quantity__gt=0).first()
        wrong_cat_payload = {
            'summary': 'PSU in CPU slot',
            'selections': {
                'cpu': {'product_id': psu.id, 'why_selected': 'Mistake'},
            },
        }
        with patch.object(AIProviderClient, 'is_configured', True), patch.object(
            AIProviderClient, 'request_structured_build', return_value=wrong_cat_payload
        ):
            outcome = BuildRecommendationOrchestrator().generate_recommendation(
                BuildRequirements(budget=Decimal('60000'), primary_use='office')
            )
        self.assertTrue(outcome.is_fallback)
        self.assertTrue(outcome.compatibility_report.is_build_valid_compatible)

    def test_valid_mocked_ai_response_accepted_and_db_grounded(self):
        cpu = Product.objects.filter(
            category__component_slot='cpu',
            spec_profile__socket='AM5',
            spec_profile__includes_stock_cooler=True,
            is_active=True,
            inventory__quantity__gt=0,
        ).first()
        mobo = Product.objects.filter(
            category__component_slot='motherboard',
            spec_profile__socket='AM5',
            spec_profile__form_factor='Micro-ATX',
            is_active=True,
            inventory__quantity__gt=0,
        ).first()
        ram = Product.objects.filter(
            category__component_slot='ram',
            spec_profile__memory_type='DDR5',
            spec_profile__ram_speed_mhz__lte=5200,
            is_active=True,
            inventory__quantity__gt=0,
        ).first() or Product.objects.filter(
            category__component_slot='ram',
            spec_profile__memory_type='DDR5',
            is_active=True,
            inventory__quantity__gt=0,
        ).first()
        ssd = Product.objects.filter(
            category__component_slot='storage',
            spec_profile__storage_type='NVMe M.2',
            is_active=True,
            inventory__quantity__gt=0,
        ).first()
        psu = Product.objects.filter(
            category__component_slot='psu',
            spec_profile__wattage__gte=550,
            is_active=True,
            inventory__quantity__gt=0,
        ).first()
        case = Product.objects.filter(
            category__component_slot='case',
            spec_profile__max_gpu_length_mm__gte=300,
            is_active=True,
            inventory__quantity__gt=0,
        ).first()

        valid_ai_payload = {
            'summary': 'Grounded AM5 productivity PC.',
            'selections': {
                'cpu': {'product_id': cpu.id, 'why_selected': 'Modern AM5 efficiency', 'suits_user': 'Fast builds', 'tradeoffs': 'Requires DDR5'},
                'motherboard': {'product_id': mobo.id, 'why_selected': 'Clean B650 platform'},
                'ram': {'product_id': ram.id, 'why_selected': 'Fast DDR5 dual-channel'},
                'storage': {'product_id': ssd.id, 'why_selected': 'NVMe boot drive'},
                'psu': {'product_id': psu.id, 'why_selected': 'Reliable wattage headroom'},
                'case': {'product_id': case.id, 'why_selected': 'Good airflow'},
            },
        }
        with patch.object(AIProviderClient, 'is_configured', True), patch.object(
            AIProviderClient, 'request_structured_build', return_value=valid_ai_payload
        ):
            outcome = BuildRecommendationOrchestrator().generate_recommendation(
                BuildRequirements(budget=Decimal('85000'), primary_use='programming')
            )

        self.assertFalse(outcome.is_fallback)
        self.assertTrue(outcome.compatibility_report.is_build_valid_compatible)
        expected_total = sum(p.price for p in (cpu, mobo, ram, ssd, psu, case))
        self.assertEqual(outcome.total_price, expected_total)
