from django.db import transaction
from django.db.models import Q

from store.models import Category


STARTER_CATEGORIES = [
    (
        'CPUs & Processors',
        'processors',
        'cpu',
        'bi-cpu',
        1,
        True,
        True,
        'Desktop processors compatible with Intel and AMD sockets.',
    ),
    (
        'Motherboards',
        'motherboards',
        'motherboard',
        'bi-motherboard',
        2,
        True,
        True,
        'ATX, Micro-ATX, and Mini-ITX system boards with verified chipset support.',
    ),
    (
        'Memory (RAM)',
        'memory-ram',
        'ram',
        'bi-memory',
        3,
        True,
        True,
        'DDR4 and DDR5 desktop memory kits.',
    ),
    (
        'Graphics Cards (GPU)',
        'graphics-cards',
        'gpu',
        'bi-gpu-card',
        4,
        True,
        True,
        'Dedicated gaming, workstation, and creative graphics cards.',
    ),
    (
        'Storage (SSD & HDD)',
        'storage',
        'storage',
        'bi-nvme',
        5,
        True,
        True,
        'NVMe M.2 SSDs, SATA SSDs, and high-capacity hard drives.',
    ),
    (
        'Power Supplies (PSU)',
        'power-supplies',
        'psu',
        'bi-lightning-charge',
        6,
        True,
        True,
        '80+ certified modular and non-modular desktop power supplies.',
    ),
    (
        'PC Cabinets & Cases',
        'cabinets-cases',
        'case',
        'bi-pc',
        7,
        True,
        True,
        'Airflow and workstation chassis supporting standard form factors.',
    ),
    (
        'CPU Coolers',
        'cpu-coolers',
        'cooler',
        'bi-fan',
        8,
        True,
        True,
        'Air tower coolers and all-in-one liquid CPU cooling systems.',
    ),
    (
        'Case Fans',
        'case-fans',
        'case_fan',
        'bi-wind',
        9,
        True,
        False,
        'Chassis cooling fans and PWM airflow packs.',
    ),
    (
        'Monitors',
        'monitors',
        'monitor',
        'bi-display',
        10,
        False,
        True,
        'Gaming, color-accurate, and productivity displays.',
    ),
    (
        'Keyboards',
        'keyboards',
        'keyboard',
        'bi-keyboard',
        11,
        False,
        True,
        'Mechanical and productivity keyboards.',
    ),
    (
        'Mice',
        'mice',
        'mouse',
        'bi-mouse',
        12,
        False,
        False,
        'Precision wired and wireless desktop mice.',
    ),
    (
        'Accessories',
        'accessories',
        'accessory',
        'bi-plug',
        13,
        False,
        False,
        'Cables, surge protection, thermal compounds, and PC accessories.',
    ),
]


@transaction.atomic
def initialize_starter_categories(overwrite_existing: bool = False) -> dict:
    """
    Create essential hardware starter categories idempotently without demo products.

    By default (`overwrite_existing=False`), existing categories matched by slug or name
    are left completely untouched so owner customizations are never lost.
    """
    created_names = []
    skipped_names = []
    categories_by_slug = {}

    for name, slug, slot, icon, order, is_pc, show_nav, description in STARTER_CATEGORIES:
        existing = Category.objects.filter(Q(slug__iexact=slug) | Q(name__iexact=name)).first()
        if existing:
            if overwrite_existing:
                existing.name = name
                existing.slug = slug
                existing.component_slot = slot
                existing.icon_class = icon
                existing.display_order = order
                existing.is_pc_component = is_pc
                existing.show_in_nav = show_nav
                if not existing.description:
                    existing.description = description
                existing.save()
            categories_by_slug[slug] = existing
            skipped_names.append(existing.name)
            continue

        created = Category.objects.create(
            name=name,
            slug=slug,
            component_slot=slot,
            icon_class=icon,
            display_order=order,
            is_pc_component=is_pc,
            show_in_nav=show_nav,
            description=description,
            is_active=True,
        )
        categories_by_slug[slug] = created
        created_names.append(created.name)

    return {
        'created': len(created_names),
        'skipped': len(skipped_names),
        'total_categories': Category.objects.count(),
        'created_names': created_names,
        'skipped_names': skipped_names,
        'categories_by_slug': categories_by_slug,
    }
