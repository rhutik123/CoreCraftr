import json
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from ai_engine.services.spec_researcher import RateLimitExceededError
from management.forms import CreateManagerUserForm, CSVImportUploadForm, ProductForm, StockAdjustmentForm
from management.models import (
    AIResearchDraft,
    AuditLog,
    CSVImportBatch,
    PriceChangeLog,
    StockMovement,
)
from management.permissions import (
    is_owner,
    owner_required,
    portal_api_permission_required,
    portal_permission_required,
)
from management.services.ai_spec_service import discard_ai_draft, run_ai_spec_research
from management.services.csv_service import (
    cancel_csv_import_batch,
    confirm_csv_import_batch,
    create_csv_import_preview,
    export_products_csv,
)
from management.services.image_service import (
    delete_product_image,
    replace_product_image,
    set_primary_product_image,
)
from management.services.inventory_service import (
    adjust_stock,
    get_verified_inventory_metrics,
    inventory_version_token,
    update_inventory_settings,
)
from management.services.product_service import (
    change_product_status,
    create_or_update_product,
    find_potential_duplicates,
)
from management.services.user_service import (
    create_inventory_manager_account,
    grant_inventory_manager,
    list_portal_users,
    revoke_inventory_manager,
    set_user_active_state,
)
from management.spec_schemas import (
    SHARED_METADATA_FIELDS,
    format_spec_for_input,
    get_spec_fields_for_slot,
)
from store.models import Brand, Category, HardwareSpecProfile, Product


def _extract_spec_and_custom_inputs(post_data, slot: str):
    """Read dynamic spec_<field> values and custom specification rows from POST data."""
    spec_data = {}
    for fdef in get_spec_fields_for_slot(slot) + SHARED_METADATA_FIELDS:
        key = fdef['name']
        field_key = f'spec_{key}'
        if field_key in post_data:
            spec_data[key] = post_data.get(field_key, '')

    custom_groups = post_data.getlist('custom_spec_group[]')
    custom_keys = post_data.getlist('custom_spec_key[]')
    custom_values = post_data.getlist('custom_spec_value[]')
    custom_units = post_data.getlist('custom_spec_unit[]')

    custom_specs = []
    for idx, key in enumerate(custom_keys):
        clean_key = (key or '').strip()
        clean_val = (custom_values[idx] if idx < len(custom_values) else '').strip()
        if clean_key and clean_val:
            custom_specs.append({
                'spec_group': (custom_groups[idx] if idx < len(custom_groups) else 'Additional').strip() or 'Additional',
                'spec_key': clean_key,
                'spec_value': clean_val,
                'unit': (custom_units[idx] if idx < len(custom_units) else '').strip(),
                'is_verified': True,
            })
    return spec_data, custom_specs


def _build_initial_spec_rows(slot: str, profile: HardwareSpecProfile | None, post_data=None) -> list[dict]:
    """Assemble typed category spec fields with current values for server-rendered form rendering."""
    rows = []
    for fdef in get_spec_fields_for_slot(slot):
        fname = fdef['name']
        if post_data is not None and f'spec_{fname}' in post_data:
            val_str = post_data.get(f'spec_{fname}', '')
        elif profile is not None:
            val_str = format_spec_for_input(fdef, getattr(profile, fname, None))
        else:
            val_str = ''
        rows.append({
            **fdef,
            'current_value': val_str,
        })
    return rows


@portal_permission_required('access_portal')
def dashboard(request):
    """Live database-driven overview for Store Owners and Inventory Managers."""
    metrics = get_verified_inventory_metrics()
    recent_movements = StockMovement.objects.select_related('product', 'performed_by').order_by('-created_at', '-id')[:10]
    recent_products = Product.objects.select_related('category', 'brand', 'inventory', 'last_edited_by').order_by('-updated_at', '-id')[:8]
    pending_ai_drafts = AIResearchDraft.objects.filter(status=AIResearchDraft.STATUS_DRAFT).count()

    recent_audit = []
    if is_owner(request.user):
        recent_audit = AuditLog.objects.order_by('-created_at', '-id')[:6]

    return render(request, 'management/dashboard.html', {
        'active_nav': 'dashboard',
        'metrics': metrics,
        'recent_movements': recent_movements,
        'recent_products': recent_products,
        'pending_ai_drafts': pending_ai_drafts,
        'recent_audit': recent_audit,
    })


