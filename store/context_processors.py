from django.db.models import Sum
from store.models import Category, Cart


def global_store_context(request):
    """Provides navigation categories, active cart count, and active builder count globally."""
    nav_categories = Category.objects.filter(show_in_nav=True).order_by('display_order', 'name')

    cart_item_count = 0
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
    elif request.session.session_key:
        cart = Cart.objects.filter(session_key=request.session.session_key, user__isnull=True).first()
    else:
        cart = None

    if cart:
        agg = cart.items.aggregate(total=Sum('quantity'))
        cart_item_count = agg['total'] or 0

    wishlist_count = 0
    if request.user.is_authenticated:
        wishlist_count = request.user.wishlist_items.count()

    return {
        'nav_categories': nav_categories,
        'cartItems': cart_item_count,
        'wishlist_count': wishlist_count,
        'compare_count': len(request.session.get('compare_product_ids', [])),
    }
