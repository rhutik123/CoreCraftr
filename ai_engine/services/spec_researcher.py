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
    normalize_cpu_family,
    normalize_socket,
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
    """Minimal safe HTML-to-text extractor skipping script/style tags while preserving spec row breaks."""

    _BLOCK_TAGS = ('p', 'div', 'li', 'tr', 'br', 'h1', 'h2', 'h3', 'h4', 'dt', 'dd', 'section', 'article')
    _CELL_TAGS = ('td', 'th')

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self.page_title = ''
        self.meta_description = ''
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ('script', 'style', 'noscript', 'svg'):
            self._skip_depth += 1
        elif t == 'title':
            self._in_title = True
        elif t == 'meta':
            attr_map = {str(k).lower(): str(v or '') for k, v in attrs if k}
            name_key = (attr_map.get('name') or attr_map.get('property') or '').lower()
            if name_key in ('description', 'og:description') and attr_map.get('content') and not self.meta_description:
                self.meta_description = attr_map['content'].strip()[:500]
        elif t == 'br' and self._skip_depth == 0:
            self._chunks.append('\n')

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ('script', 'style', 'noscript', 'svg') and self._skip_depth > 0:
            self._skip_depth -= 1
        elif t == 'title':
            self._in_title = False
        elif t in self._CELL_TAGS and self._skip_depth == 0:
            self._chunks.append(' | ')
        elif t in self._BLOCK_TAGS and self._skip_depth == 0:
            self._chunks.append('\n')

    def handle_data(self, data):
        if self._skip_depth == 0 and data:
            if self._in_title and not self.page_title:
                self.page_title = re.sub(r'\s+', ' ', data).strip()[:200]
            self._chunks.append(data)

    def get_text(self) -> str:
        raw = ''.join(self._chunks)
        lines = []
        for line in raw.splitlines():
            cleaned = re.sub(r'[ \t]+', ' ', line).strip(' |\t')
            if cleaned:
                lines.append(cleaned)
        if self.meta_description:
            lines.insert(0, f'Page Summary | {self.meta_description}')
        if self.page_title:
            lines.insert(0, f'Page Title | {self.page_title}')
        return '\n'.join(lines)


class WebSearchClient:
    """Configurable search client supporting Tavily, Serper, Google Custom Search, and safe reference URL extraction."""

    def __init__(self):
        self.provider = (getattr(settings, 'AI_SEARCH_PROVIDER', 'none') or 'none').strip().lower()
        self.api_key = (getattr(settings, 'AI_SEARCH_API_KEY', '') or '').strip()
        self.engine_id = (getattr(settings, 'AI_SEARCH_ENGINE_ID', '') or '').strip()
        self.timeout = int(getattr(settings, 'AI_TIMEOUT_SECONDS', 15) or 15)
        self.last_fetch_error = ''
        self.last_page_title = ''

    @property
    def is_configured(self) -> bool:
        if self.provider == 'google_cse':
            return bool(self.api_key and self.engine_id)
        return self.provider in ('tavily', 'serper') and bool(self.api_key)

    def fetch_page_extract(self, url: str, max_chars: int = 12000) -> str:
        """Fetch visible text excerpt from a validated public product/datasheet URL with strict caps."""
        self.last_fetch_error = ''
        self.last_page_title = ''
        if not is_safe_public_http_url(url):
            return ''
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; CoreCraftrSpecResearch/1.0)',
                    'Accept': 'text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                method='GET',
            )
            with urllib.request.urlopen(req, timeout=min(self.timeout, 10)) as resp:
                ctype = (resp.headers.get('Content-Type') or '').lower()
                if ctype and 'html' not in ctype and 'text/plain' not in ctype:
                    self.last_fetch_error = f'Unsupported content type ({ctype.split(";")[0]})'
                    return ''
                raw_bytes = resp.read(512 * 1024)
                charset = 'utf-8'
                if 'charset=' in ctype:
                    charset = ctype.split('charset=', 1)[1].split(';', 1)[0].strip() or 'utf-8'
                decoded = raw_bytes.decode(charset, errors='replace')
            parser = _HTMLTextExtractor()
            parser.feed(decoded)
            self.last_page_title = parser.page_title
            return parser.get_text()[:max_chars]
        except urllib.error.HTTPError as exc:
            self.last_fetch_error = f'HTTP {exc.code} {exc.reason}'.strip()
            logger.debug('Reference page fetch HTTP error for %s: %s', url, self.last_fetch_error)
            return ''
        except Exception as exc:
            self.last_fetch_error = str(exc)[:120]
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


