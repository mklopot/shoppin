"""
URL configuration for Shoppin project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('core/', include('apps.core.urls')),
    path('mealplans/', include('apps.mealplans.urls')),
    path('recipes/', include('apps.recipes.urls')),
    path('', include('apps.shopping.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
