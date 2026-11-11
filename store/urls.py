from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('store/', views.store, name='store'),
    path('category/<slug:slug>/', views.category_detail, name='category_detail'),
    path('detail/<str:pk>/', views.detail, name='detail'),
    path('compare/', views.compare_products, name='compare'),
    path('compare/toggle/<int:pk>/', views.toggle_compare, name='toggle_compare'),
    path('compare/clear/', views.clear_compare, name='clear_compare'),

    path('cart/', views.cart, name='cart'),
    path('cart/swap/', views.swap_cart_item, name='swap_cart_item'),
    path('checkout/', views.checkout, name='checkout'),
    path('update_item/', views.updateItem, name='update_item'),
    path('process_order/', views.processOrder, name='process_order'),
    path('order/<str:order_number>/', views.order_confirmation, name='order_confirmation'),

    path('account/profile/', views.profile, name='profile'),
    path('account/orders/', views.order_history, name='order_history'),
    path('account/wishlist/', views.wishlist, name='wishlist'),
    path('wishlist/toggle/<int:pk>/', views.toggle_wishlist, name='toggle_wishlist'),

    path('register/', views.registerPage, name='register'),
    path('login/', views.loginPage, name='login'),
    path('logout/', views.logoutUser, name='logout'),

    path(
        'reset_password/',
        auth_views.PasswordResetView.as_view(
            template_name='store/reset_password.html',
            email_template_name='store/reset_email.txt',
            subject_template_name='store/reset_subject.txt',
        ),
        name='reset_password',
    ),
    path(
        'reset_password_sent/',
        auth_views.PasswordResetDoneView.as_view(template_name='store/reset_sent.html'),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(template_name='store/change_password.html'),
        name='password_reset_confirm',
    ),
    path(
        'reset_password_complete/',
        auth_views.PasswordResetCompleteView.as_view(template_name='store/reset_complete.html'),
        name='password_reset_complete',
    ),
]
