from django.contrib import admin
from .models import (
    Brand,
    Cart,
    CartItem,
    Category,
    Customer,
    HardwareSpecProfile,
    Inventory,
    Order,
    OrderItem,
    Product,
    ProductImage,
    ProductSpecification,
    ShippingAddress,
    WishlistItem,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'component_slot', 'is_pc_component', 'display_order', 'show_in_nav')
    list_filter = ('component_slot', 'is_pc_component', 'show_in_nav')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('display_order', 'name')


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'website')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


class InventoryInline(admin.StackedInline):
    model = Inventory
    extra = 0


class HardwareSpecProfileInline(admin.StackedInline):
    model = HardwareSpecProfile
    extra = 0


class ProductSpecificationInline(admin.TabularInline):
    model = ProductSpecification
    extra = 1


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'sku',
        'category',
        'brand',
        'price',
        'stock_display',
        'is_active',
        'is_featured',
        'is_trending',
        'is_special_offer',
        'spec_verified',
        'is_demo_data',
    )
    list_filter = (
        'category',
        'brand',
        'is_active',
        'is_featured',
        'is_trending',
        'is_special_offer',
        'spec_verified',
        'is_demo_data',
    )
    search_fields = ('name', 'sku', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [InventoryInline, HardwareSpecProfileInline, ProductSpecificationInline, ProductImageInline]

    @admin.display(description='Stock')
    def stock_display(self, obj):
        return obj.stock_quantity


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'user', 'phone', 'preferred_builder_mode', 'updated_at')
    search_fields = ('name', 'email', 'user__username')
    list_filter = ('preferred_builder_mode',)


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'session_key', 'total_items', 'subtotal', 'updated_at')
    inlines = [CartItemInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'product_name_snapshot', 'unit_price', 'quantity')


class ShippingAddressInline(admin.StackedInline):
    model = ShippingAddress
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number',
        'customer',
        'customer_name',
        'status',
        'payment_method',
        'payment_status',
        'total_amount',
        'complete',
        'date_ordered',
    )
    list_filter = ('status', 'payment_method', 'payment_status', 'complete')
    search_fields = ('order_number', 'transaction_id', 'customer_name', 'customer_email')
    inlines = [OrderItemInline, ShippingAddressInline]


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'added_at')
    search_fields = ('user__username', 'product__name')


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'quantity', 'reserved_quantity', 'available_quantity', 'low_stock_threshold')
    search_fields = ('product__name', 'product__sku')
