import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from ai_engine.services.recommender import AIProviderClient
from ai_engine.services.spec_researcher import WebSearchClient
from management.models import AIResearchDraft
from store.models import Category, Product


User = get_user_model()


class AISpecResearchWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser(
            username='ai_wf_owner',
            email='ai_wf_owner@corecraftr.local',
            password='Password123!',
        )
        cls.cpu_cat = Category.objects.create(
            name='CPUs & Processors',
            slug='processors',
            component_slot='cpu',
            is_pc_component=True,
            is_active=True,
        )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)

    def test_product_create_ui_integrates_ai_research_into_identity_section(self):
        resp = self.client.get(reverse('management:product_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Research Specifications with AI')
        self.assertContains(resp, 'id="id_ai_reference_url"')
        self.assertContains(resp, 'id="btn-ai-research"')
        # Old disconnected Section 4 title must no longer exist
        self.assertNotContains(resp, '4. AI Product Specification Research')

    @override_settings(AI_PROVIDER='openai', AI_API_KEY='test-key', AI_SEARCH_PROVIDER='tavily', AI_SEARCH_API_KEY='test-search')
    def test_exact_match_uses_web_search_prioritizing_manufacturer_and_returns_field_statuses(self):
        snippets = [
            {
                'url': 'https://www.techpowerup.com/cpu-specs/ryzen-5-7600x.c2849',
                'title': 'TechPowerUp Ryzen 5 7600X',
                'snippet': '6 cores, AM5, 105W TDP.',
            },
            {
                'url': 'https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-5-7600x.html',
                'title': 'AMD Ryzen 5 7600X Official Specs',
                'snippet': 'Socket AM5, 6 Cores, 12 Threads, 4.7 GHz base, 105W TDP, DDR5.',
            },
        ]
        mock_ai = {
            'match_status': 'exact',
            'identified_name': 'AMD Ryzen 5 7600X',
            'proposed_specs': {
                'socket': 'AM5',
                'cpu_family': 'Ryzen 7000',
                'cores': 6,
                'threads': 12,
                'tdp_watts': 105,
                'max_power_watts': 142,
                'integrated_graphics': True,
                'includes_stock_cooler': False,
                'supported_memory_types': ['DDR5'],
                'price': 99999,  # Must still be stripped!
            },
            'sources': [
                {
                    'url': 'https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-5-7600x.html',
                    'title': 'AMD Official Specifications',
                }
            ],
            'missing_fields': ['pcie_version'],
            'conflicting_fields': [],
            'confidence': 'high',
            'summary_note': 'Specs sourced from AMD official processor page.',
        }

        with (
            patch.object(WebSearchClient, 'search', return_value=snippets),
            patch.object(WebSearchClient, 'fetch_page_extract', return_value='Official AM5 6-core processor') as mock_fetch,
            patch.object(AIProviderClient, 'send_json_prompt', return_value=mock_ai) as mock_prompt,
        ):
            resp = self.client.post(
                reverse('management:api_ai_research'),
                data=json.dumps({
                    'product_name': 'AMD Ryzen 5 7600X',
                    'category_id': self.cpu_cat.id,
                    'brand_name': 'AMD',
                    'model_number': '100-100000593WOF',
                }),
                content_type='application/json',
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['match_status'], 'exact')
        self.assertEqual(data['identified_name'], 'AMD Ryzen 5 7600X')
        self.assertEqual(data['verification_status'], 'verified_manufacturer')
        self.assertEqual(data['proposed_specs']['socket'], 'AM5')
        self.assertNotIn('price', data['proposed_specs'])
        self.assertTrue(any('price' in r.lower() for r in data['rejected_fields']))
        self.assertEqual(data['field_statuses']['socket'], 'sourced')
        self.assertEqual(data['field_statuses']['pcie_version'], 'not_found')
        # Manufacturer domain prioritized first so fetch_page_extract fetched amd.com!
        mock_fetch.assert_called_once()
        self.assertIn('amd.com', mock_fetch.call_args[0][0])
        prompt_payload = json.loads(mock_prompt.call_args[0][1])
        self.assertIn('amd.com', prompt_payload['web_search_results'][0]['url'])

    @override_settings(AI_PROVIDER='openai', AI_API_KEY='test-key')
    def test_typo_or_ambiguous_query_asks_confirmation_before_applying(self):
        mock_ambiguous = {
            'match_status': 'ambiguous',
            'identified_name': 'AMD Ryzen 5 7600X',
            'suggested_corrections': [
                {
                    'name': 'AMD Ryzen 5 7600X',
                    'brand': 'AMD',
                    'reason': 'Possible misspelling of "Ryzan" -> "Ryzen".',
                    'url': 'https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-5-7600x.html',
                }
            ],
            'proposed_specs': {'socket': 'AM5', 'cores': 6},
            'sources': [
                {
                    'url': 'https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-5-7600x.html',
                    'title': 'AMD Ryzen 5 7600X',
                }
            ],
            'confidence': 'medium',
            'summary_note': 'Did you mean AMD Ryzen 5 7600X?',
        }

        with patch.object(AIProviderClient, 'send_json_prompt', return_value=mock_ambiguous):
            resp = self.client.post(
                reverse('management:api_ai_research'),
                data=json.dumps({
                    'product_name': 'AMD Ryzan 5 7600X',
                    'category_id': self.cpu_cat.id,
                    'brand_name': 'AMD',
                }),
                content_type='application/json',
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['match_status'], 'ambiguous')
        # Specs are NOT blindly populated before confirmation!
        self.assertEqual(data['proposed_specs'], {})
        self.assertEqual(data['suggested_corrections'][0]['name'], 'AMD Ryzen 5 7600X')

        # Re-running after staff explicitly confirms exact product name unlocks researched specs
        mock_confirmed = dict(mock_ambiguous, match_status='exact')
        with patch.object(AIProviderClient, 'send_json_prompt', return_value=mock_confirmed):
            confirmed_resp = self.client.post(
                reverse('management:api_ai_research'),
                data=json.dumps({
                    'product_name': 'AMD Ryzen 5 7600X',
                    'category_id': self.cpu_cat.id,
                    'brand_name': 'AMD',
                    'confirmed_match': True,
                }),
                content_type='application/json',
            )
        self.assertEqual(confirmed_resp.status_code, 200)
        confirmed_data = confirmed_resp.json()
        self.assertEqual(confirmed_data['match_status'], 'exact')
        self.assertEqual(confirmed_data['proposed_specs']['socket'], 'AM5')

    @override_settings(AI_PROVIDER='openai', AI_API_KEY='test-key')
    def test_not_found_product_reports_not_confidently_identified_and_allows_manual_creation(self):
        mock_not_found = {
            'match_status': 'not_found',
            'proposed_specs': {},
            'sources': [],
            'missing_fields': ['socket', 'cores', 'tdp_watts'],
            'confidence': 'low',
            'summary_note': 'No reliable product datasheet matches "Quantum Flux 9999X".',
        }

        with patch.object(AIProviderClient, 'send_json_prompt', return_value=mock_not_found):
            resp = self.client.post(
                reverse('management:api_ai_research'),
                data=json.dumps({
                    'product_name': 'Quantum Flux 9999X',
                    'category_id': self.cpu_cat.id,
                }),
                content_type='application/json',
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['match_status'], 'not_found')
        self.assertEqual(data['proposed_specs'], {})
        self.assertIn('Product not confidently identified.', data['summary_note'])
        self.assertEqual(Product.objects.count(), 0)

        # Staff can still create product manually without AI approval blocking
        save_resp = self.client.post(
            reverse('management:product_create'),
            {
                'name': 'Custom Embedded Controller',
                'sku': 'CUSTOM-CPU-01',
                'category': str(self.cpu_cat.id),
                'status': Product.STATUS_DRAFT,
                'price': '12500.00',
                'warranty_months': '36',
                'initial_quantity': '4',
                'low_stock_threshold': '2',
                'spec_socket': 'AM4',
                'spec_cores': '4',
                'spec_tdp_watts': '45',
                'spec_performance_tier': 'entry',
            },
            follow=True,
        )
        self.assertEqual(save_resp.status_code, 200)
        saved = Product.objects.get(sku='CUSTOM-CPU-01')
        self.assertEqual(saved.spec_profile.socket, 'AM4')
        self.assertEqual(saved.spec_profile.cores, 4)

    @override_settings(AI_PROVIDER='openai', AI_API_KEY='test-key')
    def test_third_party_only_sources_are_not_marked_manufacturer_verified(self):
        mock_third_party = {
            'match_status': 'exact',
            'identified_name': 'Some Third Party Hardware',
            'proposed_specs': {
                'socket': 'AM5',
                'cpu_family': 'Ryzen 7000',
                'cores': 8,
                'threads': 16,
                'tdp_watts': 120,
                'max_power_watts': 162,
                'integrated_graphics': True,
                'includes_stock_cooler': False,
                'supported_memory_types': ['DDR5'],
            },
            'sources': [
                {
                    'url': 'https://example-forum.org/specs/hardware-review',
                    'title': 'Community Forum Review',
                }
            ],
            'confidence': 'medium',
            'summary_note': 'Retrieved from community forum benchmark.',
        }
        with patch.object(AIProviderClient, 'send_json_prompt', return_value=mock_third_party):
            resp = self.client.post(
                reverse('management:api_ai_research'),
                data=json.dumps({
                    'product_name': 'Some Third Party Hardware',
                    'category_id': self.cpu_cat.id,
                }),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotEqual(data['verification_status'], 'verified_manufacturer')
        self.assertEqual(data['verification_status'], 'mixed_sources')
        self.assertEqual(data['field_statuses']['socket'], 'needs_verification')
