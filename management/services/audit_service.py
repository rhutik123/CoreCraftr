import ipaddress
import json

from management.models import AuditLog
from management.permissions import get_portal_role_label

SENSITIVE_KEY_TOKENS = ('password', 'secret', 'token', 'api_key', 'credential', 'private_key')


def get_client_ip(request) -> str | None:
    """Extract and validate client IP address from Django request."""
    if not request:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    candidate = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '').strip()
    if not candidate:
        return None
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        return None


def _sanitize_json_payload(value):
    """Strip sensitive keys and normalize non-JSON types into JSON-safe representations."""
    if isinstance(value, dict):
        cleaned = {}
        for k, v in value.items():
            key_str = str(k)
            lowered = key_str.lower()
            if any(tok in lowered for tok in SENSITIVE_KEY_TOKENS):
                cleaned[key_str] = '[REDACTED]'
            else:
                cleaned[key_str] = _sanitize_json_payload(v)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_sanitize_json_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def log_portal_action(
    *,
    actor,
    action: str,
    target_type: str,
    target_id='',
    target_label: str = '',
    before_data=None,
    after_data=None,
    summary: str = '',
    request=None,
    ip_address=None,
) -> AuditLog:
    """Create an immutable append-only AuditLog record for a portal operation."""
    actor_user = actor if actor and getattr(actor, 'is_authenticated', False) else None
    username = actor_user.username if actor_user else 'system'
    role_label = get_portal_role_label(actor_user) if actor_user else 'System'
    resolved_ip = ip_address if ip_address is not None else get_client_ip(request)

    return AuditLog.objects.create(
        actor=actor_user,
        actor_username=username,
        actor_role=role_label,
        action=action[:80],
        target_type=target_type[:60],
        target_id=str(target_id)[:64] if target_id not in (None, '') else '',
        target_label=(target_label or '')[:255],
        before_data=_sanitize_json_payload(before_data or {}),
        after_data=_sanitize_json_payload(after_data or {}),
        summary=summary or '',
        ip_address=resolved_ip,
    )
