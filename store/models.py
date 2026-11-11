from decimal import Decimal
import os
import uuid
from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Category(models.Model):
    """Hardware product category mapped optionally to a PC Builder slot."""

    COMPONENT_SLOT_CHOICES = [
        ('cpu', 'CPU / Processor'),
        ('motherboard', 'Motherboard'),
        ('ram', 'Memory (RAM)'),
        ('gpu', 'Graphics Card (GPU)'),
        ('storage', 'Storage (SSD / HDD)'),
        ('psu', 'Power Supply (PSU)'),
        ('case', 'PC Cabinet / Case'),
        ('cooler', 'CPU Cooler'),
        ('case_fan', 'Case Fan'),
        ('monitor', 'Monitor'),
        ('keyboard', 'Keyboard'),
        ('mouse', 'Mouse'),
        ('accessory', 'Accessories'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    component_slot = models.CharField(
        max_length=30,
        choices=COMPONENT_SLOT_CHOICES,
        default='other',
        db_index=True,
    )
    description = models.TextField(blank=True)
    icon_class = models.CharField(max_length=60, default='bi-cpu')
    display_order = models.PositiveIntegerField(default=0)
    is_pc_component = models.BooleanField(default=False, db_index=True)
    show_in_nav = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['display_order', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Brand(models.Model):
    """Hardware manufacturer / brand."""

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Customer(models.Model):
    """Extended customer profile tied to Django's built-in User."""

    BUILDER_MODE_CHOICES = [
        ('beginner', 'Beginner Mode'),
        ('expert', 'Expert Mode'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True, related_name='customer')
    name = models.CharField(max_length=200, null=True, blank=True)
    email = models.EmailField(max_length=200, null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True, default='')
    default_address = models.CharField(max_length=255, blank=True, default='')
    default_city = models.CharField(max_length=120, blank=True, default='')
    default_state = models.CharField(max_length=120, blank=True, default='')
    default_zipcode = models.CharField(max_length=30, blank=True, default='')
    default_country = models.CharField(max_length=100, blank=True, default='India')
    preferred_builder_mode = models.CharField(
        max_length=20,
        choices=BUILDER_MODE_CHOICES,
        default='beginner',
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        if self.name:
            return self.name
        if self.user:
            return self.user.username
        return f'Customer #{self.pk}'


class Product(models.Model):
    """Hardware product in the e-commerce and PC Builder catalogue."""

    LEGACY_CATEGORIES = (
        ('Processors', 'Processors'),
        ('Motherboards', 'Motherboards'),
        ('Memory(ram)', 'Memory(ram)'),
        ('Storage', 'Storage'),
        ('Cabinets', 'Cabinets'),
        ('Cooling System', 'Cooling System'),
        ('Accessories', 'Accessories'),
    )

    name = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=280, unique=True, null=True, blank=True)
    sku = models.CharField(max_length=64, unique=True, null=True, blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
    )
    legacy_category = models.CharField(max_length=200, null=True, blank=True, choices=LEGACY_CATEGORIES)
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    original_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    digital = models.BooleanField(default=False, null=True, blank=True)
    image = models.ImageField(upload_to='products/', null=True, blank=True)
    static_image_path = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Optional path relative to static/, e.g. images/ryzen_3_1200.jpg',
    )
    short_description = models.CharField(max_length=300, blank=True, default='')
    description = models.TextField(max_length=4000, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    is_trending = models.BooleanField(default=False, db_index=True)
    is_special_offer = models.BooleanField(default=False, db_index=True)
    is_demo_data = models.BooleanField(
        default=False,
        help_text='Indicates seeded catalogue/demo data rather than live merchant ERP sync.',
    )
    spec_verified = models.BooleanField(default=False)
    spec_source = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Manufacturer datasheet or technical reference for verified specs.',
    )
    rating_avg = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal('4.50'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('5.00'))],
    )
    rating_count = models.PositiveIntegerField(default=0)
    warranty_months = models.PositiveIntegerField(default=36)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ['name', 'id']
        indexes = [
            models.Index(fields=['is_active', 'category']),
            models.Index(fields=['is_active', 'brand']),
            models.Index(fields=['price']),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)[:240] or 'product'
            candidate = base_slug
            counter = 1
            while Product.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base_slug}-{counter}'
                counter += 1
            self.slug = candidate
        if not self.sku:
            prefix = (self.category.component_slot[:3].upper() if self.category else 'HW')
            self.sku = f'{prefix}-{uuid.uuid4().hex[:8].upper()}'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('detail', kwargs={'pk': self.pk})

    @property
    def imageURL(self):
        # 1. Uploaded media file if present on disk
        if self.image and getattr(self.image, 'name', ''):
            image_name = self.image.name.lstrip('/')
            media_candidate = os.path.join(settings.MEDIA_ROOT, image_name)
            if os.path.exists(media_candidate):
                return self.image.url
            # Legacy compatibility: images saved as filenames inside static/images/
            static_legacy = os.path.join(settings.BASE_DIR, 'static', 'images', os.path.basename(image_name))
            if os.path.exists(static_legacy):
                return f'{settings.STATIC_URL}images/{os.path.basename(image_name)}'
        # 2. Explicit static path
        if self.static_image_path:
            clean_path = self.static_image_path.lstrip('/')
            static_candidate = os.path.join(settings.BASE_DIR, 'static', clean_path)
            if os.path.exists(static_candidate):
                return f'{settings.STATIC_URL}{clean_path}'
        # 3. Category fallback or generic placeholder
        return f'{settings.STATIC_URL}images/placeholder.png'

    @property
    def discount_percent(self):
        if self.original_price and self.original_price > self.price and self.original_price > 0:
            pct = ((self.original_price - self.price) / self.original_price) * Decimal('100')
            return int(round(pct))
        return 0

    @property
    def stock_quantity(self):
        try:
            return self.inventory.available_quantity
        except Inventory.DoesNotExist:
            return 0

    @property
    def in_stock(self):
        return self.stock_quantity > 0

    @property
    def spec_profile_safe(self):
        try:
            return self.spec_profile
        except HardwareSpecProfile.DoesNotExist:
            return None


