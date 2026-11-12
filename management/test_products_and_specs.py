import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from management.models import AuditLog, PriceChangeLog
from management.permissions import ensure_portal_roles
from store.models import Brand, Category, HardwareSpecProfile, Inventory, Product, ProductImage, ProductSpecification

User = get_user_model()
_TEMP_MEDIA_DIR = tempfile.mkdtemp(prefix='corecraftr_test_media_')


def _make_test_image_bytes(fmt='PNG', color=(25, 110, 210), size=(64, 64)) -> bytes:
    buf = BytesIO()
    img = Image.new('RGB', size, color=color)
    img.save(buf, format=fmt)
    return buf.getvalue()


@override_settings(MEDIA_ROOT=_TEMP_MEDIA_DIR)
class PortalProductsAndSpecsTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TEMP_MEDIA_DIR, ignore_errors=True)
    @classmethod
    def setUpTestData(cls):
        cls.cpu_cat = Category.objects.create(
            name='Processors', slug='processors', component_slot='cpu', is_pc_component=True
        )
        cls.mobo_cat = Category.objects.create(
            name='Motherboards', slug='motherboards', component_slot='motherboard', is_pc_component=True
        )
        cls.amd = Brand.objects.create(name='AMD', slug='amd')
        cls.manager = User.objects.create_user(
            username='catalog_mgr', email='catmgr@corecraftr.local', password='MgrPass!123'
        )
        group = ensure_portal_roles()
        cls.manager.groups.add(group)

    def setUp(self):
        self.client.force_login(self.manager)

    def test_create_draft_product_with_category_specs_hides_from_store_until_published(self):
        png_bytes = _make_test_image_bytes('PNG')
        upload = SimpleUploadedFile('ryzen.png', png_bytes, content_type='image/png')

        resp = self.client.post(
            reverse('management:product_create'),
            data={
                'name': 'AMD Ryzen 5 7600X',
                'sku': 'CPU-R5-7600X',
                'model_number': '100-100000593WOF',
                'category': self.cpu_cat.id,
                'brand': self.amd.id,
                'status': Product.STATUS_DRAFT,
                'price': '21500.00',
                'cost_price': '18200.00',
                'warranty_months': '36',
                'short_description': '6-core Zen 4 desktop CPU.',
                'initial_quantity': '7',
                'low_stock_threshold': '2',
                'spec_socket': 'AM5',
                'spec_cpu_family': 'Ryzen 7000',
                'spec_cores': '6',
                'spec_tdp_watts': '105',
                'spec_boost_clock_ghz': '',  # left blank -> None (unknown)
                'spec_supported_memory_types': 'DDR5',
                'spec_integrated_graphics': 'true',
                'spec_performance_tier': 'midrange',
                'custom_spec_group[]': ['Architecture'],
                'custom_spec_key[]': ['Process Node'],
                'custom_spec_value[]': ['5'],
                'custom_spec_unit[]': ['nm'],
                'gallery_images': [upload],
            },
        )
        self.assertEqual(resp.status_code, 302)

        prod = Product.objects.get(sku='CPU-R5-7600X')
        self.assertEqual(prod.status, Product.STATUS_DRAFT)
        self.assertFalse(prod.is_active)
        self.assertEqual(prod.created_by, self.manager)
        self.assertEqual(prod.spec_profile.socket, 'AM5')
        self.assertEqual(prod.spec_profile.tdp_watts, 105)
        self.assertIsNone(prod.spec_profile.boost_clock_ghz)  # unknown remains None
        self.assertEqual(prod.spec_profile.supported_memory_types, ['DDR5'])
        self.assertEqual(prod.inventory.quantity, 7)
        self.assertEqual(prod.gallery_images.count(), 1)
        self.assertTrue(prod.gallery_images.first().is_primary)
        self.assertTrue(ProductSpecification.objects.filter(product=prod, spec_key='Process Node').exists())
        self.assertTrue(PriceChangeLog.objects.filter(product=prod, new_price='21500.00').exists())
        self.assertTrue(AuditLog.objects.filter(action='product.created', target_id=str(prod.id)).exists())

        # Draft product MUST NOT appear on public store or detail page
        self.client.logout()
        store_resp = self.client.get(reverse('store'))
        self.assertNotIn('CPU-R5-7600X', store_resp.content.decode('utf-8'))
        self.assertEqual(self.client.get(reverse('detail', args=[prod.id])).status_code, 404)

        # Publish as manager -> visible publicly
        self.client.force_login(self.manager)
        self.client.post(
            reverse('management:product_change_status', args=[prod.id]),
            data={'status': Product.STATUS_PUBLISHED},
        )
        prod.refresh_from_db()
        self.assertEqual(prod.status, Product.STATUS_PUBLISHED)
        self.assertTrue(prod.is_active)

        self.client.logout()
        self.assertEqual(self.client.get(reverse('detail', args=[prod.id])).status_code, 200)

        # Archive -> hidden from storefront again
        self.client.force_login(self.manager)
        self.client.post(
            reverse('management:product_change_status', args=[prod.id]),
            data={'status': Product.STATUS_ARCHIVED},
        )
        prod.refresh_from_db()
        self.assertFalse(prod.is_active)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('detail', args=[prod.id])).status_code, 404)

    def test_duplicate_sku_rejected_and_advisory_duplicate_check_works(self):
        existing = Product.objects.create(
            name='Gigabyte B760M DS3H',
            sku='MOBO-GB-B760M',
            model_number='B760M-DS3H-DDR4',
            category=self.mobo_cat,
            price='12400.00',
            status=Product.STATUS_PUBLISHED,
        )
        Inventory.objects.create(product=existing, quantity=4)

        # Advisory duplicate lookup JSON
        dup_resp = self.client.get(
            reverse('management:api_duplicate_check'),
            data={'sku': 'mobo-gb-b760m', 'model_number': 'B760M-DS3H-DDR4'},
        )
        self.assertEqual(dup_resp.status_code, 200)
        matches = dup_resp.json()['matches']
        self.assertTrue(any(m['id'] == existing.id for m in matches))

        # Creating with exact duplicate SKU fails gracefully
        resp = self.client.post(
            reverse('management:product_create'),
            data={
                'name': 'Gigabyte B760M Duplicate',
                'sku': 'MOBO-GB-B760M',
                'category': self.mobo_cat.id,
                'status': Product.STATUS_DRAFT,
                'price': '12500.00',
                'warranty_months': '36',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Product.objects.filter(sku='MOBO-GB-B760M').count(), 1)

    def test_image_validation_rejects_svg_and_oversized_and_gallery_actions_work(self):
        prod = Product.objects.create(
            name='Gallery Test CPU',
            sku='CPU-GAL-01',
            category=self.cpu_cat,
            price='15000.00',
            status=Product.STATUS_PUBLISHED,
        )
        Inventory.objects.create(product=prod, quantity=3)

        # Reject fake SVG disguised as PNG
        fake_svg = SimpleUploadedFile('evil.png', b'<svg><script>alert(1)</script></svg>', content_type='image/png')
        self.client.post(
            reverse('management:product_edit', args=[prod.id]),
            data={
                'name': prod.name,
                'sku': prod.sku,
                'category': self.cpu_cat.id,
                'status': Product.STATUS_PUBLISHED,
                'price': '15000.00',
                'warranty_months': '36',
                'gallery_images': [fake_svg],
            },
        )
        self.assertEqual(prod.gallery_images.count(), 0)

        # Reject oversized file
        with override_settings(PRODUCT_IMAGE_MAX_BYTES=64):
            large_png = SimpleUploadedFile('big.png', _make_test_image_bytes('PNG', size=(300, 300)), content_type='image/png')
            self.client.post(
                reverse('management:product_edit', args=[prod.id]),
                data={
                    'name': prod.name,
                    'sku': prod.sku,
                    'category': self.cpu_cat.id,
                    'status': Product.STATUS_PUBLISHED,
                    'price': '15000.00',
                    'warranty_months': '36',
                    'gallery_images': [large_png],
                },
            )
            self.assertEqual(prod.gallery_images.count(), 0)

        # Upload 2 valid images (PNG & WEBP)
        img1 = SimpleUploadedFile('one.png', _make_test_image_bytes('PNG'), content_type='image/png')
        img2 = SimpleUploadedFile('two.webp', _make_test_image_bytes('WEBP', color=(200, 30, 30)), content_type='image/webp')
        self.client.post(
            reverse('management:product_edit', args=[prod.id]),
            data={
                'name': prod.name,
                'sku': prod.sku,
                'category': self.cpu_cat.id,
                'status': Product.STATUS_PUBLISHED,
                'price': '15000.00',
                'warranty_months': '36',
                'gallery_images': [img1, img2],
            },
        )
        imgs = list(prod.gallery_images.order_by('id'))
        self.assertEqual(len(imgs), 2)
        self.assertTrue(imgs[0].is_primary)
        self.assertFalse(imgs[1].is_primary)

        # Set second image as primary
        self.client.post(reverse('management:product_image_set_primary', args=[prod.id, imgs[1].id]))
        imgs[1].refresh_from_db()
        imgs[0].refresh_from_db()
        self.assertTrue(imgs[1].is_primary)
        self.assertFalse(imgs[0].is_primary)

        # Delete current primary -> auto-promotes remaining image
        self.client.post(reverse('management:product_image_delete', args=[prod.id, imgs[1].id]))
        self.assertEqual(prod.gallery_images.count(), 1)
        self.assertTrue(prod.gallery_images.first().is_primary)

    def test_manual_product_save_not_blocked_by_ai_input_and_verifies_complete_specs(self):
        get_resp = self.client.get(reverse('management:product_create'))
        self.assertEqual(get_resp.status_code, 200)
        html = get_resp.content.decode('utf-8')
        self.assertIn('id="id_ai_reference_url"', html)
        self.assertIn('type="text"', html)
        self.assertNotIn('<input type="url" id="id_ai_reference_url"', html)

        # Complete manual Intel CPU entry (without running AI draft workflow) should save and mark spec_verified=True
        resp = self.client.post(
            reverse('management:product_create'),
            data={
                'name': 'Intel Core i7-14700K',
                'sku': 'CPU-INT-14700K-MAN',
                'model_number': 'BX8071514700K',
                'category': self.cpu_cat.id,
                'new_brand_name': 'Intel',
                'status': Product.STATUS_PUBLISHED,
                'price': '35999.00',
                'warranty_months': '36',
                'initial_quantity': '5',
                'low_stock_threshold': '2',
                'spec_socket': 'LGA1700',
                'spec_cpu_family': 'Intel 14th Gen',
                'spec_cores': '20',
                'spec_threads': '28',
                'spec_tdp_watts': '125',
                'spec_max_power_watts': '253',
                'spec_integrated_graphics': 'true',
                'spec_includes_stock_cooler': 'false',
                'spec_supported_memory_types': 'DDR4, DDR5',
                'spec_performance_tier': 'high',
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        cpu = Product.objects.get(sku='CPU-INT-14700K-MAN')
        self.assertTrue(cpu.spec_verified)
        self.assertTrue(cpu.is_active)

        # Minimal CPU entry missing critical compatibility fields stays spec_verified=False
        resp_min = self.client.post(
            reverse('management:product_create'),
            data={
                'name': 'Incomplete Mystery CPU',
                'sku': 'CPU-INC-01',
                'category': self.cpu_cat.id,
                'status': Product.STATUS_DRAFT,
                'price': '9999.00',
                'warranty_months': '12',
                'initial_quantity': '1',
                'low_stock_threshold': '1',
            },
            follow=True,
        )
        self.assertEqual(resp_min.status_code, 200)
        incomplete = Product.objects.get(sku='CPU-INC-01')
        self.assertFalse(incomplete.spec_verified)
