from decimal import Decimal
import uuid
from django.db import migrations
from django.utils.text import slugify


def migrate_legacy_store_data(apps, schema_editor):
    Category = apps.get_model('store', 'Category')
    Brand = apps.get_model('store', 'Brand')
    Product = apps.get_model('store', 'Product')
    Inventory = apps.get_model('store', 'Inventory')
    Customer = apps.get_model('store', 'Customer')
    Order = apps.get_model('store', 'Order')
    OrderItem = apps.get_model('store', 'OrderItem')
    User = apps.get_model('auth', 'User')

    legacy_map = {
        'Processors': ('CPUs & Processors', 'processors', 'cpu', True),
        'Motherboards': ('Motherboards', 'motherboards', 'motherboard', True),
        'Memory(ram)': ('Memory (RAM)', 'memory-ram', 'ram', True),
        'Storage': ('Storage (SSD & HDD)', 'storage', 'storage', True),
        'Cabinets': ('PC Cabinets & Cases', 'cabinets-cases', 'case', True),
        'Cooling System': ('CPU Coolers', 'cpu-coolers', 'cooler', True),
        'Accessories': ('Accessories', 'accessories', 'accessory', False),
    }

    category_cache = {}
    for legacy_key, (cat_name, cat_slug, slot, is_pc) in legacy_map.items():
        if Product.objects.filter(legacy_category=legacy_key).exists():
            cat_obj, _ = Category.objects.get_or_create(
                slug=cat_slug,
                defaults={
                    'name': cat_name,
                    'component_slot': slot,
                    'is_pc_component': is_pc,
                },
            )
            category_cache[legacy_key] = cat_obj

    amd_brand = None
    for product in Product.objects.all().order_by('id'):
        changed = False
        if not product.category_id and product.legacy_category in category_cache:
            product.category = category_cache[product.legacy_category]
            changed = True
        if not product.brand_id and 'amd' in product.name.lower():
            if amd_brand is None:
                amd_brand, _ = Brand.objects.get_or_create(
                    slug='amd',
                    defaults={'name': 'AMD'},
                )
            product.brand = amd_brand
            changed = True
        if not product.slug:
            base_slug = slugify(product.name)[:220] or f'product-{product.id}'
            candidate = base_slug
            counter = 1
            while Product.objects.filter(slug=candidate).exclude(pk=product.pk).exists():
                candidate = f'{base_slug}-{counter}'
                counter += 1
            product.slug = candidate
            changed = True
        if not product.sku:
            product.sku = f'LEG-{product.id:04d}-{uuid.uuid4().hex[:4].upper()}'
            changed = True
        if changed:
            product.save()

        Inventory.objects.get_or_create(
            product=product,
            defaults={'quantity': 12},
        )

    for user in User.objects.all():
        Customer.objects.get_or_create(
            user=user,
            defaults={
                'name': user.username,
                'email': user.email or '',
            },
        )

    for item in OrderItem.objects.select_related('product').all():
        updated = False
        if item.product and not item.product_name_snapshot:
            item.product_name_snapshot = item.product.name
            updated = True
        if item.product and item.unit_price is None:
            item.unit_price = item.product.price
            updated = True
        if updated:
            item.save()

    for order in Order.objects.all():
        updated = False
        if not order.order_number:
            order.order_number = f'ORD-{order.id:06d}'
            updated = True
        if order.total_amount == Decimal('0.00'):
            items = OrderItem.objects.filter(order=order)
            calc = sum(((i.unit_price or Decimal('0.00')) * Decimal(i.quantity or 0) for i in items), Decimal('0.00'))
            if calc > Decimal('0.00'):
                order.subtotal_amount = calc
                order.total_amount = calc
                updated = True
        if updated:
            order.save()


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0005_brand_category_hardwarespecprofile_inventory_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_store_data, migrations.RunPython.noop),
    ]
