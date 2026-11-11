import json
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from pc_builder.models import PCBuild
from pc_builder.services.builder_service import PCBuilderService
from .forms import CheckoutForm, CreateUserForm, ProfileUpdateForm
from .models import Category, Customer, Order, Product, WishlistItem
from .services import cart_service, catalog_service, comparison_service, order_service


def _ensure_customer(user) -> Customer:
    customer, _ = Customer.objects.get_or_create(
        user=user,
        defaults={
            'name': user.get_full_name() or user.username,
            'email': user.email or '',
        },
    )
    return customer


def home(request):
    """Homepage showcasing categories, featured/trending hardware, budget PCs, and PC Builder modes."""
    sections = catalog_service.get_homepage_sections()
    budget_tiers = [
        {
            'title': 'Office & Study Starter',
            'budget': '35,000',
            'budget_raw': 35000,
            'use': 'office',
            'summary': 'Quiet iGPU processor, 16GB RAM, fast NVMe SSD — built for crisp everyday work.',
            'badge': 'Best Value',
        },
        {
            'title': '1080p Gaming Sweet Spot',
            'budget': '65,000',
            'budget_raw': 65000,
            'use': 'gaming',
            'summary': '6-core CPU + dedicated RTX/Radeon GPU + 16GB dual-channel RAM + Bronze PSU.',
            'badge': 'Most Popular',
        },
        {
            'title': '1440p Creator & Pro Rig',
            'budget': '1,25,000',
            'budget_raw': 125000,
            'use': 'video_editing',
            'summary': 'AM5 DDR5 or 14th Gen platform + 12GB GPU + 32GB RAM + ATX 3.0 Gold PSU.',
            'badge': 'High Longevity',
        },
    ]
    popular_builds = PCBuild.objects.filter(is_saved=True).select_related('user').prefetch_related('components__product')[:3]

    context = {
        **sections,
        'budget_tiers': budget_tiers,
        'popular_builds': popular_builds,
    }
    return render(request, 'store/home.html', context)


def store(request):
    """Full searchable & filterable hardware catalogue."""
    products_qs = catalog_service.filter_catalogue_products(request.GET)
    facets = catalog_service.get_available_filter_facets()

    paginator = Paginator(products_qs, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    active_category = None
    cat_slug = (request.GET.get('category') or '').strip()
    if cat_slug:
        active_category = Category.objects.filter(slug=cat_slug).first()

    wishlist_ids = set()
    if request.user.is_authenticated:
        wishlist_ids = set(request.user.wishlist_items.values_list('product_id', flat=True))

    compare_ids = set(request.session.get('compare_product_ids', []))

    context = {
        'products': page_obj,
        'page_obj': page_obj,
        'categories': facets['categories'],
        'brands': facets['brands'],
        'active_category': active_category,
        'wishlist_ids': wishlist_ids,
        'compare_ids': compare_ids,
        'filters': request.GET,
        'total_results': paginator.count,
    }
    return render(request, 'store/store.html', context)


def category_detail(request, slug):
    """Redirect or render category-filtered store view cleanly."""
    category = get_object_or_404(Category, slug=slug)
    params = request.GET.copy()
    params['category'] = category.slug
    request.GET = params
    return store(request)


def detail(request, pk):
    """Product detail page with verified specs, stock status, wishlist, compare, and PC Builder CTA."""
    product = get_object_or_404(
        Product.objects.select_related('category', 'brand', 'inventory', 'spec_profile'),
        pk=pk,
        is_active=True,
    )
    grouped_specs = catalog_service.get_grouped_specifications(product)
    related_products = (
        Product.objects.filter(is_active=True, category=product.category)
        .exclude(pk=product.pk)
        .select_related('brand', 'inventory')[:4]
    )
    in_wishlist = False
    if request.user.is_authenticated:
        in_wishlist = WishlistItem.objects.filter(user=request.user, product=product).exists()

    compare_ids = set(request.session.get('compare_product_ids', []))

    context = {
        'product': product,
        'spec_profile': product.spec_profile_safe,
        'grouped_specs': grouped_specs,
        'related_products': related_products,
        'in_wishlist': in_wishlist,
        'in_compare': product.id in compare_ids,
    }
    return render(request, 'store/detail.html', context)


def loginPage(request):
    if request.user.is_authenticated:
        return redirect('home')

    next_url = request.GET.get('next') or request.POST.get('next') or ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)
        if user is not None:
            pre_login_session_key = request.session.session_key
            login(request, user)
            _ensure_customer(user)
            cart_service.merge_session_cart_into_user_cart(request, user, session_key=pre_login_session_key)
            PCBuilderService().merge_guest_build_on_login(request, user, session_key=pre_login_session_key)
            messages.success(request, f'Welcome back, {user.username}!')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('home')
        messages.error(request, 'Invalid username or password. Please try again.')

    return render(request, 'store/login.html', {'next': next_url})


