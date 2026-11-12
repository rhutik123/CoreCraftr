from management.spec_schemas import get_spec_fields_for_slot
from store.models import HardwareSpecProfile, Product


def _format_profile_field(profile: HardwareSpecProfile | None, field_def: dict) -> str:
    """Format a single HardwareSpecProfile schema field for human-readable comparison."""
    if not profile:
        return ''
    val = getattr(profile, field_def['name'], None)
    if val in (None, '', [], {}):
        return ''
    ftype = field_def.get('type', 'str')
    unit = field_def.get('unit', '')
    if ftype == 'bool':
        return 'Yes' if val else 'No'
    if ftype in ('list_str', 'list_int'):
        joined = ', '.join(str(x) for x in val if x not in (None, ''))
        if not joined:
            return ''
        return f'{joined} {unit}'.strip() if unit else joined
    if ftype == 'json_dict' and isinstance(val, dict):
        return ', '.join(f'{k}: {v}' for k, v in val.items())
    return f'{val} {unit}'.strip() if unit else str(val)


def _infer_spec_from_profile(product: Product, key: str, schema_maps: dict[int, dict[str, str]]) -> str:
    """Fill a custom spec key from HardwareSpecProfile when ProductSpecification rows omit it."""
    exact = schema_maps.get(product.id, {}).get(key.lower(), '')
    if exact:
        return exact
    sp = product.spec_profile_safe
    if not sp:
        return ''

    norm = key.strip().lower()
    if norm == 'cores / threads' and (sp.cores or sp.threads):
        parts = []
        if sp.cores:
            parts.append(f'{sp.cores} Cores')
        if sp.threads:
            parts.append(f'{sp.threads} Threads')
        return ' / '.join(parts)
    if norm in ('base / boost clock', 'base / boost') and (sp.base_clock_ghz or sp.boost_clock_ghz):
        base = f'{sp.base_clock_ghz}' if sp.base_clock_ghz else '—'
        boost = f'{sp.boost_clock_ghz}' if sp.boost_clock_ghz else '—'
        return f'{base} / {boost} GHz'
    if norm == 'max turbo' and sp.boost_clock_ghz:
        return f'{sp.boost_clock_ghz} GHz'
    if norm == 'l3 cache' and sp.cache_info:
        return sp.cache_info
    if norm in ('stock cooler', 'cooler') and sp.includes_stock_cooler is not None:
        return 'Yes' if sp.includes_stock_cooler else 'No'
    if norm == 'integrated' and sp.integrated_graphics is not None:
        if sp.integrated_graphics:
            return sp.igpu_name or 'Yes'
        return 'No'
    if norm in ('supported ram', 'ram support'):
        if sp.supported_memory_types:
            return ', '.join(sp.supported_memory_types)
        if sp.memory_type:
            return sp.memory_type
    if norm == 'memory type' and not sp.memory_type and sp.supported_memory_types:
        return ', '.join(sp.supported_memory_types)
    if norm == 'base / max turbo' and (sp.tdp_watts or sp.max_power_watts):
        base_w = f'{sp.tdp_watts} W' if sp.tdp_watts else '—'
        max_w = f'{sp.max_power_watts} W' if sp.max_power_watts else '—'
        return f'{base_w} / {max_w}'
    if norm == 'socket / chipset' and (sp.socket or sp.chipset):
        return ' / '.join(x for x in (sp.socket, sp.chipset) if x)
    if norm == 'size' and sp.form_factor:
        return sp.form_factor
    if norm == 'ram slots / max' and (sp.memory_slots or sp.max_memory_gb):
        parts = []
        if sp.memory_slots:
            parts.append(f'{sp.memory_slots} Slots')
        if sp.max_memory_gb:
            parts.append(f'{sp.max_memory_gb} GB')
        return ' / '.join(parts)
    if norm == 'm.2 / sata' and (sp.m2_slots is not None or sp.sata_ports is not None):
        return f'{sp.m2_slots or 0}x M.2 / {sp.sata_ports or 0}x SATA'
    if norm in ('wi-fi', 'wi-fi / lan') and sp.wifi_included is not None:
        return 'Wi-Fi Included' if sp.wifi_included else 'Ethernet Only'
    if norm == 'vram' and sp.vram_gb:
        return f'{sp.vram_gb} GB {sp.vram_type or ""}'.strip()
    if norm == 'length' and sp.gpu_length_mm:
        return f'{sp.gpu_length_mm} mm'
    if norm == 'tdp / rec. psu' and (sp.tdp_watts or sp.recommended_psu_watts):
        tdp = f'{sp.tdp_watts} W' if sp.tdp_watts else '—'
        psu = f'{sp.recommended_psu_watts} W' if sp.recommended_psu_watts else '—'
        return f'{tdp} / {psu}'
    if norm == 'type / capacity' and (sp.memory_type or sp.ram_capacity_gb):
        return ' / '.join(x for x in (sp.memory_type, f'{sp.ram_capacity_gb} GB' if sp.ram_capacity_gb else '') if x)
    if norm == 'speed / latency' and (sp.ram_speed_mhz or sp.cas_latency):
        return ' / '.join(x for x in (f'{sp.ram_speed_mhz} MHz' if sp.ram_speed_mhz else '', sp.cas_latency) if x)
    if norm == 'capacity / form factor' and (sp.capacity_gb or sp.storage_form_factor):
        return ' / '.join(x for x in (f'{sp.capacity_gb} GB' if sp.capacity_gb else '', sp.storage_form_factor) if x)
    if norm in ('read / write', 'sequential read / write') and (sp.read_speed_mbps or sp.write_speed_mbps):
        r = f'{sp.read_speed_mbps}' if sp.read_speed_mbps else '—'
        w = f'{sp.write_speed_mbps}' if sp.write_speed_mbps else '—'
        return f'{r} / {w} MB/s'
    if norm == 'wattage / rating' and (sp.wattage or sp.efficiency_rating):
        return ' / '.join(x for x in (f'{sp.wattage} W' if sp.wattage else '', sp.efficiency_rating) if x)
    if norm == 'length / modularity' and (sp.psu_length_mm or sp.modularity):
        return ' / '.join(x for x in (f'{sp.psu_length_mm} mm' if sp.psu_length_mm else '', sp.modularity) if x)
    if norm == 'max tdp rating' and sp.max_tdp_rating_watts:
        return f'{sp.max_tdp_rating_watts} W'
    if norm == 'sockets' and sp.supported_sockets:
        return ', '.join(sp.supported_sockets)
    if norm == 'motherboards' and sp.supported_form_factors:
        return ', '.join(sp.supported_form_factors)
    if norm == 'max gpu / cooler' and (sp.max_gpu_length_mm or sp.max_cooler_height_mm):
        g = f'{sp.max_gpu_length_mm} mm' if sp.max_gpu_length_mm else '—'
        c = f'{sp.max_cooler_height_mm} mm' if sp.max_cooler_height_mm else '—'
        return f'{g} / {c}'
    if norm == 'included fans' and sp.included_fans is not None:
        return str(sp.included_fans)
    if norm == 'radiator support' and sp.supported_radiator_sizes_mm:
        return ', '.join(f'{s} mm' for s in sp.supported_radiator_sizes_mm)
    return ''


