from django.apps import AppConfig


class AppsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps'

    def ready(self):
        # Blog: kufuta cache + IndexNow makala zikibadilika
        from . import blog_signals  # noqa: F401
        # Taarifa kwa mteja website inaposimamishwa — njia zote
        from . import suspension_signals  # noqa: F401
        # Templates: IndexNow kila template inapohifadhiwa (SEO)
        from . import template_signals  # noqa: F401
        # Usalama: kuhesabu makosa ya login (brute-force lockout)
        from . import security  # noqa: F401
        # Admin: dropdown za tovuti bila swali kwa kila chaguo
        from .admin_speed import speed_up_admin
        speed_up_admin()
