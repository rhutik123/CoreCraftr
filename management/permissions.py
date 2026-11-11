from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.views import redirect_to_login
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

INVENTORY_MANAGER_GROUP_NAME = 'Inventory Manager'

INVENTORY_MANAGER_PERM_CODENAMES = (
    'access_portal',
    'manage_products',
    'manage_inventory',
    'manage_prices',
    'use_ai_research',
    'import_export_catalog',
    'view_reports',
)

OWNER_ONLY_PERM_CODENAMES = (
    'manage_users',
    'view_audit_log',
)

ALL_PORTAL_PERM_CODENAMES = INVENTORY_MANAGER_PERM_CODENAMES + OWNER_ONLY_PERM_CODENAMES


def ensure_portal_roles():
    """Ensure the 'Inventory Manager' group holds exact portal permissions."""
    from management.models import PortalPermission

    ct = ContentType.objects.get_for_model(PortalPermission)
    perms_by_code = {
        perm.codename: perm
        for perm in Permission.objects.filter(
            content_type=ct,
            codename__in=ALL_PORTAL_PERM_CODENAMES,
        )
    }
    group, _ = Group.objects.get_or_create(name=INVENTORY_MANAGER_GROUP_NAME)
    manager_perms = [
        perms_by_code[code]
        for code in INVENTORY_MANAGER_PERM_CODENAMES
        if code in perms_by_code
    ]
    if manager_perms:
        group.permissions.set(manager_perms)
    return group


def is_owner(user) -> bool:
    """Return True if user is an active Django superuser (Owner)."""
    return bool(user and getattr(user, 'is_authenticated', False) and user.is_active and user.is_superuser)


def is_inventory_manager(user) -> bool:
    """Return True if user is an active non-superuser granted portal access."""
    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and user.is_active
        and not user.is_superuser
        and user.has_perm('management.access_portal')
    )


def can_access_portal(user) -> bool:
    """Return True if user is an Owner or authorized Inventory Manager."""
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    return bool(user.is_superuser or user.has_perm('management.access_portal'))


def get_portal_role_label(user) -> str:
    """Return human-readable portal role label for UI and audit trails."""
    if is_owner(user):
        return 'Owner'
    if is_inventory_manager(user):
        return 'Inventory Manager'
    return 'Customer'


def ensure_not_last_active_superuser(target_user) -> bool:
    """Return True if another active superuser exists besides target_user."""
    if not target_user or not target_user.is_superuser or not target_user.is_active:
        return True
    User = get_user_model()
    return User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target_user.pk).exists()


def _has_all_portal_perms(user, perm_codenames) -> bool:
    if not can_access_portal(user):
        return False
    for code in perm_codenames:
        full_perm = code if '.' in code else f'management.{code}'
        if not user.has_perm(full_perm):
            return False
    return True


def portal_permission_required(*perm_codenames):
    """Require authenticated active staff user with management.access_portal and listed perms."""
    required = perm_codenames or ('access_portal',)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not _has_all_portal_perms(request.user, required):
                raise PermissionDenied('You do not have permission to access this management resource.')
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def owner_required(view_func):
    """Restrict view strictly to active superusers (Owners)."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_owner(request.user):
            raise PermissionDenied('Only the Store Owner can access this management area.')
        return view_func(request, *args, **kwargs)

    return _wrapped


def portal_api_permission_required(*perm_codenames):
    """Enforce JSON 401/403 authentication & RBAC on AJAX/API portal endpoints."""
    required = perm_codenames or ('access_portal',)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'Authentication required.'}, status=401)
            if not _has_all_portal_perms(request.user, required):
                return JsonResponse({'error': 'Permission denied for this management action.'}, status=403)
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
