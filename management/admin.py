from django.contrib import admin

from .models import AIResearchDraft, AuditLog, CSVImportBatch, PriceChangeLog, StockMovement


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'previous_quantity', 'change_amount', 'new_quantity', 'reason', 'performed_by', 'created_at')
    list_filter = ('reason', 'created_at')
    search_fields = ('product__name', 'product__sku', 'notes')
    readonly_fields = (
        'product', 'previous_quantity', 'change_amount', 'new_quantity',
        'reason', 'notes', 'reference_order', 'performed_by', 'created_at',
    )


@admin.register(PriceChangeLog)
class PriceChangeLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'previous_price', 'new_price', 'changed_by', 'created_at')
    search_fields = ('product__name', 'product__sku', 'reason')
    readonly_fields = (
        'product', 'previous_price', 'new_price', 'previous_cost_price',
        'new_cost_price', 'reason', 'changed_by', 'created_at',
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only superuser view for immutable portal audit records."""

    list_display = ('id', 'created_at', 'actor_username', 'actor_role', 'action', 'target_type', 'target_label')
    list_filter = ('action', 'target_type', 'created_at')
    search_fields = ('actor_username', 'action', 'target_label', 'summary')
    readonly_fields = (
        'actor', 'actor_username', 'actor_role', 'action', 'target_type',
        'target_id', 'target_label', 'before_data', 'after_data', 'summary',
        'ip_address', 'created_at',
    )

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIResearchDraft)
class AIResearchDraftAdmin(admin.ModelAdmin):
    list_display = ('id', 'product_name', 'category', 'status', 'verification_status', 'confidence', 'requested_by', 'created_at')
    list_filter = ('status', 'verification_status', 'confidence')
    search_fields = ('product_name', 'brand_name', 'model_number')


@admin.register(CSVImportBatch)
class CSVImportBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'filename', 'status', 'total_rows', 'valid_rows', 'error_rows', 'uploaded_by', 'created_at')
    list_filter = ('status',)
