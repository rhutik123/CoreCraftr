import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from store.models import Brand, Cart, Category, Customer, Inventory, Product


User = get_user_model()


class StorefrontAddToCartIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Category.objects.create(
            name='Graphics Cards',
            slug='graphics-cards',
            component_slot='gpu',
            is_pc_component=True,
            is_active=True,
        )
        cls.brand = Brand.objects.create(name='ZOTAC', slug='zotac')
        cls.product = Product.objects.create(
            name='RTX 4060 Solo 8GB',
            slug='rtx-4060-solo-8gb',
            sku='GPU-4060-SOLO',
            category=cls.cat,
            brand=cls.brand,
            price=Decimal('29999.00'),
            status=Product.STATUS_PUBLISHED,
            is_active=True,
        )
        Inventory.objects.create(product=cls.product, quantity=2, low_stock_threshold=1)

        cls.oos_product = Product.objects.create(
            name='RTX 4090 Sold Out',
            slug='rtx-4090-sold-out',
            sku='GPU-4090-OOS',
            category=cls.cat,
            brand=cls.brand,
            price=Decimal('175000.00'),
            status=Product.STATUS_PUBLISHED,
            is_active=True,
        )
        Inventory.objects.create(product=cls.oos_product, quantity=0, low_stock_threshold=1)

        cls.user = User.objects.create_user(
            username='cart_buyer',
            email='buyer@corecraftr.local',
            password='Password123!',
        )
        Customer.objects.get_or_create(
            user=cls.user,
            defaults={'name': 'Cart Buyer', 'email': 'buyer@corecraftr.local'},
        )

    def test_update_item_accepts_cart_js_payload_and_updates_counts(self):
        # Test exact JSON payload format sent by static/js/cart.js ({product_id, action})
        resp1 = self.client.post(
            reverse('update_item'),
            data=json.dumps({'product_id': str(self.product.id), 'action': 'add'}),
            content_type='application/json; charset=utf-8',
        )
        self.assertEqual(resp1.status_code, 200)
        d1 = resp1.json()
        self.assertTrue(d1['success'])
        self.assertEqual(d1['item_quantity'], 1)
        self.assertEqual(d1['cart_total_items'], 1)
        self.assertEqual(d1['cart_total'], 1)

        # Legacy camelCase productId & productID still work too
        resp2 = self.client.post(
            reverse('update_item'),
            data=json.dumps({'productId': self.product.id, 'action': 'add'}),
            content_type='application/json',
        )
        self.assertEqual(resp2.status_code, 200)
        d2 = resp2.json()
        self.assertEqual(d2['item_quantity'], 2)
        self.assertEqual(d2['cart_total_items'], 2)

        # Exceeding stock returns JSON 400 with clear stock message (not HTML / generic fallback)
        resp3 = self.client.post(
            reverse('update_item'),
            data=json.dumps({'product_id': self.product.id, 'action': 'add'}),
            content_type='application/json',
        )
        self.assertEqual(resp3.status_code, 400)
        d3 = resp3.json()
        self.assertFalse(d3['success'])
        self.assertIn('only', d3['message'].lower())

        # Decrement & remove item works cleanly
        resp_dec = self.client.post(
            reverse('update_item'),
            data=json.dumps({'product_id': self.product.id, 'action': 'remove'}),
            content_type='application/json',
        )
        self.assertEqual(resp_dec.status_code, 200)
        self.assertEqual(resp_dec.json()['cart_total_items'], 1)

        resp_del = self.client.post(
            reverse('update_item'),
            data=json.dumps({'product_id': self.product.id, 'action': 'delete'}),
            content_type='application/json',
        )
        self.assertEqual(resp_del.status_code, 200)
        self.assertEqual(resp_del.json()['cart_total_items'], 0)

    def test_out_of_stock_and_invalid_product_return_clean_json_errors(self):
        oos_resp = self.client.post(
            reverse('update_item'),
            data=json.dumps({'product_id': self.oos_product.id, 'action': 'add'}),
            content_type='application/json',
        )
        self.assertEqual(oos_resp.status_code, 400)
        self.assertFalse(oos_resp.json()['success'])
        self.assertIn('out of stock', oos_resp.json()['message'].lower())

        missing_resp = self.client.post(
            reverse('update_item'),
            data=json.dumps({'product_id': 999999, 'action': 'add'}),
            content_type='application/json',
        )
        self.assertEqual(missing_resp.status_code, 404)
        self.assertFalse(missing_resp.json()['success'])
        self.assertEqual(missing_resp.json()['message'], 'Product not found.')

    def test_guest_cart_persists_and_merges_upon_login(self):
        self.client.post(
            reverse('update_item'),
            data=json.dumps({'product_id': self.product.id, 'action': 'add'}),
            content_type='application/json',
        )
        cart_resp = self.client.get(reverse('cart'))
        self.assertEqual(cart_resp.status_code, 200)
        self.assertContains(cart_resp, self.product.name)

        login_resp = self.client.post(
            reverse('login'),
            {'username': 'cart_buyer', 'password': 'Password123!'},
        )
        self.assertEqual(login_resp.status_code, 302)

        user_cart = Cart.objects.filter(user=self.user).first()
        self.assertIsNotNone(user_cart)
        self.assertEqual(user_cart.total_items, 1)
