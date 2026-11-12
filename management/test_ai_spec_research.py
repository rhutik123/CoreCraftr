import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from ai_engine.services.recommender import AIProviderClient
from ai_engine.services.spec_researcher import ProductSpecResearchService, WebSearchClient
from management.models import AIResearchDraft
from management.permissions import ensure_portal_roles
from store.models import Brand, Category, HardwareSpecProfile, Inventory, Product

User = get_user_model()


class AISpecResearchTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cpu_cat = Category.objects.create(
            name='Processors', slug='processors', component_slot='cpu', is_pc_component=True
        )
        cls.brand = Brand.objects.create(name='AMD', slug='amd')
        cls.manager = User.objects.create_user(
            username='ai_mgr', email='aimgr@corecraftr.local', password='MgrPass!123'
        )
        group = ensure_portal_roles()
        cls.manager.groups.add(group)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.manager)

    @override_settings(AI_PROVIDER='none', AI_API_KEY='')
    def test_unconfigured_ai_falls_back_gracefully_without_mutating_products(self):
        before_count = Product.objects.count()
        resp = self.client.post(
            reverse('management:api_ai_research'),
            data=json.dumps({
                'product_name': 'AMD Ryzen 7 9700X',
                'category_id': self.cpu_cat.id,
                'brand_name': 'AMD',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body['available'])
        self.assertEqual(body['status'], 'unavailable')
        self.assertIn('manually', body['summary_note'].lower())
        self.assertEqual(Product.objects.count(), before_count)

    @override_settings(AI_PROVIDER='openai', AI_API_KEY='fake-key-for-mock-test')
    def test_valid_ai_output_validates_schema_strips_forbidden_fields_and_requires_approval(self):
        mock_payload = {
            'proposed_specs': {
                'socket': 'AM5',
                'tdp_watts': 65,
                'cores': 8,
                'threads': 16,
                'supported_memory_types': ['DDR5'],
                # Forbidden and unknown fields injected to test strict filtering:
                'sku': 'HACK-SKU',
                'price': 99999,
                'status': 'published',
                'made_up_spec': 'quantum_bus',
            },
            'custom_specs': {'L3 Cache': '32 MB', 'cost_price': '5000'},
            'sources': [
                {'url': 'https://www.amd.com/en/products/processors/desktops/ryzen/9000-series/amd-ryzen-7-9700x.html', 'title': 'AMD Official'},
                {'url': 'https://www.techpowerup.com/cpu-specs/ryzen-7-9700x.c3650', 'title': 'TechPowerUp'},
            ],
            'missing_fields': ['boost_clock_ghz'],
            'conflicting_fields': [
                {'field': 'max_power_watts', 'values': ['88', '142'], 'note': 'Default 88W PPT vs PBO 142W'},
            ],
            'confidence': 'high',
            'summary_note': 'Verified Zen 4/5 AM5 specifications.',
        }

        with patch.object(AIProviderClient, 'send_json_prompt', return_value=mock_payload):
            before_count = Product.objects.count()
            resp = self.client.post(
                reverse('management:api_ai_research'),
                data=json.dumps({
                    'product_name': 'AMD Ryzen 7 9700X',
                    'category_id': self.cpu_cat.id,
                    'brand_name': 'AMD',
                    'model_number': '100-100001404WOF',
                }),
                content_type='application/json',
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['available'])
        self.assertEqual(data['status'], 'draft')
        self.assertEqual(Product.objects.count(), before_count)  # Never auto-creates Product

        # Forbidden fields stripped & recorded
        self.assertEqual(data['proposed_specs']['socket'], 'AM5')
        self.assertEqual(data['proposed_specs']['tdp_watts'], 65)
        self.assertNotIn('sku', data['proposed_specs'])
        self.assertNotIn('price', data['proposed_specs'])
        self.assertNotIn('status', data['proposed_specs'])
        self.assertNotIn('made_up_spec', data['proposed_specs'])
        self.assertNotIn('cost_price', data['custom_specs'])
        # Conflicting field held out of auto-apply
        self.assertNotIn('max_power_watts', data['proposed_specs'])
        self.assertEqual(len(data['conflicting_fields']), 1)
        self.assertTrue(len(data['rejected_fields']) >= 4)

        # Manufacturer vs third-party attribution verified
        origins = {s['origin_type'] for s in data['sources']}
        self.assertEqual(origins, {'manufacturer', 'third_party'})

        # Cannot persist draft without explicit approval checkbox
        draft_id = data['draft_id']
        unapproved = self.client.post(
            reverse('management:product_create'),
            data={
                'name': 'AMD Ryzen 7 9700X',
                'sku': 'CPU-9700X',
                'category': self.cpu_cat.id,
                'brand': self.brand.id,
                'status': Product.STATUS_DRAFT,
                'price': '32000.00',
                'warranty_months': '36',
                'ai_draft_id': str(draft_id),
                'spec_socket': 'AM5',
                'spec_tdp_watts': '65',
            },
        )
        self.assertEqual(unapproved.status_code, 200)
        self.assertFalse(Product.objects.filter(sku='CPU-9700X').exists())

        # With explicit approval checkbox -> saves product and marks draft approved
        approved = self.client.post(
            reverse('management:product_create'),
            data={
                'name': 'AMD Ryzen 7 9700X',
                'sku': 'CPU-9700X',
                'category': self.cpu_cat.id,
                'brand': self.brand.id,
                'status': Product.STATUS_DRAFT,
                'price': '32000.00',
                'warranty_months': '36',
                'ai_draft_id': str(draft_id),
                'confirm_ai_approval': '1',
                'spec_socket': 'AM5',
                'spec_tdp_watts': '65',
            },
        )
        self.assertEqual(approved.status_code, 302)
        draft = AIResearchDraft.objects.get(pk=draft_id)
        self.assertEqual(draft.status, AIResearchDraft.STATUS_APPROVED)
        self.assertEqual(draft.approved_by, self.manager)

    @override_settings(AI_PROVIDER='openai', AI_API_KEY='fake-key-for-mock-test')
    def test_missing_sources_flagged_unverified_and_ssrf_url_blocked(self):
        # Missing sources downgrades verification_status to unverified
        with patch.object(AIProviderClient, 'send_json_prompt', return_value={
            'proposed_specs': {'socket': 'AM5'},
            'sources': [],
            'confidence': 'high',
        }):
            resp = self.client.post(
                reverse('management:api_ai_research'),
                data=json.dumps({'product_name': 'Ryzen 5 7600', 'category_id': self.cpu_cat.id}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['verification_status'], 'unverified')
        self.assertEqual(body['confidence'], 'low')

        # Private/loopback reference URL rejected safely
        ssrf_resp = self.client.post(
            reverse('management:api_ai_research'),
            data=json.dumps({
                'product_name': 'Ryzen 5 7600',
                'category_id': self.cpu_cat.id,
                'reference_url': 'http://127.0.0.1:8080/internal-admin',
            }),
            content_type='application/json',
        )
        self.assertEqual(ssrf_resp.status_code, 200)
        self.assertFalse(ssrf_resp.json()['available'])

    @override_settings(AI_PROVIDER='none', AI_API_KEY='', AI_RESEARCH_RATE_LIMIT_PER_HOUR=2)
    def test_hourly_rate_limit_enforced_with_429(self):
        payload = json.dumps({'product_name': 'Ryzen 5 7600', 'category_id': self.cpu_cat.id})
        r1 = self.client.post(reverse('management:api_ai_research'), data=payload, content_type='application/json')
        r2 = self.client.post(reverse('management:api_ai_research'), data=payload, content_type='application/json')
        r3 = self.client.post(reverse('management:api_ai_research'), data=payload, content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 429)
        self.assertTrue(r3.json()['rate_limited'])

    @override_settings(AI_PROVIDER='openai', AI_API_KEY='fake-key-for-mock-test')
    def test_unit_suffix_igpu_normalization_and_exact_with_optional_suggestions(self):
        mock_payload = {
            'match_status': 'exact',
            'identified_name': 'Intel Core i7-14700K',
            'suggested_corrections': [
                {'name': 'Intel Core i7-14700KF', 'reason': 'Variant without integrated graphics'},
            ],
            'proposed_specs': {
                'socket': 'FCLGA1700',
                'cpu_family': 'Core 14th Gen',
                'cores': 20,
                'threads': 28,
                'base_clock_ghz': '3.4 GHz',
                'boost_clock_ghz': '5.6 GHz',
                'tdp_watts': '125 W',
                'max_power_watts': '253 W',
                'integrated_graphics': 'Intel UHD Graphics 770',
                'includes_stock_cooler': False,
                'supported_memory_types': 'Up to DDR5 5600 MT/s, Up to DDR4 3200 MT/s',
                'performance_tier': 'High-End',
            },
            'sources': [
                {'url': 'https://www.intel.com/content/www/us/en/products/sku/236783/specs.html', 'title': 'Intel ARK'}
            ],
            'confidence': 'high',
            'summary_note': 'Verified Intel Core i7-14700K specs.',
        }
        with patch.object(AIProviderClient, 'send_json_prompt', return_value=mock_payload):
            resp = self.client.post(
                reverse('management:api_ai_research'),
                data=json.dumps({'product_name': 'Intel Core i7-14700K', 'category_id': self.cpu_cat.id, 'brand_name': 'Intel'}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['match_status'], 'exact')
        specs = data['proposed_specs']
        self.assertEqual(specs['socket'], 'LGA1700')
        self.assertEqual(specs['cpu_family'], 'Intel 14th Gen')
        self.assertEqual(specs['tdp_watts'], 125)
        self.assertEqual(specs['max_power_watts'], 253)
        self.assertEqual(specs['base_clock_ghz'], '3.4')
        self.assertTrue(specs['integrated_graphics'])
        self.assertEqual(specs['igpu_name'], 'Intel UHD Graphics 770')
        self.assertEqual(specs['supported_memory_types'], ['DDR4', 'DDR5'])
        self.assertEqual(specs['performance_tier'], 'high')

    @override_settings(AI_PROVIDER='none', AI_API_KEY='')
    def test_unconfigured_provider_extracts_specs_from_public_reference_url(self):
        sample_extract = (
            'Page Title | Intel Core i7-14700K Processor\n'
            'Sockets Supported | FCLGA1700\n'
            'Total Cores | 20\n'
            'Total Threads | 28\n'
            'Max Turbo Frequency | 5.6 GHz\n'
            'Processor Base Power | 125 W\n'
            'Maximum Turbo Power | 253 W\n'
            'Max Memory Size | 192 GB\n'
            'Memory Types | Up to DDR5 5600 MT/s, Up to DDR4 3200 MT/s\n'
            'Processor Graphics | Intel UHD Graphics 770\n'
        )
        with patch.object(WebSearchClient, 'fetch_page_extract', return_value=sample_extract):
            resp = self.client.post(
                reverse('management:api_ai_research'),
                data=json.dumps({
                    'product_name': 'Intel Core i7-14700K',
                    'category_id': self.cpu_cat.id,
                    'brand_name': 'Intel',
                    'reference_url': 'https://www.intel.com/content/www/us/en/products/sku/236783/specifications.html',
                }),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['available'])
        self.assertEqual(data['match_status'], 'exact')
        self.assertEqual(data['verification_status'], 'verified_manufacturer')
        self.assertEqual(data['proposed_specs']['socket'], 'LGA1700')
        self.assertEqual(data['proposed_specs']['cpu_family'], 'Intel 14th Gen')
        self.assertEqual(data['proposed_specs']['cores'], 20)
        self.assertEqual(data['proposed_specs']['tdp_watts'], 125)
        self.assertEqual(data['proposed_specs']['max_power_watts'], 253)
        self.assertTrue(data['proposed_specs']['integrated_graphics'])
