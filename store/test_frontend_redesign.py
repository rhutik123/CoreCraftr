import os
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from store.models import Category, Product


FORBIDDEN_BOOTSTRAP_PATTERNS = [
    re.compile(r'cdn\.jsdelivr\.net/npm/bootstrap', re.I),
    re.compile(r'bootstrap(?:\.bundle)?(?:\.min)?\.(?:css|js)', re.I),
    re.compile(r'cdn\.tailwindcss\.com', re.I),
    re.compile(r'data-bs-[a-z-]+'),
    re.compile(r'class=["\'][^"\']*\bbi-[a-z0-9-]+'),
    re.compile(r'(?:main|management|neo)\.css'),
]


class FrontendRedesignRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_hardware_catalog')
        cls.customer = User.objects.create_user(
            username='uitestcustomer',
            email='uicustomer@example.com',
            password='StrongPassword123!',
        )
        cls.owner = User.objects.create_superuser(
            username='uitestowner',
            email='uiowner@example.com',
            password='StrongPassword123!',
        )
        cls.cpu = Product.objects.filter(category__component_slot='cpu', is_active=True).first()
        cls.category = Category.objects.filter(show_in_nav=True).first()

    def _assert_modern_ui_shell(
        self,
        html: str,
        label: str,
        *,
        require_switcher: bool = True,
        require_lucide_js: bool = True,
    ):
        self.assertIn('css/app.min.css', html, f'Missing compiled Tailwind CSS on {label}')
        self.assertIn('corecraftr-theme', html, f'Missing persisted theme key on {label}')
        if require_lucide_js:
            self.assertIn('vendor/lucide.min.js', html, f'Missing local Lucide bundle on {label}')
            self.assertIn('js/theme.js', html, f'Missing theme script on {label}')
            self.assertIn('data-lucide=', html, f'Missing Lucide icons on {label}')
        if require_switcher:
            self.assertIn('data-theme-choice="dark"', html, f'Missing dark theme switcher choice on {label}')
            self.assertIn('data-theme-choice="light"', html, f'Missing light theme switcher choice on {label}')
            self.assertIn('data-theme-choice="system"', html, f'Missing system theme switcher choice on {label}')

        for pattern in FORBIDDEN_BOOTSTRAP_PATTERNS:
            match = pattern.search(html)
            self.assertIsNone(
                match,
                f'Unexpected legacy frontend reference "{match.group(0) if match else ""}" on {label}',
            )

    def test_compiled_static_assets_present_and_legacy_css_removed(self):
        static_dir = os.path.join(settings.BASE_DIR, 'static')
        app_css = os.path.join(static_dir, 'css', 'app.min.css')
        lucide_js = os.path.join(static_dir, 'vendor', 'lucide.min.js')
        theme_js = os.path.join(static_dir, 'js', 'theme.js')

        self.assertTrue(os.path.isfile(app_css))
        self.assertGreater(os.path.getsize(app_css), 10240)
        self.assertTrue(os.path.isfile(lucide_js))
        self.assertTrue(os.path.isfile(theme_js))

        for legacy_name in ('main.css', 'management.css', 'neo.css'):
            self.assertFalse(
                os.path.exists(os.path.join(static_dir, 'css', legacy_name)),
                f'Legacy unused stylesheet static/css/{legacy_name} should be removed',
            )

    def test_storefront_and_pc_builder_views_use_tailwind_and_lucide_only(self):
        client = Client()
        # Populate cart so checkout page renders directly
        add_resp = client.post(
            reverse('update_item'),
            data=f'{{"productID": {self.cpu.id}, "action": "add"}}',
            content_type='application/json',
        )
        self.assertEqual(add_resp.status_code, 200)

        public_urls = [
            reverse('home'),
            reverse('store'),
            reverse('detail', kwargs={'pk': self.cpu.id}),
            reverse('compare'),
            reverse('cart'),
            reverse('checkout'),
            reverse('login'),
            reverse('register'),
            reverse('reset_password'),
            reverse('pc_builder'),
            reverse('builder_select_slot', kwargs={'slot': 'cpu'}),
        ]
        if self.category:
            public_urls.append(reverse('category_detail', kwargs={'slug': self.category.slug}))

        for url in public_urls:
            resp = client.get(url)
            self.assertEqual(resp.status_code, 200, f'Expected 200 OK for {url}')
            self._assert_modern_ui_shell(resp.content.decode('utf-8'), url)

        # Verify switching PC Builder to Expert Mode renders redesigned Expert layout cleanly
        switch_resp = client.post(
            reverse('builder_switch_mode'),
            data={'mode': 'expert'},
            follow=True,
        )
        self.assertEqual(switch_resp.status_code, 200)
        expert_html = switch_resp.content.decode('utf-8')
        self._assert_modern_ui_shell(expert_html, 'pc_builder[expert]')
        self.assertIn('+ Choose CPU', expert_html)

    def test_authenticated_customer_and_error_templates_use_tailwind_and_lucide(self):
        client = Client()
        self.assertTrue(client.login(username='uitestcustomer', password='StrongPassword123!'))

        for url in [
            reverse('profile'),
            reverse('order_history'),
            reverse('wishlist'),
            reverse('builder_saved_list'),
        ]:
            resp = client.get(url)
            self.assertEqual(resp.status_code, 200, f'Expected 200 OK for {url}')
            self._assert_modern_ui_shell(resp.content.decode('utf-8'), url)

        forbidden_resp = client.get(reverse('management:dashboard'))
        self.assertEqual(forbidden_resp.status_code, 403)
        self._assert_modern_ui_shell(forbidden_resp.content.decode('utf-8'), '403')

        not_found_resp = client.get('/no-such-page-ui-check/')
        self.assertEqual(not_found_resp.status_code, 404)
        self._assert_modern_ui_shell(not_found_resp.content.decode('utf-8'), '404')

        rendered_500 = render_to_string('500.html')
        self._assert_modern_ui_shell(
            rendered_500,
            '500.html',
            require_switcher=False,
            require_lucide_js=False,
        )

    def test_management_portal_views_render_redesigned_sidebar_and_theme(self):
        client = Client()
        self.assertTrue(client.login(username='uitestowner', password='StrongPassword123!'))

        portal_urls = [
            reverse('management:dashboard'),
            reverse('management:product_list'),
            reverse('management:product_create'),
            reverse('management:product_edit', kwargs={'product_id': self.cpu.id}),
            reverse('management:inventory_list'),
            reverse('management:stock_history'),
            reverse('management:import_export'),
            reverse('management:reports'),
            reverse('management:user_management'),
            reverse('management:audit_log'),
        ]

        for url in portal_urls:
            resp = client.get(url)
            self.assertEqual(resp.status_code, 200, f'Expected 200 OK for {url}')
            html = resp.content.decode('utf-8')
            self._assert_modern_ui_shell(html, url)
            self.assertIn('Owner Portal', html)
            self.assertIn('data-drawer-open="portal-nav-drawer"', html)