_CUSTOM_KEY_COVERS_SCHEMA = {
    'cores / threads': {'cores', 'threads'},
    'base / boost clock': {'base clock', 'boost clock'},
    'base / boost': {'base clock', 'boost clock'},
    'max turbo': {'boost clock'},
    'l3 cache': {'cache'},
    'stock cooler': {'includes stock cooler'},
    'cooler': {'includes stock cooler'},
    'integrated': {'integrated graphics', 'igpu model'},
    'supported ram': {'supported memory types', 'memory type'},
    'ram support': {'supported memory types', 'memory type'},
    'base / max turbo': {'tdp', 'max turbo power'},
    'socket / chipset': {'socket', 'chipset'},
    'size': {'form factor', 'case class / size'},
    'ram slots / max': {'memory slots', 'max memory capacity'},
    'm.2 / sata': {'total m.2 slots', 'sata 6gb/s ports'},
    'wi-fi': {'built-in wi-fi'},
    'wi-fi / lan': {'built-in wi-fi'},
    'vram': {'vram capacity', 'vram type'},
    'length': {'card length', 'psu length'},
    'tdp / rec. psu': {'typical board power (tdp)', 'recommended psu wattage'},
    'type / capacity': {'memory type', 'total kit capacity'},
    'speed / latency': {'rated speed', 'cas latency'},
    'capacity / form factor': {'capacity', 'physical form factor'},
    'read / write': {'sequential read speed', 'sequential write speed'},
    'sequential read / write': {'sequential read speed', 'sequential write speed'},
    'wattage / rating': {'continuous wattage', 'efficiency certification'},
    'length / modularity': {'psu length', 'modularity'},
    'max tdp rating': {'max cooling tdp rating'},
    'sockets': {'supported sockets'},
    'motherboards': {'supported motherboard form factors'},
    'max gpu / cooler': {'max gpu length clearance', 'max cpu cooler height'},
    'included fans': {'included case fans'},
    'radiator support': {'supported radiator sizes (mm)'},
}


