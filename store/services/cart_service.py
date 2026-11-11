from dataclasses import dataclass
from django.db import transaction
from store.models import Cart, CartItem, Product


@dataclass
class CartOperationResult:
    success: bool
    message: str
    cart: Cart
    item_quantity: int = 0
    cart_total_items: int = 0
    cart_subtotal: str = '0.00'


def _ensure_session_key(request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def get_or_create_cart(request) -> Cart:
    """Return active Cart for authenticated user or current guest session."""
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart
    session_key = _ensure_session_key(request)
    cart, _ = Cart.objects.get_or_create(session_key=session_key, user__isnull=True)
    return cart


def merge_session_cart_into_user_cart(request, user, session_key: str | None = None) -> None:
    """Merge any guest session cart items into the logged-in user's cart."""
    session_key = session_key or request.session.session_key
    if not session_key:
        return
    guest_cart = Cart.objects.filter(session_key=session_key, user__isnull=True).first()
    if not guest_cart:
        return

    user_cart, _ = Cart.objects.get_or_create(user=user)
    for guest_item in guest_cart.items.select_related('product'):
        avail = guest_item.product.stock_quantity
        if avail <= 0:
            continue
        existing = CartItem.objects.filter(cart=user_cart, product=guest_item.product).first()
        if existing:
            existing.quantity = min(avail, existing.quantity + guest_item.quantity)
            if not existing.source_build and guest_item.source_build:
                existing.source_build = guest_item.source_build
            existing.save()
        else:
            CartItem.objects.create(
                cart=user_cart,
                product=guest_item.product,
                quantity=min(avail, guest_item.quantity),
                source_build=guest_item.source_build,
            )
    guest_cart.delete()


@transaction.atomic
def update_cart_item(cart: Cart, product: Product, action: str = 'add', quantity: int | None = None, source_build=None) -> CartOperationResult:
    """
    Add, decrement, set quantity, or remove a product in the cart with strict stock validation.
    """
    if not product.is_active:
        return CartOperationResult(
            success=False,
            message=f'{product.name} is currently unavailable.',
            cart=cart,
            cart_total_items=cart.total_items,
            cart_subtotal=f'{cart.subtotal:.2f}',
        )

    available = product.stock_quantity
    existing = CartItem.objects.filter(cart=cart, product=product).first()

    if action == 'delete' or (action == 'set' and quantity is not None and quantity <= 0):
        if existing:
            existing.delete()
        return CartOperationResult(
            success=True,
            message=f'Removed {product.name} from your cart.',
            cart=cart,
            item_quantity=0,
            cart_total_items=cart.total_items,
            cart_subtotal=f'{cart.subtotal:.2f}',
        )

    if action == 'remove':
        if not existing:
            return CartOperationResult(
                success=False,
                message=f'{product.name} is not in your cart.',
                cart=cart,
                cart_total_items=cart.total_items,
                cart_subtotal=f'{cart.subtotal:.2f}',
            )
        new_qty = existing.quantity - 1
        if new_qty <= 0:
            existing.delete()
            return CartOperationResult(
                success=True,
                message=f'Removed {product.name} from your cart.',
                cart=cart,
                item_quantity=0,
                cart_total_items=cart.total_items,
                cart_subtotal=f'{cart.subtotal:.2f}',
            )
        existing.quantity = new_qty
        existing.save()
        return CartOperationResult(
            success=True,
            message=f'Updated {product.name} quantity to {new_qty}.',
            cart=cart,
            item_quantity=new_qty,
            cart_total_items=cart.total_items,
            cart_subtotal=f'{cart.subtotal:.2f}',
        )

    # 'add' or 'set'
    if available <= 0:
        return CartOperationResult(
            success=False,
            message=f'{product.name} is currently out of stock.',
            cart=cart,
            item_quantity=existing.quantity if existing else 0,
            cart_total_items=cart.total_items,
            cart_subtotal=f'{cart.subtotal:.2f}',
        )

    if action == 'set' and quantity is not None:
        desired_qty = int(quantity)
    else:
        desired_qty = (existing.quantity if existing else 0) + (int(quantity) if quantity else 1)

    if desired_qty > available:
        return CartOperationResult(
            success=False,
            message=f'Only {available} unit(s) of {product.name} available in stock.',
            cart=cart,
            item_quantity=existing.quantity if existing else 0,
            cart_total_items=cart.total_items,
            cart_subtotal=f'{cart.subtotal:.2f}',
        )

    if existing:
        existing.quantity = desired_qty
        if source_build and not existing.source_build:
            existing.source_build = source_build
        existing.save()
    else:
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=desired_qty,
            source_build=source_build,
        )

    return CartOperationResult(
        success=True,
        message=f'Added {product.name} to your cart.',
        cart=cart,
        item_quantity=desired_qty,
        cart_total_items=cart.total_items,
        cart_subtotal=f'{cart.subtotal:.2f}',
    )


def validate_cart_stock(cart: Cart) -> list[str]:
    """Return a list of stock error strings if any item exceeds inventory."""
    errors = []
    for item in cart.items.select_related('product', 'product__inventory'):
        avail = item.product.stock_quantity
        if not item.product.is_active:
            errors.append(f'{item.product.name} is no longer available.')
        elif avail < item.quantity:
            errors.append(
                f'{item.product.name}: requested {item.quantity}, but only {avail} unit(s) remain in stock.'
            )
    return errors
