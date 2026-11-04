from django.db import migrations

# JamiiLite 5G imehamia domain yake: https://wifi.jamiitek.co.tz/ (ilikuwa jamiilite.onrender.com).
OLD, NEW = "https://jamiilite.onrender.com/", "https://wifi.jamiitek.co.tz/"


def move(apps, schema_editor, old=OLD, new=NEW):
    Service = apps.get_model("apps", "Service")
    for svc in Service.objects.filter(link_url__startswith=old):
        svc.link_url = new + svc.link_url[len(old):]
        svc.save(update_fields=["link_url"])


def back(apps, schema_editor):
    move(apps, schema_editor, old=NEW, new=OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("apps", "0064_activity_log"),
    ]

    operations = [migrations.RunPython(move, back)]
