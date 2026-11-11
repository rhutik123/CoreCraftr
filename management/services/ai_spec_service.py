from django.core.exceptions import ValidationError
from django.db import transaction

from ai_engine.services.spec_researcher import ProductSpecResearchService
from management.models import AIResearchDraft
from management.services.audit_service import log_portal_action


def run_ai_spec_research(
    *,
    actor,
    product_name: str,
    category,
    brand_name: str = '',
    model_number: str = '',
    reference_url: str = '',
    product=None,
    request=None,
) -> AIResearchDraft:
    """
    Invoke ProductSpecResearchService and store an editable AIResearchDraft for review.
    Never modifies any Product record until staff explicitly approves and saves the product form.
    """
    if not category:
        raise ValidationError('Select a hardware category before running AI specification research.')

    researcher = ProductSpecResearchService()
    result = researcher.research(
        product_name=product_name,
        category_slot=category.component_slot,
        category_name=category.name,
        brand_name=brand_name,
        model_number=model_number,
        reference_url=reference_url,
        user_id=actor.id if actor and getattr(actor, 'is_authenticated', False) else None,
    )

    draft = AIResearchDraft.objects.create(
        requested_by=actor if actor and getattr(actor, 'is_authenticated', False) else None,
        product=product,
        product_name=product_name.strip()[:255],
        brand_name=(brand_name or '').strip()[:120],
        category=category,
        model_number=(model_number or '').strip()[:120],
        reference_url=(reference_url or '').strip()[:500],
        status=result.status,
        verification_status=result.verification_status,
        confidence=result.confidence,
        proposed_specs=result.proposed_specs,
        custom_specs=result.custom_specs,
        sources=result.sources,
        missing_fields=result.missing_fields,
        conflicting_fields=result.conflicting_fields,
        rejected_fields=result.rejected_fields,
        summary_note=result.summary_note,
        raw_provider_status=result.raw_provider_status,
    )

    log_portal_action(
        actor=actor,
        action='ai.research_executed',
        target_type='ai_research_draft',
        target_id=draft.id,
        target_label=f'{draft.product_name} ({category.name})',
        after_data={
            'draft_id': draft.id,
            'status': draft.status,
            'verification_status': draft.verification_status,
            'proposed_count': len(draft.proposed_specs),
            'conflict_count': len(draft.conflicting_fields),
        },
        summary=f'Executed AI specification research draft #{draft.id} for "{draft.product_name}".',
        request=request,
    )
    return draft


@transaction.atomic
def discard_ai_draft(*, draft_id: int, actor, request=None) -> AIResearchDraft:
    draft = AIResearchDraft.objects.select_for_update().filter(pk=draft_id).first()
    if not draft:
        raise ValidationError('AI research draft not found.')
    if draft.status != AIResearchDraft.STATUS_REJECTED:
        draft.status = AIResearchDraft.STATUS_REJECTED
        draft.save(update_fields=['status'])
        log_portal_action(
            actor=actor,
            action='ai.draft_discarded',
            target_type='ai_research_draft',
            target_id=draft.id,
            target_label=draft.product_name,
            summary=f'Discarded AI research draft #{draft.id}.',
            request=request,
        )
    return draft
