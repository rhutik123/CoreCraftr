import uuid
from decimal import Decimal
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from store.models import Product


class ChipsetCPUSupport(models.Model):
    """
    Platform-level compatibility matrix mapping (socket + chipset + cpu_family)
    to verified support or BIOS update warnings.
    Prevents false assumptions where sockets match (e.g. AM4) but chipsets differ
    (e.g. B550 does not support Ryzen 1000/2000G) or BIOS updates are required.
    """

    STATUS_CHOICES = [
        ('compatible', 'Verified Compatible'),
        ('bios_update_required', 'BIOS Update May Be Required'),
        ('incompatible', 'Incompatible'),
    ]

    socket = models.CharField(max_length=40, db_index=True)
    chipset = models.CharField(max_length=60, db_index=True)
    cpu_family = models.CharField(max_length=80, db_index=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='compatible')
    notes = models.TextField(blank=True, default='')
    source_reference = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['socket', 'chipset', 'cpu_family'],
                name='unique_socket_chipset_cpufamily',
            ),
        ]
        ordering = ['socket', 'chipset', 'cpu_family']

    def __str__(self):
        return f'{self.socket} / {self.chipset} + {self.cpu_family}: {self.status}'


class MotherboardCPUSupport(models.Model):
    """
    Explicit manufacturer CPU support-list overrides for specific Motherboard + CPU pairs.
    Takes precedence over generic chipset rules when present.
    """

    STATUS_CHOICES = [
        ('verified', 'Verified Supported'),
        ('bios_required', 'Supported with Minimum BIOS Version'),
        ('unsupported', 'Not Supported on CPU Support List'),
    ]

    motherboard = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='cpu_support_entries',
    )
    cpu = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='motherboard_support_entries',
    )
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='verified')
    min_bios_version = models.CharField(max_length=60, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    source_reference = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['motherboard', 'cpu'], name='unique_mobo_cpu_support'),
        ]

    def __str__(self):
        return f'{self.motherboard.name} + {self.cpu.name}: {self.status}'


class PCBuild(models.Model):
    """
    Unified PC Build model shared seamlessly between Beginner Mode and Expert Mode.
    Switching modes preserves the exact same build and all selected components.
    """

    MODE_CHOICES = [
        ('beginner', 'Beginner Mode ("Help me build my first PC")'),
        ('expert', 'Expert Mode ("I know what I\'m looking for")'),
    ]

    PRIMARY_USE_CHOICES = [
        ('gaming', 'Gaming'),
        ('programming', 'Programming & Development'),
        ('video_editing', 'Video Editing & 3D Rendering'),
        ('office', 'Office Work & Study'),
        ('streaming', 'Streaming & Content Creation'),
        ('mixed', 'Mixed Everyday + Heavy Usage'),
    ]

    PRIORITY_CHOICES = [
        ('value', 'Best Value / Cost-Effective'),
        ('balanced', 'Balanced Performance & Value'),
        ('performance', 'Maximum Performance'),
    ]

    UPGRADEABILITY_CHOICES = [
        ('high', 'High Future Upgradeability'),
        ('moderate', 'Moderate Upgradeability'),
        ('low', 'Maximize Today\'s Performance'),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='pc_builds')
    session_key = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=160, default='My Custom PC Build')
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='beginner')
    is_active_workspace = models.BooleanField(default=True, db_index=True)
    is_saved = models.BooleanField(default=False, db_index=True)

    # Beginner Questionnaire Preferences (preserved across mode switches)
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    primary_use = models.CharField(max_length=30, choices=PRIMARY_USE_CHOICES, blank=True, default='gaming')
    preferred_brands = models.JSONField(default=list, blank=True)
    include_monitor = models.BooleanField(default=False)
    include_peripherals = models.BooleanField(default=False)
    priority_preference = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='balanced')
    upgradeability_preference = models.CharField(max_length=20, choices=UPGRADEABILITY_CHOICES, default='moderate')

    notes = models.TextField(blank=True, default='')
    ai_summary = models.TextField(blank=True, default='')
    ai_source = models.CharField(max_length=50, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', 'is_active_workspace']),
            models.Index(fields=['session_key', 'is_active_workspace']),
        ]

    @property
    def total_price(self):
        total = Decimal('0.00')
        for comp in self.components.select_related('product'):
            total += comp.line_total
        return total

    @property
    def component_count(self):
        return self.components.count()

    def get_slot_map(self):
        return {comp.slot: comp for comp in self.components.select_related('product', 'product__category', 'product__brand', 'product__spec_profile', 'product__inventory')}

    def __str__(self):
        return f'{self.name} ({self.mode})'


class BuildComponent(models.Model):
    """Selected component in a specific PC Builder slot."""

    SLOT_CHOICES = [
        ('cpu', 'CPU / Processor'),
        ('motherboard', 'Motherboard'),
        ('ram', 'Memory (RAM)'),
        ('gpu', 'Graphics Card (GPU)'),
        ('storage', 'Primary Storage'),
        ('storage_secondary', 'Secondary Storage'),
        ('psu', 'Power Supply (PSU)'),
        ('case', 'PC Case / Cabinet'),
        ('cooler', 'CPU Cooler'),
        ('case_fan', 'Additional Cooling / Case Fans'),
        ('monitor', 'Monitor'),
        ('keyboard', 'Keyboard'),
        ('mouse', 'Mouse'),
    ]

    CORE_SLOTS = ['cpu', 'motherboard', 'ram', 'gpu', 'storage', 'psu', 'case', 'cooler']
    ALL_SLOTS = [choice[0] for choice in SLOT_CHOICES]

    build = models.ForeignKey(PCBuild, on_delete=models.CASCADE, related_name='components')
    slot = models.CharField(max_length=30, choices=SLOT_CHOICES)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='build_usages')
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    selection_reason = models.TextField(blank=True, default='')
    tradeoffs = models.TextField(blank=True, default='')
    added_via_mode = models.CharField(max_length=20, default='expert')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['build', 'slot'], name='unique_build_slot'),
        ]
        ordering = ['id']

    @property
    def line_total(self):
        return self.product.price * Decimal(self.quantity)

    def __str__(self):
        return f'{self.build.name} [{self.slot}] -> {self.product.name}'
