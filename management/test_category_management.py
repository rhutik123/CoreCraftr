from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from management.models import AuditLog
from management.permissions import ensure_portal_roles
from pc_builder.models import PCBuild
from pc_builder.services.builder_service import PCBuilderService
from store.models import Brand, Category, Inventory, Product


User = get_user_model()


class CategoryManagementAndInitTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager_group = ensure_portal_roles()
        cls.owner = User.objects.create_superuser(
            username='cat_owner',
            email='cat_owner@corecraftr.local',
            password='Password123!',
        )
        cls.manager = User.objects.create_user(
            username='cat_manager',
            email='cat_manager@corecraftr.local',
            password='Password123!',
        )
        cls.manager.groups.add(cls.manager_group)
        cls.customer = User.objects.create_user(
            username='cat_customer',
            email='cat_customer@corecraftr.local',
            password='Password123!',
        )

    def test_empty_database_shows_helpful_empty_state_for_staff_and_clean_state_for_customers(self):
        self.assertEqual(Category.objects.count(), 0)

        # Guest / Customer on Home & Storefront: clean message, NO portal links exposed
        resp_guest_home = self.client.get(reverse('home'))
        self.assertEqual(resp_guest_home.status_code, 200)
        self.assertContains(resp_guest_home, 'No hardware categories have been created yet.')
        self.assertNotContains(resp_guest_home, reverse('management:category_list'))

        resp_guest_store = self.client.get(reverse('store'))
        self.assertEqual(resp_guest_store.status_code, 200)
        self.assertContains(resp_guest_store, 'No hardware categories have been created yet.')
        self.assertNotContains(resp_guest_store, reverse('management:category_list'))

        # Logged-in Customer: still no management link
        self.client.force_login(self.customer)
        resp_cust_home = self.client.get(reverse('home'))
        self.assertContains(resp_cust_home, 'No hardware categories have been created yet.')
        self.assertNotContains(resp_cust_home, reverse('management:category_list'))

        # Inventory Manager / Owner: sees direct link to Category Management
        self.client.force_login(self.manager)
        resp_staff_home = self.client.get(reverse('home'))
        self.assertContains(resp_staff_home, 'No hardware categories have been created yet.')
        self.assertContains(resp_staff_home, reverse('management:category_list'))

    def test_init_categories_is_idempotent_creates_no_products_and_preserves_owner_edits(self):
        call_command('init_categories')
        initial_count = Category.objects.count()
        self.assertGreaterEqual(initial_count, 10)
        self.assertEqual(Product.objects.count(), 0)

        # Owner edits a starter category
        processors = Category.objects.get(slug='processors')
        processors.name = 'Custom Desktop CPUs'
        processors.description = 'Owner customized description'
        processors.is_active = False
        processors.save()

        # Re-running init_categories must not duplicate or overwrite owner edits
        call_command('init_categories')
        self.assertEqual(Category.objects.count(), initial_count)
        self.assertEqual(Product.objects.count(), 0)

        processors.refresh_from_db()
        self.assertEqual(processors.name, 'Custom Desktop CPUs')
        self.assertEqual(processors.description, 'Owner customized description')
        self.assertFalse(processors.is_active)

    def test_category_portal_permissions_enforced(self):
        cat = Category.objects.create(name='Test Power', slug='test-power', component_slot='psu')
        routes_get = [
            reverse('management:category_list'),
            reverse('management:category_create'),
            reverse('management:category_edit', args=[cat.pk]),
            reverse('management:category_delete', args=[cat.pk]),
        ]
        routes_post = [
            reverse('management:category_toggle_active', args=[cat.pk]),
            reverse('management:category_init_starters'),
        ]

        # Anonymous user redirected to login
        for url in routes_get + routes_post:
            resp = self.client.get(url) if url in routes_get else self.client.post(url)
            self.assertEqual(resp.status_code, 302)
            self.assertIn('/login', resp['Location'])

        # Customer blocked with 403
        self.client.force_login(self.customer)
        for url in routes_get:
            self.assertEqual(self.client.get(url).status_code, 403)
        for url in routes_post:
            self.assertEqual(self.client.post(url).status_code, 403)

        # Inventory Manager & Owner allowed
        for staff in (self.manager, self.owner):
            self.client.force_login(staff)
            for url in routes_get:
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_category_create_validation_visibility_and_pc_builder_integration(self):
        self.client.force_login(self.manager)

        # Auto-slug creation + description + PC component mapping
        resp = self.client.post(
            reverse('management:category_create'),
            {
                'name': 'Custom Workstation CPUs',
                'slug': '',
                'component_slot': 'cpu',
                'description': 'High core count desktop processors',
                'icon_class': 'bi-cpu',
                'display_order': 1,
                'is_pc_component': 'on',
                'show_in_nav': 'on',
                'is_active': 'on',
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        cat = Category.objects.get(slug='custom-workstation-cpus')
        self.assertTrue(cat.is_active)

        # Prevent duplicate name (case-insensitive) & duplicate slug
        dup_resp = self.client.post(
            reverse('management:category_create'),
            {
                'name': 'custom workstation cpus',
                'slug': 'custom-workstation-cpus',
                'component_slot': 'cpu',
                'icon_class': 'bi-cpu',
                'display_order': 2,
                'is_active': 'on',
            },
        )
        self.assertEqual(dup_resp.status_code, 200)
        self.assertContains(dup_resp, 'already exists')
        self.assertContains(dup_resp, 'already used')
        self.assertEqual(Category.objects.filter(slug='custom-workstation-cpus').count(), 1)

        # Immediately available in Product creation, Storefront Nav, Catalogue Filter, and PC Builder
        create_page = self.client.get(reverse('management:product_create'))
        self.assertContains(create_page, 'Custom Workstation CPUs')

        store_page = self.client.get(reverse('store'))
        self.assertContains(store_page, 'Custom Workstation CPUs')

        # Add a published product under this category and confirm PC Builder slot returns it
        brand = Brand.objects.create(name='AMD', slug='amd')
        prod = Product.objects.create(
            name='Threadripper Sample',
            slug='threadripper-sample',
            sku='CPU-TR-01',
            category=cat,
            brand=brand,
            price=Decimal('55000.00'),
            status=Product.STATUS_PUBLISHED,
            is_active=True,
        )
        Inventory.objects.create(product=prod, quantity=5)
        prod.save()

        builder = PCBuilderService()
        build = PCBuild.objects.create(user=self.manager, name='WS Build')
        slot_data = builder.get_slot_candidates(build, 'cpu')
        candidate_ids = [c['product'].id for c in slot_data['candidates']]
        self.assertIn(prod.id, candidate_ids)

    def test_category_search_filter_deactivate_and_safe_delete_reassignment(self):
        self.client.force_login(self.owner)
        cat_a = Category.objects.create(
            name='NVMe Storage',
            slug='nvme-storage',
            component_slot='storage',
            is_pc_component=True,
            is_active=True,
            show_in_nav=True,
        )
        cat_b = Category.objects.create(
            name='SATA Storage',
            slug='sata-storage',
            component_slot='storage',
            is_pc_component=True,
            is_active=True,
            show_in_nav=True,
        )
        empty_cat = Category.objects.create(
            name='Empty Cables',
            slug='empty-cables',
            component_slot='accessory',
            is_pc_component=False,
            is_active=True,
        )
        prod = Product.objects.create(
            name='Gen4 1TB NVMe',
            slug='gen4-1tb-nvme',
            sku='SSD-G4-1TB',
            category=cat_a,
            price=Decimal('6999.00'),
            status=Product.STATUS_PUBLISHED,
            is_active=True,
        )

        # List shows product counts & search/filter narrows correctly
        list_resp = self.client.get(reverse('management:category_list'), {'q': 'NVMe', 'status': 'active'})
        self.assertContains(list_resp, 'NVMe Storage')
        self.assertNotContains(list_resp, 'Empty Cables')

        # Deactivating hides from storefront nav & product_create, keeps product_edit intact
        self.client.post(reverse('management:category_toggle_active', args=[cat_a.pk]))
        cat_a.refresh_from_db()
        self.assertFalse(cat_a.is_active)

        store_resp = self.client.get(reverse('store'))
        self.assertNotContains(store_resp, cat_a.slug)
        self.assertNotContains(store_resp, prod.name)

        prod_create_resp = self.client.get(reverse('management:product_create'))
        self.assertNotContains(prod_create_resp, 'NVMe Storage')
        prod_edit_resp = self.client.get(reverse('management:product_edit', args=[prod.pk]))
        self.assertContains(prod_edit_resp, 'NVMe Storage')

        # Blocking delete when category contains products
        blocked_resp = self.client.post(reverse('management:category_delete', args=[cat_a.pk]), follow=True)
        self.assertTrue(Category.objects.filter(pk=cat_a.pk).exists())
        self.assertContains(blocked_resp, 'cannot be deleted directly')

        # Safe reassignment + deletion moves product atomically and deletes source category
        reassigned_resp = self.client.post(
            reverse('management:category_delete', args=[cat_a.pk]),
            {'reassign_to': str(cat_b.pk)},
            follow=True,
        )
        self.assertFalse(Category.objects.filter(pk=cat_a.pk).exists())
        prod.refresh_from_db()
        self.assertEqual(prod.category_id, cat_b.pk)
        self.assertContains(reassigned_resp, 'Reassigned 1 product(s)')
        self.assertTrue(AuditLog.objects.filter(action='delete_category').exists())

        # Empty category deletes cleanly
        self.client.post(reverse('management:category_delete', args=[empty_cat.pk]), follow=True)
        self.assertFalse(Category.objects.filter(pk=empty_cat.pk).exists())
