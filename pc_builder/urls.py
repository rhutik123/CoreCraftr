from django.urls import path
from . import api_views, views

urlpatterns = [
    path('', views.builder_workspace, name='pc_builder'),
    path('switch-mode/', views.switch_mode, name='builder_switch_mode'),
    path('recommend/', views.beginner_recommend, name='builder_recommend'),
    path('select/<str:slot>/', views.select_component_page, name='builder_select_slot'),
    path('set-component/', views.set_component_action, name='builder_set_component'),
    path('remove-component/<str:slot>/', views.remove_component_action, name='builder_remove_component'),
    path('clear/', views.clear_build_action, name='builder_clear'),
    path('save/', views.save_build_action, name='builder_save'),
    path('saved/', views.saved_builds_list, name='builder_saved_list'),
    path('load/<uuid:build_uuid>/', views.load_saved_build_action, name='builder_load'),
    path('delete/<uuid:build_uuid>/', views.delete_saved_build_action, name='builder_delete'),
    path('add-to-cart/', views.add_build_to_cart_action, name='builder_add_to_cart'),

    # DRF JSON APIs
    path('api/build/', api_views.BuildStateAPIView.as_view(), name='api_builder_state'),
    path('api/compatibility/', api_views.CompatibilityCheckAPIView.as_view(), name='api_builder_compatibility'),
    path('api/recommend/', api_views.BeginnerRecommendAPIView.as_view(), name='api_builder_recommend'),
    path('api/alternatives/<str:slot>/', api_views.SlotAlternativesAPIView.as_view(), name='api_builder_alternatives'),
]
