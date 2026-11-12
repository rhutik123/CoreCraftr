import json
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from store.models import (
    Brand,
    Cart,
    CartItem,
    Category,
    Customer,
    HardwareSpecProfile,
    Inventory,
    Order,
    Product,
    ProductSpecification,
    WishlistItem,
)
from store.services.comparison_service import build_comparison_matrix


def _create_product(
    name: str,
    category: Category,
    brand: Brand,
    price: str,
    qty: int = 5,
    digital: bool = False,
    **spec_kwargs,
) -> Product:
    slug_base = name.lower().replace(' ', '-').replace('+', 'plus').replace('/', '-')
    product = Product.objects.create(
        name=name,
        slug=f'{slug_base}-{Product.objects.count() + 1}',
        sku=f'SKU-TST-{Product.objects.count() + 1}',
        category=category,
        brand=brand,
        price=Decimal(price),
        digital=digital,
        is_active=True,
        spec_verified=True,
    )
    Inventory.objects.update_or_create(product=product, defaults={'quantity': qty, 'reserved_quantity': 0})
    if spec_kwargs:
        HardwareSpecProfile.objects.update_or_create(product=product, defaults=spec_kwargs)
    return product


class StorefrontAndCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat_cpu = Category.objects.create(
            name='CPU / Processors',
            slug='cpu-processors',
            component_slot='cpu',
            is_pc_component=True,
        )
        cls.cat_gpu = Category.objects.create(
            name='Graphics Cards',
            slug='graphics-cards',
            component_slot='gpu',
            is_pc_component=True,
        )
        cls.brand_amd = Brand.objects.create(name='AMD', slug='amd')
        cls.brand_nvidia = Brand.objects.create(name='NVIDIA', slug='nvidia')

        cls.cpu_1 = _create_product(
            'AMD Ryzen 5 7600',
            cls.cat_cpu,
            cls.brand_amd,
            '18500.00',
            qty=4,
            socket='AM5',
            memory_type='DDR5',
            tdp_watts=65,
        )
        cls.cpu_2 = _create_product(
            'AMD Ryzen 5 5600',
            cls.cat_cpu,
            cls.brand_amd,
            '11500.00',
            qty=0,
            socket='AM4',
            memory_type='DDR4',
            tdp_watts=65,
        )
        cls.gpu_1 = _create_product(
            'NVIDIA GeForce RTX 4060',
            cls.cat_gpu,
            cls.brand_nvidia,
            '29999.00',
            qty=3,
            gpu_chipset='RTX 4060',
        )
        ProductSpecification.objects.create(
            product=cls.cpu_1,
            spec_group='Architecture',
            spec_key='Socket',
            spec_value='AM5',
        )
        ProductSpecification.objects.create(
            product=cls.cpu_2,
            spec_group='Architecture',
            spec_key='Socket',
            spec_value='AM4',
        )

    def test_guest_can_browse_storefront_pages(self):
        for route in [
            reverse('home'),
            reverse('store'),
            reverse('category_detail', kwargs={'slug': self.cat_cpu.slug}),
            reverse('detail', kwargs={'pk': self.cpu_1.pk}),
            reverse('compare'),
            reverse('cart'),
        ]:
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200, f'Route {route} failed for guest user')

    def test_store_search_filters_and_sorting(self):
        resp = self.client.get(reverse('store'), {'q': '7600'})
        self.assertContains(resp, 'AMD Ryzen 5 7600')
        self.assertNotContains(resp, 'AMD Ryzen 5 5600')

        resp_stock = self.client.get(reverse('store'), {'category': self.cat_cpu.slug, 'in_stock': '1'})
        self.assertContains(resp_stock, 'AMD Ryzen 5 7600')
        self.assertNotContains(resp_stock, 'AMD Ryzen 5 5600')

        resp_socket = self.client.get(reverse('store'), {'socket': 'AM4'})
        self.assertContains(resp_socket, 'AMD Ryzen 5 5600')
        self.assertNotContains(resp_socket, 'AMD Ryzen 5 7600')

        resp_sort = self.client.get(reverse('store'), {'sort': 'price_desc'})
        items = list(resp_sort.context['products'])
        self.assertEqual(items[0].id, self.gpu_1.id)

    def test_product_comparison_category_switch_and_limit(self):
        self.client.post(reverse('toggle_compare', kwargs={'pk': self.cpu_1.pk}))
        self.client.post(reverse('toggle_compare', kwargs={'pk': self.cpu_2.pk}))
        resp = self.client.get(reverse('compare'))
        self.assertContains(resp, 'AMD Ryzen 5 7600')
        self.assertContains(resp, 'AMD Ryzen 5 5600')

        matrix = build_comparison_matrix([self.cpu_1, self.cpu_2])
        self.assertTrue(matrix['same_category'])
        socket_row = next(r for r in matrix['rows'] if r['label'] == 'Socket')
        self.assertTrue(socket_row['differs'])

        # Adding a GPU resets compare session cleanly to the new category
        self.client.post(reverse('toggle_compare', kwargs={'pk': self.gpu_1.pk}))
        self.assertEqual(self.client.session['compare_product_ids'], [self.gpu_1.pk])

        self.client.post(reverse('clear_compare'))
        self.assertEqual(self.client.session['compare_product_ids'], [])

    def test_comparison_matrix_includes_hardware_spec_profile(self):
        brand_intel = Brand.objects.create(name='Intel', slug='intel')
        portal_cpu_1 = _create_product(
            'Intel Core i7-14700K',
            self.cat_cpu,
            brand_intel,
            '35000.00',
            qty=5,
            socket='LGA1700',
            cpu_family='Intel 14th Gen',
            cores=20,
            threads=28,
            base_clock_ghz='3.40',
            boost_clock_ghz='5.60',
            tdp_watts=125,
            includes_stock_cooler=False,
            supported_memory_types=['DDR4', 'DDR5'],
        )
        portal_cpu_2 = _create_product(
            'Intel Core i5-14600K',
            self.cat_cpu,
            brand_intel,
            '27500.00',
            qty=4,
            socket='LGA1700',
            cpu_family='Intel 14th Gen',
            cores=14,
            threads=20,
            base_clock_ghz='3.50',
            boost_clock_ghz='5.30',
            tdp_watts=125,
            includes_stock_cooler=False,
            supported_memory_types=['DDR4', 'DDR5'],
        )
        ProductSpecification.objects.create(
            product=self.cpu_1,
            spec_group='Architecture',
            spec_key='Cores / Threads',
            spec_value='6C / 12T',
        )

        # Seeded vs portal-created product fills custom spec keys from HardwareSpecProfile
        mixed = build_comparison_matrix([self.cpu_1, portal_cpu_1])
        rows_by_label = {r['label']: r for r in mixed['rows']}
        self.assertEqual(rows_by_label['Socket']['values'], ['AM5', 'LGA1700'])
        self.assertTrue(rows_by_label['Socket']['differs'])
        self.assertEqual(rows_by_label['Cores / Threads']['values'], ['6C / 12T', '20 Cores / 28 Threads'])
        self.assertEqual(rows_by_label['TDP']['values'], ['65 W', '125 W'])

        # Two portal-created products with zero ProductSpecification rows compare via schema fields
        portal_only = build_comparison_matrix([portal_cpu_1, portal_cpu_2])
        portal_rows = {r['label']: r for r in portal_only['rows']}
        self.assertEqual(portal_rows['Socket']['values'], ['LGA1700', 'LGA1700'])
        self.assertFalse(portal_rows['Socket']['differs'])
        self.assertEqual(portal_rows['Cores']['values'], ['20', '14'])
        self.assertTrue(portal_rows['Cores']['differs'])
        self.assertEqual(portal_rows['Includes Stock Cooler']['values'], ['No', 'No'])


class CartCheckoutSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Category.objects.create(name='SSDs', slug='ssd-storage', component_slot='storage', is_pc_component=True)
        cls.brand = Brand.objects.create(name='WD', slug='wd')
        cls.ssd_expensive = _create_product('WD Black SN850X 1TB', cls.cat, cls.brand, '8500.00', qty=3)
        cls.ssd_cheap = _create_product('WD Green SN350 500GB', cls.cat, cls.brand, '2900.00', qty=2)

    def setUp(self):
        self.user_a = User.objects.create_user(username='alice', email='alice@example.com', password='StrongPass123!')
        self.cust_a = self.user_a.customer
        self.user_b = User.objects.create_user(username='bob', email='bob@example.com', password='StrongPass123!')
        self.cust_b = self.user_b.customer

    def test_cart_stock_validation_and_session_merge_on_login(self):
        # Guest adds 2 items of ssd_cheap (max stock 2)
        resp1 = self.client.post(
            reverse('update_item'),
            data=json.dumps({'productID': self.ssd_cheap.id, 'action': 'add'}),
            content_type='application/json',
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()['cart_total_items'], 1)

        resp2 = self.client.post(
            reverse('update_item'),
            data=json.dumps({'productID': self.ssd_cheap.id, 'action': 'add'}),
            content_type='application/json',
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()['item_quantity'], 2)

        # Exceeding stock (3rd item) must be rejected cleanly
        resp3 = self.client.post(
            reverse('update_item'),
            data=json.dumps({'productID': self.ssd_cheap.id, 'action': 'add'}),
            content_type='application/json',
        )
        self.assertEqual(resp3.status_code, 400)
        self.assertFalse(resp3.json()['success'])

        # Log in as Alice -> guest cart merges into Alice's persistent Cart
        login_resp = self.client.post(reverse('login'), {'username': 'alice', 'password': 'StrongPass123!'})
        self.assertEqual(login_resp.status_code, 302)
        alice_cart = Cart.objects.get(user=self.user_a)
        item = CartItem.objects.get(cart=alice_cart, product=self.ssd_cheap)
        self.assertEqual(item.quantity, 2)

    def test_server_side_checkout_pricing_atomic_stock_and_idor_protection(self):
        self.client.force_login(self.user_a)
        # Add 1x ssd_cheap (2900.00 < 5000 free shipping threshold -> +199.00 shipping = 3099.00)
        self.client.post(
            reverse('update_item'),
            data=json.dumps({'productID': self.ssd_cheap.id, 'action': 'add'}),
            content_type='application/json',
        )

        # Attempt to tamper price/total via legacy process_order payload
        payload = {
            'form': {
                'name': 'Alice Gamer',
                'email': 'alice@example.com',
                'phone': '9876543210',
                'total': '1.00',  # malicious client override must be ignored
                'payment_method': 'upi_demo',
            },
            'shipping': {
                'address': '42 MG Road',
                'city': 'Bengaluru',
                'state': 'Karnataka',
                'zipcode': '560001',
                'country': 'India',
            },
        }
        resp = self.client.post(reverse('process_order'), data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['total_amount'], '3099.00')

        # Inventory decremented atomically from 2 -> 1, Cart cleared
        self.ssd_cheap.inventory.refresh_from_db()
        self.assertEqual(self.ssd_cheap.inventory.quantity, 1)
        alice_cart = Cart.objects.get(user=self.user_a)
        self.assertEqual(alice_cart.items.count(), 0)

        order = Order.objects.get(order_number=data['order_number'])
        self.assertEqual(order.subtotal_amount, Decimal('2900.00'))
        self.assertEqual(order.shipping_amount, Decimal('199.00'))
        self.assertEqual(order.total_amount, Decimal('3099.00'))
        self.assertEqual(order.payment_status, 'paid_demo')

        # Owner can view receipt
        own_receipt = self.client.get(reverse('order_confirmation', kwargs={'order_number': order.order_number}))
        self.assertEqual(own_receipt.status_code, 200)

        # Another logged-in user (Bob) must get 404 (IDOR protection)
        other_client = Client()
        other_client.force_login(self.user_b)
        bob_receipt = other_client.get(reverse('order_confirmation', kwargs={'order_number': order.order_number}))
        self.assertEqual(bob_receipt.status_code, 404)

    def test_checkout_rejects_insufficient_stock_without_corrupting_inventory(self):
        self.client.force_login(self.user_a)
        self.client.post(
            reverse('update_item'),
            data=json.dumps({'productID': self.ssd_expensive.id, 'action': 'set', 'quantity': 2}),
            content_type='application/json',
        )
        # Simulate another buyer reducing stock to 1 before Alice checks out
        self.ssd_expensive.inventory.quantity = 1
        self.ssd_expensive.inventory.save()

        resp = self.client.post(
            reverse('checkout'),
            {
                'customer_name': 'Alice',
                'customer_email': 'alice@example.com',
                'customer_phone': '9999999999',
                'address': 'Street 1',
                'city': 'Pune',
                'state': 'MH',
                'zipcode': '411001',
                'country': 'India',
                'payment_method': 'cod_demo',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.ssd_expensive.inventory.refresh_from_db()
        self.assertEqual(self.ssd_expensive.inventory.quantity, 1)
        self.assertEqual(Order.objects.count(), 0)

    def test_wishlist_and_registration_flow(self):
        # Register new user
        reg_resp = self.client.post(
            reverse('register'),
            {
                'username': 'charlie_pc',
                'email': 'charlie@example.com',
                'first_name': 'Charlie',
                'password1': 'ComplexPass987!',
                'password2': 'ComplexPass987!',
            },
        )
        self.assertEqual(reg_resp.status_code, 302)
        charlie = User.objects.get(username='charlie_pc')
        self.assertTrue(Customer.objects.filter(user=charlie).exists())

        # Wishlist requires authentication
        anon_wish = self.client.post(reverse('toggle_wishlist', kwargs={'pk': self.ssd_expensive.pk}))
        self.assertEqual(anon_wish.status_code, 302)
        self.assertIn('/login/', anon_wish.url)

        self.client.force_login(charlie)
        wish_resp = self.client.post(
            reverse('toggle_wishlist', kwargs={'pk': self.ssd_expensive.pk}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(wish_resp.status_code, 200)
        self.assertTrue(wish_resp.json()['added'])
        self.assertTrue(WishlistItem.objects.filter(user=charlie, product=self.ssd_expensive).exists())

        # Profile, wishlist page, order history, password reset page smoke render
        for route in [reverse('profile'), reverse('wishlist'), reverse('order_history'), reverse('reset_password')]:
            r = self.client.get(route)
            self.assertEqual(r.status_code, 200, f'Account page {route} failed')
