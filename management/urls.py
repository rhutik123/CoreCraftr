from django.urls import path

from . import views

app_name = 'management'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Categories
    path('categories/', views.category_list, name='category_list'),
    path('categories/add/', views.category_create, name='category_create'),
    path('categories/init-starters/', views.category_init_starters, name='category_init_starters'),
    path('categories/<int:category_id>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:category_id>/toggle-active/', views.category_toggle_active, name='category_toggle_active'),
    path('categories/<int:category_id>/delete/', views.category_delete, name='category_delete'),

    # Products & Media & Dynamic Specifications
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.product_create, name='product_create'),
    path('products/<int:product_id>/', views.product_edit, name='product_edit'),
    path('products/<int:product_id>/status/', views.product_change_status, name='product_change_status'),
    path('products/<int:product_id>/images/primary/<int:image_id>/', views.product_image_set_primary, name='product_image_set_primary'),
    path('products/<int:product_id>/images/replace/<int:image_id>/', views.product_image_replace, name='product_image_replace'),
    path('products/<int:product_id>/images/delete/<int:image_id>/', views.product_image_delete, name='product_image_delete'),

    # Portal AJAX / API helpers
    path('api/spec-schema/<int:category_id>/', views.api_category_spec_schema, name='api_spec_schema'),
    path('api/duplicate-check/', views.api_duplicate_check, name='api_duplicate_check'),
    path('api/ai-research/', views.api_ai_research_specs, name='api_ai_research'),
    path('api/ai-draft/<int:draft_id>/discard/', views.api_ai_draft_discard, name='api_ai_draft_discard'),

    # Inventory & Stock Movements
    path('inventory/', views.inventory_list, name='inventory_list'),
    path('inventory/<int:product_id>/adjust/', views.inventory_adjust, name='inventory_adjust'),
    path('inventory/<int:product_id>/settings/', views.inventory_settings, name='inventory_settings'),
    path('inventory/history/', views.stock_history, name='stock_history'),

    # CSV Bulk Import / Export
    path('import-export/', views.import_export, name='import_export'),
    path('import-export/export/', views.export_catalog_csv, name='export_csv'),

    # Reports & Valuation
    path('reports/', views.reports, name='reports'),

    # Owner-only Access & Audit Control
    path('users/', views.user_management, name='user_management'),
    path('users/action/', views.user_management_action, name='user_management_action'),
    path('audit/', views.audit_log, name='audit_log'),
]
