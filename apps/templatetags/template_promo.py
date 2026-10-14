"""{% template_promo %} — simu ndogo ya tangazo: "Website hii inauzwa".

Inaonyeshwa Home na kwenye makala za blog. Ni MARA MOJA tu kwa kila browser
(localStorage; akifuta data ya site ataiona tena). Inatokea sekunde chache
baada ya ukurasa kumaliza kufunguka, demo inapakiwa wakati huo tu, na haichukui
nafasi kwenye ukurasa (position:fixed) — haizuii wala haisogezi maudhui.
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
            .values('pk', 'name', 'is_free', 'price', 'gradient_start', 'gradient_end')[:POOL])
    return [dict(r, raw=reverse('template_preview_raw', args=[r['pk']]),
                 for_sale=not r['is_free'] and r['price'] > 0) for r in rows]


@register.inclusion_tag('includes/template_promo.html')
def template_promo():
    from apps.public_cache import get_or_build

    pool = get_or_build('template-promo', _featured, ttl=600)
    return {'promo': random.choice(pool) if pool else None}
