"""
WebSocket URL routing for the shopping application.
"""

from django.urls import path

from apps.shopping import consumers

websocket_urlpatterns = [
    path("ws/shopping/", consumers.ShoppingListConsumer.as_asgi()),
    path("ws/shopping/<int:list_id>/", consumers.ShoppingListConsumer.as_asgi()),
]
