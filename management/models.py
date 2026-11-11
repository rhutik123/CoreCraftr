from django.conf import settings
from django.db import models


class PortalPermission(models.Model):
    """Unmanaged permission anchor for CoreCraftr Owner & Inventory Portal RBAC."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ('access_portal', 'Can access Owner & Inventory Management Portal'),
            ('manage_products', 'Can create and edit products, images, and specs'),
            ('manage_inventory', 'Can adjust stock levels and thresholds'),
            ('manage_prices', 'Can change product pricing and view cost prices'),
            ('use_ai_research', 'Can run AI product specification research'),
            ('import_export_catalog', 'Can export and import catalog CSV files'),
            ('view_reports', 'Can view management reports and valuation'),
            ('manage_users', 'Can manage staff roles and portal access'),
            ('view_audit_log', 'Can view immutable staff audit logs'),
        ]


class StockMovement(models.Model):
    """Persistent ledger of every stock quantity change across portal, CSV, and orders."""

    REASON_RESTOCK = 'restock'
    REASON_CUSTOMER_RETURN = 'customer_return'
    REASON_DAMAGED = 'damaged'
    REASON_MANUAL_CORRECTION = 'manual_correction'
    REASON_SUPPLIER_ADJUSTMENT = 'supplier_adjustment'
    REASON_ORDER_DEDUCTION = 'order_deduction'
    REASON_ORDER_CANCELLATION = 'order_cancellation'
    REASON_CSV_IMPORT = 'csv_import'
    REASON_INITIAL_STOCK = 'initial_stock'
    REASON_OTHER = 'other'

    REASON_CHOICES = [
        (REASON_RESTOCK, 'Restock / Purchase Order'),
        (REASON_CUSTOMER_RETURN, 'Customer Return'),
        (REASON_DAMAGED, 'Damaged / Write-off'),
        (REASON_MANUAL_CORRECTION, 'Manual Stock Correction'),
        (REASON_SUPPLIER_ADJUSTMENT, 'Supplier Adjustment'),
        (REASON_ORDER_DEDUCTION, 'Customer Order Deduction'),
        (REASON_ORDER_CANCELLATION, 'Order Cancellation Restock'),
        (REASON_CSV_IMPORT, 'CSV Import'),
        (REASON_INITIAL_STOCK, 'Initial Stock Entry'),
        (REASON_OTHER, 'Other'),
    ]

    product = models.ForeignKey(
        'store.Product',
        on_delete=models.CASCADE,
        related_name='stock_movements',
    )
    previous_quantity = models.PositiveIntegerField()
    change_amount = models.IntegerField()
    new_quantity = models.PositiveIntegerField()
    reason = models.CharField(max_length=32, choices=REASON_CHOICES)
    notes = models.TextField(blank=True)
    reference_order = models.ForeignKey(
        'store.Order',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='stock_movements',
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='stock_movements',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        sign = '+' if self.change_amount >= 0 else ''
        return f'{self.product.sku}: {sign}{self.change_amount} ({self.reason})'


class PriceChangeLog(models.Model):
    """Historical log of catalog retail/cost price adjustments."""

    product = models.ForeignKey(
        'store.Product',
        on_delete=models.CASCADE,
        related_name='price_changes',
    )
    previous_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_price = models.DecimalField(max_digits=10, decimal_places=2)
    previous_cost_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_cost_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='price_changes',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return f'{self.product.sku}: {self.previous_price} -> {self.new_price}'


class ImmutableAuditQuerySet(models.QuerySet):
    """Prevent bulk update/delete mutations on audit records via ORM."""

    def delete(self):
        raise PermissionError('AuditLog records are immutable and cannot be deleted.')

    def update(self, **kwargs):
        raise PermissionError('AuditLog records are immutable and cannot be modified.')


class AuditLog(models.Model):
    """Append-only audit trail for Owner and Inventory Portal actions."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='portal_audit_logs',
    )
    actor_username = models.CharField(max_length=150, blank=True)
    actor_role = models.CharField(max_length=60, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    target_type = models.CharField(max_length=60, db_index=True)
    target_id = models.CharField(max_length=64, blank=True)
    target_label = models.CharField(max_length=255, blank=True)
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    summary = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableAuditQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at', '-id']
        default_permissions = ('view',)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError('AuditLog records are append-only and cannot be modified.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('AuditLog records are immutable and cannot be deleted.')

    def __str__(self) -> str:
        return f'[{self.action}] {self.target_type}:{self.target_label or self.target_id}'


class AIResearchDraft(models.Model):
    """Editable draft of AI-researched hardware specifications awaiting staff approval."""

    STATUS_DRAFT = 'draft'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_UNAVAILABLE = 'unavailable'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Pending Review'),
        (STATUS_APPROVED, 'Approved & Applied'),
        (STATUS_REJECTED, 'Discarded'),
        (STATUS_UNAVAILABLE, 'Provider Unavailable'),
    ]

    VERIFICATION_MANUFACTURER = 'verified_manufacturer'
    VERIFICATION_MIXED = 'mixed_sources'
    VERIFICATION_PARTIAL = 'partial'
    VERIFICATION_UNVERIFIED = 'unverified'
    VERIFICATION_UNAVAILABLE = 'unavailable'

    VERIFICATION_CHOICES = [
        (VERIFICATION_MANUFACTURER, 'Verified via Manufacturer Source'),
        (VERIFICATION_MIXED, 'Mixed / Third-Party Sources'),
        (VERIFICATION_PARTIAL, 'Partial / Incomplete'),
        (VERIFICATION_UNVERIFIED, 'Unverified'),
        (VERIFICATION_UNAVAILABLE, 'Unavailable'),
    ]

    MATCH_EXACT = 'exact'
    MATCH_AMBIGUOUS = 'ambiguous'
    MATCH_NOT_FOUND = 'not_found'
    MATCH_UNAVAILABLE = 'unavailable'

    MATCH_STATUS_CHOICES = [
        (MATCH_EXACT, 'Exact Product Identified'),
        (MATCH_AMBIGUOUS, 'Ambiguous / Possible Typo'),
        (MATCH_NOT_FOUND, 'Product Not Confidently Identified'),
        (MATCH_UNAVAILABLE, 'Research Unavailable'),
    ]

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ai_research_drafts',
    )
    product = models.ForeignKey(
        'store.Product',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ai_research_drafts',
    )
    product_name = models.CharField(max_length=255)
    brand_name = models.CharField(max_length=120, blank=True)
    category = models.ForeignKey(
        'store.Category',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ai_research_drafts',
    )
    model_number = models.CharField(max_length=120, blank=True)
    reference_url = models.URLField(max_length=500, blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    match_status = models.CharField(max_length=24, choices=MATCH_STATUS_CHOICES, default=MATCH_EXACT)
    identified_name = models.CharField(max_length=255, blank=True)
    verification_status = models.CharField(
        max_length=32,
        choices=VERIFICATION_CHOICES,
        default=VERIFICATION_UNVERIFIED,
    )
    confidence = models.CharField(max_length=20, default='low')
    proposed_specs = models.JSONField(default=dict, blank=True)
    custom_specs = models.JSONField(default=dict, blank=True)
    sources = models.JSONField(default=list, blank=True)
    missing_fields = models.JSONField(default=list, blank=True)
    conflicting_fields = models.JSONField(default=list, blank=True)
    rejected_fields = models.JSONField(default=list, blank=True)
    suggested_corrections = models.JSONField(default=list, blank=True)
    field_statuses = models.JSONField(default=dict, blank=True)
    summary_note = models.TextField(blank=True)
    raw_provider_status = models.CharField(max_length=80, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_ai_drafts',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return f'AI Draft: {self.product_name} ({self.status})'


class CSVImportBatch(models.Model):
    """Two-step preview and transactional confirmation batch for CSV catalog imports."""

    STATUS_PREVIEW = 'preview'
    STATUS_APPLIED = 'applied'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PREVIEW, 'Awaiting Confirmation'),
        (STATUS_APPLIED, 'Applied'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='csv_import_batches',
    )
    filename = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PREVIEW)
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)
    preview_payload = models.JSONField(default=dict, blank=True)
    applied_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return f'CSV Batch #{self.pk}: {self.filename} ({self.status})'