def logoutUser(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('home')


def registerPage(request):
    if request.user.is_authenticated:
        return redirect('home')

    form = CreateUserForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        full_name = form.cleaned_data.get('first_name') or user.username
        customer = _ensure_customer(user)
        customer.name = full_name
        customer.email = user.email
        customer.save()
        messages.success(request, f'Account created for {user.username}. You can now sign in.')
        return redirect('login')

    return render(request, 'store/register.html', {'form': form})


def cart(request):
    """Shopping cart page separated cleanly from PCBuild and completed Orders."""
    user_cart = cart_service.get_or_create_cart(request)
    items = list(
        user_cart.items.select_related('product', 'product__category', 'product__brand', 'product__inventory', 'source_build')
    )
    stock_errors = cart_service.validate_cart_stock(user_cart)
    subtotal = user_cart.subtotal
    requires_shipping = any(not item.product.digital for item in items)
    shipping_fee = order_service.calculate_shipping_fee(subtotal, requires_shipping)
    estimated_total = subtotal + shipping_fee

    context = {
        'cart': user_cart,
        'items': items,
        'subtotal': subtotal,
        'shipping_fee': shipping_fee,
        'estimated_total': estimated_total,
        'free_shipping_threshold': order_service.FREE_SHIPPING_THRESHOLD,
        'stock_errors': stock_errors,
        'requires_shipping': requires_shipping,
    }
    return render(request, 'store/cart.html', context)


@require_POST
def updateItem(request):
    """JSON/POST endpoint for adding, incrementing, decrementing, setting, or removing cart items."""
    try:
        data = json.loads(request.body.decode('utf-8')) if request.content_type == 'application/json' else request.POST
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'success': False, 'message': 'Invalid JSON payload.'}, status=400)

    product_id = data.get('productID') or data.get('product_id')
    action = data.get('action', 'add')
    qty = data.get('quantity')

    if not product_id:
        return JsonResponse({'success': False, 'message': 'Missing product ID.'}, status=400)

    product = get_object_or_404(Product, id=product_id)
    user_cart = cart_service.get_or_create_cart(request)
    parsed_qty = int(qty) if qty is not None and str(qty).isdigit() else None
    result = cart_service.update_cart_item(user_cart, product, action=action, quantity=parsed_qty)

    status_code = 200 if result.success else 400
    return JsonResponse(
        {
            'success': result.success,
            'message': result.message,
            'item_quantity': result.item_quantity,
            'cart_total_items': result.cart_total_items,
            'cart_subtotal': result.cart_subtotal,
        },
        status=status_code,
    )


