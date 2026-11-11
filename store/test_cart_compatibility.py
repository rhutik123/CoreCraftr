import re
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from ai_engine.services.recommender import AIProviderClient
from pc_builder.services.compatibility import CompatibilityEngine
from store.models import (
    Brand,
    Cart,
    CartItem,
    Category,
    HardwareSpecProfile,
    Inventory,
    Order,
    Product,
)
from store.services.cart_compatibility import CartCompatibilityService
from store.templatetags.store_extras import format_inr


class CartCompatibilityAndCheckoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_hardware_catalog')
        cls.ryzen_5600 = Product.objects.get(name='AMD Ryzen 5 5600')
        cls.b760m_ddr4 = Product.objects.get(name='Gigabyte B760M DS3H DDR4')
        cls.ryzen_7600 = Product.objects.filter(
            category__component_slot='cpu',
            spec_profile__socket='AM5',
            spec_profile__integrated_graphics=True,
            is_active=True,
            inventory__quantity__gt=0,
        ).first()
        cls.am5_mobo = Product.objects.filter(
            category__component_slot='motherboard',
            spec_profile__socket='AM5',
            is_active=True,
            inventory__quantity__gt=0,
        ).first()
        cls.am4_mobo = Product.objects.filter(
            category__component_slot='motherboard',
            spec_profile__socket='AM4',
            is_active=True,
            inventory__quantity__gt=0,
        ).first()
        cls.mouse = Product.objects.filter(category__component_slot='mouse', is_active=True).first()

        cls.cat_mobo = Category.objects.get(component_slot='motherboard')
        cls.brand_msi = Brand.objects.first()

    def _add_to_client_cart(self, client: Client, *products: Product):
        # Ensure session exists and populate cart via /update_item/
        for product in products:
            resp = client.post(
                reverse('update_item'),
                data=f'{{"productID": {product.id}, "action": "add"}}',
                content_type='application/json',
            )
            self.assertEqual(resp.status_code, 200)

    def test_incompatible_ryzen_5600_and_b760m_shows_full_warning_and_directions(self):
        client = Client()
        self._add_to_client_cart(client, self.ryzen_5600, self.b760m_ddr4)

        response = client.get(reverse('cart'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        self.assertIn('PC BUILD COMPATIBILITY CHECK', html)
        self.assertIn('Incompatible components detected.', html)
        self.assertIn('Your CPU and motherboard are incompatible.', html)
        self.assertIn('AMD Ryzen 5 5600', html)
        self.assertIn('Gigabyte B760M DS3H DDR4', html)
        self.assertIn('AM4', html)
        self.assertIn('LGA1700', html)
        self.assertIn('Beginner Guide', html)
        self.assertIn('Expert Spec Detail', html)
        self.assertIn('₹10,799.00', html)
        self.assertIn('₹11,499.00', html)

        # Ensure checkout button is NOT disabled
        checkout_match = re.search(rf'<a\s+[^>]*href="{re.escape(reverse("checkout"))}"[^>]*>', html)
        self.assertIsNotNone(checkout_match)
        self.assertNotIn('disabled', checkout_match.group(0))

        # Verify both Direction A (AM4 boards) and Direction B (LGA1700 CPUs) are DB-verified & compatible
        compat = response.context['compat']
        self.assertTrue(compat.has_incompatibility)
        cpu_mobo_issue = next(i for i in compat.detailed_issues if i.rule_code == 'CPU_MOBO_SOCKET_MISMATCH')
        dir_a = next(
            d for d in cpu_mobo_issue.fix_directions
            if d.keep_slot == 'cpu' and d.target_slot == 'motherboard'
        )
        dir_b = next(
            d for d in cpu_mobo_issue.fix_directions
            if d.keep_slot == 'motherboard' and d.target_slot == 'cpu'
        )

        am4_replacements = dir_a.replacements
        self.assertGreater(len(am4_replacements), 0)
        for rep in am4_replacements:
            self.assertEqual(rep.product.spec_profile.socket, 'AM4')
            self.assertGreater(rep.product.stock_quantity, 0)

        lga1700_replacements = dir_b.replacements
        self.assertGreater(len(lga1700_replacements), 0)
        for rep in lga1700_replacements:
            self.assertEqual(rep.product.spec_profile.socket, 'LGA1700')
            self.assertGreater(rep.product.stock_quantity, 0)

    def test_compatible_cart_reports_all_verified_components_compatible(self):
        self.assertIsNotNone(self.ryzen_7600)
        self.assertIsNotNone(self.am5_mobo)
        client = Client()
        self._add_to_client_cart(client, self.ryzen_7600, self.am5_mobo)

        response = client.get(reverse('cart'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        compat = response.context['compat']

        self.assertTrue(compat.is_applicable)
        self.assertTrue(compat.is_all_compatible)
        self.assertFalse(compat.has_incompatibility)
        self.assertIn('All verified components are compatible.', html)

    def test_single_component_or_peripheral_only_not_treated_as_full_build_conflict(self):
        client = Client()
        if self.mouse:
            self._add_to_client_cart(client, self.ryzen_5600, self.mouse)
        else:
            self._add_to_client_cart(client, self.ryzen_5600)

        response = client.get(reverse('cart'))
        self.assertEqual(response.status_code, 200)
        compat = response.context['compat']
        self.assertFalse(compat.is_applicable)
        self.assertNotIn('PC BUILD COMPATIBILITY CHECK', response.content.decode('utf-8'))

    def test_unknown_specs_report_unknown_and_never_claim_all_compatible(self):
        unverified_mobo = Product.objects.create(
            name='Mystery Unverified Motherboard',
            slug='mystery-unverified-mobo-test',
            sku='SKU-UNV-MOBO-1',
            category=self.cat_mobo,
            brand=self.brand_msi,
            price=Decimal('9999.00'),
            is_active=True,
            spec_verified=False,
        )
        Inventory.objects.create(product=unverified_mobo, quantity=5, reserved_quantity=0)

        client = Client()
        self._add_to_client_cart(client, self.ryzen_7600, unverified_mobo)
        response = client.get(reverse('cart'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        compat = response.context['compat']

        self.assertTrue(compat.is_applicable)
        self.assertEqual(compat.status, 'unknown')
        self.assertFalse(compat.is_all_compatible)
        self.assertIn('Some specifications are unknown.', html)
        self.assertNotIn('All verified components are compatible.', html)

    def test_checkout_requires_explicit_acknowledgement_when_incompatible_then_records_on_order(self):
        client = Client()
        self._add_to_client_cart(client, self.ryzen_5600, self.b760m_ddr4)

        # GET checkout renders warning, acknowledgement checkbox, and enabled submit button
        get_resp = client.get(reverse('checkout'))
        self.assertEqual(get_resp.status_code, 200)
        get_html = get_resp.content.decode('utf-8')
        self.assertIn('I understand that some selected components may not work together.', get_html)
        self.assertIn('Incompatible components detected.', get_html)

        submit_match = re.search(r'<button[^>]*type="submit"[^>]*>\s*Place Order \(Demo\)', get_html)
        self.assertIsNotNone(submit_match)
        self.assertNotIn('disabled', submit_match.group(0))

        base_payload = {
            'customer_name': 'Aarav Sharma',
            'customer_email': 'aarav@example.com',
            'customer_phone': '9876543210',
            'address': '42 MG Road',
            'city': 'Bengaluru',
            'state': 'Karnataka',
            'zipcode': '560001',
            'country': 'India',
            'payment_method': 'cod_demo',
            'notes': 'Keep parts anyway',
        }

        # POST without acknowledgement -> validation error, NO order created
        post_unacked = client.post(reverse('checkout'), data=base_payload)
        self.assertEqual(post_unacked.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)
        self.assertTrue(post_unacked.context['form'].errors.get('acknowledge_incompatibility'))

        # POST with acknowledgement -> Order succeeds and saves compatibility metadata
        acked_payload = dict(base_payload, acknowledge_incompatibility='on')
        post_acked = client.post(reverse('checkout'), data=acked_payload)
        self.assertEqual(post_acked.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)

        order = Order.objects.first()
        self.assertEqual(order.compatibility_status, 'incompatible')
        self.assertTrue(order.incompatibility_acknowledged)
        self.assertIsNotNone(order.incompatibility_acknowledged_at)
        self.assertTrue(order.compatibility_summary.get('checked'))
        self.assertEqual(order.compatibility_summary['issues'][0]['rule_code'], 'CPU_MOBO_SOCKET_MISMATCH')

        conf_resp = client.get(reverse('order_confirmation', kwargs={'order_number': order.order_number}))
        self.assertEqual(conf_resp.status_code, 200)
        conf_html = conf_resp.content.decode('utf-8')
        self.assertIn('Incompatibility Acknowledged', conf_html)
        self.assertIn('Socket Mismatch', conf_html)
        self.assertIn('₹22,298.00', conf_html)

    def test_checkout_recalculates_compatibility_fresh_when_specs_change(self):
        temp_mobo = Product.objects.create(
            name='Temp Recheck Motherboard',
            slug='temp-recheck-mobo',
            sku='SKU-RECHECK-1',
            category=self.cat_mobo,
            brand=self.brand_msi,
            price=Decimal('12000.00'),
            is_active=True,
            spec_verified=True,
        )
        Inventory.objects.create(product=temp_mobo, quantity=4, reserved_quantity=0)
        am5_spec = self.am5_mobo.spec_profile
        spec = HardwareSpecProfile.objects.create(
            product=temp_mobo,
            socket=am5_spec.socket,
            chipset=am5_spec.chipset,
            supported_cpu_families=am5_spec.supported_cpu_families,
            memory_type=am5_spec.memory_type,
            form_factor=am5_spec.form_factor,
        )

        client = Client()
        self._add_to_client_cart(client, self.ryzen_7600, temp_mobo)

        # Initially compatible in cart
        cart_resp = client.get(reverse('cart'))
        self.assertTrue(cart_resp.context['compat'].is_all_compatible)

        # Simulate DB spec correction BEFORE checkout submission
        spec.socket = 'LGA1700'
        spec.save()

        # Checkout recalculates fresh and detects the new incompatibility
        checkout_resp = client.get(reverse('checkout'))
        self.assertTrue(checkout_resp.context['compat'].has_incompatibility)
        self.assertIn('Incompatible components detected.', checkout_resp.content.decode('utf-8'))

        # Posting without acknowledgement must now fail validation due to fresh check
        post_resp = client.post(
            reverse('checkout'),
            data={
                'customer_name': 'Fresh Check User',
                'customer_email': 'fresh@example.com',
                'customer_phone': '9876543210',
                'address': '10 Park Street',
                'city': 'Kolkata',
                'state': 'West Bengal',
                'zipcode': '700016',
                'country': 'India',
                'payment_method': 'upi_demo',
            },
        )
        self.assertEqual(post_resp.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)
        self.assertTrue(post_resp.context['form'].errors.get('acknowledge_incompatibility'))

    def test_swap_cart_item_replaces_incompatible_board_with_am4_alternative(self):
        self.assertIsNotNone(self.am4_mobo)
        client = Client()
        self._add_to_client_cart(client, self.ryzen_5600, self.b760m_ddr4)

        swap_resp = client.post(
            reverse('swap_cart_item'),
            data={'remove_product_id': self.b760m_ddr4.id, 'add_product_id': self.am4_mobo.id},
        )
        self.assertEqual(swap_resp.status_code, 302)

        cart_resp = client.get(reverse('cart'))
        self.assertEqual(cart_resp.status_code, 200)
        compat = cart_resp.context['compat']
        product_ids = {item.product_id for item in cart_resp.context['items']}
        self.assertIn(self.ryzen_5600.id, product_ids)
        self.assertIn(self.am4_mobo.id, product_ids)
        self.assertNotIn(self.b760m_ddr4.id, product_ids)
        self.assertFalse(compat.has_incompatibility)

    def test_ambiguity_notes_when_multiple_motherboards_and_peripheral_in_cart(self):
        client = Client()
        to_add = [self.ryzen_5600, self.b760m_ddr4, self.am4_mobo]
        if self.mouse:
            to_add.append(self.mouse)
        self._add_to_client_cart(client, *to_add)

        response = client.get(reverse('cart'))
        compat = response.context['compat']
        self.assertTrue(compat.is_applicable)
        joined_notes = ' '.join(compat.ambiguity_notes).lower()
        self.assertIn('multiple', joined_notes)
        if self.mouse:
            self.assertIn('peripheral', joined_notes)

    def test_cart_advisor_ai_validation_gate_rejects_bad_swaps_and_accepts_verified_ones(self):
        cart = Cart.objects.create(session_key='ai-cart-advisor-test')
        CartItem.objects.create(cart=cart, product=self.ryzen_5600, quantity=1)
        CartItem.objects.create(cart=cart, product=self.b760m_ddr4, quantity=1)

        # 1. Mocked AI suggests an AM5 board for Ryzen 5600 (AM4) -> MUST be rejected
        bad_ai = {
            'summary': 'Use an AM5 board with your AM4 CPU!',
            'directions': {
                'issue_0_A_cpu_replace_motherboard': {
                    'tip': 'Bad AI pick',
                    'recommended_ids': [self.am5_mobo.id],
                    'reasons': {str(self.am5_mobo.id): 'Newer board'},
                }
            },
        }
        with patch.object(AIProviderClient, 'is_configured', True), patch.object(
            AIProviderClient, 'send_json_prompt', return_value=bad_ai
        ):
            compat = CartCompatibilityService().evaluate_cart(cart, include_ai=True)
        self.assertTrue(compat.is_ai_fallback)
        self.assertIn('rejected', compat.advisor_notice.lower())

        # 2. Mocked AI suggests genuine in-stock AM4 board -> passes compatibility gate
        good_ai = {
            'summary': 'Your CPU uses AM4 while the board uses LGA1700. Swap one component to fix the build.',
            'directions': {
                'issue_0_A_cpu_replace_motherboard': {
                    'tip': 'Switch to a verified AM4 motherboard to keep your Ryzen 5 5600.',
                    'recommended_ids': [self.am4_mobo.id],
                    'reasons': {str(self.am4_mobo.id): 'Matches AM4 socket and DDR4 memory.'},
                }
            },
        }
        with patch.object(AIProviderClient, 'is_configured', True), patch.object(
            AIProviderClient, 'send_json_prompt', return_value=good_ai
        ):
            compat_good = CartCompatibilityService().evaluate_cart(cart, include_ai=True)
        self.assertFalse(compat_good.is_ai_fallback)
        self.assertIn('AI-Assisted', compat_good.advisor_source_label)

    def test_detail_highlights_category_specs_and_marks_missing_attributes_unknown(self):
        # Verified CPU detail shows CPU attributes in INR
        resp = self.client.get(reverse('detail', kwargs={'pk': self.ryzen_5600.id}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')
        self.assertIn('₹11,499.00', html)
        self.assertIn('AM4', html)
        self.assertIn('Specs Verified', html)

        # Product missing key attributes shows 'Unknown / Not verified' instead of fabricating values
        partial_mobo = Product.objects.create(
            name='Partial Spec Board',
            slug='partial-spec-board-test',
            sku='SKU-PARTIAL-1',
            category=self.cat_mobo,
            brand=self.brand_msi,
            price=Decimal('8499.00'),
            is_active=True,
            spec_verified=False,
        )
        Inventory.objects.create(product=partial_mobo, quantity=3, reserved_quantity=0)
        HardwareSpecProfile.objects.create(product=partial_mobo, socket='AM4')

        partial_resp = self.client.get(reverse('detail', kwargs={'pk': partial_mobo.id}))
        self.assertEqual(partial_resp.status_code, 200)
        partial_html = partial_resp.content.decode('utf-8')
        self.assertIn('Unknown / Not verified', partial_html)
        self.assertIn('₹8,499.00', partial_html)

    def test_format_inr_indian_grouping(self):
        self.assertEqual(format_inr(Decimal('10799.00')), '₹10,799.00')
        self.assertEqual(format_inr(Decimal('125000.50')), '₹1,25,000.50')
        self.assertEqual(format_inr(Decimal('999.00')), '₹999.00')
        self.assertEqual(format_inr(Decimal('1000000'), decimals=0), '₹10,00,000')
