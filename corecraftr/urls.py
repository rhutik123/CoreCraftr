from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'CoreCraftr Administration'
admin.site.site_title = 'CoreCraftr Admin'
admin.site.index_title = 'CoreCraftr Storefront, Catalog & PC Builder Control'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('builder/', include('pc_builder.urls')),
    path('', include('store.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