def checkout(request):
    """Dummy checkout flow with customer details, delivery address, and simulated payment selection."""
    user_cart = cart_service.get_or_create_cart(request)
    items = list(user_cart.items.select_related('product', 'product__inventory'))
    if not items:
        messages.warning(request, 'Your cart is empty. Add hardware items before checking out.')
        return redirect('store')

    stock_errors = cart_service.validate_cart_stock(user_cart)
    subtotal = user_cart.subtotal
    requires_shipping = any(not item.product.digital for item in items)
    shipping_fee = order_service.calculate_shipping_fee(subtotal, requires_shipping)
    total = subtotal + shipping_fee

    initial = {}
    customer = None
    if request.user.is_authenticated:
        customer = _ensure_customer(request.user)
        initial = {
            'customer_name': customer.name or request.user.username,
            'customer_email': customer.email or request.user.email,
            'customer_phone': customer.phone,
            'address': customer.default_address,
            'city': customer.default_city,
            'state': customer.default_state,
            'zipcode': customer.default_zipcode,
            'country': customer.default_country or 'India',
        }

    form = CheckoutForm(request.POST or None, initial=initial)
    if request.method == 'POST':
        if form.is_valid():
            cd = form.cleaned_data
            if requires_shipping and not all([cd.get('address'), cd.get('city'), cd.get('state'), cd.get('zipcode')]):
                messages.error(request, 'Please fill in your complete delivery address (street, city, state, PIN/ZIP code).')
            else:
                res = order_service.create_order_from_cart(
                    cart=user_cart,
                    customer=customer,
                    customer_name=cd['customer_name'],
                    customer_email=cd['customer_email'],
                    customer_phone=cd['customer_phone'],
                    address=cd.get('address', ''),
                    city=cd.get('city', ''),
                    state=cd.get('state', ''),
                    zipcode=cd.get('zipcode', ''),
                    country=cd.get('country') or 'India',
                    payment_method=cd['payment_method'],
                    notes=cd.get('notes', ''),
                )
                if res.success and res.order:
                    recent = request.session.get('recent_order_numbers', [])
                    recent.append(res.order.order_number)
                    request.session['recent_order_numbers'] = recent[-10:]
                    messages.success(request, res.message)
                    return redirect('order_confirmation', order_number=res.order.order_number)
                for err in (res.errors or [res.message]):
                    messages.error(request, err)
        else:
            messages.error(request, 'Please check the checkout form fields below.')

    context = {
        'form': form,
        'items': items,
        'subtotal': subtotal,
        'shipping_fee': shipping_fee,
        'total': total,
        'requires_shipping': requires_shipping,
        'stock_errors': stock_errors,
    }
    return render(request, 'store/checkout.html', context)


@require_POST
def processOrder(request):
    """JSON checkout API endpoint (backwards-compatible path, server-side pricing & stock enforced)."""
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'success': False, 'message': 'Invalid JSON payload.'}, status=400)

    user_cart = cart_service.get_or_create_cart(request)
    form_data = data.get('form', {})
    ship_data = data.get('shipping', {})
    customer = _ensure_customer(request.user) if request.user.is_authenticated else None

    customer_name = (form_data.get('name') or (customer.name if customer else '') or '').strip()
    customer_email = (form_data.get('email') or (customer.email if customer else '') or '').strip()
    customer_phone = (form_data.get('phone') or (customer.phone if customer else '') or '0000000000').strip()
    payment_method = form_data.get('payment_method', 'cod_demo')

    if not customer_name or not customer_email:
        return JsonResponse({'success': False, 'message': 'Customer name and email are required.'}, status=400)

    res = order_service.create_order_from_cart(
        cart=user_cart,
        customer=customer,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        address=(ship_data.get('address') or '').strip(),
        city=(ship_data.get('city') or '').strip(),
        state=(ship_data.get('state') or '').strip(),
        zipcode=(ship_data.get('zipcode') or '').strip(),
        country=(ship_data.get('country') or 'India').strip(),
        payment_method=payment_method,
    )

    if not res.success or not res.order:
        return JsonResponse({'success': False, 'message': res.message, 'errors': res.errors or []}, status=400)

    recent = request.session.get('recent_order_numbers', [])
    recent.append(res.order.order_number)
    request.session['recent_order_numbers'] = recent[-10:]

    return JsonResponse({
        'success': True,
        'message': res.message,
        'order_number': res.order.order_number,
        'total_amount': f'{res.order.total_amount:.2f}',
    })


def order_confirmation(request, order_number):
    """Order confirmation page restricted to order owner or current checkout session."""
    order = get_object_or_404(
        Order.objects.prefetch_related('orderitem_set__product', 'shipping_addresses'),
        order_number=order_number,
    )
    recent = request.session.get('recent_order_numbers', [])
    is_owner = (
        request.user.is_authenticated
        and order.customer
        and order.customer.user_id == request.user.id
    )
    if not is_owner and order.order_number not in recent and not request.user.is_staff:
        raise Http404('Order not found.')

    return render(
        request,
        'store/order_confirmation.html',
        {
            'order': order,
            'items': order.orderitem_set.all(),
            'shipping_address': order.shipping_addresses.first(),
        },
    )


