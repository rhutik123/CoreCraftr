from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from management.models import AIResearchDraft, AuditLog, PriceChangeLog, StockMovement
from management.permissions import ensure_portal_roles
from store.models import (
    Brand,
    Category,
    Customer,
    HardwareSpecProfile,
    Inventory,
    Order,
    OrderItem,
    Product,
    ShippingAddress,
)


class Command(BaseCommand):
    help = (
        'Seed CoreCraftr with full hardware catalog data plus idempotent Owner & '
        'Inventory Portal demo data (draft/archived/low-stock SKUs, stock movements, '
        'price logs, AI draft sample, orders, and audit records).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-catalog',
            action='store_true',
            help='Skip invoking seed_hardware_catalog before portal demo seeding.',
        )
        parser.add_argument(
            '--demo-password',
            type=str,
            default='',
            help='Optional password for newly created demo accounts (defaults to random generated password).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options['skip_catalog']:
            call_command('seed_hardware_catalog', stdout=self.stdout)

        group = ensure_portal_roles()
        User = get_user_model()
        demo_password = (options.get('demo_password') or '').strip()

        created_credentials = []

        owner_user = User.objects.filter(is_superuser=True, is_active=True).order_by('id').first()
        if not owner_user:
            pwd = demo_password or get_random_string(14)
            owner_user = User.objects.create_superuser(
                username='demo_owner',
                email='owner@corecraftr.local',
                password=pwd,
            )
            created_credentials.append(('Owner (Superuser)', 'demo_owner', pwd))

        manager_user, mgr_created = User.objects.get_or_create(
            username='demo_manager',
            defaults={
                'email': 'manager@corecraftr.local',
                'first_name': 'Aarav',
                'last_name': 'Inventory',
                'is_staff': False,
                'is_superuser': False,
                'is_active': True,
            },
        )
        if mgr_created:
            pwd = demo_password or get_random_string(14)
            manager_user.set_password(pwd)
            manager_user.save(update_fields=['password'])
            created_credentials.append(('Inventory Manager', 'demo_manager', pwd))
        manager_user.groups.add(group)

        buyer_user, buyer_created = User.objects.get_or_create(
            username='demo_customer',
            defaults={
                'email': 'customer@corecraftr.local',
                'first_name': 'Priya',
                'last_name': 'Builder',
                'is_staff': False,
                'is_superuser': False,
                'is_active': True,
            },
        )
        if buyer_created:
            pwd = demo_password or get_random_string(14)
            buyer_user.set_password(pwd)
            buyer_user.save(update_fields=['password'])
            created_credentials.append(('Customer', 'demo_customer', pwd))
        customer, _ = Customer.objects.get_or_create(
            user=buyer_user,
            defaults={'name': 'Priya Builder', 'email': buyer_user.email},
        )

        # Backfill realistic verified cost prices and MPNs across most active SKUs,
        # intentionally leaving 5 SKUs without cost_price so partial cost coverage works cleanly.
        published_prods = list(Product.objects.filter(status='published').order_by('id'))
        updated_cost_count = 0
        for idx, prod in enumerate(published_prods):
            changed_fields = []
            if not prod.model_number and prod.sku:
                prod.model_number = f'MPN-{prod.sku}'
                changed_fields.append('model_number')
            if idx >= 5 and prod.cost_price is None and prod.price:
                prod.cost_price = (prod.price * Decimal('0.84')).quantize(Decimal('0.01'))
                changed_fields.append('cost_price')
            if not prod.created_by_id:
                prod.created_by = owner_user
                changed_fields.append('created_by')
            if not prod.last_edited_by_id:
                prod.last_edited_by = owner_user
                changed_fields.append('last_edited_by')
            if changed_fields:
                prod.save(update_fields=changed_fields)
                updated_cost_count += 1

        # Create realistic low-stock and out-of-stock scenarios cleanly on curated demo items
        today = timezone.localdate()
        low_targets = list(Product.objects.filter(status='published', is_demo_data=True).order_by('id')[:3])
        for offset, prod in enumerate(low_targets):
            inv, _ = Inventory.objects.get_or_create(product=prod)
            inv.quantity = 1 + (offset % 2)
            inv.low_stock_threshold = 4
            inv.restock_date = today + timedelta(days=5 + offset * 2)
            inv.save(update_fields=['quantity', 'low_stock_threshold', 'restock_date', 'updated_at'])

        out_targets = list(Product.objects.filter(status='published', is_demo_data=True).order_by('-id')[:2])
        for offset, prod in enumerate(out_targets):
            inv, _ = Inventory.objects.get_or_create(product=prod)
            inv.quantity = 0
            inv.low_stock_threshold = 3
            inv.restock_date = today + timedelta(days=7 + offset * 3)
            inv.save(update_fields=['quantity', 'low_stock_threshold', 'restock_date', 'updated_at'])

        # Seed draft & archived lifecycle demo products
        cpu_cat = Category.objects.filter(component_slot='cpu').first()
        gpu_cat = Category.objects.filter(component_slot='gpu').first()
        amd_brand = Brand.objects.filter(slug='amd').first()
        asus_brand = Brand.objects.filter(slug='asus').first()

        draft_cpu = None
        if cpu_cat:
            draft_cpu, created = Product.objects.update_or_create(
                sku='DEMO-DRAFT-9600X',
                defaults={
                    'name': 'AMD Ryzen 5 9600X (Draft Pre-Release)',
                    'slug': 'demo-draft-amd-ryzen-5-9600x',
                    'model_number': '100-100001405WOF',
                    'category': cpu_cat,
                    'brand': amd_brand,
                    'price': Decimal('25999.00'),
                    'cost_price': Decimal('21800.00'),
                    'status': Product.STATUS_DRAFT,
                    'short_description': 'Pending spec review before publishing to storefront.',
                    'static_image_path': 'images/categories/cpu.svg',
                    'is_demo_data': True,
                    'created_by': manager_user,
                    'last_edited_by': manager_user,
                },
            )
            Inventory.objects.update_or_create(
                product=draft_cpu,
                defaults={'quantity': 12, 'low_stock_threshold': 3},
            )
            HardwareSpecProfile.objects.update_or_create(
                product=draft_cpu,
                defaults={
                    'socket': 'AM5',
                    'cpu_family': 'Ryzen 9000',
                    'cores': 6,
                    'threads': 12,
                    'tdp_watts': 65,
                    'supported_memory_types': ['DDR5'],
                    'integrated_graphics': True,
                    'performance_tier': 'midrange',
                },
            )

        archived_gpu = None
        if gpu_cat:
            archived_gpu, _ = Product.objects.update_or_create(
                sku='DEMO-ARCH-RTX3060',
                defaults={
                    'name': 'ASUS Dual GeForce RTX 3060 V2 (Archived Legacy)',
                    'slug': 'demo-archived-asus-dual-rtx-3060',
                    'model_number': 'DUAL-RTX3060-O12G-V2',
                    'category': gpu_cat,
                    'brand': asus_brand,
                    'price': Decimal('26499.00'),
                    'cost_price': Decimal('22100.00'),
                    'status': Product.STATUS_ARCHIVED,
                    'short_description': 'Discontinued GPU archived to preserve historical orders.',
                    'static_image_path': 'images/categories/gpu.svg',
                    'is_demo_data': True,
                    'created_by': owner_user,
                    'last_edited_by': owner_user,
                },
            )
            Inventory.objects.update_or_create(
                product=archived_gpu,
                defaults={'quantity': 0, 'low_stock_threshold': 2},
            )
            HardwareSpecProfile.objects.update_or_create(
                product=archived_gpu,
                defaults={
                    'gpu_chipset': 'GeForce RTX 3060',
                    'vram_gb': 12,
                    'vram_type': 'GDDR6',
                    'gpu_length_mm': 200,
                    'tdp_watts': 170,
                    'recommended_psu_watts': 550,
                    'performance_tier': 'budget',
                },
            )

        # Idempotent sample orders with ShippingAddress and StockMovement ledger
        sample_products = list(Product.objects.filter(status='published').order_by('id')[:3])
        if sample_products and not Order.objects.filter(order_number='ORD-DEMO-1001').exists():
            item_p1 = sample_products[0]
            order1 = Order.objects.create(
                customer=customer,
                order_number='ORD-DEMO-1001',
                complete=True,
                status='delivered',
                payment_method='upi_demo',
                payment_status='paid_demo',
                subtotal_amount=item_p1.price,
                shipping_amount=Decimal('0.00'),
                total_amount=item_p1.price,
                customer_name='Priya Builder',
                customer_email=buyer_user.email,
                customer_phone='9876543210',
                notes='Seeded sample order for demo verification',
                compatibility_status='not_applicable',
            )
            OrderItem.objects.create(
                order=order1,
                product=item_p1,
                product_name_snapshot=item_p1.name,
                unit_price=item_p1.price,
                quantity=1,
            )
            ShippingAddress.objects.create(
                customer=customer,
                order=order1,
                address='42 Indiranagar 100ft Rd',
                city='Bengaluru',
                state='Karnataka',
                zipcode='560038',
                country='India',
                phone='9876543210',
            )
            StockMovement.objects.create(
                product=item_p1,
                previous_quantity=item_p1.stock_quantity + 1,
                change_amount=-1,
                new_quantity=item_p1.stock_quantity,
                reason=StockMovement.REASON_ORDER_DEDUCTION,
                notes='Seeded demo order ORD-DEMO-1001 deduction',
                reference_order=order1,
                performed_by=buyer_user,
            )

        # Seed sample stock movements & price changes once if empty
        if StockMovement.objects.filter(notes__startswith='[Seed Demo]').count() == 0 and len(sample_products) >= 2:
            StockMovement.objects.create(
                product=sample_products[0],
                previous_quantity=0,
                change_amount=10,
                new_quantity=10,
                reason=StockMovement.REASON_RESTOCK,
                notes='[Seed Demo] Initial distributor shipment PO-4410',
                performed_by=manager_user,
            )
            StockMovement.objects.create(
                product=sample_products[1],
                previous_quantity=6,
                change_amount=-1,
                new_quantity=5,
                reason=StockMovement.REASON_DAMAGED,
                notes='[Seed Demo] Damaged box write-off',
                performed_by=manager_user,
            )

        if PriceChangeLog.objects.filter(reason__startswith='[Seed Demo]').count() == 0 and sample_products:
            p0 = sample_products[0]
            PriceChangeLog.objects.create(
                product=p0,
                previous_price=(p0.price + Decimal('1000.00')),
                new_price=p0.price,
                previous_cost_price=p0.cost_price,
                new_cost_price=p0.cost_price,
                reason='[Seed Demo] Seasonal hardware price revision',
                changed_by=owner_user,
            )

        if AIResearchDraft.objects.filter(product_name='AMD Ryzen 5 9600X (Draft Pre-Release)').count() == 0 and draft_cpu:
            AIResearchDraft.objects.create(
                requested_by=manager_user,
                product=draft_cpu,
                product_name=draft_cpu.name,
                brand_name='AMD',
                category=cpu_cat,
                model_number=draft_cpu.model_number,
                status=AIResearchDraft.STATUS_DRAFT,
                verification_status=AIResearchDraft.VERIFICATION_MANUFACTURER,
                confidence='high',
                proposed_specs={
                    'socket': 'AM5',
                    'cpu_family': 'Ryzen 9000',
                    'cores': 6,
                    'threads': 12,
                    'tdp_watts': 65,
                    'supported_memory_types': ['DDR5'],
                },
                sources=[
                    {
                        'url': 'https://www.amd.com/en/products/processors/desktops/ryzen/9000-series/amd-ryzen-5-9600x.html',
                        'title': 'AMD Ryzen 5 9600X Official Specs',
                        'origin_type': 'manufacturer',
                    }
                ],
                missing_fields=['max_power_watts'],
                conflicting_fields=[],
                summary_note='[Seed Demo] Pending manual staff approval inside Product Studio.',
                raw_provider_status='demo_seed',
            )

        if AuditLog.objects.filter(action='seed.portal_demo').count() == 0:
            AuditLog.objects.create(
                actor=owner_user,
                actor_username=owner_user.username,
                actor_role='Owner',
                action='seed.portal_demo',
                target_type='catalog',
                target_label='CoreCraftr Demo Seed',
                after_data={
                    'products_total': Product.objects.count(),
                    'published': Product.objects.filter(status='published').count(),
                    'drafts': Product.objects.filter(status='draft').count(),
                    'archived': Product.objects.filter(status='archived').count(),
                },
                summary='Initialized idempotent CoreCraftr hardware catalog and management portal demo data.',
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'Portal demo seed complete: {Product.objects.count()} products '
                f'({Product.objects.filter(status="published").count()} published, '
                f'{Product.objects.filter(status="draft").count()} draft, '
                f'{Product.objects.filter(status="archived").count()} archived), '
                f'{updated_cost_count} enriched SKUs, '
                f'{StockMovement.objects.count()} stock movements, '
                f'{Order.objects.count()} order(s), '
                f'{AuditLog.objects.count()} audit log(s).'
            )
        )
        for role_label, uname, pwd in created_credentials:
            self.stdout.write(
                self.style.WARNING(
                    f'Created demo {role_label} -> username: {uname} | temporary password: {pwd}'
                )
            )
