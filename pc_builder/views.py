from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from store.models import Product
from store.services import cart_service
from ai_engine.services.recommender import BuildRecommendationOrchestrator, BuildRequirements
from pc_builder.forms import BeginnerPreferencesForm, SaveBuildForm
from pc_builder.models import BuildComponent, PCBuild
from pc_builder.services.builder_service import PCBuilderService, SLOT_METADATA


def builder_workspace(request):
    """
    Main unified PC Builder view supporting both Beginner Mode ("Help me build my first PC")
    and Expert Mode ("I know what I'm looking for") on the exact same underlying PCBuild.
    """
    builder = PCBuilderService()
    build = builder.get_or_create_active_build(request)

    requested_mode = request.GET.get('mode')
    if requested_mode in ('beginner', 'expert') and build.mode != requested_mode:
        builder.switch_mode(build, requested_mode, user=request.user)

    # Optional quick-start query params from homepage budget tiers
    prefill_budget = request.GET.get('budget')
    prefill_use = request.GET.get('use')
    if prefill_budget or prefill_use:
        updated = False
        if prefill_budget:
            try:
                build.budget = Decimal(str(prefill_budget))
                updated = True
            except Exception:
                pass
        if prefill_use and prefill_use in dict(PCBuild.PRIMARY_USE_CHOICES):
            build.primary_use = prefill_use
            updated = True
        if updated:
            build.save()

    ctx = builder.get_build_context(build)
    beginner_form = BeginnerPreferencesForm(
        initial={
            'budget': build.budget or Decimal('65000'),
            'primary_use': build.primary_use or 'gaming',
            'priority_preference': build.priority_preference or 'balanced',
            'upgradeability_preference': build.upgradeability_preference or 'moderate',
            'preferred_brands': build.preferred_brands or [],
            'include_monitor': build.include_monitor,
            'include_peripherals': build.include_peripherals,
            'preserve_existing': build.component_count > 0,
        }
    )

    guidance = None
    if build.mode == 'beginner' and build.component_count > 0:
        guidance = BuildRecommendationOrchestrator().explain_existing_build(build)

    ctx.update({
        'beginner_form': beginner_form,
        'save_form': SaveBuildForm(initial={'name': build.name}),
        'guidance': guidance,
    })
    return render(request, 'pc_builder/workspace.html', ctx)


@require_POST
def switch_mode(request):
    """Switch Beginner <-> Expert mode while preserving the entire PC build."""
    builder = PCBuilderService()
    build = builder.get_or_create_active_build(request)
    target_mode = request.POST.get('mode', 'expert')
    if target_mode in ('beginner', 'expert'):
        builder.switch_mode(build, target_mode, user=request.user)
        mode_label = 'Beginner Mode' if target_mode == 'beginner' else 'Expert Mode'
        messages.info(request, f'Switched to {mode_label}. All selected components were preserved.')
    return redirect('pc_builder')


@require_POST
def beginner_recommend(request):
    """Generate a compatibility-verified build recommendation from Beginner questionnaire."""
    builder = PCBuilderService()
    build = builder.get_or_create_active_build(request)
    form = BeginnerPreferencesForm(request.POST)

    if not form.is_valid():
        for field, errs in form.errors.items():
            for err in errs:
                messages.error(request, f'{field}: {err}')
        return redirect('pc_builder')

    cd = form.cleaned_data
    build.mode = 'beginner'
    build.budget = cd['budget']
    build.primary_use = cd['primary_use']
    build.priority_preference = cd['priority_preference']
    build.upgradeability_preference = cd['upgradeability_preference']
    build.preferred_brands = list(cd.get('preferred_brands') or [])
    build.include_monitor = cd['include_monitor']
    build.include_peripherals = cd['include_peripherals']

    existing_components = {}
    if cd.get('preserve_existing'):
        for comp in build.components.select_related('product', 'product__spec_profile'):
            existing_components[comp.slot] = comp.product

    requirements = BuildRequirements(
        budget=cd['budget'],
        primary_use=cd['primary_use'],
        preferred_brands=build.preferred_brands,
        include_monitor=cd['include_monitor'],
        include_peripherals=cd['include_peripherals'],
        priority_preference=cd['priority_preference'],
        upgradeability_preference=cd['upgradeability_preference'],
    )

    orchestrator = BuildRecommendationOrchestrator()
    outcome = orchestrator.generate_recommendation(requirements, existing_components=existing_components)

    if not outcome.success:
        messages.error(request, 'Unable to find a compatible build within your constraints. Try increasing your budget slightly.')
        return redirect('pc_builder')

    # Persist validated components into active workspace build
    build.components.all().delete()
    for rec in outcome.recommendations:
        BuildComponent.objects.create(
            build=build,
            slot=rec.slot,
            product=rec.product,
            quantity=1,
            selection_reason=rec.why_selected,
            tradeoffs=rec.tradeoffs,
            added_via_mode='beginner',
        )

    build.ai_summary = outcome.summary
    build.ai_source = outcome.source_label
    build.name = f'{build.get_primary_use_display()} Build (Rs. {outcome.total_price:,.0f})'
    build.save()

    if outcome.is_fallback:
        messages.info(request, outcome.notice_message)
    else:
        messages.success(request, outcome.notice_message)

    return redirect('pc_builder')