_PERFORMANCE_TIER_ALIASES = {
    'entry': 'entry',
    'entry-level': 'entry',
    'entry level': 'entry',
    'budget': 'budget',
    'value': 'budget',
    'mid': 'midrange',
    'midrange': 'midrange',
    'mid-range': 'midrange',
    'mainstream': 'midrange',
    'upper_mid': 'upper_mid',
    'upper-mid': 'upper_mid',
    'upper mid': 'upper_mid',
    'upper mid-range': 'upper_mid',
    'high': 'high',
    'high-end': 'high',
    'high end': 'high',
    'enthusiast': 'enthusiast',
    'flagship': 'enthusiast',
    'workstation': 'enthusiast',
}


def _strip_numeric_unit(raw_val, *, allow_decimal: bool):
    if not isinstance(raw_val, str):
        return raw_val
    pattern = (
        r'^[\s~≈]*([+-]?\d+(?:,\d{3})*(?:\.\d+)?)'
        r'(?:\s*(?:w|watts?|ghz|mhz|mt/s|gb|tb|mm|mb/s|cm|hz|dpi|cfm|slots?|inches?|inch|"))?[\s]*$'
    )
    match = re.match(pattern, raw_val.strip(), flags=re.IGNORECASE)
    if not match:
        return raw_val
    num_text = match.group(1).replace(',', '')
    if not allow_decimal and '.' in num_text:
        try:
            flt = float(num_text)
            if flt.is_integer():
                return int(flt)
        except ValueError:
            return raw_val
    return num_text


def _split_list_tokens(raw_val) -> list[str]:
    if isinstance(raw_val, list):
        return [str(x).strip() for x in raw_val if str(x).strip()]
    text = str(raw_val or '').strip()
    if text.startswith('['):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in text.split(',') if part.strip()]


def _normalize_raw_spec_value(field_def: dict, raw_val, derived_extras: dict):
    """Pre-normalize AI/extracted values (unit suffixes, family aliases, iGPU strings) before strict coercion."""
    fname = field_def['name']
    ftype = field_def['type']

    if raw_val is None:
        return None

    if fname == 'integrated_graphics' and isinstance(raw_val, str):
        lowered = raw_val.strip().lower()
        if lowered in ('', 'unknown', 'n/a', 'na', 'unspecified', 'tbd', 'null'):
            return raw_val
        if lowered in ('true', '1', 'yes', 'y'):
            return True
        if lowered in ('false', '0', 'no', 'n', 'none') or lowered.startswith(('no ', 'none', 'discrete')):
            return False
        cleaned_igpu = re.sub(r'^(?:yes|true)\s*[-:(]?\s*|\)\s*$', '', raw_val.strip(), flags=re.IGNORECASE).strip()
        if cleaned_igpu:
            derived_extras.setdefault('igpu_name', cleaned_igpu[:80])
        return True

    if fname == 'socket' and isinstance(raw_val, str):
        return normalize_socket(raw_val)

    if fname == 'cpu_family' and isinstance(raw_val, str):
        return normalize_cpu_family(raw_val)

    if fname == 'supported_sockets':
        return [normalize_socket(tok) for tok in _split_list_tokens(raw_val)]

    if fname == 'supported_cpu_families':
        return [normalize_cpu_family(tok) for tok in _split_list_tokens(raw_val)]

    if fname == 'memory_type' and isinstance(raw_val, str):
        mem = re.search(r'\b(LPDDR[45]X?|DDR[345])\b', raw_val, flags=re.IGNORECASE)
        return mem.group(1).upper() if mem else raw_val

    if fname == 'supported_memory_types':
        if isinstance(raw_val, str) and re.search(r'\bDDR[345]\b', raw_val, flags=re.IGNORECASE):
            tokens = sorted({m.upper() for m in re.findall(r'\bDDR[345]\b', raw_val, flags=re.IGNORECASE)})
            if tokens:
                return tokens
        return _split_list_tokens(raw_val)

    if fname == 'performance_tier' and isinstance(raw_val, str):
        return _PERFORMANCE_TIER_ALIASES.get(raw_val.strip().lower(), raw_val.strip().lower())

    if ftype == 'int':
        return _strip_numeric_unit(raw_val, allow_decimal=False)

    if ftype == 'decimal':
        return _strip_numeric_unit(raw_val, allow_decimal=True)

    if ftype == 'list_int':
        tokens = _split_list_tokens(raw_val)
        cleaned = []
        for tok in tokens:
            m = re.search(r'(\d{2,5})\s*(?:mhz|mt/s|mm)?', tok, flags=re.IGNORECASE)
            cleaned.append(m.group(1) if m else tok)
        return cleaned

    return raw_val


