import json
import re
from decimal import Decimal, InvalidOperation

UNKNOWN_SENTINELS = {'', 'unknown', 'n/a', 'na', 'unspecified', 'tbd', 'none', 'null'}

# Strongly-typed hardware specification schema mapped by Category.component_slot.
# Every field name maps 1-to-1 to an attribute on store.models.HardwareSpecProfile.
# Fields marked compatibility_critical=True are evaluated by pc_builder.services.compatibility.
CATEGORY_SPEC_FIELDS = {
    'cpu': [
        {'name': 'socket', 'label': 'Socket', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. AM5, LGA1700'},
        {'name': 'cpu_family', 'label': 'CPU Family / Series', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. Ryzen 7000, Intel 14th Gen'},
        {'name': 'microarchitecture', 'label': 'Microarchitecture', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. Zen 4, Raptor Lake'},
        {'name': 'cores', 'label': 'Cores', 'type': 'int', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 8'},
        {'name': 'threads', 'label': 'Threads', 'type': 'int', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 16'},
        {'name': 'base_clock_ghz', 'label': 'Base Clock', 'type': 'decimal', 'unit': 'GHz', 'compatibility_critical': False, 'placeholder': 'e.g. 4.20'},
        {'name': 'boost_clock_ghz', 'label': 'Boost Clock', 'type': 'decimal', 'unit': 'GHz', 'compatibility_critical': False, 'placeholder': 'e.g. 5.00'},
        {'name': 'tdp_watts', 'label': 'TDP', 'type': 'int', 'unit': 'W', 'compatibility_critical': True, 'placeholder': 'e.g. 120'},
        {'name': 'max_power_watts', 'label': 'Max Turbo Power', 'type': 'int', 'unit': 'W', 'compatibility_critical': True, 'placeholder': 'e.g. 162'},
        {'name': 'cache_info', 'label': 'Cache', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 32 MB L3 + 6 MB L2'},
        {'name': 'integrated_graphics', 'label': 'Integrated Graphics', 'type': 'bool', 'unit': '', 'compatibility_critical': True},
        {'name': 'igpu_name', 'label': 'iGPU Model', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. AMD Radeon Graphics'},
        {'name': 'includes_stock_cooler', 'label': 'Includes Stock Cooler', 'type': 'bool', 'unit': '', 'compatibility_critical': True},
        {'name': 'supported_memory_types', 'label': 'Supported Memory Types', 'type': 'list_str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. DDR4, DDR5'},
        {'name': 'max_memory_gb', 'label': 'Max Memory Capacity', 'type': 'int', 'unit': 'GB', 'compatibility_critical': False, 'placeholder': 'e.g. 128'},
        {'name': 'max_memory_speed_mhz', 'label': 'Max Memory Speed', 'type': 'int', 'unit': 'MHz', 'compatibility_critical': False, 'placeholder': 'e.g. 5200'},
        {'name': 'pcie_version', 'label': 'PCIe Version', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. PCIe 5.0'},
    ],
    'motherboard': [
        {'name': 'socket', 'label': 'Socket', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. AM5, LGA1700'},
        {'name': 'chipset', 'label': 'Chipset', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. B650, B760'},
        {'name': 'form_factor', 'label': 'Form Factor', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. ATX, Micro-ATX, Mini-ITX'},
        {'name': 'memory_type', 'label': 'Memory Type', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. DDR4, DDR5'},
        {'name': 'memory_slots', 'label': 'Memory Slots', 'type': 'int', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. 4'},
        {'name': 'max_memory_gb', 'label': 'Max Memory Capacity', 'type': 'int', 'unit': 'GB', 'compatibility_critical': True, 'placeholder': 'e.g. 192'},
        {'name': 'supported_memory_speeds', 'label': 'Supported RAM Speeds (MHz)', 'type': 'list_int', 'unit': 'MHz', 'compatibility_critical': True, 'placeholder': 'e.g. 4800, 5200, 6000'},
        {'name': 'supported_cpu_families', 'label': 'Supported CPU Families', 'type': 'list_str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. Ryzen 7000, Ryzen 9000'},
        {'name': 'pcie_version', 'label': 'Primary PCIe Version', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. PCIe 4.0'},
        {'name': 'pcie_x16_slots', 'label': 'PCIe x16 Slots', 'type': 'int', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 2'},
        {'name': 'm2_slots', 'label': 'Total M.2 Slots', 'type': 'int', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. 2'},
        {'name': 'm2_nvme_slots', 'label': 'NVMe M.2 Slots', 'type': 'int', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. 2'},
        {'name': 'm2_sata_slots', 'label': 'SATA M.2 Slots', 'type': 'int', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. 1'},
        {'name': 'sata_ports', 'label': 'SATA 6Gb/s Ports', 'type': 'int', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. 4'},
        {'name': 'eps_connectors_required', 'label': '8-Pin EPS Connectors Required', 'type': 'int', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. 1 or 2'},
        {'name': 'wifi_included', 'label': 'Built-in Wi-Fi', 'type': 'bool', 'unit': '', 'compatibility_critical': False},
        {'name': 'bios_flashback', 'label': 'BIOS Flashback Support', 'type': 'bool', 'unit': '', 'compatibility_critical': False},
        {'name': 'min_bios_note', 'label': 'Minimum BIOS / CPU Support Note', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. BIOS F20+ required for 14th Gen'},
        {'name': 'slot_sharing_notes', 'label': 'M.2 / SATA Lane Sharing Notes', 'type': 'text', 'unit': '', 'compatibility_critical': False},
    ],
    'ram': [
        {'name': 'memory_type', 'label': 'Memory Type', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. DDR4, DDR5'},
        {'name': 'ram_capacity_gb', 'label': 'Total Kit Capacity', 'type': 'int', 'unit': 'GB', 'compatibility_critical': True, 'placeholder': 'e.g. 32'},
        {'name': 'ram_modules', 'label': 'Number of Modules', 'type': 'int', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. 2'},
        {'name': 'ram_speed_mhz', 'label': 'Rated Speed', 'type': 'int', 'unit': 'MHz', 'compatibility_critical': True, 'placeholder': 'e.g. 6000'},
        {'name': 'cas_latency', 'label': 'CAS Latency', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. CL30'},
        {'name': 'ecc_support', 'label': 'ECC Support', 'type': 'bool', 'unit': '', 'compatibility_critical': False},
        {'name': 'module_height_mm', 'label': 'Heatspreader Height', 'type': 'int', 'unit': 'mm', 'compatibility_critical': False, 'placeholder': 'e.g. 35'},
    ],
    'gpu': [
        {'name': 'gpu_chipset', 'label': 'GPU Chipset', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. GeForce RTX 4070 Super'},
        {'name': 'vram_gb', 'label': 'VRAM Capacity', 'type': 'int', 'unit': 'GB', 'compatibility_critical': False, 'placeholder': 'e.g. 12'},
        {'name': 'vram_type', 'label': 'VRAM Type', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. GDDR6X'},
        {'name': 'pcie_version', 'label': 'PCIe Interface', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. PCIe 4.0 x16'},
        {'name': 'gpu_length_mm', 'label': 'Card Length', 'type': 'int', 'unit': 'mm', 'compatibility_critical': True, 'placeholder': 'e.g. 242'},
        {'name': 'gpu_slot_width', 'label': 'Slot Width', 'type': 'decimal', 'unit': 'slots', 'compatibility_critical': False, 'placeholder': 'e.g. 2.5'},
        {'name': 'tdp_watts', 'label': 'Typical Board Power (TDP)', 'type': 'int', 'unit': 'W', 'compatibility_critical': True, 'placeholder': 'e.g. 220'},
        {'name': 'max_power_watts', 'label': 'Peak Transient Power', 'type': 'int', 'unit': 'W', 'compatibility_critical': True, 'placeholder': 'e.g. 250'},
        {'name': 'recommended_psu_watts', 'label': 'Recommended PSU Wattage', 'type': 'int', 'unit': 'W', 'compatibility_critical': True, 'placeholder': 'e.g. 650'},
        {'name': 'required_power_connectors', 'label': 'Required Power Connectors (JSON)', 'type': 'json_dict', 'unit': '', 'compatibility_critical': True, 'placeholder': '{"pcie_8pin": 1} or {"12vhpwr": 1}'},
        {'name': 'display_outputs', 'label': 'Display Outputs', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 3x DisplayPort 1.4a, 1x HDMI 2.1'},
    ],
    'storage': [
        {'name': 'storage_type', 'label': 'Storage Protocol / Type', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'NVMe M.2 / SATA M.2 / SATA 2.5" SSD / SATA 3.5" HDD'},
        {'name': 'storage_form_factor', 'label': 'Physical Form Factor', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. M.2 2280, 2.5", 3.5"'},
        {'name': 'storage_interface', 'label': 'Bus Interface', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. PCIe 4.0 x4 NVMe, SATA III 6Gb/s'},
        {'name': 'capacity_gb', 'label': 'Capacity', 'type': 'int', 'unit': 'GB', 'compatibility_critical': False, 'placeholder': 'e.g. 1000'},
        {'name': 'read_speed_mbps', 'label': 'Sequential Read Speed', 'type': 'int', 'unit': 'MB/s', 'compatibility_critical': False, 'placeholder': 'e.g. 7300'},
        {'name': 'write_speed_mbps', 'label': 'Sequential Write Speed', 'type': 'int', 'unit': 'MB/s', 'compatibility_critical': False, 'placeholder': 'e.g. 6000'},
    ],
    'psu': [
        {'name': 'wattage', 'label': 'Continuous Wattage', 'type': 'int', 'unit': 'W', 'compatibility_critical': True, 'placeholder': 'e.g. 750'},
        {'name': 'efficiency_rating', 'label': 'Efficiency Certification', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 80 PLUS Gold'},
        {'name': 'modularity', 'label': 'Modularity', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. Fully Modular'},
        {'name': 'psu_form_factor', 'label': 'PSU Form Factor', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. ATX, SFX'},
        {'name': 'atx_version', 'label': 'ATX / PCIe Spec Version', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. ATX 3.0 / PCIe 5.0 Ready'},
        {'name': 'psu_length_mm', 'label': 'PSU Length', 'type': 'int', 'unit': 'mm', 'compatibility_critical': True, 'placeholder': 'e.g. 150'},
        {'name': 'psu_connectors', 'label': 'Included Power Connectors (JSON)', 'type': 'json_dict', 'unit': '', 'compatibility_critical': True, 'placeholder': '{"eps_8pin": 2, "pcie_8pin": 3, "12vhpwr": 1}'},
    ],
    'case': [
        {'name': 'form_factor', 'label': 'Case Class / Size', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. Mid-Tower ATX, Micro-ATX, Mini-ITX'},
        {'name': 'supported_form_factors', 'label': 'Supported Motherboard Form Factors', 'type': 'list_str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. ATX, Micro-ATX, Mini-ITX'},
        {'name': 'max_gpu_length_mm', 'label': 'Max GPU Length Clearance', 'type': 'int', 'unit': 'mm', 'compatibility_critical': True, 'placeholder': 'e.g. 360'},
        {'name': 'max_cooler_height_mm', 'label': 'Max CPU Cooler Height', 'type': 'int', 'unit': 'mm', 'compatibility_critical': True, 'placeholder': 'e.g. 165'},
        {'name': 'max_psu_length_mm', 'label': 'Max PSU Length', 'type': 'int', 'unit': 'mm', 'compatibility_critical': True, 'placeholder': 'e.g. 180'},
        {'name': 'supported_radiator_sizes_mm', 'label': 'Supported Radiator Sizes (mm)', 'type': 'list_int', 'unit': 'mm', 'compatibility_critical': True, 'placeholder': 'e.g. 120, 240, 360'},
        {'name': 'drive_bays_35', 'label': '3.5" Drive Bays', 'type': 'int', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. 2'},
        {'name': 'drive_bays_25', 'label': '2.5" Drive Bays', 'type': 'int', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. 2'},
        {'name': 'included_fans', 'label': 'Included Case Fans', 'type': 'int', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 3'},
        {'name': 'max_fans', 'label': 'Max Fan Mounts', 'type': 'int', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 7'},
    ],
    'cooler': [
        {'name': 'cooler_type', 'label': 'Cooler Type', 'type': 'str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'Air / Liquid AIO'},
        {'name': 'supported_sockets', 'label': 'Supported Sockets', 'type': 'list_str', 'unit': '', 'compatibility_critical': True, 'placeholder': 'e.g. AM4, AM5, LGA1700, LGA1851'},
        {'name': 'cooler_height_mm', 'label': 'Air Tower Height', 'type': 'int', 'unit': 'mm', 'compatibility_critical': True, 'placeholder': 'e.g. 154 (for Air coolers)'},
        {'name': 'radiator_size_mm', 'label': 'Radiator Size', 'type': 'int', 'unit': 'mm', 'compatibility_critical': True, 'placeholder': 'e.g. 240 (for Liquid AIO)'},
        {'name': 'max_tdp_rating_watts', 'label': 'Max Cooling TDP Rating', 'type': 'int', 'unit': 'W', 'compatibility_critical': True, 'placeholder': 'e.g. 250'},
        {'name': 'fan_size_mm', 'label': 'Fan Diameter', 'type': 'int', 'unit': 'mm', 'compatibility_critical': False, 'placeholder': 'e.g. 120'},
        {'name': 'airflow_cfm', 'label': 'Max Airflow', 'type': 'decimal', 'unit': 'CFM', 'compatibility_critical': False, 'placeholder': 'e.g. 66.2'},
    ],
    'case_fan': [
        {'name': 'fan_size_mm', 'label': 'Fan Size', 'type': 'int', 'unit': 'mm', 'compatibility_critical': True, 'placeholder': 'e.g. 120 or 140'},
        {'name': 'fan_pack_count', 'label': 'Fans Per Pack', 'type': 'int', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 3'},
        {'name': 'airflow_cfm', 'label': 'Max Airflow', 'type': 'decimal', 'unit': 'CFM', 'compatibility_critical': False, 'placeholder': 'e.g. 58.0'},
    ],
    'monitor': [
        {'name': 'screen_size_inch', 'label': 'Screen Size', 'type': 'decimal', 'unit': '"', 'compatibility_critical': False, 'placeholder': 'e.g. 27.0'},
        {'name': 'resolution', 'label': 'Resolution', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 2560x1440 (QHD)'},
        {'name': 'refresh_rate_hz', 'label': 'Refresh Rate', 'type': 'int', 'unit': 'Hz', 'compatibility_critical': False, 'placeholder': 'e.g. 165'},
        {'name': 'panel_type', 'label': 'Panel Technology', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. IPS, OLED, VA'},
        {'name': 'connectivity', 'label': 'Video & USB Ports', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. 2x HDMI 2.1, 1x DisplayPort 1.4'},
    ],
    'keyboard': [
        {'name': 'switch_type', 'label': 'Switch Type', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. Linear Red Mechanical'},
        {'name': 'form_factor', 'label': 'Layout Size', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. TKL, 75%, Full-Size'},
        {'name': 'connectivity', 'label': 'Connectivity', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. USB-C Wired / 2.4GHz Wireless'},
    ],
    'mouse': [
        {'name': 'dpi', 'label': 'Max Sensor DPI', 'type': 'int', 'unit': 'DPI', 'compatibility_critical': False, 'placeholder': 'e.g. 26000'},
        {'name': 'connectivity', 'label': 'Connectivity', 'type': 'str', 'unit': '', 'compatibility_critical': False, 'placeholder': 'e.g. Wireless 2.4GHz + USB-C'},
    ],
    'accessory': [
        {'name': 'connectivity', 'label': 'Interface / Compatibility Note', 'type': 'str', 'unit': '', 'compatibility_critical': False},
    ],
    'other': [
        {'name': 'connectivity', 'label': 'Interface / General Spec', 'type': 'str', 'unit': '', 'compatibility_critical': False},
    ],
}


SHARED_METADATA_FIELDS = [
    {'name': 'performance_tier', 'label': 'Performance Tier', 'type': 'str', 'unit': '', 'compatibility_critical': False},
    {'name': 'benchmark_score', 'label': 'Relative Benchmark Score (1-100)', 'type': 'int', 'unit': '', 'compatibility_critical': False},
    {'name': 'beginner_summary', 'label': 'Plain-English Summary', 'type': 'text', 'unit': '', 'compatibility_critical': False},
    {'name': 'tradeoffs_note', 'label': 'Trade-offs / Buying Notes', 'type': 'text', 'unit': '', 'compatibility_critical': False},
]


def get_spec_fields_for_slot(slot: str) -> list:
    """Return ordered spec descriptors for a category component_slot."""
    return list(CATEGORY_SPEC_FIELDS.get(slot or 'other', CATEGORY_SPEC_FIELDS['other']))


def get_all_spec_schemas_by_slot() -> dict:
    """Return full slot -> fields dictionary for client-side dynamic forms."""
    return CATEGORY_SPEC_FIELDS


def get_critical_field_names(slot: str) -> list:
    """Return list of compatibility-critical field names for a slot."""
    return [f['name'] for f in get_spec_fields_for_slot(slot) if f.get('compatibility_critical')]


def is_unknown_raw(raw_val) -> bool:
    """Return True when raw_val represents an explicit or blank unknown value."""
    if raw_val is None:
        return True
    if isinstance(raw_val, str):
        return raw_val.strip().lower() in UNKNOWN_SENTINELS
    if isinstance(raw_val, (list, dict)):
        return len(raw_val) == 0
    return False


def coerce_spec_value(field_def: dict, raw_val):
    """
    Validate and coerce an incoming spec value into the exact HardwareSpecProfile column type.
    Returns (coerced_value, error_message_or_None). Unknown inputs become safe blank/None.
    """
    ftype = field_def['type']
    label = field_def['label']

    if is_unknown_raw(raw_val):
        if ftype in ('str', 'text'):
            return '', None
        if ftype in ('list_str', 'list_int'):
            return [], None
        if ftype == 'json_dict':
            return {}, None
        return None, None

    if ftype == 'str':
        return str(raw_val).strip()[:255], None

    if ftype == 'text':
        return str(raw_val).strip(), None

    if ftype == 'int':
        try:
            text = str(raw_val).strip().replace(',', '')
            val = int(float(text)) if '.' in text and float(text).is_integer() else int(text)
        except (TypeError, ValueError):
            return None, f'{label} must be a whole integer.'
        if val < 0:
            return None, f'{label} cannot be negative.'
        return val, None

    if ftype == 'decimal':
        try:
            val = Decimal(str(raw_val).strip().replace(',', ''))
        except (InvalidOperation, ValueError):
            return None, f'{label} must be a valid decimal number.'
        if val < 0:
            return None, f'{label} cannot be negative.'
        return val, None

    if ftype == 'bool':
        if isinstance(raw_val, bool):
            return raw_val, None
        lowered = str(raw_val).strip().lower()
        if lowered in ('true', '1', 'yes', 'y'):
            return True, None
        if lowered in ('false', '0', 'no', 'n'):
            return False, None
        if lowered in UNKNOWN_SENTINELS:
            return None, None
        return None, f'{label} must be Yes, No, or Unknown.'

    if ftype == 'list_str':
        if isinstance(raw_val, list):
            items = [str(item).strip() for item in raw_val if str(item).strip()]
            return items, None
        text = str(raw_val).strip()
        if text.startswith('['):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()], None
            except json.JSONDecodeError:
                pass
        items = [part.strip() for part in text.split(',') if part.strip()]
        return items, None

    if ftype == 'list_int':
        if isinstance(raw_val, list):
            raw_items = raw_val
        else:
            text = str(raw_val).strip()
            if text.startswith('['):
                try:
                    parsed = json.loads(text)
                    raw_items = parsed if isinstance(parsed, list) else [text]
                except json.JSONDecodeError:
                    raw_items = [p.strip() for p in text.split(',') if p.strip()]
            else:
                raw_items = [p.strip() for p in text.split(',') if p.strip()]
        result = []
        for item in raw_items:
            try:
                num = int(str(item).strip())
                if num < 0:
                    return [], f'{label} cannot include negative values.'
                result.append(num)
            except (TypeError, ValueError):
                return [], f'{label} must contain whole numbers separated by commas.'
        return result, None

    if ftype == 'json_dict':
        if isinstance(raw_val, dict):
            return raw_val, None
        text = str(raw_val).strip()
        if not text:
            return {}, None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}, f'{label} must be a valid JSON object (e.g. {{"pcie_8pin": 2}}).'
        if not isinstance(parsed, dict):
            return {}, f'{label} must be a JSON key/value object.'
        return parsed, None

    return raw_val, None


def format_spec_for_input(field_def: dict, value) -> str:
    """Format a HardwareSpecProfile value cleanly for an HTML input or CSV cell."""
    if value is None:
        return ''
    ftype = field_def['type']
    if ftype == 'bool':
        return 'true' if value else 'false'
    if ftype in ('list_str', 'list_int'):
        return ', '.join(str(v) for v in value) if value else ''
    if ftype == 'json_dict':
        return json.dumps(value) if value else ''
    return str(value)


CORE_COMPATIBILITY_REQUIREMENTS_BY_SLOT = {
    'cpu': [('socket',), ('cpu_family',), ('tdp_watts', 'max_power_watts'), ('supported_memory_types',)],
    'motherboard': [('socket',), ('chipset',), ('form_factor',), ('memory_type',)],
    'ram': [('memory_type',), ('ram_capacity_gb',), ('ram_modules',), ('ram_speed_mhz',)],
    'gpu': [('gpu_length_mm',), ('tdp_watts', 'max_power_watts', 'recommended_psu_watts')],
    'storage': [('storage_type',), ('storage_form_factor',)],
    'psu': [('wattage',), ('psu_form_factor',)],
    'case': [('supported_form_factors', 'form_factor'), ('max_gpu_length_mm',), ('max_cooler_height_mm',)],
    'cooler': [('cooler_type',), ('supported_sockets',), ('cooler_height_mm', 'radiator_size_mm')],
    'case_fan': [('fan_size_mm',)],
}


def has_complete_critical_specs(profile, category) -> bool:
    """
    Return True when a HardwareSpecProfile supplies the core compatibility-critical specs
    for its category slot so CompatibilityEngine, SmartAlternatives, and AI advisors can rely on it.
    """
    if profile is None or category is None:
        return False
    slot = getattr(category, 'component_slot', None) or 'other'
    requirements = CORE_COMPATIBILITY_REQUIREMENTS_BY_SLOT.get(slot)
    if not requirements:
        return not get_critical_field_names(slot)

    for candidate_fields in requirements:
        if not any(not is_unknown_raw(getattr(profile, fname, None)) for fname in candidate_fields):
            return False
    return True


def normalize_socket(value: str) -> str:
    """Normalize common socket formatting differences (e.g. 'FCLGA1700', 'LGA 1700', 'Socket AM5')."""
    if not value:
        return ''
    text = re.sub(r'\s+', ' ', str(value).strip())
    upper = text.upper()
    if upper.startswith('SOCKET '):
        upper = upper[7:].strip()
    if upper.startswith('FC') and 'LGA' in upper:
        upper = upper.replace('FC', '', 1).strip()
    compact = upper.replace(' ', '')
    if compact.startswith(('LGA', 'AM', 'TR', 'STR', 'SP', 'FM')):
        return compact
    return text


def normalize_cpu_family(value: str) -> str:
    """Normalize equivalent CPU generation names (e.g. 'Core 14th Gen' -> 'Intel 14th Gen')."""
    if not value:
        return ''
    text = re.sub(r'\s+', ' ', str(value).strip())
    lowered = text.lower()
    intel_gen = re.match(
        r'^(?:intel\s+)?(?:core\s+)?(\d{2})th\s+gen(?:\s+intel)?(?:\s+core)?(?:\s+processors?)?$',
        lowered,
    )
    if intel_gen:
        return f'Intel {intel_gen.group(1)}th Gen'
    if re.match(r'^(?:intel\s+)?core\s+ultra\s+(?:series\s+2|200s?)(?:\s+processors?)?$', lowered):
        return 'Intel Core Ultra 200'
    ryzen = re.match(
        r'^(?:amd\s+)?ryzen(?:\s+(threadripper))?\s+(\d{4}[a-z]?)(?:\s+series|\s+desktop|\s+processors?)?$',
        lowered,
    )
    if ryzen:
        mid = ' Threadripper' if ryzen.group(1) else ''
        return f'Ryzen{mid} {ryzen.group(2).upper()}'
    return text