def select_component_page(request, slot):
    """Expert Mode (and Beginner swap) slot picker with specs, filters, sorting, and live compatibility."""
    if slot not in BuildComponent.ALL_SLOTS:
        messages.error(request, 'Invalid hardware component slot.')
        return redirect('pc_builder')

    builder = PCBuilderService()
    build = builder.get_or_create_active_build(request)
    slot_meta = next((m for m in SLOT_METADATA if m['slot'] == slot), {'slot': slot, 'label': slot.title()})
    current_comp = build.components.filter(slot=slot).select_related('product').first()

    candidates_data = builder.get_slot_candidates(build, slot, request.GET)

    context = {
        'build': build,
        'slot': slot,
        'slot_meta': slot_meta,
        'current_component': current_comp,
        'candidates': candidates_data['candidates'],
        'brands': candidates_data['brands'],
        'filters': request.GET,
    }
    return render(request, 'pc_builder/select_component.html', context)


@require_POST
def set_component_action(request):
    """Add or replace a component in a build slot without silently dropping other parts."""
    builder = PCBuilderService()
    build = builder.get_or_create_active_build(request)

    slot = request.POST.get('slot', '').strip()
    product_id = request.POST.get('product_id')
    quantity = request.POST.get('quantity', '1')

    product = get_object_or_404(Product, id=product_id, is_active=True)
    try:
        qty = max(1, int(quantity))
    except (ValueError, TypeError):
        qty = 1

    try:
        _, report = builder.set_component(build, slot, product, quantity=qty, mode=build.mode)
        if report.incompatibilities:
            messages.warning(
                request,
                f'Added {product.name} to {slot.upper()}. Compatibility alert: {report.incompatibilities[0].title}',
            )
        else:
            messages.success(request, f'Selected {product.name} for {slot.upper()}.')
    except ValueError as exc:
        messages.error(request, str(exc))

    return redirect('pc_builder')


@require_POST
def remove_component_action(request, slot):
    builder = PCBuilderService()
    build = builder.get_or_create_active_build(request)
    builder.remove_component(build, slot)
    messages.info(request, f'Removed component from {slot.replace("_", " ").title()} slot.')
    return redirect('pc_builder')


@require_POST
def clear_build_action(request):
    builder = PCBuilderService()
    build = builder.get_or_create_active_build(request)
    builder.clear_build_components(build)
    messages.info(request, 'Cleared all components from your active workspace build.')
    return redirect('pc_builder')


@login_required
@require_POST
def save_build_action(request):
    builder = PCBuilderService()
    build = builder.get_or_create_active_build(request)
    if build.component_count == 0:
        messages.warning(request, 'Add at least one component before saving your build.')
        return redirect('pc_builder')

    form = SaveBuildForm(request.POST)
    name = form.cleaned_data['name'] if form.is_valid() else (request.POST.get('name') or build.name)
    saved = builder.save_build_snapshot(build, request.user, name)
    messages.success(request, f'Saved PC build "{saved.name}".')
    return redirect('builder_saved_list')


@login_required
def saved_builds_list(request):
    builds = (
        PCBuild.objects.filter(user=request.user, is_saved=True)
        .prefetch_related('components__product__category', 'components__product__spec_profile')
        .order_by('-updated_at')
    )
    builder = PCBuilderService()
    enriched = []
    for b in builds:
        report = builder.compat_engine.evaluate_build(b)
        enriched.append({
            'build': b,
            'compatibility': report,
            'total_price': b.total_price,
        })
    return render(request, 'pc_builder/saved_builds.html', {'saved_builds': enriched})


@login_required
@require_POST
def load_saved_build_action(request, build_uuid):
    saved = get_object_or_404(PCBuild, uuid=build_uuid, user=request.user, is_saved=True)
    builder = PCBuilderService()
    workspace = builder.get_or_create_active_build(request)
    builder.load_saved_build(workspace, saved)
    messages.success(request, f'Loaded "{saved.name}" into your active PC Builder.')
    return redirect('pc_builder')


@login_required
@require_POST
def delete_saved_build_action(request, build_uuid):
    saved = get_object_or_404(PCBuild, uuid=build_uuid, user=request.user, is_saved=True)
    name = saved.name
    saved.delete()
    messages.info(request, f'Deleted saved build "{name}".')
    return redirect('builder_saved_list')


@require_POST
def add_build_to_cart_action(request):
    builder = PCBuilderService()
    build_uuid = request.POST.get('build_uuid')
    if build_uuid:
        if request.user.is_authenticated:
            build = get_object_or_404(PCBuild, uuid=build_uuid, user=request.user)
        else:
            build = get_object_or_404(PCBuild, uuid=build_uuid, session_key=request.session.session_key)
    else:
        build = builder.get_or_create_active_build(request)

    user_cart = cart_service.get_or_create_cart(request)
    res = builder.add_build_to_cart(build, user_cart)
    if res.success:
        messages.success(request, res.message)
        return redirect('cart')
    for err in (res.errors or [res.message]):
        messages.error(request, err)
    return redirect('pc_builder')
