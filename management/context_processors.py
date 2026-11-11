from management.permissions import (
    can_access_portal,
    get_portal_role_label,
    is_owner,
)


def portal_context(request):
    """Expose staff portal visibility flags without leaking portal details to customers."""
    user = getattr(request, 'user', None)
    if not can_access_portal(user):
        return {
            'can_access_portal': False,
            'is_portal_owner': False,
            'portal_role_label': '',
        }
    return {
        'can_access_portal': True,
        'is_portal_owner': is_owner(user),
        'portal_role_label': get_portal_role_label(user),
    }
