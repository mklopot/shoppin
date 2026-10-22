"""
URL configuration for Shoppin project.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('core/', include('apps.core.urls')),
    path('mealplans/', include('apps.mealplans.urls')),
    path('', include('apps.shopping.urls')),
]