@login_required
def order_history(request):
    customer = _ensure_customer(request.user)
    orders = (
        Order.objects.filter(customer=customer, complete=True)
        .prefetch_related('orderitem_set__product', 'shipping_addresses')
        .order_by('-date_ordered')
    )
    return render(request, 'store/order_history.html', {'orders': orders})


@login_required
def profile(request):
    customer = _ensure_customer(request.user)
    form = ProfileUpdateForm(request.POST or None, instance=customer)
    if request.method == 'POST' and form.is_valid():
        updated_customer = form.save()
        if updated_customer.email and request.user.email != updated_customer.email:
            request.user.email = updated_customer.email
            request.user.save(update_fields=['email'])
        messages.success(request, 'Profile preferences updated.')
        return redirect('profile')

    saved_builds_count = PCBuild.objects.filter(user=request.user, is_saved=True).count()
    orders_count = Order.objects.filter(customer=customer, complete=True).count()
    wishlist_count = WishlistItem.objects.filter(user=request.user).count()

    return render(
        request,
        'store/profile.html',
        {
            'form': form,
            'customer': customer,
            'saved_builds_count': saved_builds_count,
            'orders_count': orders_count,
            'wishlist_count': wishlist_count,
        },
    )


@login_required
def wishlist(request):
    items = (
        WishlistItem.objects.filter(user=request.user)
        .select_related('product', 'product__category', 'product__brand', 'product__inventory')
    )
    return render(request, 'store/wishlist.html', {'wishlist_items': items})


@login_required
@require_POST
def toggle_wishlist(request, pk):
    product = get_object_or_404(Product, pk=pk, is_active=True)
    existing = WishlistItem.objects.filter(user=request.user, product=product).first()
    if existing:
        existing.delete()
        added = False
        msg = f'Removed {product.name} from your wishlist.'
    else:
        WishlistItem.objects.create(user=request.user, product=product)
        added = True
        msg = f'Saved {product.name} to your wishlist.'

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({'success': True, 'added': added, 'message': msg})

    messages.success(request, msg)
    next_url = request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('detail', pk=product.pk)


def compare_products(request):
    """Side-by-side comparison view for up to 4 products of the same category."""
    compare_ids = request.session.get('compare_product_ids', [])
    products = list(
        Product.objects.filter(id__in=compare_ids, is_active=True)
        .select_related('category', 'brand', 'inventory')
        .prefetch_related('specifications')
    )
    # Preserve session insertion order
    id_pos = {pid: i for i, pid in enumerate(compare_ids)}
    products.sort(key=lambda p: id_pos.get(p.id, 999))

    matrix = comparison_service.build_comparison_matrix(products)
    return render(request, 'store/compare.html', matrix)


@require_POST
def toggle_compare(request, pk):
    product = get_object_or_404(Product, pk=pk, is_active=True)
    compare_ids = list(request.session.get('compare_product_ids', []))

    if product.id in compare_ids:
        compare_ids.remove(product.id)
        messages.info(request, f'Removed {product.name} from comparison.')
    else:
        existing = Product.objects.filter(id__in=compare_ids).select_related('category')
        if existing.exists():
            first_cat_id = existing.first().category_id
            if first_cat_id != product.category_id:
                compare_ids = [product.id]
                messages.info(
                    request,
                    f'Started a fresh {product.category.name if product.category else ""} comparison with {product.name}.',
                )
            elif len(compare_ids) >= 4:
                messages.warning(request, 'You can compare up to 4 products at a time.')
            else:
                compare_ids.append(product.id)
                messages.success(request, f'Added {product.name} to comparison.')
        else:
            compare_ids.append(product.id)
            messages.success(request, f'Added {product.name} to comparison.')

    request.session['compare_product_ids'] = compare_ids
    next_url = request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('compare')


@require_POST
def clear_compare(request):
    request.session['compare_product_ids'] = []
    messages.info(request, 'Cleared product comparison list.')
    return redirect('compare')