class Inventory(models.Model):
    """Inventory stock tracking for a Product."""

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='inventory')
    quantity = models.PositiveIntegerField(default=0)
    reserved_quantity = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=3)
    restock_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Inventories'

    @property
    def available_quantity(self):
        return max(0, self.quantity - self.reserved_quantity)

    @property
    def is_low_stock(self):
        return 0 < self.available_quantity <= self.low_stock_threshold

    @property
    def stock_status_label(self):
        avail = self.available_quantity
        if avail <= 0:
            return 'Out of Stock'
        if avail <= self.low_stock_threshold:
            return f'Low Stock ({avail} left)'
        return f'In Stock ({avail} available)'

    def __str__(self):
        return f'{self.product.name}: {self.available_quantity} avail'


class ProductImage(models.Model):
    """Additional gallery images for a Product."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='gallery_images')
    image = models.ImageField(upload_to='products/gallery/', null=True, blank=True)
    static_path = models.CharField(max_length=255, blank=True, default='')
    alt_text = models.CharField(max_length=200, blank=True, default='')
    is_primary = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-is_primary', 'display_order', 'id']

    @property
    def url(self):
        if self.image and getattr(self.image, 'name', ''):
            return self.image.url
        if self.static_path:
            return f'{settings.STATIC_URL}{self.static_path.lstrip("/")}'
        return f'{settings.STATIC_URL}images/placeholder.png'

    def __str__(self):
        return f'{self.product.name} image #{self.pk}'


class HardwareSpecProfile(models.Model):
    """
    Strongly-typed hardware attributes for deterministic compatibility checks,
    Expert Mode filtering, and Beginner Mode guidance.
    Any None/empty attribute represents UNKNOWN (never assumed compatible).
    """

    PERFORMANCE_TIER_CHOICES = [
        ('entry', 'Entry-Level'),
        ('budget', 'Budget Value'),
        ('midrange', 'Mid-Range'),
        ('upper_mid', 'Upper Mid-Range'),
        ('high', 'High-End'),
        ('enthusiast', 'Enthusiast / Flagship'),
    ]

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='spec_profile')

    # Shared Platform & Tier Info
    socket = models.CharField(max_length=40, blank=True, default='', db_index=True)
    chipset = models.CharField(max_length=60, blank=True, default='', db_index=True)
    form_factor = models.CharField(max_length=40, blank=True, default='', db_index=True)
    memory_type = models.CharField(max_length=20, blank=True, default='', db_index=True)  # DDR4 / DDR5
    tdp_watts = models.PositiveIntegerField(null=True, blank=True)
    max_power_watts = models.PositiveIntegerField(null=True, blank=True)

    # CPU Specific
    cpu_family = models.CharField(max_length=80, blank=True, default='')
    microarchitecture = models.CharField(max_length=80, blank=True, default='')
    cores = models.PositiveIntegerField(null=True, blank=True)
    threads = models.PositiveIntegerField(null=True, blank=True)
    base_clock_ghz = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    boost_clock_ghz = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    integrated_graphics = models.BooleanField(null=True, blank=True)
    igpu_name = models.CharField(max_length=80, blank=True, default='')
    includes_stock_cooler = models.BooleanField(null=True, blank=True)
    supported_memory_types = models.JSONField(default=list, blank=True)
    max_memory_gb = models.PositiveIntegerField(null=True, blank=True)
    max_memory_speed_mhz = models.PositiveIntegerField(null=True, blank=True)
    pcie_version = models.CharField(max_length=20, blank=True, default='')

    # Motherboard Specific
    supported_cpu_families = models.JSONField(default=list, blank=True)
    memory_slots = models.PositiveIntegerField(null=True, blank=True)
    supported_memory_speeds = models.JSONField(default=list, blank=True)
    m2_slots = models.PositiveIntegerField(null=True, blank=True)
    m2_nvme_slots = models.PositiveIntegerField(null=True, blank=True)
    m2_sata_slots = models.PositiveIntegerField(null=True, blank=True)
    sata_ports = models.PositiveIntegerField(null=True, blank=True)
    pcie_x16_slots = models.PositiveIntegerField(null=True, blank=True)
    bios_flashback = models.BooleanField(null=True, blank=True)
    min_bios_note = models.CharField(max_length=255, blank=True, default='')
    slot_sharing_notes = models.TextField(blank=True, default='')
    wifi_included = models.BooleanField(null=True, blank=True)
    eps_connectors_required = models.PositiveIntegerField(null=True, blank=True)

    # RAM Specific
    ram_capacity_gb = models.PositiveIntegerField(null=True, blank=True)
    ram_modules = models.PositiveIntegerField(null=True, blank=True)
    ram_speed_mhz = models.PositiveIntegerField(null=True, blank=True)
    cas_latency = models.CharField(max_length=20, blank=True, default='')
    ecc_support = models.BooleanField(null=True, blank=True)
    module_height_mm = models.PositiveIntegerField(null=True, blank=True)

    # GPU Specific
    gpu_chipset = models.CharField(max_length=100, blank=True, default='')
    vram_gb = models.PositiveIntegerField(null=True, blank=True)
    vram_type = models.CharField(max_length=30, blank=True, default='')
    gpu_length_mm = models.PositiveIntegerField(null=True, blank=True)
    gpu_slot_width = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    recommended_psu_watts = models.PositiveIntegerField(null=True, blank=True)
    required_power_connectors = models.JSONField(default=dict, blank=True)

    # Storage Specific
    storage_type = models.CharField(max_length=40, blank=True, default='')  # NVMe M.2, SATA M.2, SATA 2.5" SSD, SATA 3.5" HDD
    storage_interface = models.CharField(max_length=60, blank=True, default='')
    storage_form_factor = models.CharField(max_length=30, blank=True, default='')  # M.2 2280, 2.5", 3.5"
    capacity_gb = models.PositiveIntegerField(null=True, blank=True)
    read_speed_mbps = models.PositiveIntegerField(null=True, blank=True)
    write_speed_mbps = models.PositiveIntegerField(null=True, blank=True)

    # PSU Specific
    wattage = models.PositiveIntegerField(null=True, blank=True)
    efficiency_rating = models.CharField(max_length=40, blank=True, default='')
    modularity = models.CharField(max_length=30, blank=True, default='')
    psu_form_factor = models.CharField(max_length=20, blank=True, default='')  # ATX, SFX
    psu_length_mm = models.PositiveIntegerField(null=True, blank=True)
    psu_connectors = models.JSONField(default=dict, blank=True)

    # Case / Cabinet Specific
    supported_form_factors = models.JSONField(default=list, blank=True)
    max_gpu_length_mm = models.PositiveIntegerField(null=True, blank=True)
    max_cooler_height_mm = models.PositiveIntegerField(null=True, blank=True)
    max_psu_length_mm = models.PositiveIntegerField(null=True, blank=True)
    drive_bays_35 = models.PositiveIntegerField(null=True, blank=True)
    drive_bays_25 = models.PositiveIntegerField(null=True, blank=True)
    supported_radiator_sizes_mm = models.JSONField(default=list, blank=True)
    included_fans = models.PositiveIntegerField(null=True, blank=True)
    max_fans = models.PositiveIntegerField(null=True, blank=True)

    # Cooler & Case Fan Specific
    cooler_type = models.CharField(max_length=30, blank=True, default='')  # Air / Liquid AIO
    cooler_height_mm = models.PositiveIntegerField(null=True, blank=True)
    radiator_size_mm = models.PositiveIntegerField(null=True, blank=True)
    supported_sockets = models.JSONField(default=list, blank=True)
    max_tdp_rating_watts = models.PositiveIntegerField(null=True, blank=True)
    fan_size_mm = models.PositiveIntegerField(null=True, blank=True)
    fan_pack_count = models.PositiveIntegerField(null=True, blank=True)
    airflow_cfm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)

    # Monitor & Peripherals Specific
    screen_size_inch = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    resolution = models.CharField(max_length=40, blank=True, default='')
    refresh_rate_hz = models.PositiveIntegerField(null=True, blank=True)
    panel_type = models.CharField(max_length=30, blank=True, default='')
    connectivity = models.CharField(max_length=120, blank=True, default='')
    switch_type = models.CharField(max_length=60, blank=True, default='')
    dpi = models.PositiveIntegerField(null=True, blank=True)

    # Builder Ranking & Beginner Guidance Metadata
    performance_tier = models.CharField(
        max_length=20,
        choices=PERFORMANCE_TIER_CHOICES,
        default='midrange',
        db_index=True,
    )
    benchmark_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Relative within-category tier score (1-100) used for ranking & alternatives.',
    )
    target_use_cases = models.JSONField(default=list, blank=True)
    beginner_summary = models.TextField(blank=True, default='')
    tradeoffs_note = models.TextField(blank=True, default='')

    def __str__(self):
        return f'Specs for {self.product.name}'


class ProductSpecification(models.Model):
    """Display-oriented key/value specifications for product detail and comparison pages."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='specifications')
    spec_group = models.CharField(max_length=80, default='General')
    spec_key = models.CharField(max_length=120)
    spec_value = models.CharField(max_length=255)
    unit = models.CharField(max_length=30, blank=True, default='')
    is_highlight = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['spec_group', 'display_order', 'id']
        indexes = [
            models.Index(fields=['product', 'spec_key']),
        ]

    @property
    def formatted_value(self):
        return f'{self.spec_value} {self.unit}'.strip()

    def __str__(self):
        return f'{self.product.name} - {self.spec_key}: {self.formatted_value}'


