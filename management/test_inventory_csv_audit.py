from decimal import Decimal
import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from management.models import AuditLog, CSVImportBatch, PriceChangeLog, StockMovement
from management.permissions import ensure_portal_roles
from management.services.inventory_service import get_verified_inventory_metrics, inventory_version_token
from store.models import Brand, Cart, Category, Customer, Inventory, Order, OrderItem, Product
from store.services.cart_service import update_cart_item
from store.services.order_service import create_order_from_cart

User = get_user_model()


class InventoryCSVAuditTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cpu_cat = Category.objects.create(
            name='Processors', slug='processors', component_slot='cpu', is_pc_component=True
        )
        cls.brand = Brand.objects.create(name='AMD', slug='amd')
        cls.owner = User.objects.create_superuser(
            username='audit_owner', email='owner@corecraftr.local', password='OwnerPass!123'
        )
        cls.manager = User.objects.create_user(
            username='stock_mgr', email='stockmgr@corecraftr.local', password='MgrPass!123'
        )
        group = ensure_portal_roles()
        cls.manager.groups.add(group)

        cls.shopper = User.objects.create_user(
            username='buyer01', email='buyer01@corecraftr.local', password='BuyerPass!123'
        )
        cls.customer = Customer.objects.get(user=cls.shopper)

    def test_atomic_stock_adjustments_and_negative_and_reserved_guards(self):
        prod = Product.objects.create(
            name='Ryzen 7 7800X3D',
            sku='CPU-7800X3D',
            category=self.cpu_cat,
            brand=self.brand,
            price='38000.00',
            cost_price='32000.00',
            status=Product.STATUS_PUBLISHED,
        )
        inv = Inventory.objects.create(product=prod, quantity=10, reserved_quantity=4, low_stock_threshold=3)

        self.client.force_login(self.manager)
        token = inventory_version_token(inv)

        # Valid add
        self.client.post(
            reverse('management:inventory_adjust', args=[prod.id]),
            data={
                'adjustment_mode': 'add',
                'quantity_value': '5',
                'reason': StockMovement.REASON_RESTOCK,
                'notes': 'PO-2026-11',
                'expected_version_token': token,
            },
        )
        inv.refresh_from_db()
        self.assertEqual(inv.quantity, 15)
        self.assertTrue(StockMovement.objects.filter(product=prod, change_amount=5, reason='restock').exists())

        # Reject stale concurrency token
        self.client.post(
            reverse('management:inventory_adjust', args=[prod.id]),
            data={
                'adjustment_mode': 'set',
                'quantity_value': '20',
                'reason': StockMovement.REASON_MANUAL_CORRECTION,
                'expected_version_token': token,  # stale token
            },
        )
        inv.refresh_from_db()
        self.assertEqual(inv.quantity, 15)

        # Reject reducing below reserved_quantity (4)
        self.client.post(
            reverse('management:inventory_adjust', args=[prod.id]),
            data={
                'adjustment_mode': 'set',
                'quantity_value': '2',
                'reason': StockMovement.REASON_MANUAL_CORRECTION,
            },
        )
        inv.refresh_from_db()
        self.assertEqual(inv.quantity, 15)

        # Reject subtracting below 0
        self.client.post(
            reverse('management:inventory_adjust', args=[prod.id]),
            data={
                'adjustment_mode': 'subtract',
                'quantity_value': '99',
                'reason': StockMovement.REASON_DAMAGED,
            },
        )
        inv.refresh_from_db()
        self.assertEqual(inv.quantity, 15)

    def test_order_deduction_records_stock_movement_and_price_change_preserves_order_history(self):
        prod = Product.objects.create(
            name='Ryzen 5 5600',
            sku='CPU-R5-5600',
            category=self.cpu_cat,
            brand=self.brand,
            price='11500.00',
            status=Product.STATUS_PUBLISHED,
        )
        Inventory.objects.create(product=prod, quantity=8, low_stock_threshold=2)

        cart = Cart.objects.create(user=self.shopper)
        cart_result = update_cart_item(cart, prod, action='add', quantity=2)
        self.assertTrue(cart_result.success)

        checkout_res = create_order_from_cart(
            cart=cart,
            customer=self.customer,
            customer_name='Buyer One',
            customer_email='buyer01@corecraftr.local',
            customer_phone='9876543210',
            address='12 Tech Park',
            city='Bengaluru',
            state='Karnataka',
            zipcode='560001',
            country='India',
            notes='Order test',
        )
        self.assertTrue(checkout_res.success)
        order = checkout_res.order
        prod.refresh_from_db()
        self.assertEqual(prod.inventory.quantity, 6)
        mv = StockMovement.objects.filter(product=prod, reason=StockMovement.REASON_ORDER_DEDUCTION).first()
        self.assertIsNotNone(mv)
        self.assertEqual(mv.change_amount, -2)
        self.assertEqual(mv.new_quantity, 6)
        self.assertEqual(mv.reference_order_id, order.id)

        # Now price increases via portal: existing OrderItem keeps historical unit_price!
        self.client.force_login(self.manager)
        self.client.post(
            reverse('management:product_edit', args=[prod.id]),
            data={
                'name': prod.name,
                'sku': prod.sku,
                'category': self.cpu_cat.id,
                'brand': self.brand.id,
                'status': Product.STATUS_PUBLISHED,
                'price': '13900.00',
                'warranty_months': '36',
                'price_change_reason': 'Supplier FX adjustment',
            },
        )
        prod.refresh_from_db()
        self.assertEqual(prod.price, Decimal('13900.00'))
        order_item = OrderItem.objects.get(order=order, product=prod)
        self.assertEqual(order_item.unit_price, Decimal('11500.00'))
        self.assertTrue(PriceChangeLog.objects.filter(product=prod, previous_price='11500.00', new_price='13900.00').exists())

    def test_csv_two_step_import_validation_and_export(self):
        self.client.force_login(self.manager)

        # Upload CSV with duplicate SKU and bad price -> preview step ONLY
        bad_csv = (
            'sku,name,category_slug,brand_name,price,stock_quantity,status,socket,tdp_watts\n'
            'CSV-CPU-01,CSV Ryzen 1,processors,AMD,14000.00,5,draft,AM5,65\n'
            'CSV-CPU-01,Duplicate Row,processors,AMD,14000.00,2,draft,AM5,65\n'
            'CSV-CPU-02,Bad Price CPU,processors,AMD,not_a_price,5,draft,AM5,65\n'
        ).encode('utf-8')
        self.client.post(
            reverse('management:import_export'),
            data={
                'action': 'preview',
                'csv_file': SimpleUploadedFile('bad_batch.csv', bad_csv, content_type='text/csv'),
            },
        )
        batch = CSVImportBatch.objects.order_by('-id').first()
        self.assertIsNotNone(batch)
        self.assertEqual(batch.status, CSVImportBatch.STATUS_PREVIEW)
        self.assertEqual(batch.valid_rows, 1)
        self.assertEqual(batch.error_rows, 2)
        # No product written yet during Step 1!
        self.assertFalse(Product.objects.filter(sku='CSV-CPU-01').exists())

        # Attempting full confirm while error rows exist is blocked
        self.client.post(
            reverse('management:import_export'),
            data={'action': 'confirm', 'batch_id': batch.id},
        )
        batch.refresh_from_db()
        self.assertEqual(batch.status, CSVImportBatch.STATUS_PREVIEW)

        # Confirm clean CSV batch
        clean_csv = (
            'sku,name,category_slug,brand_name,price,cost_price,stock_quantity,status,socket,tdp_watts\n'
            'CSV-CPU-10,CSV Ryzen 9 7900,processors,AMD,36500.00,31000.00,4,published,AM5,65\n'
        ).encode('utf-8')
        self.client.post(
            reverse('management:import_export'),
            data={
                'action': 'preview',
                'csv_file': SimpleUploadedFile('clean.csv', clean_csv, content_type='text/csv'),
            },
        )
        clean_batch = CSVImportBatch.objects.order_by('-id').first()
        self.assertEqual(clean_batch.error_rows, 0)
        self.client.post(
            reverse('management:import_export'),
            data={'action': 'confirm', 'batch_id': clean_batch.id},
        )
        clean_batch.refresh_from_db()
        self.assertEqual(clean_batch.status, CSVImportBatch.STATUS_APPLIED)
        imported = Product.objects.get(sku='CSV-CPU-10')
        self.assertEqual(imported.spec_profile.socket, 'AM5')
        self.assertEqual(imported.spec_profile.tdp_watts, 65)
        self.assertTrue(StockMovement.objects.filter(product=imported, reason=StockMovement.REASON_CSV_IMPORT).exists())

        # Export CSV works cleanly
        export_resp = self.client.get(reverse('management:export_csv'))
        self.assertEqual(export_resp.status_code, 200)
        self.assertIn('CSV-CPU-10', export_resp.content.decode('utf-8'))

    def test_audit_log_immutability_and_verified_cost_valuation(self):
        p_with_cost = Product.objects.create(
            name='Cost Known CPU', sku='COST-1', category=self.cpu_cat, price='1000.00', cost_price='700.00', status=Product.STATUS_PUBLISHED
        )
        Inventory.objects.create(product=p_with_cost, quantity=3)
        p_no_cost = Product.objects.create(
            name='Cost Missing CPU', sku='COST-2', category=self.cpu_cat, price='2000.00', cost_price=None, status=Product.STATUS_PUBLISHED
        )
        Inventory.objects.create(product=p_no_cost, quantity=5)

        metrics = get_verified_inventory_metrics()
        self.assertEqual(metrics['valued_sku_count'], 1)
        self.assertEqual(metrics['missing_cost_count'], 1)
        self.assertEqual(metrics['cost_valuation_total'], Decimal('2100.00'))  # strictly 700 * 3

        log = AuditLog.objects.create(
            actor=self.owner,
            actor_username=self.owner.username,
            actor_role='Owner',
            action='test.immutable',
            target_type='product',
            target_id=str(p_with_cost.id),
            summary='Testing immutability',
        )
        with self.assertRaises(PermissionError):
            log.summary = 'tampered'
            log.save()
        with self.assertRaises(PermissionError):
            log.delete()
        with self.assertRaises(PermissionError):
            AuditLog.objects.filter(pk=log.id).delete()
        with self.assertRaises(PermissionError):
            AuditLog.objects.filter(pk=log.id).update(summary='tampered')

    def test_seed_portal_demo_is_idempotent_and_populates_portal_metrics(self):
        out = io.StringIO()
        call_command('seed_portal_demo', '--demo-password', 'TestDemoPass!99', stdout=out)
        first_total = Product.objects.count()
        first_orders = Order.objects.filter(order_number='ORD-DEMO-1001').count()
        self.assertGreaterEqual(first_total, 77)
        self.assertEqual(first_orders, 1)
        self.assertTrue(Product.objects.filter(sku='DEMO-DRAFT-9600X', status=Product.STATUS_DRAFT, is_active=False).exists())
        self.assertTrue(Product.objects.filter(sku='DEMO-ARCH-RTX3060', status=Product.STATUS_ARCHIVED, is_active=False).exists())

        # Re-run to verify idempotency (no duplicate products/orders/movements)
        call_command('seed_portal_demo', '--demo-password', 'TestDemoPass!99', stdout=out)
        self.assertEqual(Product.objects.count(), first_total)
        self.assertEqual(Order.objects.filter(order_number='ORD-DEMO-1001').count(), 1)
