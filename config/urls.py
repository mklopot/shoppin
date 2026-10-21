"""
URL configuration for Shoppin project.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.shopping.urls')),
    path('shopping/', include('apps.shopping.urls')),
]