class WishlistItem(models.Model):
    """Saved wishlist items for an authenticated user."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlisted_by')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'product'], name='unique_user_wishlist_product'),
        ]
        ordering = ['-added_at']

    def __str__(self):
        return f'{self.user.username} -> {self.product.name}'


class Cart(models.Model):
    """
    Shopping Cart model cleanly separated from Order and PCBuild.
    Supports both authenticated users and guest sessions.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True, related_name='cart')
    session_key = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def subtotal(self):
        total = Decimal('0.00')
        for item in self.items.select_related('product'):
            total += item.line_total
        return total

    def __str__(self):
        owner = self.user.username if self.user else f'session:{self.session_key}'
        return f'Cart ({owner})'


class CartItem(models.Model):
    """Individual line item in a Cart."""

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    source_build = models.ForeignKey(
        'pc_builder.PCBuild',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cart_items',
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cart', 'product'], name='unique_cart_product'),
        ]
        ordering = ['added_at', 'id']

    @property
    def line_total(self):
        return self.product.price * self.quantity

    def __str__(self):
        return f'{self.quantity}x {self.product.name}'


class Order(models.Model):
    """Completed or submitted e-commerce order (upgraded from legacy Order model)."""

    STATUS_CHOICES = [
        ('pending', 'Pending Confirmation'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing & Assembly Check'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('cod_demo', 'Cash on Delivery (Demo)'),
        ('upi_demo', 'UPI / QR (Demo Simulation)'),
        ('card_demo', 'Credit / Debit Card (Demo Simulation — No Real Card Collected)'),
        ('netbanking_demo', 'NetBanking (Demo Simulation)'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid_demo', 'Paid (Demo Simulation)'),
        ('cod_pending', 'Pay on Delivery (Demo)'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    order_number = models.CharField(max_length=32, unique=True, null=True, blank=True, db_index=True)
    date_ordered = models.DateTimeField(auto_now_add=True)
    complete = models.BooleanField(default=False)
    transaction_id = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES, default='cod_demo')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='cod_pending')
    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    customer_name = models.CharField(max_length=200, blank=True, default='')
    customer_email = models.EmailField(blank=True, default='')
    customer_phone = models.CharField(max_length=30, blank=True, default='')
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-date_ordered']

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f'ORD-{uuid.uuid4().hex[:10].upper()}'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.order_number or f'Order #{self.id}'

    @property
    def get_cart_total(self):
        if self.total_amount and self.total_amount > 0:
            return self.total_amount
        orderitems = self.orderitem_set.all()
        return sum((item.get_total for item in orderitems), Decimal('0.00'))

    @property
    def get_cart_items(self):
        orderitems = self.orderitem_set.all()
        return sum((item.quantity or 0) for item in orderitems)

    @property
    def shipping(self):
        for item in self.orderitem_set.select_related('product'):
            if item.product and not item.product.digital:
                return True
        return False


class OrderItem(models.Model):
    """Line item captured inside an Order."""

    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True)
    product_name_snapshot = models.CharField(max_length=255, blank=True, default='')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    quantity = models.IntegerField(default=0, null=True, blank=True)
    date_added = models.DateTimeField(auto_now_add=True)

    @property
    def effective_unit_price(self):
        if self.unit_price is not None:
            return self.unit_price
        if self.product:
            return self.product.price
        return Decimal('0.00')

    @property
    def get_total(self):
        return self.effective_unit_price * Decimal(self.quantity or 0)

    def __str__(self):
        name = self.product_name_snapshot or (self.product.name if self.product else 'Removed Product')
        return f'{self.quantity}x {name}'


class ShippingAddress(models.Model):
    """Delivery address linked to an Order."""

    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, related_name='shipping_addresses')
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=200)
    state = models.CharField(max_length=200)
    zipcode = models.CharField(max_length=50)
    country = models.CharField(max_length=100, default='India')
    phone = models.CharField(max_length=30, blank=True, default='')
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.address}, {self.city}'