def _find_first_regex(text: str, patterns: list[str]) -> str:
    for pat in patterns:
        match = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return ''


def _extract_specs_from_text(
    page_text: str,
    *,
    category_slot: str,
    product_name: str,
    reference_url: str,
    page_title: str = '',
) -> dict | None:
    """
    Deterministic pattern extraction from a fetched public datasheet/product HTML text
    when AI_PROVIDER is unconfigured.
    """
    if not page_text:
        return None

    proposed: dict = {}
    custom: dict = {}

    if category_slot in ('cpu', 'motherboard'):
        sock = _find_first_regex(page_text, [
            r'(?:sockets?[ \t]+supported|cpu[ \t]+socket|socket)[ \t]*[:|][ \t]*([^\n|]{2,25})',
            r'\b(FCLGA[ \t]*\d{4}|LGA[ \t]*\d{4}|AM[45]|s?TRX?\d)\b',
        ])
        if sock:
            proposed['socket'] = normalize_socket(sock)

    if category_slot == 'cpu':
        fam = _find_first_regex(page_text, [
            r'\b((?:Intel[ \t]+Core[ \t]+i\d[ \t]+)?\d{2}th[ \t]+Gen(?:[ \t]+Intel(?:[ \t]+Core)?)?)\b',
            r'\b(Intel[ \t]+Core[ \t]+Ultra[ \t]+(?:Series[ \t]+2|200S?))\b',
            r'\b((?:AMD[ \t]+)?Ryzen[ \t]+\d{4}[a-z]?(?:[ \t]+Series)?)\b',
        ]) or _find_first_regex(product_name, [
            r'\b(?:i\d[- ])?(1[234])\d{3}[A-Z]*\b',
        ])
        if fam:
            if fam.isdigit() and len(fam) == 2:
                fam = f'Intel {fam}th Gen'
            proposed['cpu_family'] = normalize_cpu_family(fam)

        patterns = {
            'cores': [r'(?:total[ \t]+cores|#[ \t]*of[ \t]+cores|cores)[ \t]*[:|][ \t]*(\d{1,3})\b'],
            'threads': [r'(?:total[ \t]+threads|#[ \t]*of[ \t]+threads|threads)[ \t]*[:|][ \t]*(\d{1,3})\b'],
            'base_clock_ghz': [r'(?:processor[ \t]+base[ \t]+frequency|base[ \t]+clock|p-core[ \t]+base[ \t]+frequency)[ \t]*[:|][ \t]*(\d+(?:\.\d+)?)[ \t]*ghz'],
            'boost_clock_ghz': [r'(?:max[ \t]+turbo[ \t]+frequency|max[ \t]+boost[ \t]+clock|boost[ \t]+clock)[ \t]*[:|][ \t]*(\d+(?:\.\d+)?)[ \t]*ghz'],
            'tdp_watts': [r'(?:processor[ \t]+base[ \t]+power|default[ \t]+tdp|base[ \t]+power|tdp)[ \t]*[:|][ \t]*(\d{2,4})[ \t]*w\b'],
            'max_power_watts': [r'(?:maximum[ \t]+turbo[ \t]+power|max[ \t]+turbo[ \t]+power|package[ \t]+power)[ \t]*[:|][ \t]*(\d{2,4})[ \t]*w\b'],
            'max_memory_gb': [r'(?:max[ \t]+memory[ \t]+size|max(?:imum)?[ \t]+memory)[ \t]*[:|][ \t]*(\d{2,4})[ \t]*gb'],
            'max_memory_speed_mhz': [r'DDR5(?:[ \t]*[-/])?[ \t]*(\d{4})[ \t]*(?:MHz|MT/s)'],
            'cache_info': [r'(?:intel[ \t]+smart[ \t]+cache|l3[ \t]+cache|cache)[ \t]*[:|][ \t]*([^\n|]{3,60})'],
        }
        for key, pats in patterns.items():
            val = _find_first_regex(page_text, pats)
            if val:
                proposed[key] = val

        mem_line = _find_first_regex(page_text, [r'(?:memory[ \t]+types|system[ \t]+memory[ \t]+specification)[ \t]*[:|][ \t]*([^\n]+)']) or page_text
        mem_tokens = sorted({m.upper() for m in re.findall(r'\bDDR[345]\b', mem_line, flags=re.IGNORECASE)})
        if mem_tokens:
            proposed['supported_memory_types'] = mem_tokens

        igpu = _find_first_regex(page_text, [r'(?:processor[ \t]+graphics|integrated[ \t]+graphics|graphics[ \t]+model)[ \t]*[:|][ \t]*([^\n|]{2,80})'])
        if igpu:
            proposed['integrated_graphics'] = igpu

    elif category_slot == 'motherboard':
        for key, pats in {
            'chipset': [r'(?:chipset)\s*[:|]\s*([A-Z]\d{3}[A-Z]?)\b'],
            'form_factor': [r'(?:form\s+factor)\s*[:|]\s*(E-ATX|Micro-ATX|mATX|Mini-ITX|ATX)'],
            'memory_type': [r'(?:memory\s+type|supported\s+memory)\s*[:|][^\n]*?\b(DDR[345])\b'],
            'memory_slots': [r'(?:memory\s+slots|dimm\s+slots)\s*[:|]\s*(\d)\b', r'\b(\d)\s*x?\s*DIMM\b'],
            'max_memory_gb': [r'(?:max\s+memory|max\.\s*memory)\s*[:|]\s*(\d{2,4})\s*gb'],
        }.items():
            val = _find_first_regex(page_text, pats)
            if val:
                proposed[key] = 'Micro-ATX' if key == 'form_factor' and val.lower() == 'matx' else val

    elif category_slot == 'ram':
        for key, pats in {
            'memory_type': [r'\b(DDR[345])\b'],
            'ram_capacity_gb': [r'(?:capacity|memory\s+size)\s*[:|]\s*(\d{1,3})\s*GB', r'\b(\d{1,3})\s*GB\s*\(\d\s*x\s*\d+\s*GB\)'],
            'ram_speed_mhz': [r'(\d{4,5})\s*(?:MHz|MT/s)'],
            'cas_latency': [r'\b(CL\d{2})\b'],
        }.items():
            val = _find_first_regex(page_text, pats)
            if val:
                proposed[key] = val

    elif category_slot == 'gpu':
        for key, pats in {
            'vram_gb': [r'(?:memory\s+size|video\s+memory|vram)\s*[:|]\s*(\d{1,3})\s*GB'],
            'vram_type': [r'\b(GDDR6X|GDDR6|GDDR7|HBM2E?|HBM3)\b'],
            'gpu_length_mm': [r'(?:length|card\s+dimensions)[^\n]*?\b(\d{3})\s*mm\b'],
            'tdp_watts': [r'(?:tdp|total\s+board\s+power|graphics\s+card\s+power)\s*[:|]\s*(\d{2,4})\s*w\b'],
            'recommended_psu_watts': [r'(?:recommended\s+psu|recommended\s+system\s+power)\s*[:|]\s*(\d{3,4})\s*w\b'],
        }.items():
            val = _find_first_regex(page_text, pats)
            if val:
                proposed[key] = val

    elif category_slot == 'psu':
        for key, pats in {
            'wattage': [r'(?:wattage|max\s+dc\s+output|continuous\s+power)\s*[:|]\s*(\d{3,4})\s*w\b', r'\b(\d{3,4})\s*W\b'],
            'efficiency_rating': [r'(80\s*PLUS\s*(?:Titanium|Platinum|Gold|Silver|Bronze|White))'],
            'psu_form_factor': [r'(?:form\s+factor)\s*[:|]\s*(SFX-L|SFX|ATX)'],
            'psu_length_mm': [r'(?:length|dimensions)[^\n]*?\b(\d{3})\s*mm\b'],
        }.items():
            val = _find_first_regex(page_text, pats)
            if val:
                proposed[key] = val

    elif category_slot == 'cooler':
        if re.search(r'\b(liquid|aio|radiator)\b', page_text, flags=re.IGNORECASE):
            proposed['cooler_type'] = 'Liquid AIO'
            rad = _find_first_regex(page_text, [r'(?:radiator)[^\n]*?\b(120|240|280|360|420)\s*mm\b'])
            if rad:
                proposed['radiator_size_mm'] = rad
        else:
            proposed['cooler_type'] = 'Air'
            h = _find_first_regex(page_text, [r'(?:height)[^\n]*?\b(\d{2,3})\s*mm\b'])
            if h:
                proposed['cooler_height_mm'] = h
        socks = sorted({normalize_socket(s) for s in re.findall(r'\b(?:LGA\s*\d{4}|AM[45])\b', page_text, flags=re.IGNORECASE)})
        if socks:
            proposed['supported_sockets'] = socks

    pcie = _find_first_regex(page_text, [r'\b(PCIe\s*(?:3\.0|4\.0|5\.0))\b'])
    if pcie and category_slot in ('cpu', 'motherboard', 'gpu'):
        proposed['pcie_version'] = pcie

    if not proposed and not custom:
        return None

    return {
        'match_status': 'exact',
        'identified_name': product_name or page_title,
        'proposed_specs': proposed,
        'custom_specs': custom,
        'sources': [{'url': reference_url, 'title': page_title or reference_url}],
        'confidence': 'medium',
        'summary_note': (
            'Extracted structured specifications directly from the public reference URL '
            '(LLM provider unconfigured). Review every field against the datasheet before approving.'
        ),
    }


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

        slot_fields = get_spec_fields_for_slot(category_slot)
        allowed_fields = {f['name']: f for f in slot_fields + SHARED_METADATA_FIELDS}
        critical_fields = get_critical_field_names(category_slot)

        if not self.ai_client.is_configured:
            if clean_ref_url:
                ref_text = self.search_client.fetch_page_extract(clean_ref_url)
                extracted = _extract_specs_from_text(
                    ref_text,
                    category_slot=category_slot,
                    product_name=clean_name,
                    reference_url=clean_ref_url,
                    page_title=self.search_client.last_page_title,
                )
                if extracted:
                    return self._validate_ai_response(
                        raw_response=extracted,
                        product_name=clean_name,
                        allowed_fields=allowed_fields,
                        slot_fields=slot_fields,
                        critical_fields=critical_fields,
                        brand_name=brand_name,
                        reference_url=clean_ref_url,
                        search_snippets=[],
                        confirmed_match=True,
                    )
                fetch_reason = (
                    f'Reference page could not be read ({self.search_client.last_fetch_error}).'
                    if self.search_client.last_fetch_error
                    else 'Reference page did not expose static HTML specifications (it may require JavaScript rendering).'
                )
                return SpecResearchResult(
                    available=False,
                    status='unavailable',
                    verification_status='unavailable',
                    confidence='low',
                    match_status='unavailable',
                    summary_note=(
                        f'AI provider is unconfigured (AI_PROVIDER=none) and {fetch_reason} '
                        'Enter specifications manually below or configure AI_PROVIDER in .env.'
                    ),
                    raw_provider_status='provider_unconfigured',
                )
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
            'Formatting & situation rules: '
            '1) Exact product identified: set match_status="exact", fill verified proposed_specs from sources, put unverified fields in missing_fields. '
            '2) Possible typo or ambiguous query (for example "AMD Ryzan 5 7600X" unless user confirmed): set match_status="ambiguous", '
            'put likely candidate product name(s) in suggested_corrections with reason, and keep proposed_specs empty until confirmed. '
            '3) Product not found or fictional: set match_status="not_found", leave proposed_specs empty, never guess values, and explain clearly. '
            'NEVER invent, estimate, or guess unknown values. '
            'NEVER output commercial fields such as sku, price, cost_price, quantity, stock, id, or status. '
            'If sources disagree on a spec, DO NOT pick one silently; include it in conflicting_fields. '
            'Use only field keys from allowed_schema. Prefer plain numbers for int/decimal fields (no units), '
            'booleans true/false, canonical socket names (e.g. LGA1700, AM5, LGA1851), '
            'canonical CPU families (e.g. Intel 14th Gen, Ryzen 7000, Ryzen 9000), and performance_tier in '
            '{entry, budget, midrange, upper_mid, high, enthusiast}.'
        )
        schema_desc = [
            {
                'field': f['name'],
                'label': f['label'],
                'type': f['type'],
                'unit': f.get('unit', ''),
                'critical_for_compatibility': bool(f.get('compatibility_critical')),
                **({'example': f['placeholder']} if f.get('placeholder') else {}),
            }
            for f in (slot_fields + SHARED_METADATA_FIELDS)
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

        use_gemini_search = (
            self.ai_client.provider == 'gemini'
            and not search_snippets
            and not reference_page_extract
        )
        prev_search_flag = getattr(self.ai_client, 'enable_google_search', False)
        self.ai_client.enable_google_search = use_gemini_search
        try:
            raw_response = self.ai_client.send_json_prompt(system_prompt, json.dumps(user_payload))
        finally:
            self.ai_client.enable_google_search = prev_search_flag

        grounding_sources = getattr(self.ai_client, 'last_grounding_sources', None) or []
        if grounding_sources:
            seen = {s['url'] for s in search_snippets if isinstance(s, dict) and s.get('url')}
            for gs in grounding_sources:
                url = gs.get('url', '')
                if url and is_safe_public_http_url(url) and url not in seen:
                    seen.add(url)
                    search_snippets.append({
                        'url': url,
                        'title': gs.get('title', url),
                        'snippet': '',
                    })
            search_snippets.sort(
                key=lambda item: 0 if classify_source_origin(item.get('url', ''), brand_name=brand_name) == 'manufacturer' else 1,
            )

        if not isinstance(raw_response, dict):
            err_detail = getattr(self.ai_client, 'last_error', '')
            extra = f' ({err_detail})' if err_detail else ''
            return SpecResearchResult(
                available=False,
                status='unavailable',
                verification_status='unavailable',
                confidence='low',
                match_status='unavailable',
                summary_note=(
                    f'AI specification provider did not return a valid structured response{extra}. '
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
        derived_extras: dict = {}
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
                normalized_val = _normalize_raw_spec_value(fdef, raw_val, derived_extras)
                coerced, err = coerce_spec_value(fdef, normalized_val)
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

            for extra_key, extra_val in derived_extras.items():
                if (
                    extra_key in allowed_fields
                    and extra_key not in proposed_specs
                    and extra_key not in conflicted_field_names
                ):
                    extra_coerced, extra_err = coerce_spec_value(allowed_fields[extra_key], extra_val)
                    if not extra_err and extra_coerced not in (None, '', [], {}):
                        proposed_specs[extra_key] = extra_coerced

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

        if raw_match_status == 'ambiguous' or (not confirmed_match and suggested_corrections and not proposed_specs):
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
