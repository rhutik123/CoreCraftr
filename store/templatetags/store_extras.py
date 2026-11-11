from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


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
