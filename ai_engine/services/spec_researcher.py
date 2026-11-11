"""
Schema-Constrained AI Product Specification Research Service.

Reuses AIProviderClient from ai_engine.services.recommender and extends it with
an optional configurable WebSearchClient.

Strict non-negotiable guardrails:
1. Read-only suggestion generator: NEVER creates, modifies, or publishes Products,
   prices, cost prices, SKUs, stock quantities, or compatibility verdicts.
2. Enforces per-user hourly rate limiting via Django cache.
3. Validates every proposed field strictly against management.spec_schemas.
4. Strips and rejects forbidden commercial/system keys (sku, price, cost_price, etc.).
5. Requires verifiable source attribution and distinguishes manufacturer vs
   third-party sources; flags conflicting or missing specifications clearly.
6. Falls back cleanly with an unavailable status when unconfigured or offline.
"""

from dataclasses import dataclass, field
import ipaddress
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

from ai_engine.services.recommender import AIProviderClient
from management.spec_schemas import (
    SHARED_METADATA_FIELDS,
    coerce_spec_value,
    get_critical_field_names,
    get_spec_fields_for_slot,
)

logger = logging.getLogger(__name__)

FORBIDDEN_AI_FIELDS = {
    'id',
    'pk',
    'sku',
    'price',
    'cost_price',
    'quantity',
    'stock',
    'stock_quantity',
    'reserved_quantity',
    'status',
    'is_active',
    'slug',
    'created_by',
    'last_edited_by',
}

KNOWN_MANUFACTURER_DOMAINS = {
    'amd.com',
    'intel.com',
    'nvidia.com',
    'asus.com',
    'msi.com',
    'gigabyte.com',
    'asrock.com',
    'corsair.com',
    'seasonic.com',
    'nzxt.com',
    'noctua.at',
    'samsung.com',
    'crucial.com',
    'kingston.com',
    'gskill.com',
    'westerndigital.com',
    'wdc.com',
    'seagate.com',
    'coolermaster.com',
    'fractal-design.com',
    'lian-li.com',
    'bequiet.com',
    'deepcool.com',
    'thermalright.com',
    'sapphiretech.com',
    'zotac.com',
    'evga.com',
    'lg.com',
    'dell.com',
    'benq.com',
    'acer.com',
    'logitech.com',
    'logitechg.com',
    'razer.com',
    'keychron.com',
    'thermaltake.com',
    'phanteks.com',
    'arctic.de',
    'teamgroupinc.com',
    'lexar.com',
    'sabrent.com',
    'kioxia.com',
}


class RateLimitExceededError(Exception):
    """Raised when a staff user exceeds hourly AI specification research quota."""


