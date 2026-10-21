from django.db import migrations

NAME = "JamiiLite 5G — WiFi Hotspot Billing"
URL = "https://jamiilite.onrender.com/"


def go_live(apps, schema_editor):
    """JamiiLite 5G iko hewani: badilisha "Coming soon" kuwa kujisajili. Mabadiliko ya admin yanabaki."""
    Service = apps.get_model("apps", "Service")
    Service.objects.filter(service_type=NAME, link_label="Coming soon").update(
        summary="WiFi hotspot billing for MikroTik owners: customers buy packages by mobile money, "
                "get a voucher instantly and are cut off when time runs out. Now live — start free for 14 days.",
        description=(
            "JamiiLite 5G is a WiFi hotspot billing system for MikroTik router owners. Customers choose a "
            "package, pay by mobile money and are connected instantly; when their time runs out they are "
            "disconnected automatically. Vouchers are issued automatically after payment, every package has "
            "its own time and speed limit, and one voucher only works on the number of devices you allow, "
            "so there is no password sharing. You can see your routers online and restart them remotely. "
            "JamiiLite 5G is now live — create your account and try it free for 14 days."
        ),
        link_label="Start free",
        link_url=URL + "jisajili/",
    )


def back_to_coming_soon(apps, schema_editor):
    Service = apps.get_model("apps", "Service")
    Service.objects.filter(service_type=NAME, link_label="Start free").update(
        link_label="Coming soon", link_url="/#jamiilite",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("apps", "0059_template_funnel"),
    ]

    operations = [migrations.RunPython(go_live, back_to_coming_soon)]
