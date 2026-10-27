"""
URL configuration for Shoppin project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core import auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
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