def is_safe_public_http_url(raw_url: str) -> bool:
    """Validate that URL uses http(s) and does not point to localhost or private IP space."""
    if not raw_url or not isinstance(raw_url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(raw_url.strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.netloc:
        return False
    host = (parsed.hostname or '').strip().lower()
    if not host or host in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
        return False
    if host.endswith('.local') or host.endswith('.internal'):
        return False
    try:
        ip_obj = ipaddress.ip_address(host)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
            return False
    except ValueError:
        # Hostname rather than literal IP; block only explicit unresolvable IP literals here
        # without requiring live DNS resolution during unit tests/offline environments.
        pass
    return True


def classify_source_origin(url: str, brand_name: str = '') -> str:
    """Classify source URL as 'manufacturer' or 'third_party' based on domain heuristics."""
    if not is_safe_public_http_url(url):
        return 'third_party'
    host = (urllib.parse.urlparse(url).hostname or '').lower()
    for domain in KNOWN_MANUFACTURER_DOMAINS:
        if host == domain or host.endswith('.' + domain):
            return 'manufacturer'
    brand_clean = ''.join(ch for ch in (brand_name or '').lower() if ch.isalnum())
    if len(brand_clean) >= 3:
        host_labels = host.split('.')
        if any(brand_clean == label or label.startswith(brand_clean) for label in host_labels[:-1]):
            return 'manufacturer'
    return 'third_party'


class WebSearchClient:
    """Configurable search client supporting Tavily, Serper, or Google Custom Search."""

    def __init__(self):
        self.provider = (getattr(settings, 'AI_SEARCH_PROVIDER', 'none') or 'none').strip().lower()
        self.api_key = (getattr(settings, 'AI_SEARCH_API_KEY', '') or '').strip()
        self.engine_id = (getattr(settings, 'AI_SEARCH_ENGINE_ID', '') or '').strip()
        self.timeout = int(getattr(settings, 'AI_TIMEOUT_SECONDS', 15) or 15)

    @property
    def is_configured(self) -> bool:
        if self.provider == 'google_cse':
            return bool(self.api_key and self.engine_id)
        return self.provider in ('tavily', 'serper') and bool(self.api_key)

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Run a web search against configured search API; return normalized source snippets."""
        if not self.is_configured or not query:
            return []
        try:
            if self.provider == 'tavily':
                return self._search_tavily(query, max_results)
            if self.provider == 'serper':
                return self._search_serper(query, max_results)
            if self.provider == 'google_cse':
                return self._search_google_cse(query, max_results)
        except Exception as exc:
            logger.warning('WebSearchClient failed (%s): %s', self.provider, exc)
        return []

    def _search_tavily(self, query: str, max_results: int) -> list[dict]:
        req = urllib.request.Request(
            'https://api.tavily.com/search',
            data=json.dumps({
                'api_key': self.api_key,
                'query': query,
                'search_depth': 'basic',
                'max_results': max_results,
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        results = []
        for item in payload.get('results', [])[:max_results]:
            url = item.get('url', '')
            if is_safe_public_http_url(url):
                results.append({
                    'url': url,
                    'title': (item.get('title') or '')[:200],
                    'snippet': (item.get('content') or '')[:500],
                })
        return results

    def _search_serper(self, query: str, max_results: int) -> list[dict]:
        req = urllib.request.Request(
            'https://google.serper.dev/search',
            data=json.dumps({'q': query, 'num': max_results}).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'X-API-KEY': self.api_key,
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        results = []
        for item in payload.get('organic', [])[:max_results]:
            url = item.get('link', '')
            if is_safe_public_http_url(url):
                results.append({
                    'url': url,
                    'title': (item.get('title') or '')[:200],
                    'snippet': (item.get('snippet') or '')[:500],
                })
        return results

    def _search_google_cse(self, query: str, max_results: int) -> list[dict]:
        qs = urllib.parse.urlencode({
            'key': self.api_key,
            'cx': self.engine_id,
            'q': query,
            'num': min(max_results, 10),
        })
        req = urllib.request.Request(f'https://www.googleapis.com/customsearch/v1?{qs}', method='GET')
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        results = []
        for item in payload.get('items', [])[:max_results]:
            url = item.get('link', '')
            if is_safe_public_http_url(url):
                results.append({
                    'url': url,
                    'title': (item.get('title') or '')[:200],
                    'snippet': (item.get('snippet') or '')[:500],
                })
        return results


@dataclass
class SpecResearchResult:
    available: bool
    status: str  # draft / unavailable
    verification_status: str  # verified_manufacturer / mixed_sources / partial / unverified / unavailable
    confidence: str  # high / medium / low
    proposed_specs: dict = field(default_factory=dict)
    custom_specs: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    missing_fields: list = field(default_factory=list)
    conflicting_fields: list = field(default_factory=list)
    rejected_fields: list = field(default_factory=list)
    summary_note: str = ''
    raw_provider_status: str = ''


class ProductSpecResearchService:
    """
    Researches technical specifications for a hardware product against the category schema.
    Produces an editable, non-destructive draft result with source attribution and validation.
    """

    def __init__(
        self,
        ai_client: AIProviderClient | None = None,
        search_client: WebSearchClient | None = None,
    ):
        self.ai_client = ai_client or AIProviderClient()
        self.search_client = search_client or WebSearchClient()

    @staticmethod
    def check_and_consume_rate_limit(user_id: int) -> None:
        """Enforce hourly per-user rate limit on AI spec research requests."""
        if not user_id:
            return
        limit = int(getattr(settings, 'AI_RESEARCH_RATE_LIMIT_PER_HOUR', 20) or 20)
        if limit <= 0:
            return
        cache_key = f'corecraftr_ai_spec_rl:{user_id}'
        current = cache.get(cache_key)
        if current is None:
            cache.set(cache_key, 1, timeout=3600)
            return
        if int(current) >= limit:
            raise RateLimitExceededError(
                f'Hourly limit of {limit} AI specification research requests reached. Enter specifications manually or retry later.'
            )
        try:
            cache.incr(cache_key)
        except ValueError:
            cache.set(cache_key, int(current) + 1, timeout=3600)

    def research(
        self,
        *,
        product_name: str,
        category_slot: str,
        category_name: str = '',
        brand_name: str = '',
        model_number: str = '',
        reference_url: str = '',
        user_id: int | None = None,
    ) -> SpecResearchResult:
        """
        Execute schema-constrained specification research and strictly validate output.
        Never mutates Product, Inventory, SKU, Price, or Publication Status.
        """
        if user_id:
            self.check_and_consume_rate_limit(user_id)

        clean_name = (product_name or '').strip()
        if not clean_name:
            return SpecResearchResult(
                available=False,
                status='unavailable',
                verification_status='unavailable',
                confidence='low',
                summary_note='Provide a product name before requesting AI specification research.',
                raw_provider_status='missing_product_name',
            )

        clean_ref_url = (reference_url or '').strip()
        if clean_ref_url and not is_safe_public_http_url(clean_ref_url):
            return SpecResearchResult(
                available=False,
                status='unavailable',
                verification_status='unavailable',
                confidence='low',
                summary_note='Reference URL was rejected because only public http/https URLs are permitted.',
                raw_provider_status='invalid_reference_url',
            )

        if not self.ai_client.is_configured:
            return SpecResearchResult(
                available=False,
                status='unavailable',
                verification_status='unavailable',
                confidence='low',
                summary_note=(
                    'AI specification research is currently unconfigured (AI_PROVIDER=none or missing API key). '
                    'Enter specifications manually below.'
                ),
                raw_provider_status='provider_unconfigured',
            )

        slot_fields = get_spec_fields_for_slot(category_slot)
        allowed_fields = {f['name']: f for f in slot_fields + SHARED_METADATA_FIELDS}
        critical_fields = get_critical_field_names(category_slot)

        # Optional live web search context
        search_snippets = []
        if self.search_client.is_configured:
            query_parts = [p for p in [brand_name, clean_name, model_number, 'official specifications'] if p]
            search_snippets = self.search_client.search(' '.join(query_parts), max_results=5)

        system_prompt = (
            'You are a precision computer hardware technical specification assistant for CoreCraftr. '
            'Return STRICT JSON ONLY with this exact top-level schema: '
            '{"proposed_specs": {field: value}, "custom_specs": {label: value_str}, '
            '"sources": [{"url": "https://...", "title": "...", "origin_type": "manufacturer"|"third_party"}], '
            '"missing_fields": ["field_name"], '
            '"conflicting_fields": [{"field": "field_name", "values": ["v1", "v2"], "note": "..."}], '
            '"confidence": "high"|"medium"|"low", '
            '"summary_note": "..."}. '
            'NEVER invent, estimate, or guess unknown values — put unknown fields in missing_fields instead. '
            'NEVER output commercial fields such as sku, price, cost_price, quantity, stock, id, or status. '
            'If sources disagree on a spec, DO NOT pick one silently; include it in conflicting_fields. '
            'Use only field keys from the provided schema.'
        )
        schema_desc = [
            {
                'field': f['name'],
                'label': f['label'],
                'type': f['type'],
                'unit': f.get('unit', ''),
                'critical_for_compatibility': bool(f.get('compatibility_critical')),
            }
            for f in slot_fields
        ]
        user_payload = {
            'product_name': clean_name,
            'brand_name': brand_name,
            'model_number': model_number,
            'category_name': category_name or category_slot,
            'category_slot': category_slot,
            'reference_url': clean_ref_url,
            'allowed_schema': schema_desc,
            'web_search_results': search_snippets,
        }

        raw_response = self.ai_client.send_json_prompt(system_prompt, json.dumps(user_payload))
        if not isinstance(raw_response, dict):
            return SpecResearchResult(
                available=False,
                status='unavailable',
                verification_status='unavailable',
                confidence='low',
                summary_note=(
                    'AI specification provider did not return a valid structured response. '
                    'Please enter specifications manually.'
                ),
                raw_provider_status='provider_error_or_invalid_json',
            )

        return self._validate_ai_response(
            raw_response=raw_response,
            allowed_fields=allowed_fields,
            critical_fields=critical_fields,
            brand_name=brand_name,
            reference_url=clean_ref_url,
            search_snippets=search_snippets,
        )

    def _validate_ai_response(
        self,
        *,
        raw_response: dict,
        allowed_fields: dict,
        critical_fields: list[str],
        brand_name: str,
        reference_url: str,
        search_snippets: list[dict],
    ) -> SpecResearchResult:
        rejected_fields = []
        proposed_specs = {}
        custom_specs = {}
        missing_fields = set()

        # Flag any forbidden top-level keys returned by AI
        for k in raw_response.keys():
            if k.lower() in FORBIDDEN_AI_FIELDS:
                rejected_fields.append(f'Forbidden commercial/system key "{k}" stripped')

        raw_missing = raw_response.get('missing_fields') or []
        if isinstance(raw_missing, list):
            for item in raw_missing:
                if isinstance(item, str) and item in allowed_fields:
                    missing_fields.add(item)

        # Parse & normalize conflicts before applying proposed_specs so conflicting fields are never silently applied
        conflicting_fields = []
        conflicted_field_names = set()
        raw_conflicts = raw_response.get('conflicting_fields') or []
        if isinstance(raw_conflicts, list):
            for c in raw_conflicts:
                if not isinstance(c, dict):
                    continue
                fname = (c.get('field') or '').strip()
                vals = c.get('values') if isinstance(c.get('values'), list) else []
                note = (c.get('note') or '').strip()
                if fname:
                    conflicted_field_names.add(fname)
                    label = allowed_fields[fname]['label'] if fname in allowed_fields else fname
                    conflicting_fields.append({
                        'field': fname,
                        'label': label,
                        'values': [str(v) for v in vals[:5]],
                        'note': note or 'Conflicting data across sources; manual verification required.',
                    })

        # Validate schema-constrained proposed_specs
        raw_proposed = raw_response.get('proposed_specs')
        if isinstance(raw_proposed, dict):
            for raw_key, raw_val in raw_proposed.items():
                key = str(raw_key).strip()
                if key.lower() in FORBIDDEN_AI_FIELDS:
                    rejected_fields.append(f'Forbidden commercial/system spec "{key}" blocked')
                    continue
                if key not in allowed_fields:
                    rejected_fields.append(f'Unrecognized spec key "{key}" outside category schema')
                    continue
                if key in conflicted_field_names:
                    rejected_fields.append(f'Held "{key}" out of auto-fill due to source conflict')
                    continue

                fdef = allowed_fields[key]
                coerced, err = coerce_spec_value(fdef, raw_val)
                if err:
                    rejected_fields.append(f'Invalid value for {key}: {err}')
                    continue

                # Check empty / explicitly unknown value
                if coerced is None or coerced == '' or coerced == [] or coerced == {}:
                    missing_fields.add(key)
                    continue

                # JSON serialization friendliness for Decimal in draft storage
                if fdef['type'] == 'decimal':
                    proposed_specs[key] = str(coerced)
                else:
                    proposed_specs[key] = coerced

        # Validate optional custom display specs
        raw_custom = raw_response.get('custom_specs')
        if isinstance(raw_custom, dict):
            for k, v in raw_custom.items():
                ckey = str(k).strip()
                cval = str(v).strip()
                if ckey.lower() in FORBIDDEN_AI_FIELDS:
                    rejected_fields.append(f'Forbidden custom spec "{ckey}" blocked')
                    continue
                if ckey and cval and cval.lower() not in ('unknown', 'n/a', 'unspecified'):
                    custom_specs[ckey[:120]] = cval[:255]

        # Any critical field missing from proposed_specs is explicitly tracked in missing_fields
        for crit in critical_fields:
            if crit not in proposed_specs and crit not in conflicted_field_names:
                missing_fields.add(crit)

        # Validate & classify source attribution
        validated_sources = []
        seen_urls = set()
        raw_sources = raw_response.get('sources') or []
        if isinstance(raw_sources, list):
            for src in raw_sources:
                if isinstance(src, str):
                    src = {'url': src, 'title': src}
                if not isinstance(src, dict):
                    continue
                url = (src.get('url') or '').strip()
                if is_safe_public_http_url(url) and url not in seen_urls:
                    seen_urls.add(url)
                    origin = classify_source_origin(url, brand_name=brand_name)
                    validated_sources.append({
                        'url': url,
                        'title': (src.get('title') or url)[:200],
                        'origin_type': origin,
                        'snippet': (src.get('snippet') or '')[:300],
                    })

        # Fallback: include search snippets if AI omitted them, clearly labeled
        for s in search_snippets:
            if s['url'] not in seen_urls:
                seen_urls.add(s['url'])
                validated_sources.append({
                    'url': s['url'],
                    'title': s.get('title') or s['url'],
                    'origin_type': classify_source_origin(s['url'], brand_name=brand_name),
                    'snippet': s.get('snippet', ''),
                })

        has_manufacturer = any(s['origin_type'] == 'manufacturer' for s in validated_sources)
        has_any_source = len(validated_sources) > 0

        raw_conf = (raw_response.get('confidence') or 'low').strip().lower()
        if raw_conf not in ('high', 'medium', 'low'):
            raw_conf = 'low'

        summary_note = (raw_response.get('summary_note') or '').strip()

        if not has_any_source:
            verification_status = 'unverified'
            confidence = 'low'
            unverified_warning = (
                'Warning: No external source URL was attributed for these suggested values. '
                'Verify every field manually against the official datasheet before saving.'
            )
            summary_note = f'{unverified_warning} {summary_note}'.strip()
        elif conflicting_fields:
            verification_status = 'partial'
            confidence = 'low'
        elif any(crit in missing_fields for crit in critical_fields):
            verification_status = 'verified_manufacturer' if has_manufacturer and not rejected_fields else 'partial'
            confidence = 'medium' if raw_conf == 'high' else raw_conf
        else:
            verification_status = 'verified_manufacturer' if has_manufacturer else 'mixed_sources'
            confidence = raw_conf

        return SpecResearchResult(
            available=True,
            status='draft',
            verification_status=verification_status,
            confidence=confidence,
            proposed_specs=proposed_specs,
            custom_specs=custom_specs,
            sources=validated_sources,
            missing_fields=sorted(missing_fields),
            conflicting_fields=conflicting_fields,
            rejected_fields=rejected_fields,
            summary_note=summary_note,
            raw_provider_status='ok',
        )
