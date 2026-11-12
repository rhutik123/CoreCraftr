"""
Catalog-Grounded AI & Deterministic PC Build Recommendation Service.

Key safety & architecture guarantees:
1. No generic chatbot — structured PC recommendation & trade-off guidance only.
2. AI NEVER invents products, prices, specs, or compatibility verdicts.
3. Every AI proposal is strictly validated against real DB records AND the
   deterministic CompatibilityEngine.
4. If AI is unconfigured, offline, or produces invalid/incompatible output,
   DeterministicBuildRecommender executes seamlessly as a clearly-labeled fallback.
"""

from dataclasses import dataclass, field
from decimal import Decimal
import json
import logging
import re
import urllib.error
import urllib.request
from django.conf import settings
from management.spec_schemas import normalize_socket
from store.models import Product
from pc_builder.services.alternatives import SmartAlternativesService, slot_to_category_slot
from pc_builder.services.compatibility import (
    CompatibilityEngine,
    CompatibilityReport,
    STATUS_COMPATIBLE,
    STATUS_PRIORITY,
)

logger = logging.getLogger(__name__)


SIMPLE_ROLE_DESCRIPTIONS = {
    'cpu': 'The processor (CPU) is the brain of your PC—it handles all calculations, app logic, and background tasks.',
    'motherboard': 'The motherboard connects every component together and determines which CPUs, memory, and storage slots you can use.',
    'ram': 'Memory (RAM) is your PC’s short-term workspace so games, browsers, and tools run smoothly without stuttering.',
    'gpu': 'The graphics card (GPU) renders 3D game worlds, accelerates video effects, and drives high-refresh monitors.',
    'storage': 'Your SSD stores Windows, games, and files with ultra-fast boot and loading times.',
    'psu': 'The power supply (PSU) safely converts wall power into clean, stable electricity for all components.',
    'case': 'The PC cabinet houses all components, protects them, and keeps airflow moving so parts stay cool.',
    'cooler': 'The CPU cooler pulls heat away from the processor so it stays quiet and maintains top boost speeds.',
    'monitor': 'Your monitor displays everything your PC renders; resolution and refresh rate shape sharpness and motion smoothness.',
    'keyboard': 'Your primary typing and gaming input device.',
    'mouse': 'Controls cursor precision and ergonomics for work or gaming.',
}

USE_CASE_ALLOCATIONS = {
    'gaming': {
        'cpu': 0.21,
        'gpu': 0.37,
        'motherboard': 0.13,
        'ram': 0.08,
        'storage': 0.07,
        'psu': 0.06,
        'case': 0.05,
        'cooler': 0.03,
        'needs_gpu': True,
    },
    'video_editing': {
        'cpu': 0.27,
        'gpu': 0.28,
        'motherboard': 0.13,
        'ram': 0.11,
        'storage': 0.09,
        'psu': 0.05,
        'case': 0.04,
        'cooler': 0.03,
        'needs_gpu': True,
    },
    'streaming': {
        'cpu': 0.25,
        'gpu': 0.32,
        'motherboard': 0.13,
        'ram': 0.09,
        'storage': 0.07,
        'psu': 0.06,
        'case': 0.05,
        'cooler': 0.03,
        'needs_gpu': True,
    },
    'programming': {
        'cpu': 0.32,
        'gpu': 0.12,
        'motherboard': 0.16,
        'ram': 0.14,
        'storage': 0.11,
        'psu': 0.06,
        'case': 0.05,
        'cooler': 0.04,
        'needs_gpu': False,
    },
    'office': {
        'cpu': 0.32,
        'gpu': 0.0,
        'motherboard': 0.20,
        'ram': 0.14,
        'storage': 0.14,
        'psu': 0.09,
        'case': 0.08,
        'cooler': 0.03,
        'needs_gpu': False,
    },
    'mixed': {
        'cpu': 0.24,
        'gpu': 0.30,
        'motherboard': 0.14,
        'ram': 0.09,
        'storage': 0.08,
        'psu': 0.06,
        'case': 0.05,
        'cooler': 0.04,
        'needs_gpu': True,
    },
}


@dataclass
class BuildRequirements:
    budget: Decimal
    primary_use: str = 'gaming'
    preferred_brands: list[str] = field(default_factory=list)
    include_monitor: bool = False
    include_peripherals: bool = False
    priority_preference: str = 'balanced'  # value | balanced | performance
    upgradeability_preference: str = 'moderate'  # high | moderate | low


@dataclass
class ComponentRecommendation:
    slot: str
    product: Product
    why_selected: str
    what_it_does: str
    suits_user: str
    tradeoffs: str
    cheaper_alternative: dict | None = None
    upgrade_alternative: dict | None = None


