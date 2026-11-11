from dataclasses import dataclass
from decimal import Decimal
import uuid
from django.db import transaction
from django.utils import timezone
from store.models import Cart, Customer, Inventory, Order, OrderItem, ShippingAddress


FREE_SHIPPING_THRESHOLD = Decimal('5000.00')
STANDARD_SHIPPING_FEE = Decimal('199.00')


@dataclass
class CheckoutResult:
    success: bool
    message: str
    order: Order | None = None
    errors: list[str] | None = None


def calculate_shipping_fee(subtotal: Decimal, requires_shipping: bool) -> Decimal:
    if not requires_shipping or subtotal <= Decimal('0.00'):
        return Decimal('0.00')
    if subtotal >= FREE_SHIPPING_THRESHOLD:
        return Decimal('0.00')
    return STANDARD_SHIPPING_FEE


@transaction.atomic
def create_order_from_cart(
    *,
    cart: Cart,
    customer: Customer | None,
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    address: str,
    city: str,
    state: str,
    zipcode: str,
    country: str = 'India',
    payment_method: str = 'cod_demo',
    notes: str = '',
    compatibility_status: str = '',
    compatibility_summary: dict | None = None,
    incompatibility_acknowledged: bool = False,
) -> CheckoutResult:
    """
    Convert Cart into a confirmed Order inside a database transaction:
    - Computes prices and totals strictly on the server from DB Product prices.
    - Locks Inventory rows and decrements stock atomically.
    - Records dummy payment method (never processes real card credentials).
    - Clears the Cart upon success.
    """
    cart_items = list(cart.items.select_related('product').order_by('id'))
    if not cart_items:
        return CheckoutResult(
            success=False,
            message='Your shopping cart is empty.',
            errors=['Add at least one item to your cart before checking out.'],
        )

    stock_errors = []
    subtotal = Decimal('0.00')
    requires_shipping = False

    # Lock inventory rows in deterministic order to avoid deadlocks
    product_ids = [item.product_id for item in cart_items]
    inventories = {
        inv.product_id: inv
        for inv in Inventory.objects.select_for_update().filter(product_id__in=product_ids).order_by('product_id')
    }

    for item in cart_items:
        product = item.product
        inv = inventories.get(product.id)
        avail = inv.available_quantity if inv else 0
        if not product.is_active:
            stock_errors.append(f'{product.name} is currently unavailable.')
        elif avail < item.quantity:
            stock_errors.append(
                f'{product.name}: requested {item.quantity}, but only {avail} left in stock.'
            )
        subtotal += product.price * Decimal(item.quantity)
        if not product.digital:
            requires_shipping = True

    if stock_errors:
        return CheckoutResult(
            success=False,
            message='Some items in your cart do not have sufficient stock.',
            errors=stock_errors,
        )

    shipping_fee = calculate_shipping_fee(subtotal, requires_shipping)
    total_amount = subtotal + shipping_fee

    valid_methods = {code for code, _ in Order.PAYMENT_METHOD_CHOICES}
    if payment_method not in valid_methods:
        payment_method = 'cod_demo'

    payment_status = 'cod_pending' if payment_method == 'cod_demo' else 'paid_demo'
    transaction_id = f'DEMO-{uuid.uuid4().hex[:12].upper()}'

    order = Order.objects.create(
        customer=customer,
        complete=True,
        transaction_id=transaction_id,
        status='confirmed',
        payment_method=payment_method,
        payment_status=payment_status,
        subtotal_amount=subtotal,
        shipping_amount=shipping_fee,
        total_amount=total_amount,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        notes=notes,
        compatibility_status=compatibility_status,
        compatibility_summary=compatibility_summary or {},
        incompatibility_acknowledged=incompatibility_acknowledged,
        incompatibility_acknowledged_at=timezone.now() if incompatibility_acknowledged else None,
    )

    for item in cart_items:
        product = item.product
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name_snapshot=product.name,
            unit_price=product.price,
            quantity=item.quantity,
        )
        inv = inventories[product.id]
        previous_quantity = inv.quantity
        inv.quantity = max(0, previous_quantity - item.quantity)
        inv.save(update_fields=['quantity', 'updated_at'])
        if previous_quantity != inv.quantity:
            from django.apps import apps

            if apps.is_installed('management'):
                StockMovement = apps.get_model('management', 'StockMovement')
                actor_user = (
                    order.customer.user
                    if getattr(order, 'customer_id', None) and getattr(order.customer, 'user_id', None)
                    else None
                )
                StockMovement.objects.create(
                    product=product,
                    previous_quantity=previous_quantity,
                    change_amount=inv.quantity - previous_quantity,
                    new_quantity=inv.quantity,
                    reason='order_deduction',
                    notes=f'Order #{order.id} placement deduction',
                    reference_order=order,
                    performed_by=actor_user,
                )

    if requires_shipping:
        ShippingAddress.objects.create(
            customer=customer,
            order=order,
            address=address,
            city=city,
            state=state,
            zipcode=zipcode,
            country=country or 'India',
            phone=customer_phone,
        )

    # Save customer default shipping info if logged in and currently empty
    if customer and requires_shipping:
        changed = False
        if not customer.default_address and address:
            customer.default_address = address
            customer.default_city = city
            customer.default_state = state
            customer.default_zipcode = zipcode
            customer.default_country = country or 'India'
            changed = True
        if not customer.phone and customer_phone:
            customer.phone = customer_phone
            changed = True
        if changed:
            customer.save()

    cart.items.all().delete()

    return CheckoutResult(
        success=True,
        message=f'Order {order.order_number} placed successfully!',
        order=order,
    )