def build_comparison_matrix(products: list[Product]) -> dict:
    """
    Build a structured side-by-side comparison matrix for products of the same category,
    combining custom ProductSpecification rows with structured HardwareSpecProfile fields.
    """
    if not products:
        return {'products': [], 'rows': [], 'same_category': True}

    category_ids = {p.category_id for p in products}
    same_category = len(category_ids) <= 1

    # Gather custom ProductSpecification keys across selected products preserving order
    spec_keys_ordered = []
    seen_keys = set()
    product_spec_maps = {}

    for p in products:
        smap = {}
        for spec in p.specifications.all():
            label = spec.spec_key
            smap[label] = spec.formatted_value
            if label not in seen_keys:
                seen_keys.add(label)
                spec_keys_ordered.append((spec.spec_group, label))
        product_spec_maps[p.id] = smap

    # Also build structured HardwareSpecProfile maps from slot schema
    schema_fields_ordered = []
    seen_schema_labels = set()
    schema_maps = {p.id: {} for p in products}
    for p in products:
        slot = p.category.component_slot if p.category else None
        sp = p.spec_profile_safe
        for fdef in get_spec_fields_for_slot(slot):
            label = fdef['label']
            formatted = _format_profile_field(sp, fdef)
            if formatted:
                schema_maps[p.id][label.lower()] = formatted
            if label not in seen_schema_labels:
                seen_schema_labels.add(label)
                schema_fields_ordered.append(label)

    rows = []

    # Core summary rows first
    core_rows = [
        ('Overview', 'Brand', [p.brand.name if p.brand else '—' for p in products]),
        ('Overview', 'Price', [f'Rs. {p.price:,.2f}' for p in products]),
        ('Overview', 'Availability', [p.inventory.stock_status_label if hasattr(p, 'inventory') else 'Check Stock' for p in products]),
        ('Overview', 'Warranty', [f'{p.warranty_months} months' for p in products]),
        ('Overview', 'Spec Verified', ['Verified' if p.spec_verified else 'Incomplete / Unverified' for p in products]),
    ]
    for group, label, vals in core_rows:
        rows.append({
            'group': group,
            'label': label,
            'values': vals,
            'differs': len(set(vals)) > 1,
        })

    # Custom spec rows, enriched from HardwareSpecProfile when another product omits them
    covered_schema_labels = {k.strip().lower() for k in seen_keys}
    for custom_label in list(covered_schema_labels):
        covered_schema_labels.update(_CUSTOM_KEY_COVERS_SCHEMA.get(custom_label, ()))
    for group, key in spec_keys_ordered:
        vals = []
        for p in products:
            val = product_spec_maps[p.id].get(key)
            if not val:
                val = _infer_spec_from_profile(p, key, schema_maps) or 'Unknown / Not Listed'
            vals.append(val)
        rows.append({
            'group': group,
            'label': key,
            'values': vals,
            'differs': len(set(vals)) > 1,
        })

    # Append populated HardwareSpecProfile schema fields not already represented above
    for label in schema_fields_ordered:
        if label.lower() in covered_schema_labels:
            continue
        vals = [schema_maps[p.id].get(label.lower()) or 'Unknown / Not Listed' for p in products]
        if all(v == 'Unknown / Not Listed' for v in vals):
            continue
        rows.append({
            'group': 'Hardware Specifications',
            'label': label,
            'values': vals,
            'differs': len(set(vals)) > 1,
        })

    return {
        'products': products,
        'rows': rows,
        'same_category': same_category,
    }