@portal_permission_required('access_portal', 'manage_products')
def product_list(request):
    """Searchable, filterable catalog table for staff product management."""
    qs = Product.objects.select_related('category', 'brand', 'inventory', 'last_edited_by').order_by('-updated_at', '-id')

    q = (request.GET.get('q') or '').strip()
    status_filter = (request.GET.get('status') or '').strip()
    category_filter = (request.GET.get('category') or '').strip()
    stock_filter = (request.GET.get('stock') or '').strip()

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(model_number__icontains=q))
    if status_filter in {c[0] for c in Product.STATUS_CHOICES}:
        qs = qs.filter(status=status_filter)
    if category_filter:
        qs = qs.filter(category__slug=category_filter)
    if stock_filter == 'out':
        qs = qs.filter(inventory__quantity__lte=0)
    elif stock_filter == 'low':
        qs = qs.filter(inventory__quantity__gt=0, inventory__quantity__lte=F('inventory__low_stock_threshold'))

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'management/product_list.html', {
        'active_nav': 'products',
        'page_obj': page_obj,
        'categories': Category.objects.order_by('display_order', 'name'),
        'q': q,
        'status_filter': status_filter,
        'category_filter': category_filter,
        'stock_filter': stock_filter,
        'status_choices': Product.STATUS_CHOICES,
    })


