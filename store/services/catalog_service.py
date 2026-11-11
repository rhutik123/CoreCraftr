from decimal import Decimal
from django.db.models import Count, Q
from store.models import Brand, Category, Product


def get_homepage_sections():
    """Fetch curated sections for the homepage."""
    base_qs = (
        Product.objects.filter(is_active=True)
        .select_related('category', 'brand', 'inventory', 'spec_profile')
    )
    return {
        'categories': Category.objects.annotate(
            product_count=Count('products', filter=Q(products__is_active=True))
        ).order_by('display_order', 'name'),
        'featured_products': base_qs.filter(is_featured=True)[:8],
        'trending_products': base_qs.filter(is_trending=True)[:8],
        'special_offers': base_qs.filter(is_special_offer=True)[:6],
    }


def filter_catalogue_products(params: dict):
    """
    Filter and sort active catalogue products by query, category, brand,
    price range, availability, and hardware attributes.
    """
    qs = (
        Product.objects.filter(is_active=True)
        .select_related('category', 'brand', 'inventory', 'spec_profile')
    )

    q = (params.get('q') or '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(short_description__icontains=q)
            | Q(description__icontains=q)
            | Q(brand__name__icontains=q)
            | Q(category__name__icontains=q)
            | Q(sku__icontains=q)
            | Q(spec_profile__socket__icontains=q)
            | Q(spec_profile__chipset__icontains=q)
            | Q(spec_profile__memory_type__icontains=q)
            | Q(spec_profile__gpu_chipset__icontains=q)
        )

    category_slug = (params.get('category') or '').strip()
    if category_slug:
        qs = qs.filter(category__slug=category_slug)

    brand_slug = (params.get('brand') or '').strip()
    if brand_slug:
        qs = qs.filter(brand__slug=brand_slug)

    min_price = params.get('min_price')
    if min_price:
        try:
            qs = qs.filter(price__gte=Decimal(str(min_price)))
        except Exception:
            pass

    max_price = params.get('max_price')
    if max_price:
        try:
            qs = qs.filter(price__lte=Decimal(str(max_price)))
        except Exception:
            pass

    in_stock_only = str(params.get('in_stock') or '').lower() in ('1', 'true', 'yes', 'on')
    if in_stock_only:
        qs = qs.filter(inventory__quantity__gt=0)

    socket_filter = (params.get('socket') or '').strip()
    if socket_filter:
        qs = qs.filter(spec_profile__socket__iexact=socket_filter)

    memory_filter = (params.get('memory_type') or '').strip()
    if memory_filter:
        qs = qs.filter(spec_profile__memory_type__iexact=memory_filter)

    sort = (params.get('sort') or 'featured').strip()
    sort_map = {
        'featured': ('-is_featured', '-is_trending', 'name'),
        'price_asc': ('price', 'name'),
        'price_desc': ('-price', 'name'),
        'rating': ('-rating_avg', '-rating_count', 'name'),
        'newest': ('-created_at', '-id'),
        'name': ('name',),
    }
    qs = qs.order_by(*sort_map.get(sort, ('-is_featured', 'name')))
    return qs


def get_grouped_specifications(product: Product) -> dict[str, list]:
    """Group ProductSpecification rows by spec_group for clean product detail rendering."""
    grouped = {}
    for spec in product.specifications.all():
        grouped.setdefault(spec.spec_group, []).append(spec)
    return grouped


def get_available_filter_facets():
    """Return available categories, brands, sockets, and memory types for filter sidebars."""
    categories = Category.objects.annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    ).order_by('display_order', 'name')
    brands = Brand.objects.annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    ).filter(product_count__gt=0).order_by('name')
    return {
        'categories': categories,
        'brands': brands,
    }


def _fmt_spec(val, suffix: str = '', fallback: str = 'Unknown / Not verified') -> tuple[str, bool]:
    if val is None or val == '' or val == []:
        return fallback, True
    if isinstance(val, list):
        return f'{", ".join(str(v) for v in val)}{suffix}', False
    return f'{val}{suffix}', False


