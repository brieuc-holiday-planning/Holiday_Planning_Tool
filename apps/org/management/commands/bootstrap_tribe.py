import os
from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.org.models import Cluster, Squad, Tribe
from apps.org.titles import seed_default_titles


class Command(BaseCommand):
    help = (
        "Idempotently creates the default Tribe and a break-glass Scrum "
        "Master superuser account. Safe to re-run: existing rows are left "
        "untouched. Optionally also creates a first Cluster/Squad."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tribe-name", default="Default Tribe")
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument("--admin-email", default="")
        parser.add_argument(
            "--admin-password",
            default=None,
            help="Falls back to DJANGO_SUPERUSER_PASSWORD env var, then an interactive prompt.",
        )
        parser.add_argument("--cluster-name", default=None)
        parser.add_argument("--squad-name", default=None)

    def handle(self, *args, **options):
        with transaction.atomic():
            tribe, created = Tribe.objects.get_or_create(name=options["tribe_name"])
            self.stdout.write(
                self.style.SUCCESS(f"Tribe '{tribe.name}' {'created' if created else 'already exists'}.")
            )

            titles = seed_default_titles(tribe)
            self.stdout.write(self.style.SUCCESS(f"Default titles ready: {', '.join(t.name for t in titles.values())}."))

            self._bootstrap_admin(tribe, titles, options)

            if options["cluster_name"]:
                cluster, created = Cluster.objects.get_or_create(tribe=tribe, name=options["cluster_name"])
                self.stdout.write(
                    self.style.SUCCESS(f"Cluster '{cluster.name}' {'created' if created else 'already exists'}.")
                )
                if options["squad_name"]:
                    squad, created = Squad.objects.get_or_create(cluster=cluster, name=options["squad_name"])
                    self.stdout.write(
                        self.style.SUCCESS(f"Squad '{squad.name}' {'created' if created else 'already exists'}.")
                    )

    def _bootstrap_admin(self, tribe, titles, options):
        username = options["admin_username"]
        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f"User '{username}' already exists, skipping."))
            return

        password = (
            options["admin_password"]
            or os.environ.get("DJANGO_SUPERUSER_PASSWORD")
            or getpass(f"Password for break-glass admin '{username}': ")
        )
        if not password:
            raise CommandError("An admin password is required (flag, env var, or prompt).")

        User.objects.create_superuser(
            username=username,
            email=options["admin_email"],
            password=password,
            title=titles["scrum_master"],
            is_staff=True,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created break-glass Scrum Master superuser '{username}'. "
                "This is the only account that should ever be is_superuser=True; "
                "create every other Scrum Master through the app's User admin."
            )
        )