@dataclass
class RecommendationOutcome:
    success: bool
    is_fallback: bool
    source_label: str
    notice_message: str
    summary: str
    recommendations: list[ComponentRecommendation]
    compatibility_report: CompatibilityReport
    total_price: Decimal
    budget_diff: Decimal


class AIProviderClient:
    """Thin configurable LLM client supporting OpenAI and Gemini REST APIs."""

    def __init__(self):
        self.provider = getattr(settings, 'AI_PROVIDER', 'none').lower()
        self.api_key = getattr(settings, 'AI_API_KEY', '')
        self.model = getattr(settings, 'AI_MODEL', 'gpt-4o-mini')
        self.timeout = getattr(settings, 'AI_TIMEOUT_SECONDS', 15)
        self.enable_google_search = False
        self.last_error = ''
        self.last_grounding_sources: list[dict] = []

    @property
    def is_configured(self) -> bool:
        return self.provider in ('openai', 'gemini') and bool(self.api_key)

    def _resolve_model(self) -> str:
        raw = (self.model or '').strip()
        lowered = raw.lower()
        if self.provider == 'gemini':
            if not raw or lowered.startswith(('gpt-', 'o1', 'o3', 'o4', 'chatgpt')):
                return 'gemini-3.8-flash'
            return raw
        if self.provider == 'openai':
            if not raw or lowered.startswith('gemini'):
                return 'gpt-4o-mini'
            return raw
        return raw

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict | None:
        text = (raw_text or '').strip()
        if not text:
            return None
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\s*```$', '', text)
            text = text.strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end > start:
                parsed = json.loads(text[start:end + 1])
                return parsed if isinstance(parsed, dict) else None
            raise

    @staticmethod
    def _sanitize_error(exc: Exception) -> str:
        msg = str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            detail = ''
            try:
                body = exc.read().decode('utf-8', errors='replace')
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    err_obj = parsed.get('error')
                    if isinstance(err_obj, dict) and err_obj.get('message'):
                        detail = str(err_obj['message'])[:200]
            except Exception:
                detail = ''
            msg = f'HTTP {exc.code}: {detail}' if detail else f'HTTP {exc.code} {exc.reason}'
        msg = re.sub(r'([?&]key=)[^&\s]+', r'\1***', msg)
        return msg[:240]

    def request_structured_build(
        self,
        requirements: BuildRequirements,
        catalog_payload: list[dict],
        locked_slots: dict[str, int],
    ) -> dict | None:
        system_prompt = (
            'You are a PC hardware recommendation engine. Select ONLY real product IDs '
            'from the provided JSON catalog to satisfy the user requirements and budget. '
            'Never invent products, prices, or specs. Respect any locked_slots. '
            'Return ONLY valid JSON with keys: "summary" (string) and "selections" '
            '(object mapping slot -> {"product_id": int, "why_selected": string, '
            '"suits_user": string, "tradeoffs": string}).'
        )
        user_prompt = json.dumps({
            'requirements': {
                'budget_inr': float(requirements.budget),
                'primary_use': requirements.primary_use,
                'preferred_brands': requirements.preferred_brands,
                'include_monitor': requirements.include_monitor,
                'include_peripherals': requirements.include_peripherals,
                'priority_preference': requirements.priority_preference,
                'upgradeability_preference': requirements.upgradeability_preference,
            },
            'locked_slots': locked_slots,
            'catalog': catalog_payload,
        })
        return self.send_json_prompt(system_prompt, user_prompt)

    def send_json_prompt(self, system_prompt: str, user_prompt: str) -> dict | None:
        """Send a structured JSON prompt to the configured AI provider with safe error handling."""
        self.last_error = ''
        self.last_grounding_sources = []
        if not self.is_configured:
            return None

        try:
            if self.provider == 'openai':
                raw_text = self._call_openai(system_prompt, user_prompt)
            elif self.provider == 'gemini':
                raw_text = self._call_gemini(system_prompt, user_prompt)
            else:
                return None

            if not raw_text:
                return None
            return self._extract_json_object(raw_text)
        except Exception as exc:
            self.last_error = self._sanitize_error(exc)
            logger.warning('AI provider request failed (%s); falling back to deterministic engine.', self.last_error)
            return None

    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=json.dumps({
                'model': self._resolve_model(),
                'response_format': {'type': 'json_object'},
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'temperature': 0.2,
            }).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        return payload['choices'][0]['message']['content']

    def _post_gemini_payload(self, body: dict) -> dict:
        model = self._resolve_model()
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}'
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        payload = None
        if self.enable_google_search:
            try:
                payload = self._post_gemini_payload({
                    'contents': [{'parts': [{'text': f'{system_prompt}\n\n{user_prompt}'}]}],
                    'tools': [{'google_search': {}}],
                    'generationConfig': {'temperature': 0.2},
                })
            except urllib.error.HTTPError:
                payload = None

        if payload is None:
            payload = self._post_gemini_payload({
                'contents': [{'parts': [{'text': f'{system_prompt}\n\n{user_prompt}'}]}],
                'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.2},
            })

        candidate = (payload.get('candidates') or [{}])[0]
        chunks = candidate.get('groundingMetadata', {}).get('groundingChunks', []) or []
        grounding_sources = []
        for chunk in chunks:
            web = chunk.get('web') if isinstance(chunk, dict) else None
            if isinstance(web, dict) and str(web.get('uri') or '').startswith(('http://', 'https://')):
                grounding_sources.append({
                    'title': str(web.get('title') or web['uri'])[:160],
                    'url': str(web['uri'])[:500],
                })
        self.last_grounding_sources = grounding_sources

        parts = candidate.get('content', {}).get('parts', []) or []
        return '\n'.join(str(p.get('text', '')) for p in parts if isinstance(p, dict) and p.get('text'))


class DeterministicBuildRecommender:
    """
    Rule-based PC build generator and fallback advisor using verified catalog data
    and the deterministic CompatibilityEngine.
    """

    def __init__(self, compatibility_engine: CompatibilityEngine | None = None):
        self.engine = compatibility_engine or CompatibilityEngine()
        self.alt_service = SmartAlternativesService(self.engine)

    def recommend(
        self,
        requirements: BuildRequirements,
        existing_components: dict[str, Product] | None = None,
    ) -> dict[str, Product]:
        existing = dict(existing_components or {})
        selected: dict[str, Product] = {}
        for slot, prod in existing.items():
            if prod is not None:
                selected[slot] = prod

        total_budget = float(requirements.budget or Decimal('55000'))
        total_budget = max(18000.0, total_budget)

        # Reserve optional monitor & peripherals first from budget
        pc_budget = total_budget
        if requirements.include_monitor and 'monitor' not in selected:
            mon_budget = min(total_budget * 0.22, 24000.0)
            mon = self._pick_best_for_slot('monitor', mon_budget, selected, requirements)
            if mon:
                selected['monitor'] = mon
                pc_budget -= float(mon.price)

        if requirements.include_peripherals:
            if 'keyboard' not in selected:
                kb = self._pick_best_for_slot('keyboard', min(total_budget * 0.05, 3500.0), selected, requirements)
                if kb:
                    selected['keyboard'] = kb
                    pc_budget -= float(kb.price)
            if 'mouse' not in selected:
                ms = self._pick_best_for_slot('mouse', min(total_budget * 0.04, 2500.0), selected, requirements)
                if ms:
                    selected['mouse'] = ms
                    pc_budget -= float(ms.price)

        pc_budget = max(16000.0, pc_budget)
        alloc = dict(USE_CASE_ALLOCATIONS.get(requirements.primary_use, USE_CASE_ALLOCATIONS['gaming']))

        # Adjust whether discrete GPU is needed
        use_discrete_gpu = alloc['needs_gpu'] or ('gpu' in selected) or (
            requirements.primary_use == 'programming' and pc_budget >= 65000
        )
        if requirements.primary_use == 'office' and 'gpu' not in selected:
            use_discrete_gpu = False
        if pc_budget < 38000 and 'gpu' not in selected and requirements.primary_use in ('office', 'programming', 'mixed'):
            use_discrete_gpu = False

        if not use_discrete_gpu:
            # Redistribute GPU budget share to CPU, RAM, Storage
            extra = alloc['gpu']
            alloc['gpu'] = 0.0
            alloc['cpu'] += extra * 0.45
            alloc['ram'] += extra * 0.25
            alloc['storage'] += extra * 0.20
            alloc['motherboard'] += extra * 0.10

        # Order of deterministic selection so compatibility dependencies flow cleanly:
        # 1. CPU -> 2. Motherboard -> 3. RAM -> 4. GPU -> 5. Storage -> 6. Cooler -> 7. Case -> 8. PSU
        if 'cpu' not in selected:
            cpu_budget = pc_budget * alloc['cpu']
            cpu = self._pick_cpu(cpu_budget, selected, requirements, require_igpu=not use_discrete_gpu)
            if cpu:
                selected['cpu'] = cpu

        if 'motherboard' not in selected:
            mobo = self._pick_best_for_slot('motherboard', pc_budget * alloc['motherboard'], selected, requirements)
            if mobo:
                selected['motherboard'] = mobo

        if 'ram' not in selected:
            ram = self._pick_best_for_slot('ram', pc_budget * alloc['ram'], selected, requirements)
            if ram:
                selected['ram'] = ram

        if use_discrete_gpu and 'gpu' not in selected:
            # Allocate remaining flexible headroom towards GPU so gaming builds get strong GPUs
            spent_so_far = sum(float(p.price) for s, p in selected.items() if s not in ('monitor', 'keyboard', 'mouse'))
            est_non_gpu_rest = pc_budget * (alloc['storage'] + alloc['psu'] + alloc['case'] + alloc['cooler'])
            gpu_budget = max(pc_budget * alloc['gpu'], pc_budget - spent_so_far - est_non_gpu_rest)
            gpu = self._pick_best_for_slot('gpu', gpu_budget, selected, requirements)
            if gpu:
                selected['gpu'] = gpu

        if 'storage' not in selected:
            storage = self._pick_best_for_slot('storage', pc_budget * alloc['storage'], selected, requirements)
            if storage:
                selected['storage'] = storage

        if 'cooler' not in selected:
            cpu_prod = selected.get('cpu')
            cpu_spec = cpu_prod.spec_profile_safe if cpu_prod else None
            needs_cooler = (cpu_spec is None) or (cpu_spec.includes_stock_cooler is not True) or (pc_budget >= 50000)
            if needs_cooler:
                cooler = self._pick_best_for_slot('cooler', max(2200.0, pc_budget * alloc['cooler']), selected, requirements)
                if cooler:
                    selected['cooler'] = cooler

        if 'case' not in selected:
            case = self._pick_best_for_slot('case', max(3500.0, pc_budget * alloc['case']), selected, requirements)
            if case:
                selected['case'] = case

        if 'psu' not in selected:
            psu = self._pick_best_for_slot('psu', max(3500.0, pc_budget * alloc['psu']), selected, requirements)
            if psu:
                selected['psu'] = psu

        return selected

    def _pick_cpu(self, target_budget: float, selected: dict, req: BuildRequirements, require_igpu: bool) -> Product | None:
        qs = Product.objects.filter(
            is_active=True,
            category__component_slot='cpu',
            inventory__quantity__gt=0,
        ).select_related('category', 'brand', 'inventory', 'spec_profile')

        candidates = list(qs)
        if require_igpu:
            igpu_cands = [p for p in candidates if p.spec_profile_safe and p.spec_profile_safe.integrated_graphics is True]
            if igpu_cands:
                candidates = igpu_cands

        return self._score_and_select('cpu', candidates, target_budget, selected, req)

    def _pick_best_for_slot(self, slot: str, target_budget: float, selected: dict, req: BuildRequirements) -> Product | None:
        cat_slot = slot_to_category_slot(slot)
        candidates = list(
            Product.objects.filter(
                is_active=True,
                category__component_slot=cat_slot,
                inventory__quantity__gt=0,
            ).select_related('category', 'brand', 'inventory', 'spec_profile')
        )
        return self._score_and_select(slot, candidates, target_budget, selected, req)

    def _score_and_select(
        self,
        slot: str,
        candidates: list[Product],
        target_budget: float,
        selected: dict,
        req: BuildRequirements,
    ) -> Product | None:
        if not candidates:
            return None

        pref_brands = {b.strip().lower() for b in (req.preferred_brands or []) if b.strip()}
        compatible_pool = []

        for cand in candidates:
            test_map = dict(selected)
            test_map[slot] = cand
            report = self.engine.evaluate_products(test_map)
            if not report.is_build_valid_compatible:
                continue

            spec = cand.spec_profile_safe
            perf_score = (spec.benchmark_score if spec and spec.benchmark_score else 45)
            price = float(cand.price)

            # Budget fit score
            if price <= target_budget * 1.15:
                budget_fit = 30.0 - abs(target_budget - price) / max(target_budget, 1.0) * 18.0
            else:
                # Penalize over-budget items strongly unless value/performance dictates
                overshoot = (price - target_budget) / max(target_budget, 1.0)
                budget_fit = -overshoot * 65.0

            # Priority adjustments
            if req.priority_preference == 'performance':
                score = perf_score * 1.35 + budget_fit * 0.6
            elif req.priority_preference == 'value':
                value_ratio = (perf_score / max(price / 1000.0, 1.0)) * 8.0
                score = perf_score * 0.7 + value_ratio + budget_fit * 1.2
            else:
                score = perf_score * 1.0 + budget_fit * 1.0

            # Upgradeability bonus
            if req.upgradeability_preference == 'high' and spec:
                if slot in ('cpu', 'motherboard') and normalize_socket(spec.socket) in ('AM5', 'LGA1700', 'LGA1851'):
                    score += 18.0
                if slot == 'motherboard' and (spec.memory_slots or 0) >= 4:
                    score += 8.0
                if slot == 'psu' and (spec.wattage or 0) >= 650:
                    score += 10.0

            # Brand preference bonus
            if pref_brands and cand.brand and cand.brand.name.lower() in pref_brands:
                score += 18.0

            # Prefer dual-stick RAM over single-stick
            if slot == 'ram' and spec and (spec.ram_modules or 1) >= 2:
                score += 10.0

            # Compatibility purity bonus (verified compatible beats warning/unknown)
            compat_bonus = (3 - STATUS_PRIORITY[report.overall_status]) * 25.0
            score += compat_bonus

            compatible_pool.append((score, cand))

        if not compatible_pool:
            # Fallback to cheapest compatible or cheapest candidate if none fit strict filter
            return None

        compatible_pool.sort(key=lambda item: (-item[0], item[1].price))
        return compatible_pool[0][1]

    def build_explanations(
        self,
        selected: dict[str, Product],
        requirements: BuildRequirements,
        ai_notes: dict[str, dict] | None = None,
    ) -> list[ComponentRecommendation]:
        """Generate structured beginner explanations & verified alternatives for every component."""
        ai_notes = ai_notes or {}
        slot_order = ['cpu', 'motherboard', 'ram', 'gpu', 'storage', 'storage_secondary', 'psu', 'case', 'cooler', 'case_fan', 'monitor', 'keyboard', 'mouse']
        results = []

        for slot in slot_order:
            product = selected.get(slot)
            if not product:
                continue

            spec = product.spec_profile_safe
            alts = self.alt_service.get_slot_alternatives(selected, slot, product)
            custom_ai = ai_notes.get(slot, {})

            why = custom_ai.get('why_selected') or self._default_why_selected(slot, product, spec, requirements)
            suits = custom_ai.get('suits_user') or self._default_suits_user(slot, product, spec, requirements)
            tradeoffs = custom_ai.get('tradeoffs') or (spec.tradeoffs_note if spec and spec.tradeoffs_note else self._default_tradeoff(slot, product, spec))

            results.append(ComponentRecommendation(
                slot=slot,
                product=product,
                why_selected=why,
                what_it_does=SIMPLE_ROLE_DESCRIPTIONS.get(slot, 'Key system hardware component.'),
                suits_user=suits,
                tradeoffs=tradeoffs,
                cheaper_alternative=alts.get('cheaper'),
                upgrade_alternative=alts.get('higher'),
            ))
        return results

    @staticmethod
    def _default_why_selected(slot: str, product: Product, spec, req: BuildRequirements) -> str:
        if spec and spec.beginner_summary:
            return spec.beginner_summary
        use_label = req.primary_use.replace('_', ' ')
        return f'Selected as a balanced, verified-compatible {slot.upper()} choice for a Rs. {req.budget:,.0f} {use_label} build.'

    @staticmethod
    def _default_suits_user(slot: str, product: Product, spec, req: BuildRequirements) -> str:
        use_label = req.primary_use.replace('_', ' ')
        if slot == 'cpu' and spec:
            return f'Delivers {spec.cores or "multi"}-core processing well suited for {use_label} workloads.'
        if slot == 'gpu' and spec:
            return f'{spec.vram_gb or ""}GB VRAM handles modern {use_label} rendering and high frame rates cleanly.'
        if slot == 'ram' and spec:
            return f'{spec.ram_capacity_gb or ""}GB {spec.memory_type} gives smooth multitasking without memory bottlenecks.'
        if slot == 'psu' and spec:
            return f'{spec.wattage}W {spec.efficiency_rating} provides clean power with safe upgrade headroom.'
        return f'Matches your {req.priority_preference} priority and {req.upgradeability_preference} upgradeability target.'

    @staticmethod
    def _default_tradeoff(slot: str, product: Product, spec) -> str:
        if slot == 'cpu' and spec and spec.integrated_graphics is False:
            return 'Does not include integrated graphics, so a dedicated graphics card is required for monitor output.'
        if slot == 'motherboard' and spec and spec.socket == 'AM4':
            return 'AM4 keeps total build cost low, though CPU upgrades stop at Ryzen 5000 series.'
        if slot == 'ram' and spec and (spec.ram_capacity_gb or 0) <= 16:
            return '16GB is ideal for gaming and daily tasks; heavy 4K editing or many VMs may benefit from 32GB later.'
        return 'Balanced price-to-performance choice; stepping up increases cost more than everyday speed.'


class BuildRecommendationOrchestrator:
    """
    Coordinates optional AI provider proposals with strict DB & compatibility
    validation, falling back deterministically whenever needed.
    """

    def __init__(self):
        self.engine = CompatibilityEngine()
        self.ai_client = AIProviderClient()
        self.deterministic = DeterministicBuildRecommender(self.engine)

    def generate_recommendation(
        self,
        requirements: BuildRequirements,
        existing_components: dict[str, Product] | None = None,
    ) -> RecommendationOutcome:
        existing = {k: v for k, v in (existing_components or {}).items() if v is not None}

        # Try optional external AI provider if configured
        ai_raw = None
        ai_error_reason = ''
        if self.ai_client.is_configured:
            catalog_payload = self._serialize_catalog_for_ai()
            locked = {slot: prod.id for slot, prod in existing.items()}
            ai_raw = self.ai_client.request_structured_build(requirements, catalog_payload, locked)
            if ai_raw is None:
                ai_error_reason = 'AI provider did not return a usable response; used rule-based fallback.'

        selected_map: dict[str, Product] | None = None
        ai_notes: dict[str, dict] = {}
        ai_summary = ''
        is_fallback = True
        source_label = 'Deterministic Rule-Based Advisor (Fallback)'
        notice_message = (
            ai_error_reason
            or 'No external AI API key is configured. Generated using deterministic catalog rules and verified compatibility checks.'
        )

        if ai_raw:
            validated = self._validate_and_ground_ai_output(ai_raw, existing)
            if validated is not None:
                selected_map, ai_notes, ai_summary = validated
                is_fallback = False
                source_label = f'AI-Assisted ({self.ai_client.provider.upper()}) + Deterministic Compatibility Verified'
                notice_message = 'Recommendations ranked by configured AI provider and strictly verified against real inventory & compatibility rules.'
            else:
                notice_message = (
                    'AI proposal included unavailable or incompatible components and was rejected by the compatibility gate; '
                    'used verified deterministic fallback instead.'
                )

        if selected_map is None:
            selected_map = self.deterministic.recommend(requirements, existing)
            ai_summary = self._build_deterministic_summary(selected_map, requirements)

        report = self.engine.evaluate_products(selected_map)
        recommendations = self.deterministic.build_explanations(selected_map, requirements, ai_notes=ai_notes)
        total_price = sum((rec.product.price for rec in recommendations), Decimal('0.00'))
        budget_diff = (requirements.budget or Decimal('0.00')) - total_price

        return RecommendationOutcome(
            success=len(recommendations) > 0,
            is_fallback=is_fallback,
            source_label=source_label,
            notice_message=notice_message,
            summary=ai_summary,
            recommendations=recommendations,
            compatibility_report=report,
            total_price=total_price,
            budget_diff=budget_diff,
        )

    def explain_existing_build(self, build) -> RecommendationOutcome:
        """Provide Beginner-mode plain-English guidance for a user's existing build without modifying it."""
        slot_map = {comp.slot: comp.product for comp in build.components.select_related('product', 'product__spec_profile', 'product__brand', 'product__category')}
        req = BuildRequirements(
            budget=build.budget or Decimal('60000'),
            primary_use=build.primary_use or 'gaming',
            preferred_brands=list(build.preferred_brands or []),
            include_monitor=build.include_monitor,
            include_peripherals=build.include_peripherals,
            priority_preference=build.priority_preference or 'balanced',
            upgradeability_preference=build.upgradeability_preference or 'moderate',
        )
        report = self.engine.evaluate_products(slot_map)
        recommendations = self.deterministic.build_explanations(slot_map, req)
        total_price = sum((rec.product.price for rec in recommendations), Decimal('0.00'))
        return RecommendationOutcome(
            success=True,
            is_fallback=True,
            source_label='Current Build Guided Breakdown',
            notice_message='Showing beginner-friendly explanations and compatible alternatives for your current selected parts.',
            summary=f'Your current build includes {len(recommendations)} component(s) totaling Rs. {total_price:,.2f}.',
            recommendations=recommendations,
            compatibility_report=report,
            total_price=total_price,
            budget_diff=(req.budget - total_price),
        )

    def _validate_and_ground_ai_output(self, ai_raw: dict, locked_existing: dict[str, Product]):
        """
        Strictly validate every AI-selected product_id against the real database,
        verify stock and category matching, and enforce zero incompatibilities
        via CompatibilityEngine.
        """
        selections = ai_raw.get('selections')
        if not isinstance(selections, dict) or not selections:
            return None

        grounded: dict[str, Product] = dict(locked_existing)
        ai_notes: dict[str, dict] = {}

        for slot, entry in selections.items():
            if slot in locked_existing:
                # Preserve user's locked component
                continue
            if not isinstance(entry, dict):
                return None
            prod_id = entry.get('product_id')
            if not isinstance(prod_id, int):
                return None

            cat_slot = slot_to_category_slot(slot)
            product = (
                Product.objects.filter(
                    id=prod_id,
                    is_active=True,
                    category__component_slot=cat_slot,
                    inventory__quantity__gt=0,
                )
                .select_related('category', 'brand', 'inventory', 'spec_profile')
                .first()
            )
            if not product:
                return None

            grounded[slot] = product
            ai_notes[slot] = {
                'why_selected': str(entry.get('why_selected', ''))[:500],
                'suits_user': str(entry.get('suits_user', ''))[:500],
                'tradeoffs': str(entry.get('tradeoffs', ''))[:500],
            }

        # Deterministic Compatibility Gate: AI NEVER decides compatibility
        report = self.engine.evaluate_products(grounded)
        if not report.is_build_valid_compatible:
            return None

        summary = str(ai_raw.get('summary') or 'AI-assisted PC build verified by deterministic compatibility checks.')[:800]
        return grounded, ai_notes, summary

    @staticmethod
    def _serialize_catalog_for_ai() -> list[dict]:
        products = (
            Product.objects.filter(is_active=True, category__is_pc_component=True, inventory__quantity__gt=0)
            .select_related('category', 'brand', 'spec_profile')
        )
        extra_spec_fields = (
            'cpu_family', 'chipset', 'form_factor', 'supported_form_factors',
            'supported_cpu_families', 'supported_memory_types', 'memory_slots',
            'max_memory_gb', 'ram_capacity_gb', 'ram_modules', 'ram_speed_mhz',
            'gpu_length_mm', 'max_gpu_length_mm', 'cooler_type', 'supported_sockets',
            'cooler_height_mm', 'radiator_size_mm', 'max_cooler_height_mm',
            'supported_radiator_sizes_mm', 'max_tdp_rating_watts',
            'includes_stock_cooler', 'integrated_graphics', 'recommended_psu_watts',
            'storage_type', 'storage_form_factor', 'max_power_watts', 'benchmark_score',
        )
        rows = []
        for p in products:
            spec = p.spec_profile_safe
            entry = {
                'id': p.id,
                'name': p.name,
                'slot': p.category.component_slot if p.category else 'other',
                'brand': p.brand.name if p.brand else '',
                'price_inr': float(p.price),
                'tier': spec.performance_tier if spec else 'unknown',
                'socket': spec.socket if spec else '',
                'memory_type': spec.memory_type if spec else '',
                'wattage': spec.wattage if spec else None,
                'tdp_watts': spec.tdp_watts if spec else None,
            }
            if spec:
                for fname in extra_spec_fields:
                    val = getattr(spec, fname, None)
                    if val not in (None, '', [], {}):
                        entry[fname] = val
            rows.append(entry)
        return rows

    @staticmethod
    def _build_deterministic_summary(selected: dict[str, Product], req: BuildRequirements) -> str:
        total = sum((p.price for p in selected.values()), Decimal('0.00'))
        use_label = req.primary_use.replace('_', ' ').title()
        return (
            f'Recommended {use_label} PC build across {len(selected)} verified components '
            f'for Rs. {total:,.2f} (target budget: Rs. {req.budget:,.2f}). '
            'Every component was checked by our deterministic compatibility engine.'
        )


@dataclass
class CartAdviceOutcome:
    is_fallback: bool
    source_label: str
    notice_message: str
    summary: str
    direction_suggestions: dict[str, dict] = field(default_factory=dict)


class CartCompatibilityAdvisor:
    """
    Catalog-grounded AI & deterministic fallback advisor for shopping cart
    compatibility warnings. Never overrides deterministic rules or invents products.
    """

    def __init__(self, compatibility_engine: CompatibilityEngine | None = None):
        self.engine = compatibility_engine or CompatibilityEngine()
        self.ai_client = AIProviderClient()

    def advise_on_conflicts(
        self,
        detailed_issues: list,
        slot_items: dict,
        allow_ai_call: bool = True,
    ) -> CartAdviceOutcome:
        """
        Enrich cart compatibility issues with Beginner + Expert guidance and
        validated, in-stock real replacement rationale.
        """
        serious_issues = [i for i in detailed_issues if i.status == 'incompatible']
        candidate_pools_payload = []

        # Collect pre-validated candidate replacement options grouped by direction key
        direction_map = {}
        for issue in detailed_issues:
            for d in issue.fix_directions:
                direction_map[d.direction_key] = d
                if d.replacements:
                    candidate_pools_payload.append({
                        'direction_key': d.direction_key,
                        'rule_code': issue.rule_code,
                        'action_title': d.title,
                        'target_slot': d.target_slot,
                        'candidates': [
                            {
                                'product_id': rep.product.id,
                                'name': rep.product.name,
                                'price_inr': float(rep.product.price),
                                'highlights': rep.spec_summary,
                            }
                            for rep in d.replacements
                        ],
                    })

        is_fallback = True
        source_label = 'Deterministic Compatibility Advisor (Fallback)'
        notice_message = 'Showing verified catalogue alternatives validated by our deterministic compatibility rules.'
        summary = self._default_summary(detailed_issues)
        validated_direction_notes: dict[str, dict] = {}

        if allow_ai_call and serious_issues and candidate_pools_payload and self.ai_client.is_configured:
            ai_raw = self._request_ai_cart_advice(detailed_issues, candidate_pools_payload)
            if ai_raw is not None:
                validated = self._validate_ai_cart_advice(ai_raw, direction_map, slot_items)
                if validated is not None:
                    is_fallback = False
                    source_label = f'AI-Assisted ({self.ai_client.provider.upper()}) + Compatibility Verified'
                    notice_message = (
                        'Plain-English explanations and replacement ranking are assisted by AI using only '
                        'verified in-stock products passed through our deterministic compatibility gate.'
                    )
                    summary = validated['summary'] or summary
                    validated_direction_notes = validated['direction_notes']
                else:
                    notice_message = (
                        'AI suggestion referenced unavailable or incompatible components and was rejected; '
                        'showing verified deterministic replacements instead.'
                    )

        return CartAdviceOutcome(
            is_fallback=is_fallback,
            source_label=source_label,
            notice_message=notice_message,
            summary=summary,
            direction_suggestions=validated_direction_notes,
        )

    def _request_ai_cart_advice(self, detailed_issues: list, pools_payload: list[dict]) -> dict | None:
        system_prompt = (
            'You are a hardware compatibility advisor for an e-commerce cart. '
            'Using ONLY the supplied product_id values from each direction candidate list, explain the '
            'compatibility conflict in simple beginner language and recommend which supplied product_ids '
            'resolve it. Never invent products, prices, or specs. '
            'Return ONLY valid JSON: {"summary": string, "directions": {direction_key: '
            '{"tip": string, "recommended_ids": [int], "reasons": {product_id_str: string}}}}.'
        )
        user_prompt = json.dumps({
            'issues': [
                {
                    'rule_code': i.rule_code,
                    'status': i.status,
                    'title': i.title,
                    'expert_explanation': i.expert_explanation,
                    'beginner_explanation': i.beginner_explanation,
                }
                for i in detailed_issues if i.status in ('incompatible', 'warning')
            ],
            'verified_replacement_pools': pools_payload,
        })
        return self.ai_client.send_json_prompt(system_prompt, user_prompt)

    def _validate_ai_cart_advice(self, ai_raw: dict, direction_map: dict, slot_items: dict) -> dict | None:
        if not isinstance(ai_raw, dict):
            return None
        ai_dirs = ai_raw.get('directions')
        if not isinstance(ai_dirs, dict):
            return None

        validated_notes: dict[str, dict] = {}
        for dkey, dir_entry in ai_dirs.items():
            direction = direction_map.get(dkey)
            if not direction or not isinstance(dir_entry, dict):
                return None

            rec_ids = dir_entry.get('recommended_ids') or []
            if not isinstance(rec_ids, list):
                return None

            cat_slot = slot_to_category_slot(direction.target_slot)
            verified_ordered_ids = []
            for pid in rec_ids:
                if not isinstance(pid, int):
                    return None
                prod = (
                    Product.objects.filter(
                        id=pid,
                        is_active=True,
                        spec_verified=True,
                        category__component_slot=cat_slot,
                        inventory__quantity__gt=0,
                    )
                    .select_related('category', 'brand', 'inventory', 'spec_profile')
                    .first()
                )
                if not prod or prod.spec_profile_safe is None:
                    return None

                # Always enforce deterministic compatibility gate on AI's proposed swap
                test_map = dict(slot_items)
                if direction.keep_product and direction.keep_slot:
                    test_map[direction.keep_slot] = (direction.keep_product, 1)
                test_map[direction.target_slot] = (prod, 1)
                report = self.engine.evaluate_products(test_map)
                if not report.is_build_valid_compatible:
                    return None
                if any(
                    c.status == 'unknown' and direction.target_slot in c.affected_slots
                    for c in report.checks
                ):
                    return None
                verified_ordered_ids.append(pid)

            raw_reasons = dir_entry.get('reasons') if isinstance(dir_entry.get('reasons'), dict) else {}
            clean_reasons = {
                int(k): str(v)[:300]
                for k, v in raw_reasons.items()
                if str(k).isdigit()
            }
            validated_notes[dkey] = {
                'tip': str(dir_entry.get('tip') or '')[:400],
                'recommended_ids': verified_ordered_ids,
                'reasons': clean_reasons,
            }

        summary = str(ai_raw.get('summary') or '')[:600]
        return {'summary': summary, 'direction_notes': validated_notes}

    @staticmethod
    def _default_summary(detailed_issues: list) -> str:
        incompat = sum(1 for i in detailed_issues if i.status == 'incompatible')
        warns = sum(1 for i in detailed_issues if i.status == 'warning')
        unk = sum(1 for i in detailed_issues if i.status == 'unknown')
        if incompat:
            return (
                f'Found {incompat} serious hardware incompatibility issue(s). '
                'You can swap a conflicting item using the verified compatible options below, '
                'or still proceed to checkout after confirming the compatibility notice.'
            )
        if unk:
            return (
                'One or more components are missing verified specifications, so complete compatibility '
                'cannot be guaranteed automatically.'
            )
        if warns:
            return (
                f'No fatal hardware conflicts were detected, though {warns} advisory notice(s) '
                '(such as BIOS version checks or companion parts) need your attention.'
            )
        return 'All checked hardware components in your cart work cleanly together.'
