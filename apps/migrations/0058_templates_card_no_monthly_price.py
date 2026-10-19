from django.db import migrations

# Kadi ya "Ready-Made Templates" (0033) ilisema "Hosted from TZS 15,000/month" — bei ya zamani.
# Templates sasa ni bure kujaribu, na zinazouzwa zina bei moja ya mara moja.
OLD = "Launch in hours, not weeks. Hosted from TZS 15,000/month."
NEW = "Launch in hours, not weeks. Try any design free before you pay anything."


def forwards(apps, schema_editor):
    # Maandishi uliyoyaandika mwenyewe kwenye admin hayaguswi — ya mbegu ya zamani tu
    Service = apps.get_model("apps", "Service")
    Service.objects.filter(summary=OLD).update(summary=NEW)
    Service.objects.filter(description=OLD).update(description=NEW)


def backwards(apps, schema_editor):
    Service = apps.get_model("apps", "Service")
    Service.objects.filter(summary=NEW).update(summary=OLD)
    Service.objects.filter(description=NEW).update(description=OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("apps", "0057_jamiilite_service"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
