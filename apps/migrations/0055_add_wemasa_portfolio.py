from django.db import migrations


def add_wemasa(apps, schema_editor):
    PortfolioItem = apps.get_model('apps', 'PortfolioItem')
    if PortfolioItem.objects.filter(live_url__icontains='wemasatanzania.org').exists():
        return
    PortfolioItem.objects.create(
        title='WEMASA Tanzania',
        client='WEMASA Tanzania Organization',
        category='NGO',
        summary='Website and content dashboard for an environmental NGO.',
        live_url='https://www.wemasatanzania.org/',
        year='2026',
        image='https://www.jamiitek.com/static/images/work/wemasa-tanzania.webp',
        is_featured=True,
        order=0,
    )


class Migration(migrations.Migration):
    dependencies = [('apps', '0054_is_free_help_text')]
    operations = [migrations.RunPython(add_wemasa, migrations.RunPython.noop)]