def get_key_hardware_highlights(product: Product) -> list[dict]:
    """
    Build category-specific hardware specification highlight cards for the product detail page.
    Missing attributes are explicitly marked unknown rather than invented or hidden silently.
    """
    slot = product.category.component_slot if product.category else 'other'
    spec = product.spec_profile_safe

    def item(label: str, raw_val, suffix: str = '') -> dict:
        text, is_unknown = _fmt_spec(raw_val, suffix=suffix)
        return {'label': label, 'value': text, 'is_unknown': is_unknown}

    if slot == 'cpu':
        cores_threads = (
            f'{spec.cores} Cores / {spec.threads} Threads'
            if spec and spec.cores and spec.threads
            else (f'{spec.cores} Cores' if spec and spec.cores else None)
        )
        return [
            item('Socket', spec.socket if spec else None),
            item('Architecture', spec.microarchitecture or spec.cpu_family if spec else None),
            item('Cores / Threads', cores_threads),
            item('TDP / Max Power', f'{spec.tdp_watts} W' + (f' (Max {spec.max_power_watts} W)' if spec.max_power_watts and spec.max_power_watts != spec.tdp_watts else '') if spec and spec.tdp_watts else None),
            item('Supported Memory', spec.supported_memory_types if spec else None),
            item('Integrated Graphics', (spec.igpu_name or 'Yes' if spec.integrated_graphics else 'None (Discrete GPU Required)') if spec and spec.integrated_graphics is not None else None),
            item('Stock Cooler', ('Included in Box' if spec.includes_stock_cooler else 'Not Included (Aftermarket Required)') if spec and spec.includes_stock_cooler is not None else None),
        ]

    if slot == 'motherboard':
        bios_text = None
        if spec:
            parts = []
            if spec.min_bios_note:
                parts.append(spec.min_bios_note)
            if spec.bios_flashback is True:
                parts.append('BIOS Flashback Supported')
            elif spec.bios_flashback is False:
                parts.append('No USB BIOS Flashback')
            bios_text = ' • '.join(parts) if parts else None
        return [
            item('Socket', spec.socket if spec else None),
            item('Chipset', spec.chipset if spec else None),
            item('RAM Generation', spec.memory_type if spec else None),
            item('Max RAM Capacity', spec.max_memory_gb if spec else None, f' GB ({spec.memory_slots} DIMM slots)' if spec and spec.memory_slots else ' GB'),
            item('Form Factor', spec.form_factor if spec else None),
            item('Supported CPUs', spec.supported_cpu_families if spec else None),
            item('BIOS Notes', bios_text),
            item('M.2 / SATA Storage', f'{spec.m2_slots or 0}x M.2 ({spec.m2_nvme_slots or 0} NVMe) / {spec.sata_ports or 0}x SATA' if spec and spec.m2_slots is not None else None),
        ]

    if slot == 'ram':
        return [
            item('DDR Generation', spec.memory_type if spec else None),
            item('Total Capacity', spec.ram_capacity_gb if spec else None, ' GB'),
            item('Speed', spec.ram_speed_mhz if spec else None, ' MT/s'),
            item('Module Count', f'{spec.ram_modules}x Module(s)' if spec and spec.ram_modules else None),
            item('CAS Latency', spec.cas_latency if spec else None),
        ]

    if slot == 'gpu':
        req = spec.required_power_connectors if spec and spec.required_power_connectors else {}
        conn_parts = []
        if req.get('pcie_16pin_12vhpwr'):
            conn_parts.append(f'{req["pcie_16pin_12vhpwr"]}x 16-pin 12VHPWR')
        if req.get('pcie_8pin'):
            conn_parts.append(f'{req["pcie_8pin"]}x 8-pin PCIe')
        conn_text = ', '.join(conn_parts) if conn_parts else None
        return [
            item('GPU Chipset', spec.gpu_chipset if spec else None),
            item('VRAM', f'{spec.vram_gb} GB {spec.vram_type}'.strip() if spec and spec.vram_gb else None),
            item('Card Length', spec.gpu_length_mm if spec else None, ' mm'),
            item('Recommended Clearance', (spec.gpu_length_mm + 15) if spec and spec.gpu_length_mm else None, ' mm+ case GPU clearance'),
            item('Power Requirements', f'{spec.tdp_watts} W TDP / {spec.recommended_psu_watts} W Rec. PSU' if spec and spec.recommended_psu_watts else (f'{spec.tdp_watts} W TDP' if spec and spec.tdp_watts else None)),
            item('Power Connectors', conn_text),
        ]

    if slot == 'psu':
        avail = spec.psu_connectors if spec and spec.psu_connectors else {}
        conn_parts = []
        if avail.get('pcie_16pin_12vhpwr'):
            conn_parts.append(f'{avail["pcie_16pin_12vhpwr"]}x Native 12VHPWR')
        if avail.get('pcie_8pin'):
            conn_parts.append(f'{avail["pcie_8pin"]}x 8-pin PCIe')
        if avail.get('eps_8pin'):
            conn_parts.append(f'{avail["eps_8pin"]}x EPS CPU')
        conn_text = ', '.join(conn_parts) if conn_parts else None
        return [
            item('Wattage', spec.wattage if spec else None, ' W'),
            item('Efficiency Rating', spec.efficiency_rating if spec else None),
            item('Modularity', spec.modularity if spec else None),
            item('Available Connectors', conn_text),
            item('PSU Length', spec.psu_length_mm if spec else None, ' mm'),
        ]

    if slot == 'case':
        return [
            item('Supported Motherboards', spec.supported_form_factors if spec else None),
            item('Max GPU Length', spec.max_gpu_length_mm if spec else None, ' mm'),
            item('Max CPU Cooler Height', spec.max_cooler_height_mm if spec else None, ' mm'),
            item('Max PSU Length', spec.max_psu_length_mm if spec else None, ' mm'),
            item('Radiator Support', [f'{r}mm' for r in spec.supported_radiator_sizes_mm] if spec and spec.supported_radiator_sizes_mm else None),
        ]

    if slot == 'cooler':
        return [
            item('Cooler Type', spec.cooler_type if spec else None),
            item('Supported Sockets', spec.supported_sockets if spec else None),
            item('Cooler Height', spec.cooler_height_mm if spec else None, ' mm'),
            item('Radiator Size', spec.radiator_size_mm if spec else None, ' mm'),
            item('Thermal Capacity', spec.max_tdp_rating_watts if spec else None, ' W Max TDP'),
        ]

    if slot == 'storage':
        return [
            item('Storage Type', spec.storage_type if spec else None),
            item('Capacity', spec.capacity_gb if spec else None, ' GB'),
            item('Form Factor', spec.storage_form_factor if spec else None),
            item('Read / Write', f'{spec.read_speed_mbps} / {spec.write_speed_mbps or "?"} MB/s' if spec and spec.read_speed_mbps else None),
        ]

    if slot == 'monitor':
        return [
            item('Screen Size', spec.screen_size_inch if spec else None, '"'),
            item('Resolution', spec.resolution if spec else None),
            item('Refresh Rate', spec.refresh_rate_hz if spec else None, ' Hz'),
            item('Panel Type', spec.panel_type if spec else None),
        ]

    return []
