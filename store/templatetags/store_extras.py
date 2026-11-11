from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()

_ICON_MAP = {
    'bi-cpu': 'cpu',
    'bi-cpu-fill': 'cpu',
    'bi-motherboard': 'circuit-board',
    'bi-memory': 'memory-stick',
    'bi-gpu-card': 'microchip',
    'bi-nvme': 'hard-drive',
    'bi-device-hdd': 'database',
    'bi-lightning-charge': 'zap',
    'bi-pc': 'pc-case',
    'bi-pc-display': 'pc-case',
    'bi-fan': 'fan',
    'bi-wind': 'wind',
    'bi-display': 'monitor',
    'bi-keyboard': 'keyboard',
    'bi-mouse': 'mouse',
    'bi-plug': 'cable',
    'bi-tools': 'wrench',
    'bi-sliders': 'sliders-horizontal',
    'bi-magic': 'sparkles',
    'bi-check-circle-fill': 'circle-check',
    'bi-check-circle': 'circle-check',
    'bi-exclamation-octagon-fill': 'octagon-alert',
    'bi-x-octagon-fill': 'octagon-alert',
    'bi-exclamation-triangle-fill': 'triangle-alert',
    'bi-exclamation-triangle': 'triangle-alert',
    'bi-question-circle-fill': 'circle-help',
    'bi-question-circle': 'circle-help',
    'bi-shield-check': 'shield-check',
    'bi-info-circle': 'info',
    'bi-box-seam': 'package',
    'bi-cart3': 'shopping-cart',
    'bi-cart-plus': 'shopping-cart',
    'bi-heart': 'heart',
    'bi-heart-fill': 'heart',
    'bi-columns-gap': 'columns-3',
}

_SLOT_ICON_MAP = {
    'cpu': 'cpu',
    'motherboard': 'circuit-board',
    'ram': 'memory-stick',
    'gpu': 'microchip',
    'storage': 'hard-drive',
    'storage_secondary': 'database',
    'psu': 'zap',
    'case': 'pc-case',
    'cooler': 'fan',
    'case_fan': 'wind',
    'monitor': 'monitor',
    'keyboard': 'keyboard',
    'mouse': 'mouse',
    'accessory': 'cable',
}


def format_inr(value, decimals: int = 2) -> str:
    """Format numeric amounts in authentic Indian numbering (e.g. ₹10,799.00, ₹1,25,000.00)."""
    if value is None or value == '':
        return f'₹0.{"0" * decimals}' if decimals > 0 else '₹0'
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)

    sign = '-' if dec < 0 else ''
    dec = abs(dec)
    if decimals > 0:
        formatted = f'{dec:.{decimals}f}'
        int_part, frac_part = formatted.split('.')
    else:
        int_part = f'{dec:.0f}'
        frac_part = ''

    if len(int_part) > 3:
        last_three = int_part[-3:]
        rest = int_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.append(rest)
        int_grouped = ','.join(reversed(groups)) + ',' + last_three
    else:
        int_grouped = int_part

    if decimals > 0:
        return f'{sign}₹{int_grouped}.{frac_part}'
    return f'{sign}₹{int_grouped}'


@register.filter(name='inr')
def inr_filter(value, decimals: int = 2) -> str:
    try:
        dec_count = int(decimals)
    except (ValueError, TypeError):
        dec_count = 2
    return format_inr(value, decimals=dec_count)


@register.filter(name='inr_whole')
def inr_whole_filter(value) -> str:
    return format_inr(value, decimals=0)


@register.filter(name='lucide_icon')
def lucide_icon_filter(value: str, fallback: str = 'cpu') -> str:
    """Resolve Bootstrap bi-* icon classes or hardware slot keys into verified Lucide icon names."""
    if not value:
        return fallback
    key = str(value).strip().lower()
    if key in _ICON_MAP:
        return _ICON_MAP[key]
    if key in _SLOT_ICON_MAP:
        return _SLOT_ICON_MAP[key]
    if not key.startswith('bi-'):
        return key
    return fallback