def _render_product_editor(request, product: Product | None = None):
    is_create = product is None
    categories = list(Category.objects.order_by('display_order', 'name'))
    selected_category = product.category if product else (categories[0] if categories else None)
    profile = getattr(product, 'spec_profile', None) if product else None
    inventory = getattr(product, 'inventory', None) if product else None

    if request.method == 'POST':
        form = ProductForm(request.POST)
        post_cat_id = request.POST.get('category')
        if post_cat_id:
            cat_match = Category.objects.filter(pk=post_cat_id).first()
            if cat_match:
                selected_category = cat_match

        slot = selected_category.component_slot if selected_category else 'other'
        spec_data, custom_specs = _extract_spec_and_custom_inputs(request.POST, slot)
        duplicate_warnings = []

        if form.is_valid():
            cd = form.cleaned_data
            brand = cd.get('brand')
            new_brand_name = (cd.get('new_brand_name') or '').strip()
            if not brand and new_brand_name:
                brand = Brand.objects.filter(name__iexact=new_brand_name).first()
                if not brand:
                    brand, _ = Brand.objects.get_or_create(
                        slug=slugify(new_brand_name)[:140] or 'brand',
                        defaults={'name': new_brand_name[:120]},
                    )

            ai_draft_id = request.POST.get('ai_draft_id') or None
            if ai_draft_id:
                try:
                    ai_draft_id = int(ai_draft_id)
                except ValueError:
                    ai_draft_id = None

            if ai_draft_id and not request.POST.get('confirm_ai_approval'):
                messages.error(
                    request,
                    'Check "I reviewed and approve these AI-researched specifications" before saving an AI draft.',
                )
            else:
                uploaded_files = request.FILES.getlist('gallery_images')
                try:
                    saved_product = create_or_update_product(
                        product=product,
                        product_data={
                            'name': cd['name'],
                            'sku': cd.get('sku', ''),
                            'model_number': cd.get('model_number', ''),
                            'category': cd['category'],
                            'brand': brand,
                            'status': cd['status'],
                            'price': cd['price'],
                            'cost_price': cd.get('cost_price'),
                            'warranty_months': cd.get('warranty_months', 36),
                            'short_description': cd.get('short_description', ''),
                            'description': cd.get('description', ''),
                            'is_featured': cd.get('is_featured', False),
                            'digital': cd.get('digital', False),
                        },
                        spec_data=spec_data,
                        custom_specs=custom_specs,
                        initial_quantity=cd.get('initial_quantity') if is_create else None,
                        low_stock_threshold=cd.get('low_stock_threshold'),
                        restock_date=cd.get('restock_date'),
                        uploaded_files=uploaded_files,
                        price_change_reason=cd.get('price_change_reason', ''),
                        ai_draft_id=ai_draft_id,
                        actor=request.user,
                        request=request,
                    )
                    messages.success(
                        request,
                        f'{"Created" if is_create else "Updated"} product "{saved_product.name}" ({saved_product.sku}).',
                    )
                    return redirect('management:product_edit', product_id=saved_product.id)
                except ValidationError as exc:
                    for err in exc.messages:
                        messages.error(request, err)
                    duplicate_warnings = find_potential_duplicates(
                        name=cd.get('name', ''),
                        sku=cd.get('sku', ''),
                        model_number=cd.get('model_number', ''),
                        brand=brand,
                        category=cd.get('category'),
                        exclude_product_id=product.id if product else None,
                    )
        else:
            for field_name, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f'{field_name}: {err}')

        spec_rows = _build_initial_spec_rows(slot, profile, post_data=request.POST)
        existing_custom_specs = custom_specs
        perf_tier_val = request.POST.get('spec_performance_tier', profile.performance_tier if profile else 'midrange')
        benchmark_val = request.POST.get('spec_benchmark_score', profile.benchmark_score if profile else '')
        beginner_summary_val = request.POST.get('spec_beginner_summary', profile.beginner_summary if profile else '')
        tradeoffs_val = request.POST.get('spec_tradeoffs_note', profile.tradeoffs_note if profile else '')
    else:
        initial = {}
        if product:
            initial = {
                'name': product.name,
                'sku': product.sku,
                'model_number': product.model_number,
                'category': product.category_id,
                'brand': product.brand_id,
                'status': product.status,
                'price': product.price,
                'cost_price': product.cost_price,
                'warranty_months': product.warranty_months,
                'short_description': product.short_description,
                'description': product.description,
                'is_featured': product.is_featured,
                'digital': product.digital,
                'low_stock_threshold': inventory.low_stock_threshold if inventory else 3,
                'restock_date': inventory.restock_date if inventory else None,
            }
        elif selected_category:
            initial = {'category': selected_category.id, 'status': Product.STATUS_DRAFT}
        form = ProductForm(initial=initial)
        slot = selected_category.component_slot if selected_category else 'other'
        spec_rows = _build_initial_spec_rows(slot, profile, post_data=None)
        existing_custom_specs = (
            list(product.specifications.values('spec_group', 'spec_key', 'spec_value', 'unit'))
            if product else []
        )
        duplicate_warnings = (
            find_potential_duplicates(
                name=product.name,
                sku=product.sku,
                model_number=product.model_number,
                brand=product.brand,
                category=product.category,
                exclude_product_id=product.id,
            )
            if product else []
        )
        perf_tier_val = profile.performance_tier if profile else 'midrange'
        benchmark_val = profile.benchmark_score if profile and profile.benchmark_score is not None else ''
        beginner_summary_val = profile.beginner_summary if profile else ''
        tradeoffs_val = profile.tradeoffs_note if profile else ''

    return render(request, 'management/product_form.html', {
        'active_nav': 'products',
        'is_create': is_create,
        'product': product,
        'inventory': inventory,
        'gallery_images': list(product.gallery_images.all()) if product else [],
        'form': form,
        'selected_category': selected_category,
        'spec_rows': spec_rows,
        'existing_custom_specs': existing_custom_specs,
        'duplicate_warnings': duplicate_warnings,
        'performance_tier_choices': HardwareSpecProfile.PERFORMANCE_TIER_CHOICES,
        'perf_tier_val': perf_tier_val,
        'benchmark_val': benchmark_val,
        'beginner_summary_val': beginner_summary_val,
        'tradeoffs_val': tradeoffs_val,
        'price_history': list(product.price_changes.select_related('changed_by')[:8]) if product else [],
        'recent_stock_movements': list(product.stock_movements.select_related('performed_by')[:8]) if product else [],
    })


@portal_permission_required('access_portal', 'manage_products')
def product_create(request):
    """Create new hardware product with dynamic category specifications and multi-image upload."""
    return _render_product_editor(request, product=None)


