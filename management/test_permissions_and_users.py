import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from management.models import AuditLog
from management.permissions import (
    INVENTORY_MANAGER_GROUP_NAME,
    can_access_portal,
    ensure_portal_roles,
    is_inventory_manager,
    is_owner,
)
from store.models import Category, Inventory, Product

User = get_user_model()


class PortalPermissionsAndUsersTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            name='Processors', slug='processors', component_slot='cpu', is_pc_component=True
        )
        cls.owner = User.objects.create_superuser(
            username='portal_owner', email='owner@corecraftr.local', password='OwnerPass!123'
        )
        cls.manager = User.objects.create_user(
            username='inv_manager', email='manager@corecraftr.local', password='ManagerPass!123'
        )
        group = ensure_portal_roles()
        cls.manager.groups.add(group)

        cls.customer = User.objects.create_user(
            username='normal_customer', email='cust@corecraftr.local', password='CustPass!123'
        )
        cls.product = Product.objects.create(
            name='Ryzen Test CPU',
            sku='CPU-TEST-001',
            category=cls.category,
            price='19999.00',
            status=Product.STATUS_PUBLISHED,
        )
        Inventory.objects.create(product=cls.product, quantity=5, low_stock_threshold=2)

    def test_role_helpers_identify_owner_manager_customer(self):
        self.assertTrue(is_owner(self.owner))
        self.assertTrue(can_access_portal(self.owner))
        self.assertFalse(is_inventory_manager(self.owner))

        self.assertTrue(is_inventory_manager(self.manager))
        self.assertTrue(can_access_portal(self.manager))
        self.assertFalse(is_owner(self.manager))

        self.assertFalse(can_access_portal(self.customer))
        self.assertFalse(is_owner(self.customer))
        self.assertFalse(is_inventory_manager(self.customer))

    def test_anonymous_redirected_on_html_and_401_on_api(self):
        protected_urls = [
            reverse('management:dashboard'),
            reverse('management:product_list'),
            reverse('management:product_create'),
            reverse('management:inventory_list'),
            reverse('management:stock_history'),
            reverse('management:import_export'),
            reverse('management:export_csv'),
            reverse('management:reports'),
            reverse('management:user_management'),
            reverse('management:audit_log'),
        ]
        for url in protected_urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, f'Expected login redirect for {url}')
            self.assertIn('/login/', resp['Location'])

        api_urls = [
            ('GET', reverse('management:api_spec_schema', args=[self.category.id])),
            ('GET', reverse('management:api_duplicate_check')),
            ('POST', reverse('management:api_ai_research')),
        ]
        for method, url in api_urls:
            resp = self.client.get(url) if method == 'GET' else self.client.post(url, data='{}', content_type='application/json')
            self.assertEqual(resp.status_code, 401, f'Expected 401 JSON for anonymous {url}')

    def test_customer_gets_403_across_all_portal_and_api_routes(self):
        self.client.force_login(self.customer)
        portal_gets = [
            reverse('management:dashboard'),
            reverse('management:product_list'),
            reverse('management:product_create'),
            reverse('management:product_edit', args=[self.product.id]),
            reverse('management:inventory_list'),
            reverse('management:stock_history'),
            reverse('management:import_export'),
            reverse('management:export_csv'),
            reverse('management:reports'),
            reverse('management:user_management'),
            reverse('management:audit_log'),
            reverse('management:api_spec_schema', args=[self.category.id]),
            reverse('management:api_duplicate_check'),
        ]
        for url in portal_gets:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 403, f'Customer should receive 403 on {url}')

        portal_posts = [
            reverse('management:product_change_status', args=[self.product.id]),
            reverse('management:inventory_adjust', args=[self.product.id]),
            reverse('management:user_management_action'),
            reverse('management:api_ai_research'),
        ]
        for url in portal_posts:
            resp = self.client.post(url, data={'action': 'grant_manager', 'user_id': self.customer.id})
            self.assertEqual(resp.status_code, 403, f'Customer should receive 403 on POST {url}')

    def test_inventory_manager_access_and_owner_only_restriction(self):
        self.client.force_login(self.manager)

        # Allowed views
        for url in [
            reverse('management:dashboard'),
            reverse('management:product_list'),
            reverse('management:product_create'),
            reverse('management:inventory_list'),
            reverse('management:stock_history'),
            reverse('management:import_export'),
            reverse('management:reports'),
        ]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f'Manager should access {url}')

        # Owner-only screens and Django admin blocked for Inventory Manager
        self.assertEqual(self.client.get(reverse('management:user_management')).status_code, 403)
        self.assertEqual(self.client.get(reverse('management:audit_log')).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse('management:user_management_action'),
                data={'action': 'grant_manager', 'user_id': self.customer.id},
            ).status_code,
            403,
        )
        admin_resp = self.client.get('/admin/')
        self.assertIn(admin_resp.status_code, (302, 403))

    def test_owner_can_grant_revoke_create_and_last_superuser_protected(self):
        self.client.force_login(self.owner)

        self.assertEqual(self.client.get(reverse('management:user_management')).status_code, 200)
        self.assertEqual(self.client.get(reverse('management:audit_log')).status_code, 200)

        # Grant manager role to customer
        resp = self.client.post(
            reverse('management:user_management_action'),
            data={'action': 'grant_manager', 'user_id': self.customer.id},
        )
        self.assertEqual(resp.status_code, 302)
        fresh_customer = User.objects.get(pk=self.customer.id)
        self.assertTrue(fresh_customer.groups.filter(name=INVENTORY_MANAGER_GROUP_NAME).exists())
        self.assertFalse(fresh_customer.is_staff)
        self.assertFalse(fresh_customer.is_superuser)
        self.assertTrue(AuditLog.objects.filter(action='user.role_granted', target_label=fresh_customer.username).exists())

        # Revoke manager role
        self.client.post(
            reverse('management:user_management_action'),
            data={'action': 'revoke_manager', 'user_id': self.customer.id},
        )
        fresh_customer.refresh_from_db()
        self.assertFalse(can_access_portal(fresh_customer))
        self.assertTrue(AuditLog.objects.filter(action='user.role_revoked', target_label=fresh_customer.username).exists())

        # Owner cannot deactivate self / last active superuser
        self.client.post(
            reverse('management:user_management_action'),
            data={'action': 'deactivate', 'user_id': self.owner.id},
        )
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertTrue(self.owner.is_superuser)

        # Create a new Inventory Manager account
        self.client.post(
            reverse('management:user_management_action'),
            data={
                'action': 'create_manager',
                'username': 'new_mgr_01',
                'email': 'newmgr@corecraftr.local',
                'first_name': 'New',
                'last_name': 'Manager',
                'password': 'StrongPortalPass!999',
                'confirm_password': 'StrongPortalPass!999',
            },
        )
        created = User.objects.get(username='new_mgr_01')
        self.assertTrue(is_inventory_manager(created))
        self.assertFalse(created.is_superuser)
        self.assertFalse(created.is_staff)

    def test_storefront_navbar_hides_portal_link_from_customers(self):
        # Customer does not see portal link
        self.client.force_login(self.customer)
        cust_home = self.client.get(reverse('home')).content.decode('utf-8')
        self.assertNotIn('/management/', cust_home)

        # Inventory manager sees portal link
        self.client.force_login(self.manager)
        mgr_home = self.client.get(reverse('home')).content.decode('utf-8')
        self.assertIn('/management/', mgr_home)
