from decimal import Decimal
from django.db.models import Count, Q
from store.models import Brand, Category, Product


def get_homepage_sections():
    """Fetch curated sections for the homepage."""
    base_qs = (
        Product.objects.filter(is_active=True)
        .select_related('category', 'brand', 'inventory', 'spec_profile')
    )
    return {
        'categories': Category.objects.annotate(
            product_count=Count('products', filter=Q(products__is_active=True))
        ).order_by('display_order', 'name'),
        'featured_products': base_qs.filter(is_featured=True)[:8],
        'trending_products': base_qs.filter(is_trending=True)[:8],
        'special_offers': base_qs.filter(is_special_offer=True)[:6],
    }


def filter_catalogue_products(params: dict):
    """
    Filter and sort active catalogue products by query, category, brand,
    price range, availability, and hardware attributes.
    """
    qs = (
        Product.objects.filter(is_active=True)
        .select_related('category', 'brand', 'inventory', 'spec_profile')
    )

    q = (params.get('q') or '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(short_description__icontains=q)
            | Q(description__icontains=q)
            | Q(brand__name__icontains=q)
            | Q(category__name__icontains=q)
            | Q(sku__icontains=q)
            | Q(spec_profile__socket__icontains=q)
            | Q(spec_profile__chipset__icontains=q)
            | Q(spec_profile__memory_type__icontains=q)
            | Q(spec_profile__gpu_chipset__icontains=q)
        )

    category_slug = (params.get('category') or '').strip()
    if category_slug:
        qs = qs.filter(category__slug=category_slug)

    brand_slug = (params.get('brand') or '').strip()
    if brand_slug:
        qs = qs.filter(brand__slug=brand_slug)

    min_price = params.get('min_price')
    if min_price:
        try:
            qs = qs.filter(price__gte=Decimal(str(min_price)))
        except Exception:
            pass

    max_price = params.get('max_price')
    if max_price:
        try:
            qs = qs.filter(price__lte=Decimal(str(max_price)))
        except Exception:
            pass

    in_stock_only = str(params.get('in_stock') or '').lower() in ('1', 'true', 'yes', 'on')
    if in_stock_only:
        qs = qs.filter(inventory__quantity__gt=0)

    socket_filter = (params.get('socket') or '').strip()
    if socket_filter:
        qs = qs.filter(spec_profile__socket__iexact=socket_filter)

    memory_filter = (params.get('memory_type') or '').strip()
    if memory_filter:
        qs = qs.filter(spec_profile__memory_type__iexact=memory_filter)

    sort = (params.get('sort') or 'featured').strip()
    sort_map = {
        'featured': ('-is_featured', '-is_trending', 'name'),
        'price_asc': ('price', 'name'),
        'price_desc': ('-price', 'name'),
        'rating': ('-rating_avg', '-rating_count', 'name'),
        'newest': ('-created_at', '-id'),
        'name': ('name',),
    }
    qs = qs.order_by(*sort_map.get(sort, ('-is_featured', 'name')))
    return qs


def get_grouped_specifications(product: Product) -> dict[str, list]:
    """Group ProductSpecification rows by spec_group for clean product detail rendering."""
    grouped = {}
    for spec in product.specifications.all():
        grouped.setdefault(spec.spec_group, []).append(spec)
    return grouped


def get_available_filter_facets():
    """Return available categories, brands, sockets, and memory types for filter sidebars."""
    categories = Category.objects.annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    ).order_by('display_order', 'name')
    brands = Brand.objects.annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    ).filter(product_count__gt=0).order_by('name')
    return {
        'categories': categories,
        'brands': brands,
    }
