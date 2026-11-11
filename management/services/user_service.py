from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from management.permissions import (
    INVENTORY_MANAGER_GROUP_NAME,
    ensure_not_last_active_superuser,
    ensure_portal_roles,
    get_portal_role_label,
    is_inventory_manager,
    is_owner,
)
from management.services.audit_service import log_portal_action


def list_portal_users(query: str = '') -> list[dict]:
    """Return all user accounts annotated with server-derived portal role metadata."""
    User = get_user_model()
    qs = User.objects.prefetch_related('groups').order_by('-is_superuser', 'username')
    if query:
        q = query.strip()
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )

    rows = []
    for user in qs:
        rows.append({
            'user': user,
            'role_label': get_portal_role_label(user),
            'is_owner': user.is_superuser,
            'is_manager': is_inventory_manager(user),
            'can_be_disabled': not (user.is_superuser and not ensure_not_last_active_superuser(user)),
        })
    return rows


def _require_owner(actor):
    if not is_owner(actor):
        raise PermissionDenied('Only an active Store Owner can manage user access or roles.')


@transaction.atomic
def grant_inventory_manager(*, actor, target_user_id: int, request=None):
    """Grant 'Inventory Manager' portal group to an existing user without granting superuser/admin."""
    _require_owner(actor)
    User = get_user_model()
    target = User.objects.select_for_update().filter(pk=target_user_id).first()
    if not target:
        raise ValidationError('Target user not found.')
    if target.is_superuser:
        raise ValidationError('Owner (superuser) accounts already hold full access.')
    if not target.is_active:
        raise ValidationError('Activate the user account before assigning a staff role.')

    before_role = get_portal_role_label(target)
    group = ensure_portal_roles()
    target.groups.add(group)

    log_portal_action(
        actor=actor,
        action='user.role_granted',
        target_type='user',
        target_id=target.id,
        target_label=target.username,
        before_data={'role': before_role},
        after_data={'role': 'Inventory Manager', 'group': INVENTORY_MANAGER_GROUP_NAME},
        summary=f'Granted Inventory Manager access to "{target.username}".',
        request=request,
    )
    return target


@transaction.atomic
def revoke_inventory_manager(*, actor, target_user_id: int, request=None):
    """Revoke 'Inventory Manager' group access, returning user cleanly to standard Customer role."""
    _require_owner(actor)
    User = get_user_model()
    target = User.objects.select_for_update().filter(pk=target_user_id).first()
    if not target:
        raise ValidationError('Target user not found.')
    if target.is_superuser:
        raise ValidationError('Superuser accounts cannot be modified from staff role assignment.')

    before_role = get_portal_role_label(target)
    group = ensure_portal_roles()
    target.groups.remove(group)
    # Remove any accidental direct management permissions
    direct_mgmt_perms = target.user_permissions.filter(content_type__app_label='management')
    if direct_mgmt_perms.exists():
        target.user_permissions.remove(*direct_mgmt_perms)

    log_portal_action(
        actor=actor,
        action='user.role_revoked',
        target_type='user',
        target_id=target.id,
        target_label=target.username,
        before_data={'role': before_role},
        after_data={'role': 'Customer'},
        summary=f'Revoked Inventory Manager access from "{target.username}".',
        request=request,
    )
    return target


@transaction.atomic
def set_user_active_state(*, actor, target_user_id: int, is_active: bool, request=None):
    """Activate or deactivate an account while strictly protecting active superusers."""
    _require_owner(actor)
    User = get_user_model()
    target = User.objects.select_for_update().filter(pk=target_user_id).first()
    if not target:
        raise ValidationError('Target user not found.')

    if not is_active:
        if actor.pk == target.pk:
            raise ValidationError('You cannot deactivate your own active Owner session.')
        if target.is_superuser:
            if not ensure_not_last_active_superuser(target):
                raise ValidationError('Cannot deactivate the last active Owner (superuser) account.')
            raise ValidationError('Owner (superuser) accounts cannot be deactivated via portal user management.')

    prev_active = target.is_active
    target.is_active = bool(is_active)
    target.save(update_fields=['is_active'])

    action = 'user.activated' if target.is_active else 'user.deactivated'
    log_portal_action(
        actor=actor,
        action=action,
        target_type='user',
        target_id=target.id,
        target_label=target.username,
        before_data={'is_active': prev_active},
        after_data={'is_active': target.is_active},
        summary=f'{"Activated" if target.is_active else "Deactivated"} account "{target.username}".',
        request=request,
    )
    return target


@transaction.atomic
def create_inventory_manager_account(
    *,
    actor,
    username: str,
    email: str,
    password: str,
    first_name: str = '',
    last_name: str = '',
    request=None,
):
    """Allow an Owner to create a new Inventory Manager account safely."""
    _require_owner(actor)
    User = get_user_model()

    clean_username = (username or '').strip()
    clean_email = (email or '').strip()
    if not clean_username:
        raise ValidationError('Username is required.')
    if User.objects.filter(username__iexact=clean_username).exists():
        raise ValidationError(f'Username "{clean_username}" is already taken.')

    candidate = User(
        username=clean_username,
        email=clean_email,
        first_name=(first_name or '').strip(),
        last_name=(last_name or '').strip(),
        is_staff=False,
        is_superuser=False,
        is_active=True,
    )
    validate_password(password, user=candidate)
    candidate.set_password(password)
    candidate.save()

    group = ensure_portal_roles()
    candidate.groups.add(group)

    log_portal_action(
        actor=actor,
        action='user.staff_created',
        target_type='user',
        target_id=candidate.id,
        target_label=candidate.username,
        after_data={'username': candidate.username, 'email': candidate.email, 'role': 'Inventory Manager'},
        summary=f'Created Inventory Manager account "{candidate.username}".',
        request=request,
    )
    return candidate
