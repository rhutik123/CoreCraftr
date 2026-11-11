from decimal import Decimal
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from store.models import Cart, CartItem, Product
from pc_builder.models import BuildComponent, PCBuild
from pc_builder.services.alternatives import SmartAlternativesService
from pc_builder.services.builder_service import PCBuilderService
from pc_builder.services.compatibility import STATUS_INCOMPATIBLE


class PCBuilderWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_hardware_catalog')

    def setUp(self):
        self.user_a = User.objects.create_user(username='builder_alice', email='ba@example.com', password='Password123!')
        self.user_b = User.objects.create_user(username='builder_bob', email='bb@example.com', password='Password123!')

    def test_beginner_recommendation_mode_switch_preserves_build_and_expert_edits(self):
        # 1. Start in Beginner Mode and request recommendation
        resp = self.client.post(
            reverse('builder_recommend'),
            {
                'budget': '70000',
                'primary_use': 'gaming',
                'priority_preference': 'balanced',
                'upgradeability_preference': 'moderate',
                'preserve_existing': '',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('pc_builder'))

        ws_resp = self.client.get(reverse('pc_builder'))
        self.assertEqual(ws_resp.status_code, 200)
        build = ws_resp.context['build']
        self.assertEqual(build.mode, 'beginner')
        initial_count = build.component_count
        self.assertGreaterEqual(initial_count, 6)  # CPU, Mobo, RAM, GPU, Storage, PSU, Case...

        # Snapshot original component IDs
        original_cpu = build.components.get(slot='cpu').product

        # 2. Switch to Expert Mode — MUST preserve all components
        switch_resp = self.client.post(reverse('builder_switch_mode'), {'mode': 'expert'})
        self.assertEqual(switch_resp.status_code, 302)
        build.refresh_from_db()
        self.assertEqual(build.mode, 'expert')
        self.assertEqual(build.component_count, initial_count)
        self.assertEqual(build.components.get(slot='cpu').product_id, original_cpu.id)

        # 3. Manually change GPU in Expert Mode
        alt_gpu = (
            Product.objects.filter(category__component_slot='gpu', is_active=True, inventory__quantity__gt=0)
            .exclude(id=build.components.get(slot='gpu').product_id)
            .first()
        )
        self.assertIsNotNone(alt_gpu)
        self.client.post(reverse('builder_set_component'), {'slot': 'gpu', 'product_id': alt_gpu.id, 'quantity': 1})
        self.assertEqual(build.components.get(slot='gpu').product_id, alt_gpu.id)
        self.assertEqual(build.components.get(slot='cpu').product_id, original_cpu.id)

        # 4. Switch back to Beginner Mode — modified GPU and all parts remain intact!
        self.client.post(reverse('builder_switch_mode'), {'mode': 'beginner'})
        build.refresh_from_db()
        self.assertEqual(build.mode, 'beginner')
        self.assertEqual(build.components.get(slot='gpu').product_id, alt_gpu.id)
        self.assertEqual(build.components.get(slot='cpu').product_id, original_cpu.id)
        beginner_resp = self.client.get(reverse('pc_builder'))
        self.assertEqual(beginner_resp.status_code, 200)
        self.assertIsNotNone(beginner_resp.context['guidance'])

    def test_incompatible_selection_is_not_silently_deleted(self):
        am5_cpu = Product.objects.filter(category__component_slot='cpu', spec_profile__socket='AM5', is_active=True).first()
        ddr4_ram = Product.objects.filter(category__component_slot='ram', spec_profile__memory_type='DDR4', is_active=True).first()
        am5_mobo = Product.objects.filter(category__component_slot='motherboard', spec_profile__socket='AM5', is_active=True).first()

        self.client.post(reverse('builder_set_component'), {'slot': 'cpu', 'product_id': am5_cpu.id})
        self.client.post(reverse('builder_set_component'), {'slot': 'motherboard', 'product_id': am5_mobo.id})
        self.client.post(reverse('builder_set_component'), {'slot': 'ram', 'product_id': ddr4_ram.id})

        ws = self.client.get(reverse('pc_builder'))
        build = ws.context['build']
        report = ws.context['compatibility']
        # All 3 selected parts must still be present (nothing silently removed)
        self.assertEqual(build.components.count(), 3)
        self.assertEqual(report.overall_status, STATUS_INCOMPATIBLE)

        # Select slot page with only_compatible=1 filters out DDR4 for AM5 build
        select_ram = self.client.get(reverse('builder_select_slot', kwargs={'slot': 'ram'}), {'only_compatible': '1'})
        self.assertEqual(select_ram.status_code, 200)
        candidate_ids = {c['product'].id for c in select_ram.context['candidates']}
        self.assertNotIn(ddr4_ram.id, candidate_ids)

    def test_smart_alternatives_returns_compatible_options_only(self):
        am5_cpu = Product.objects.filter(category__component_slot='cpu', spec_profile__socket='AM5', is_active=True).first()
        am5_mobo = Product.objects.filter(category__component_slot='motherboard', spec_profile__socket='AM5', is_active=True).first()
        ddr5_ram = Product.objects.filter(category__component_slot='ram', spec_profile__memory_type='DDR5', is_active=True).first()

        alts = SmartAlternativesService().get_slot_alternatives(
            {'cpu': (am5_cpu, 1), 'motherboard': (am5_mobo, 1), 'ram': (ddr5_ram, 1)},
            'ram',
            ddr5_ram,
        )
        self.assertTrue(len(alts) >= 1)
        for key, item in alts.items():
            self.assertEqual(item['product'].spec_profile.memory_type, 'DDR5')

    def test_saved_builds_ownership_isolation_and_load_delete(self):
        # Guest selects CPU, signs in through real login view so guest build merges cleanly
        cpu = Product.objects.filter(category__component_slot='cpu', is_active=True).first()
        self.client.post(reverse('builder_set_component'), {'slot': 'cpu', 'product_id': cpu.id})
        login_resp = self.client.post(
            reverse('login'),
            {'username': 'builder_alice', 'password': 'Password123!'},
        )
        self.assertEqual(login_resp.status_code, 302)

        # Save named build
        save_resp = self.client.post(reverse('builder_save'), {'name': 'Alice Workstation'})
        self.assertEqual(save_resp.status_code, 302)
        saved = PCBuild.objects.get(user=self.user_a, is_saved=True, name='Alice Workstation')
        self.assertEqual(saved.components.get(slot='cpu').product_id, cpu.id)

        # Saved builds list renders cleanly
        list_resp = self.client.get(reverse('builder_saved_list'))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, 'Alice Workstation')

        # Bob cannot load or delete Alice's saved build
        bob_client = Client()
        bob_client.force_login(self.user_b)
        self.assertEqual(bob_client.post(reverse('builder_load', kwargs={'build_uuid': saved.uuid})).status_code, 404)
        self.assertEqual(bob_client.post(reverse('builder_delete', kwargs={'build_uuid': saved.uuid})).status_code, 404)

        # Alice clears workspace, loads saved build back, and verifies restoration
        self.client.post(reverse('builder_clear'))
        self.assertEqual(self.client.get(reverse('pc_builder')).context['build'].component_count, 0)
        self.client.post(reverse('builder_load', kwargs={'build_uuid': saved.uuid}))
        self.assertEqual(self.client.get(reverse('pc_builder')).context['build'].components.get(slot='cpu').product_id, cpu.id)

    def test_add_build_to_cart_and_stock_error_handling(self):
        rec_resp = self.client.post(
            reverse('builder_recommend'),
            {
                'budget': '65000',
                'primary_use': 'gaming',
                'priority_preference': 'balanced',
                'upgradeability_preference': 'moderate',
            },
        )
        self.assertEqual(rec_resp.status_code, 302)
        add_resp = self.client.post(reverse('builder_add_to_cart'))
        self.assertEqual(add_resp.status_code, 302)
        self.assertEqual(add_resp.url, reverse('cart'))

        cart_resp = self.client.get(reverse('cart'))
        self.assertEqual(cart_resp.status_code, 200)
        self.assertGreaterEqual(len(cart_resp.context['items']), 6)

        # Verify stock failure prevents partial corrupt add
        ws = self.client.get(reverse('pc_builder')).context['build']
        cpu_comp = ws.components.get(slot='cpu')
        cpu_comp.product.inventory.quantity = 0
        cpu_comp.product.inventory.save()

        new_client = Client()
        res = PCBuilderService().add_build_to_cart(ws, Cart.objects.create(session_key='stockfailtest'))
        self.assertFalse(res.success)
        self.assertEqual(CartItem.objects.filter(cart__session_key='stockfailtest').count(), 0)

    def test_drf_builder_api_endpoints(self):
        am5_cpu = Product.objects.filter(category__component_slot='cpu', spec_profile__socket='AM5', is_active=True).first()
        am5_mobo = Product.objects.filter(category__component_slot='motherboard', spec_profile__socket='AM5', is_active=True).first()
        ddr4_ram = Product.objects.filter(category__component_slot='ram', spec_profile__memory_type='DDR4', is_active=True).first()

        compat_resp = self.client.post(
            reverse('api_builder_compatibility'),
            {'slots': {'cpu': am5_cpu.id, 'motherboard': am5_mobo.id, 'ram': ddr4_ram.id}},
            content_type='application/json',
        )
        self.assertEqual(compat_resp.status_code, 200)
        self.assertEqual(compat_resp.json()['overall_status'], STATUS_INCOMPATIBLE)

        rec_resp = self.client.post(
            reverse('api_builder_recommend'),
            {'budget': 65000, 'primary_use': 'gaming'},
            content_type='application/json',
        )
        self.assertEqual(rec_resp.status_code, 200)
        rec_data = rec_resp.json()
        self.assertTrue(rec_data['success'])
        self.assertNotEqual(rec_data['compatibility']['overall_status'], STATUS_INCOMPATIBLE)

        state_resp = self.client.get(reverse('api_builder_state'))
        self.assertEqual(state_resp.status_code, 200)
        self.assertIn('compatibility', state_resp.json())
