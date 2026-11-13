"""
Management command to provision standard dev personas and sample workspaces.
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.core.models import Workspace, WorkspaceMember, WorkspaceRole
from apps.mealplans.models import MealPlan
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem, StoreLocation

User = get_user_model()


class Command(BaseCommand):
    """Seed standard personas for testing multi-user workspace sharing."""

    help = "Seeds test user accounts (admin, alice, bob, carol) and workspaces."

    def handle(self, *args: Any, **options: Any) -> None:
        personas = [
            ("admin", "admin123", True, "Admin User"),
            ("alice", "alice123", False, "Alice Johnson"),
            ("bob", "bob123", False, "Bob Smith"),
            ("carol", "carol123", False, "Carol Danvers"),
        ]

        users: dict[str, Any] = {}
        for username, password, is_super, full_name in personas:
            user, created = User.objects.get_or_create(username=username)
            if created or not user.has_usable_password():
                user.set_password(password)
            user.is_staff = is_super
            user.is_superuser = is_super
            user.first_name = full_name.split()[0]
            user.last_name = full_name.split()[1] if len(full_name.split()) > 1 else ""
            user.save()
            users[username] = user
            self.stdout.write(f"User ready: {username}")

        # Ensure TOS acceptance for dev personas
        from apps.core.models import TermsOfServiceAcceptance
        for u in users.values():
            TermsOfServiceAcceptance.objects.get_or_create(
                user=u,
                version=TermsOfServiceAcceptance.CURRENT_VERSION,
                defaults={
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "ip_address": "127.0.0.1",
                    "user_agent": "Seeded Dev Persona",
                    "screen_resolution": "1920x1080",
                },
            )

        # Ensure default store
        store = StoreLocation.objects.first()

        # 1. Main Home Workspace (Owner: admin)
        home_ws, _ = Workspace.objects.get_or_create(
            name="Home",
            defaults={"owner": users["admin"]},
        )
        if home_ws.owner != users["admin"]:
            home_ws.owner = users["admin"]
            home_ws.save()

        # Add alice as Editor, bob as Viewer in Home
        WorkspaceMember.objects.update_or_create(
            workspace=home_ws,
            user=users["alice"],
            defaults={"role": WorkspaceRole.EDITOR},
        )
        WorkspaceMember.objects.update_or_create(
            workspace=home_ws,
            user=users["bob"],
            defaults={"role": WorkspaceRole.VIEWER},
        )

        # 2. Bob's Cabin Workspace (Owner: bob)
        cabin_ws, _ = Workspace.objects.get_or_create(
            name="Mountain Cabin",
            defaults={"owner": users["bob"]},
        )
        if not cabin_ws.get_primary_list():
            cabin_list = ShoppingList.objects.create(
                name="Cabin Shopping List",
                workspace=cabin_ws,
                owner=users["bob"],
                is_preset=False,
                active_store=store,
            )
            ShoppingListItem.objects.create(
                shopping_list=cabin_list,
                name="Firewood Bundle",
                amount=2,
                status=ItemStatus.NEED,
            )
            ShoppingListItem.objects.create(
                shopping_list=cabin_list,
                name="Hot Cocoa",
                amount=1,
                status=ItemStatus.NEED,
            )
        if not cabin_ws.get_meal_plan():
            MealPlan.objects.create(
                name="Cabin Weekend Meals",
                workspace=cabin_ws,
                owner=users["bob"],
            )

        # Share Cabin with Alice as Viewer
        WorkspaceMember.objects.update_or_create(
            workspace=cabin_ws,
            user=users["alice"],
            defaults={"role": WorkspaceRole.VIEWER},
        )

        self.stdout.write(self.style.SUCCESS("Successfully seeded personas and workspaces."))
