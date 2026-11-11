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
from difflib import SequenceMatcher
from html.parser import HTMLParser
import ipaddress
import json
import logging
import re
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


class _HTMLTextExtractor(HTMLParser):
    """Minimal safe HTML-to-text extractor skipping script/style tags."""

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ('script', 'style', 'noscript', 'svg'):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in ('script', 'style', 'noscript', 'svg') and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag.lower() in ('p', 'div', 'li', 'tr', 'br', 'h1', 'h2', 'h3', 'h4', 'td', 'th'):
            self._chunks.append(' ')

    def handle_data(self, data):
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    def get_text(self) -> str:
        joined = ' '.join(self._chunks)
        return re.sub(r'\s+', ' ', joined).strip()


class WebSearchClient:
    """Configurable search client supporting Tavily, Serper, Google Custom Search, and safe reference URL extraction."""

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

    def fetch_page_extract(self, url: str, max_chars: int = 3500) -> str:
        """Fetch visible text excerpt from a validated public product/datasheet URL with strict caps."""
        if not is_safe_public_http_url(url):
            return ''
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'CoreCraftrSpecResearch/1.0 (+https://corecraftr.local)'},
                method='GET',
            )
            with urllib.request.urlopen(req, timeout=min(self.timeout, 8)) as resp:
                ctype = (resp.headers.get('Content-Type') or '').lower()
                if 'html' not in ctype and 'text/plain' not in ctype:
                    return ''
                raw_bytes = resp.read(512 * 1024)
                decoded = raw_bytes.decode('utf-8', errors='replace')
            parser = _HTMLTextExtractor()
            parser.feed(decoded)
            return parser.get_text()[:max_chars]
        except Exception as exc:
            logger.debug('Reference page fetch skipped for %s: %s', url, exc)
            return ''

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
    match_status: str = 'exact'  # exact / ambiguous / not_found / unavailable
    identified_name: str = ''
    suggested_corrections: list = field(default_factory=list)
    field_statuses: dict = field(default_factory=dict)
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
        confirmed_match: bool = False,
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
                match_status='unavailable',
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
                match_status='unavailable',
                summary_note='Reference URL was rejected because only public http/https URLs are permitted.',
                raw_provider_status='invalid_reference_url',
            )

        if not self.ai_client.is_configured:
            return SpecResearchResult(
                available=False,
                status='unavailable',
                verification_status='unavailable',
                confidence='low',
                match_status='unavailable',
                summary_note=(
                    'AI specification research is currently unconfigured (AI_PROVIDER=none or missing API key). '
                    'Enter specifications manually below.'
                ),
                raw_provider_status='provider_unconfigured',
            )

        slot_fields = get_spec_fields_for_slot(category_slot)
        allowed_fields = {f['name']: f for f in slot_fields + SHARED_METADATA_FIELDS}
        critical_fields = get_critical_field_names(category_slot)

        # Optional live web search context, prioritizing official manufacturer sources first
        search_snippets = []
        if self.search_client.is_configured:
            query_parts = [p for p in [brand_name, clean_name, model_number, 'official specifications datasheet'] if p]
            raw_snippets = self.search_client.search(' '.join(query_parts), max_results=6)
            search_snippets = sorted(
                raw_snippets,
                key=lambda item: 0 if classify_source_origin(item.get('url', ''), brand_name=brand_name) == 'manufacturer' else 1,
            )

        reference_page_extract = ''
        if clean_ref_url:
            reference_page_extract = self.search_client.fetch_page_extract(clean_ref_url)
        elif search_snippets and self.search_client.is_configured:
            top_url = search_snippets[0].get('url', '')
            if top_url and classify_source_origin(top_url, brand_name=brand_name) == 'manufacturer':
                reference_page_extract = self.search_client.fetch_page_extract(top_url)

        system_prompt = (
            'You are a precision computer hardware technical specification assistant for CoreCraftr. '
            'Prioritize official manufacturer product pages and datasheets, then official docs, then reputable hardware databases. '
            'Return STRICT JSON ONLY with this exact top-level schema: '
            '{"match_status": "exact"|"ambiguous"|"not_found", '
            '"identified_name": "...", '
            '"suggested_corrections": [{"name": "...", "brand": "...", "reason": "...", "url": "https://..."}], '
            '"proposed_specs": {field: value}, "custom_specs": {label: value_str}, '
            '"sources": [{"url": "https://...", "title": "...", "origin_type": "manufacturer"|"third_party"}], '
            '"missing_fields": ["field_name"], '
            '"conflicting_fields": [{"field": "field_name", "values": ["v1", "v2"], "note": "..."}], '
            '"confidence": "high"|"medium"|"low", '
            '"summary_note": "..."}. '
            'Situation rules: '
            '1) Exact product identified: set match_status="exact", fill verified proposed_specs from sources, put unverified fields in missing_fields. '
            '2) Possible typo or ambiguous query (for example "AMD Ryzan 5 7600X" unless user confirmed): set match_status="ambiguous", '
            'put likely candidate product name(s) in suggested_corrections with reason, and keep proposed_specs empty until confirmed. '
            '3) Product not found or fictional: set match_status="not_found", leave proposed_specs empty, never guess values, and explain clearly. '
            'NEVER invent, estimate, or guess unknown values. '
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
            'reference_page_extract': reference_page_extract,
            'confirmed_match': bool(confirmed_match),
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
                match_status='unavailable',
                summary_note=(
                    'AI specification provider did not return a valid structured response. '
                    'Please enter specifications manually.'
                ),
                raw_provider_status='provider_error_or_invalid_json',
            )

        return self._validate_ai_response(
            raw_response=raw_response,
            product_name=clean_name,
            allowed_fields=allowed_fields,
            slot_fields=slot_fields,
            critical_fields=critical_fields,
            brand_name=brand_name,
            reference_url=clean_ref_url,
            search_snippets=search_snippets,
            confirmed_match=confirmed_match,
        )

    @staticmethod
    def _looks_like_typo_or_mismatch(entered_name: str, identified_name: str) -> bool:
        """Detect likely misspellings between user query and identified product name without flagging short prefixes."""
        entered = (entered_name or '').strip().lower()
        identified = (identified_name or '').strip().lower()
        if not entered or not identified or entered == identified:
            return False
        entered_tokens = [tok for tok in re.findall(r'[a-z0-9]+', entered) if len(tok) >= 3]
        identified_tokens = re.findall(r'[a-z0-9]+', identified)
        if not entered_tokens or not identified_tokens:
            return False
        if all(tok in identified_tokens for tok in entered_tokens):
            return False
        ratio = SequenceMatcher(None, entered, identified).ratio()
        if 0.65 <= ratio < 0.98:
            return True
        for tok in entered_tokens:
            if tok not in identified_tokens:
                best = max((SequenceMatcher(None, tok, cand).ratio() for cand in identified_tokens), default=0.0)
                if 0.65 <= best < 1.0:
                    return True
        return False

    def _validate_ai_response(
        self,
        *,
        raw_response: dict,
        product_name: str,
        allowed_fields: dict,
        slot_fields: list[dict],
        critical_fields: list[str],
        brand_name: str,
        reference_url: str,
        search_snippets: list[dict],
        confirmed_match: bool = False,
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

        raw_match_status = (raw_response.get('match_status') or '').strip().lower()
        identified_name = (raw_response.get('identified_name') or '').strip()[:255]

        suggested_corrections = []
        raw_suggestions = raw_response.get('suggested_corrections') or []
        if isinstance(raw_suggestions, list):
            for sug in raw_suggestions[:5]:
                if isinstance(sug, str) and sug.strip():
                    suggested_corrections.append({
                        'name': sug.strip()[:255],
                        'brand': brand_name,
                        'reason': f'Did you mean "{sug.strip()[:255]}"?',
                        'url': '',
                    })
                elif isinstance(sug, dict):
                    sname = (sug.get('name') or '').strip()[:255]
                    if sname:
                        surl = (sug.get('url') or '').strip()
                        suggested_corrections.append({
                            'name': sname,
                            'brand': (sug.get('brand') or brand_name)[:120],
                            'reason': (sug.get('reason') or f'Did you mean "{sname}"?')[:255],
                            'url': surl if is_safe_public_http_url(surl) else '',
                        })

        if (
            not confirmed_match
            and raw_match_status != 'not_found'
            and identified_name
            and self._looks_like_typo_or_mismatch(product_name, identified_name)
        ):
            if not any(s['name'].lower() == identified_name.lower() for s in suggested_corrections):
                suggested_corrections.insert(0, {
                    'name': identified_name,
                    'brand': brand_name,
                    'reason': f'Possible typo or close match for "{product_name}". Confirm before applying specifications.',
                    'url': validated_sources[0]['url'] if validated_sources else '',
                })
            raw_match_status = 'ambiguous'

        slot_field_names = [f['name'] for f in slot_fields]

        if raw_match_status == 'ambiguous' or (not confirmed_match and suggested_corrections):
            if not suggested_corrections and identified_name:
                suggested_corrections.append({
                    'name': identified_name,
                    'brand': brand_name,
                    'reason': 'Ambiguous or close product match detected. Confirm exact product identity first.',
                    'url': validated_sources[0]['url'] if validated_sources else '',
                })
            field_statuses = {fname: 'not_found' for fname in slot_field_names}
            note = summary_note or (
                f'Possible typo or ambiguous product query for "{product_name}". '
                'Confirm a suggested product match or continue entering specifications manually.'
            )
            return SpecResearchResult(
                available=True,
                status='draft',
                verification_status='unverified',
                confidence='low',
                match_status='ambiguous',
                identified_name=identified_name,
                suggested_corrections=suggested_corrections,
                field_statuses=field_statuses,
                proposed_specs={},
                custom_specs={},
                sources=validated_sources,
                missing_fields=sorted(set(missing_fields) | set(critical_fields)),
                conflicting_fields=[],
                rejected_fields=rejected_fields,
                summary_note=note,
                raw_provider_status='ambiguous_or_typo',
            )

        if raw_match_status == 'not_found' or (
            not proposed_specs and not custom_specs and not conflicting_fields
        ):
            field_statuses = {fname: 'not_found' for fname in slot_field_names}
            note = 'Product not confidently identified. No specifications were guessed; enter specifications manually below.'
            if summary_note and 'product not confidently identified' not in summary_note.lower():
                note = f'Product not confidently identified. {summary_note}'
            return SpecResearchResult(
                available=True,
                status='draft',
                verification_status='unverified',
                confidence='low',
                match_status='not_found',
                identified_name='',
                suggested_corrections=[],
                field_statuses=field_statuses,
                proposed_specs={},
                custom_specs={},
                sources=validated_sources,
                missing_fields=sorted(set(missing_fields) | set(slot_field_names)),
                conflicting_fields=[],
                rejected_fields=rejected_fields,
                summary_note=note,
                raw_provider_status='not_found',
            )

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

        field_statuses = {}
        all_schema_names = set(slot_field_names) | set(proposed_specs.keys()) | conflicted_field_names | set(missing_fields)
        for fname in all_schema_names:
            if fname in conflicted_field_names:
                field_statuses[fname] = 'conflicting'
            elif fname in proposed_specs:
                field_statuses[fname] = 'sourced' if has_manufacturer else 'needs_verification'
            else:
                field_statuses[fname] = 'not_found'

        return SpecResearchResult(
            available=True,
            status='draft',
            verification_status=verification_status,
            confidence=confidence,
            match_status='exact',
            identified_name=identified_name or product_name,
            suggested_corrections=suggested_corrections,
            field_statuses=field_statuses,
            proposed_specs=proposed_specs,
            custom_specs=custom_specs,
            sources=validated_sources,
            missing_fields=sorted(missing_fields),
            conflicting_fields=conflicting_fields,
            rejected_fields=rejected_fields,
            summary_note=summary_note,
            raw_provider_status='ok',
        )
