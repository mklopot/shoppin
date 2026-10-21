"""
URL configuration for Shoppin project.
"""

from django.contrib import admin
from django.urls import path

from apps.core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', core_views.index, name='index'),
]
