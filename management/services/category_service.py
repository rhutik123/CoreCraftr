from django.db import transaction
from django.db.models import Count, Q

from management.services.audit_service import log_portal_action
from store.models import Category, Product


def list_categories_with_counts(
    *,
    q: str = '',
    status_filter: str = '',
    slot_filter: str = '',
    pc_filter: str = '',
):
    """Return categories annotated with total and published product counts, filtered by query params."""
    qs = Category.objects.annotate(
        total_products=Count('products', distinct=True),
        published_products=Count(
            'products',
            filter=Q(products__status=Product.STATUS_PUBLISHED),
            distinct=True,
        ),
    )

    q_clean = (q or '').strip()
    if q_clean:
        qs = qs.filter(
            Q(name__icontains=q_clean)
            | Q(slug__icontains=q_clean)
            | Q(description__icontains=q_clean)
        )

    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    if slot_filter:
        qs = qs.filter(component_slot=slot_filter)

    if pc_filter == 'yes':
        qs = qs.filter(is_pc_component=True)
    elif pc_filter == 'no':
        qs = qs.filter(is_pc_component=False)

    return qs.order_by('display_order', 'name')


def _snapshot_category(cat: Category) -> dict:
    return {
        'id': cat.pk,
        'name': cat.name,
        'slug': cat.slug,
        'component_slot': cat.component_slot,
        'description': cat.description,
        'icon_class': cat.icon_class,
        'display_order': cat.display_order,
        'is_pc_component': cat.is_pc_component,
        'show_in_nav': cat.show_in_nav,
        'is_active': cat.is_active,
    }


@transaction.atomic
def save_category(*, cleaned_data: dict, actor, request=None, category: Category | None = None) -> Category:
    """Create or update a Category with model validation and audit logging."""
    is_create = category is None
    before_data = _snapshot_category(category) if category else {}

    target = category or Category()
    target.name = cleaned_data['name']
    target.slug = cleaned_data['slug']
    target.component_slot = cleaned_data['component_slot']
    target.description = cleaned_data.get('description', '')
    target.icon_class = cleaned_data.get('icon_class') or 'bi-cpu'
    target.display_order = cleaned_data.get('display_order') or 0
    target.is_pc_component = bool(cleaned_data.get('is_pc_component'))
    target.show_in_nav = bool(cleaned_data.get('show_in_nav'))
    target.is_active = bool(cleaned_data.get('is_active'))

    target.full_clean()
    target.save()

    log_portal_action(
        actor=actor,
        action='create_category' if is_create else 'update_category',
        target_type='Category',
        target_id=target.pk,
        target_label=target.name,
        before_data=before_data,
        after_data=_snapshot_category(target),
        summary=f'{"Created" if is_create else "Updated"} category "{target.name}" ({target.slug}).',
        request=request,
    )
    return target


@transaction.atomic
def toggle_category_active(*, category: Category, actor, request=None) -> Category:
    """Activate or deactivate a Category and record the audit trail."""
    before_data = _snapshot_category(category)
    category.is_active = not category.is_active
    category.save(update_fields=['is_active'])

    state_label = 'Activated' if category.is_active else 'Deactivated'
    log_portal_action(
        actor=actor,
        action='toggle_category_active',
        target_type='Category',
        target_id=category.pk,
        target_label=category.name,
        before_data=before_data,
        after_data=_snapshot_category(category),
        summary=f'{state_label} category "{category.name}".',
        request=request,
    )
    return category


@transaction.atomic
def delete_category_safely(*, category: Category, actor, reassign_to: Category | None = None, request=None) -> dict:
    """
    Delete a category safely. Categories that contain products cannot be deleted unless
    products are explicitly reassigned to a different category first.
    """
    products_qs = Product.objects.filter(category=category)
    product_count = products_qs.count()
    reassigned_count = 0

    if product_count > 0:
        if reassign_to is None:
            raise ValueError(
                f'Category "{category.name}" still contains {product_count} product(s). '
                'Select another category to reassign them before deleting.'
            )
        if reassign_to.pk == category.pk:
            raise ValueError('Select a different target category to reassign existing products.')
        reassigned_count = products_qs.update(category=reassign_to)

    before_data = _snapshot_category(category)
    before_data['product_count'] = product_count
    deleted_name = category.name
    deleted_id = category.pk
    category.delete()

    summary = f'Deleted category "{deleted_name}".'
    if reassigned_count > 0 and reassign_to is not None:
        summary = (
            f'Reassigned {reassigned_count} product(s) from "{deleted_name}" '
            f'to "{reassign_to.name}" and deleted "{deleted_name}".'
        )

    log_portal_action(
        actor=actor,
        action='delete_category',
        target_type='Category',
        target_id=deleted_id,
        target_label=deleted_name,
        before_data=before_data,
        after_data={
            'deleted': True,
            'reassigned_count': reassigned_count,
            'reassigned_to_id': reassign_to.pk if reassign_to else None,
            'reassigned_to_name': reassign_to.name if reassign_to else None,
        },
        summary=summary,
        request=request,
    )

    return {
        'deleted_name': deleted_name,
        'reassigned_count': reassigned_count,
        'reassigned_to_name': reassign_to.name if reassign_to else '',
    }