@portal_permission_required('access_portal', 'manage_products')
def product_edit(request, product_id: int):
    """Edit existing hardware product, gallery images, specifications, and status."""
    product = get_object_or_404(
        Product.objects.select_related('category', 'brand', 'inventory', 'spec_profile'),
        pk=product_id,
    )
    return _render_product_editor(request, product=product)


@require_POST
@portal_permission_required('access_portal', 'manage_products')
def product_change_status(request, product_id: int):
    target_status = (request.POST.get('status') or '').strip()
    try:
        prod = change_product_status(
            product_id=product_id,
            new_status=target_status,
            actor=request.user,
            request=request,
        )
        messages.success(request, f'Product "{prod.sku}" status updated to {prod.get_status_display()}.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    next_url = request.POST.get('next') or ''
    if next_url.startswith('/management/'):
        return redirect(next_url)
    return redirect('management:product_edit', product_id=product_id)


@require_POST
@portal_permission_required('access_portal', 'manage_products')
def product_image_set_primary(request, product_id: int, image_id: int):
    product = get_object_or_404(Product, pk=product_id)
    try:
        set_primary_product_image(product, image_id, actor=request.user, request=request)
        messages.success(request, 'Updated primary product image.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('management:product_edit', product_id=product.id)


@require_POST
@portal_permission_required('access_portal', 'manage_products')
def product_image_replace(request, product_id: int, image_id: int):
    product = get_object_or_404(Product, pk=product_id)
    replacement = request.FILES.get('replacement_image')
    try:
        replace_product_image(product, image_id, replacement, actor=request.user, request=request)
        messages.success(request, 'Replaced product gallery image.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('management:product_edit', product_id=product.id)


@require_POST
@portal_permission_required('access_portal', 'manage_products')
def product_image_delete(request, product_id: int, image_id: int):
    product = get_object_or_404(Product, pk=product_id)
    try:
        delete_product_image(product, image_id, actor=request.user, request=request)
        messages.success(request, 'Removed image from product gallery.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('management:product_edit', product_id=product.id)


@require_GET
@portal_api_permission_required('access_portal', 'manage_products')
def api_category_spec_schema(request, category_id: int):
    """Return dynamic spec field definitions for a selected Category."""
    category = Category.objects.filter(pk=category_id).first()
    if not category:
        return JsonResponse({'error': 'Category not found.'}, status=404)
    return JsonResponse({
        'category_id': category.id,
        'category_name': category.name,
        'component_slot': category.component_slot,
        'fields': get_spec_fields_for_slot(category.component_slot),
    })


@require_GET
@portal_api_permission_required('access_portal', 'manage_products')
def api_duplicate_check(request):
    """Advisory real-time duplicate lookup across SKU, model number, brand, and name."""
    exclude_id = request.GET.get('exclude_id')
    try:
        exclude_int = int(exclude_id) if exclude_id else None
    except ValueError:
        exclude_int = None

    cat_id = request.GET.get('category_id')
    brand_id = request.GET.get('brand_id')
    category = Category.objects.filter(pk=cat_id).first() if cat_id and cat_id.isdigit() else None
    brand = Brand.objects.filter(pk=brand_id).first() if brand_id and brand_id.isdigit() else None

    matches = find_potential_duplicates(
        name=request.GET.get('name', ''),
        sku=request.GET.get('sku', ''),
        model_number=request.GET.get('model_number', ''),
        brand=brand,
        category=category,
        exclude_product_id=exclude_int,
    )
    return JsonResponse({'matches': matches})


@require_POST
@portal_api_permission_required('access_portal', 'use_ai_research')
def api_ai_research_specs(request):
    """Execute schema-validated, rate-limited AI product specification research."""
    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else request.POST
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON request payload.'}, status=400)

    product_name = (payload.get('product_name') or '').strip()
    category_id = payload.get('category_id')
    brand_name = (payload.get('brand_name') or '').strip()
    model_number = (payload.get('model_number') or '').strip()
    reference_url = (payload.get('reference_url') or '').strip()
    product_id = payload.get('product_id')

    if not category_id:
        return JsonResponse({'error': 'Category selection is required before researching specs.'}, status=400)
    category = Category.objects.filter(pk=category_id).first()
    if not category:
        return JsonResponse({'error': 'Selected category does not exist.'}, status=400)

    product = Product.objects.filter(pk=product_id).first() if product_id else None

    try:
        draft = run_ai_spec_research(
            actor=request.user,
            product_name=product_name,
            category=category,
            brand_name=brand_name,
            model_number=model_number,
            reference_url=reference_url,
            product=product,
            request=request,
        )
    except RateLimitExceededError as exc:
        return JsonResponse({'error': str(exc), 'rate_limited': True}, status=429)
    except ValidationError as exc:
        return JsonResponse({'error': '; '.join(exc.messages)}, status=400)

    return JsonResponse({
        'draft_id': draft.id,
        'status': draft.status,
        'available': draft.status != AIResearchDraft.STATUS_UNAVAILABLE,
        'verification_status': draft.verification_status,
        'verification_label': draft.get_verification_status_display(),
        'confidence': draft.confidence,
        'proposed_specs': draft.proposed_specs,
        'custom_specs': draft.custom_specs,
        'sources': draft.sources,
        'missing_fields': draft.missing_fields,
        'conflicting_fields': draft.conflicting_fields,
        'rejected_fields': draft.rejected_fields,
        'summary_note': draft.summary_note,
    })


@require_POST
@portal_api_permission_required('access_portal', 'use_ai_research')
def api_ai_draft_discard(request, draft_id: int):
    try:
        draft = discard_ai_draft(draft_id=draft_id, actor=request.user, request=request)
        return JsonResponse({'draft_id': draft.id, 'status': draft.status})
    except ValidationError as exc:
        return JsonResponse({'error': '; '.join(exc.messages)}, status=404)


@portal_permission_required('access_portal', 'manage_inventory')
def inventory_list(request):
    """Inventory control screen with quick atomic stock adjustments & threshold controls."""
    qs = Product.objects.select_related('category', 'brand', 'inventory').order_by('inventory__quantity', 'sku')
    q = (request.GET.get('q') or '').strip()
    state = (request.GET.get('state') or '').strip()

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if state == 'out':
        qs = qs.filter(inventory__quantity__lte=0)
    elif state == 'low':
        qs = qs.filter(inventory__quantity__gt=0, inventory__quantity__lte=F('inventory__low_stock_threshold'))
    elif state == 'healthy':
        qs = qs.filter(inventory__quantity__gt=F('inventory__low_stock_threshold'))

    items = []
    for prod in qs:
        inv = getattr(prod, 'inventory', None)
        items.append({
            'product': prod,
            'inventory': inv,
            'version_token': inventory_version_token(inv) if inv else '',
        })

    paginator = Paginator(items, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'management/inventory_list.html', {
        'active_nav': 'inventory',
        'page_obj': page_obj,
        'q': q,
        'state': state,
        'mode_choices': StockAdjustmentForm.MODE_CHOICES,
        'reason_choices': StockAdjustmentForm.REASON_CHOICES,
    })


@require_POST
@portal_permission_required('access_portal', 'manage_inventory')
def inventory_adjust(request, product_id: int):
    form = StockAdjustmentForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Provide valid stock adjustment quantity, mode, and reason.')
        return redirect('management:inventory_list')

    cd = form.cleaned_data
    try:
        movement = adjust_stock(
            product_id=product_id,
            adjustment_mode=cd['adjustment_mode'],
            quantity_value=cd['quantity_value'],
            reason=cd['reason'],
            notes=cd.get('notes', ''),
            actor=request.user,
            request=request,
            expected_version_token=cd.get('expected_version_token'),
        )
        messages.success(
            request,
            f'Updated stock for {movement.product.sku}: {movement.previous_quantity} -> {movement.new_quantity}.',
        )
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('management:inventory_list')


@require_POST
@portal_permission_required('access_portal', 'manage_inventory')
def inventory_settings(request, product_id: int):
    threshold = request.POST.get('low_stock_threshold', 3)
    raw_date = (request.POST.get('restock_date') or '').strip()
    parsed_date = None
    if raw_date:
        try:
            parsed_date = date.fromisoformat(raw_date)
        except ValueError:
            messages.error(request, 'Invalid restock date format (expected YYYY-MM-DD).')
            return redirect('management:inventory_list')

    try:
        inv = update_inventory_settings(
            product_id=product_id,
            low_stock_threshold=threshold,
            restock_date=parsed_date,
            actor=request.user,
            request=request,
        )
        messages.success(
            request,
            f'Updated threshold ({inv.low_stock_threshold}) for {inv.product.sku}.',
        )
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('management:inventory_list')


@portal_permission_required('access_portal', 'manage_inventory')
def stock_history(request):
    """Filterable stock movement ledger across manual, CSV, and customer order deductions."""
    qs = StockMovement.objects.select_related('product', 'performed_by', 'reference_order').order_by('-created_at', '-id')
    q = (request.GET.get('q') or '').strip()
    reason = (request.GET.get('reason') or '').strip()

    if q:
        qs = qs.filter(Q(product__sku__icontains=q) | Q(product__name__icontains=q) | Q(notes__icontains=q))
    if reason:
        qs = qs.filter(reason=reason)

    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'management/stock_history.html', {
        'active_nav': 'stock_history',
        'page_obj': page_obj,
        'q': q,
        'reason': reason,
        'reason_choices': StockMovement.REASON_CHOICES,
    })


@portal_permission_required('access_portal', 'import_export_catalog')
def import_export(request):
    """Two-step preview -> confirm CSV catalog importer plus CSV export controls."""
    form = CSVImportUploadForm()
    active_batch = None
    batch_id = request.GET.get('batch')

    if request.method == 'POST':
        action = request.POST.get('action', 'preview')
        if action == 'preview':
            form = CSVImportUploadForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    batch = create_csv_import_preview(
                        form.cleaned_data['csv_file'],
                        actor=request.user,
                        request=request,
                    )
                    messages.info(
                        request,
                        f'CSV "{batch.filename}" analyzed: {batch.valid_rows} valid row(s), {batch.error_rows} error row(s). Review below before applying.',
                    )
                    return redirect(f'{request.path}?batch={batch.id}')
                except ValidationError as exc:
                    messages.error(request, '; '.join(exc.messages))
            else:
                for errs in form.errors.values():
                    for err in errs:
                        messages.error(request, err)
        elif action in ('confirm', 'confirm_skip_errors'):
            try:
                batch = confirm_csv_import_batch(
                    int(request.POST.get('batch_id')),
                    actor=request.user,
                    skip_error_rows=(action == 'confirm_skip_errors'),
                    request=request,
                )
                summary = batch.applied_summary
                messages.success(
                    request,
                    f'Applied CSV "{batch.filename}": {summary.get("created", 0)} created, {summary.get("updated", 0)} updated.',
                )
                return redirect('management:import_export')
            except (TypeError, ValueError):
                messages.error(request, 'Invalid import batch reference.')
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
                batch_id = request.POST.get('batch_id')
        elif action == 'cancel':
            try:
                batch = cancel_csv_import_batch(int(request.POST.get('batch_id')), actor=request.user, request=request)
                messages.info(request, f'Cancelled CSV import batch #{batch.id}.')
                return redirect('management:import_export')
            except (TypeError, ValueError, ValidationError) as exc:
                messages.error(request, str(exc))

    if batch_id and str(batch_id).isdigit():
        active_batch = CSVImportBatch.objects.filter(pk=int(batch_id)).first()
    if active_batch is None:
        active_batch = CSVImportBatch.objects.filter(status=CSVImportBatch.STATUS_PREVIEW).order_by('-created_at').first()

    recent_batches = CSVImportBatch.objects.select_related('uploaded_by').order_by('-created_at')[:10]

    return render(request, 'management/import_export.html', {
        'active_nav': 'import_export',
        'form': form,
        'active_batch': active_batch,
        'recent_batches': recent_batches,
        'categories': Category.objects.order_by('display_order', 'name'),
    })


@require_GET
@portal_permission_required('access_portal', 'import_export_catalog')
def export_catalog_csv(request):
    """Download UTF-8 BOM CSV export of catalog products, stock, and hardware specs."""
    csv_text = export_products_csv()
    response = HttpResponse(csv_text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="corecraftr_catalog_export.csv"'
    return response


@portal_permission_required('access_portal', 'view_reports')
def reports(request):
    """Inventory valuation, category breakdown, low-stock alerts, and recent price changes."""
    metrics = get_verified_inventory_metrics()
    category_breakdown = (
        Category.objects.annotate(
            total_products=Count('products'),
            published_products=Count('products', filter=Q(products__status=Product.STATUS_PUBLISHED)),
        )
        .order_by('display_order', 'name')
    )
    recent_price_changes = PriceChangeLog.objects.select_related('product', 'changed_by').order_by('-created_at', '-id')[:20]

    return render(request, 'management/reports.html', {
        'active_nav': 'reports',
        'metrics': metrics,
        'category_breakdown': category_breakdown,
        'recent_price_changes': recent_price_changes,
    })


@owner_required
def user_management(request):
    """Owner-only user access, Inventory Manager group assignment, and account status management."""
    q = (request.GET.get('q') or '').strip()
    user_rows = list_portal_users(query=q)
    create_form = CreateManagerUserForm()

    return render(request, 'management/user_management.html', {
        'active_nav': 'users',
        'user_rows': user_rows,
        'q': q,
        'create_form': create_form,
    })


@require_POST
@owner_required
def user_management_action(request):
    """Process Owner-only role grant/revoke, activate/deactivate, or Inventory Manager creation."""
    action = (request.POST.get('action') or '').strip()
    target_id = request.POST.get('user_id')

    try:
        if action == 'grant_manager':
            user = grant_inventory_manager(actor=request.user, target_user_id=int(target_id), request=request)
            messages.success(request, f'Granted Inventory Manager access to "{user.username}".')
        elif action == 'revoke_manager':
            user = revoke_inventory_manager(actor=request.user, target_user_id=int(target_id), request=request)
            messages.success(request, f'Revoked Inventory Manager access from "{user.username}".')
        elif action == 'activate':
            user = set_user_active_state(actor=request.user, target_user_id=int(target_id), is_active=True, request=request)
            messages.success(request, f'Activated user account "{user.username}".')
        elif action == 'deactivate':
            user = set_user_active_state(actor=request.user, target_user_id=int(target_id), is_active=False, request=request)
            messages.success(request, f'Deactivated user account "{user.username}".')
        elif action == 'create_manager':
            form = CreateManagerUserForm(request.POST)
            if not form.is_valid():
                for errs in form.errors.values():
                    for err in errs:
                        messages.error(request, err)
                return redirect('management:user_management')
            cd = form.cleaned_data
            user = create_inventory_manager_account(
                actor=request.user,
                username=cd['username'],
                email=cd.get('email', ''),
                password=cd['password'],
                first_name=cd.get('first_name', ''),
                last_name=cd.get('last_name', ''),
                request=request,
            )
            messages.success(request, f'Created new Inventory Manager account "{user.username}".')
        else:
            messages.error(request, 'Unknown user management action.')
    except (ValueError, TypeError):
        messages.error(request, 'Invalid user reference.')
    except PermissionDenied as exc:
        messages.error(request, str(exc))
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))

    return redirect('management:user_management')


@owner_required
def audit_log(request):
    """Owner-only read-only view of immutable staff audit events."""
    qs = AuditLog.objects.select_related('actor').order_by('-created_at', '-id')
    q = (request.GET.get('q') or '').strip()
    action_filter = (request.GET.get('action') or '').strip()

    if q:
        qs = qs.filter(
            Q(actor_username__icontains=q)
            | Q(target_label__icontains=q)
            | Q(summary__icontains=q)
            | Q(action__icontains=q)
        )
    if action_filter:
        qs = qs.filter(action=action_filter)

    paginator = Paginator(qs, 40)
    page_obj = paginator.get_page(request.GET.get('page'))
    distinct_actions = AuditLog.objects.order_by('action').values_list('action', flat=True).distinct()

    return render(request, 'management/audit_log.html', {
        'active_nav': 'audit',
        'page_obj': page_obj,
        'q': q,
        'action_filter': action_filter,
        'distinct_actions': distinct_actions,
    })
