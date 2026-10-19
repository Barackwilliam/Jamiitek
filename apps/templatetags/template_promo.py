"""{% template_promo %} — simu ndogo ya tangazo: "Website hii inauzwa · Gusa kuitazama".

Inaonyeshwa Home na kwenye makala za blog. Inatokea mtu akianza ku-scroll, kisha
inapumzika saa 2 kwenye browser hiyo (localStorage). Demo inajisogeza ndani ya simu,
na haichukui nafasi kwenye ukurasa (position:fixed) — haizuii wala haisogezi maudhui.
wILife inaonyesha simu hiyo hiyo kwa data ya /templates/promo.json.
"""
import random

from django import template
from django.urls import reverse

register = template.Library()

POOL = 6        # templates za mbele kabisa zinazopokezana kwenye tangazo


def _featured():
    from apps.models import WebsiteTemplate

    rows = (WebsiteTemplate.objects.filter(is_active=True).exclude(preview_html='')
            .order_by('order', '-created_at')
            .values('pk', 'name', 'slug', 'gradient_start', 'gradient_end')[:POOL])
    # Kugusa simu kunafungua ukurasa wa template hiyo hiyo ("Gusa kuitazama")
    return [dict(r, raw=reverse('template_preview_raw', args=[r['pk']]),
                 url=reverse('template_detail', args=[r['slug']]) if r['slug'] else reverse('templates_marketplace'))
            for r in rows]


@register.inclusion_tag('includes/template_promo.html')
def template_promo():
    from apps.public_cache import get_or_build

    pool = get_or_build('template-promo', _featured, ttl=600)
    return {'promo': random.choice(pool) if pool else None}
