from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from store.models import Category, Product


class CoreCraftrBrandingAndIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_hardware_catalog')
        cls.user = User.objects.create_user(
            username='brandtester',
            email='brandtester@example.com',
            password='StrongPassword123!',
        )
        cls.cpu = Product.objects.filter(category__component_slot='cpu', is_active=True).first()
        cls.cat = Category.objects.filter(show_in_nav=True).first()

    def test_django_package_renamed_to_corecraftr(self):
        self.assertEqual(settings.SETTINGS_MODULE, 'corecraftr.settings')
        self.assertEqual(settings.ROOT_URLCONF, 'corecraftr.urls')
        self.assertEqual(settings.WSGI_APPLICATION, 'corecraftr.wsgi.application')
        self.assertEqual(settings.ASGI_APPLICATION, 'corecraftr.asgi.application')
        self.assertIn('corecraftr', settings.DEFAULT_FROM_EMAIL)

    def test_public_pages_use_corecraftr_branding_without_hardwarehub(self):
        urls = [
            reverse('home'),
            reverse('store'),
            reverse('compare'),
            reverse('cart'),
            reverse('pc_builder'),
            reverse('login'),
            reverse('register'),
            reverse('reset_password'),
            reverse('detail', kwargs={'pk': self.cpu.id}),
        ]
        if self.cat:
            urls.append(reverse('category_detail', kwargs={'slug': self.cat.slug}))

        client = Client()
        for url in urls:
            resp = client.get(url)
            self.assertEqual(resp.status_code, 200, f'Failed GET {url}')
            html = resp.content.decode('utf-8')
            self.assertIn('CoreCraftr', html, f'Missing CoreCraftr on {url}')
            self.assertNotIn('HardwareHub', html, f'Found stale HardwareHub on {url}')

        home_html = client.get(reverse('home')).content.decode('utf-8')
        self.assertIn('Build Smarter. Build Better.', home_html)

    def test_authenticated_pages_and_admin_use_corecraftr_branding(self):
        client = Client()
        logged_in = client.login(username='brandtester', password='StrongPassword123!')
        self.assertTrue(logged_in)

        for url in [
            reverse('profile'),
            reverse('wishlist'),
            reverse('order_history'),
            reverse('builder_saved_list'),
        ]:
            resp = client.get(url)
            self.assertEqual(resp.status_code, 200, f'Failed auth GET {url}')
            html = resp.content.decode('utf-8')
            self.assertIn('CoreCraftr', html)
            self.assertNotIn('HardwareHub', html)

        admin_login = client.get('/admin/login/')
        self.assertEqual(admin_login.status_code, 200)
        admin_html = admin_login.content.decode('utf-8')
        self.assertIn('CoreCraftr Administration', admin_html)

    def test_email_and_error_templates_branded_for_corecraftr(self):
        subj = render_to_string('store/reset_subject.txt').strip()
        self.assertEqual(subj, 'CoreCraftr — Password Reset Request')

        email_body = render_to_string(
            'store/reset_email.txt',
            {
                'user': self.user,
                'protocol': 'https',
                'domain': 'example.com',
                'uid': 'MQ',
                'token': 'abc-token',
            },
        )
        self.assertIn('CoreCraftr', email_body)
        self.assertIn('Build Smarter. Build Better.', email_body)
        self.assertNotIn('HardwareHub', email_body)

        err_500 = render_to_string('500.html')
        self.assertIn('CoreCraftr', err_500)
        self.assertIn('Build Smarter. Build Better.', err_500)

        req_resp = self.client.get('/definitely-nonexistent-page-404/')
        self.assertEqual(req_resp.status_code, 404)
        self.assertIn('CoreCraftr', req_resp.content.decode('utf-8'))
