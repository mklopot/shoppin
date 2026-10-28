"""
URL configuration for Shoppin project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView

from apps.core import auth_views, tos_views, views

urlpatterns = [
    path('health/', views.health_check, name='health_check'),
    path('admin/', admin.site.urls),
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.ico', permanent=True)),
    # Terms of Service & Compliance
    path('terms/', tos_views.terms_view, name='terms_root'),
    path('terms/accept/', tos_views.terms_accept_view, name='terms_accept_root'),
    # Authentication & Google OAuth
    path('accounts/login/', auth_views.login_view, name='login'),
    path('accounts/logout/', auth_views.logout_view, name='logout'),
    path('accounts/google/login/', auth_views.google_login_view, name='google_login'),
    path('accounts/google/callback/', auth_views.google_callback_view, name='google_callback'),
    path('login/', auth_views.login_view),
    path('logout/', auth_views.logout_view),
    path('core/', include('apps.core.urls')),
    path('mealplans/', include('apps.mealplans.urls')),
    path('recipes/', include('apps.recipes.urls')),
    path('', include('apps.shopping.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
