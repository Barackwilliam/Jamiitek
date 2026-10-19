"""
"Unahitaji tukutengenezee?" — mteja anaijaza fomu fupi kwenye template, analipa
(bei ya template + ada ya kazi, Pesapal pekee), na timu ya JamiiTek inamjengea website.

  /templates/<slug>/build-for-me/  → fomu + muhtasari wa bei → Pesapal
  /build/<token>/                  → hali ya ombi (Pesapal inamrudisha hapa)

Malipo yakithibitishwa (apps.pesapal_fulfill → fulfill hapa chini): ombi linakuwa
'paid', timu inaarifiwa (apps.notify) na mteja anapata email. Ada ya kazi inawekwa
kwenye Admin → Builder pricing; ikiwa 0, fomu haipo na vitufe vinaelekeza kwenye
proposal kama zamani.
"""
import logging

from django import forms
from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import BuildRequest

logger = logging.getLogger(__name__)

MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PER_HOUR = 5                      # maombi kwa IP kwa saa — kinga ya spam


def build_fee():
    from .billing import pricing
    return pricing().build_fee


def _renew_fee():
    from .billing import pricing
    return pricing().yearly_hosting_price


class BuildForm(forms.ModelForm):
    class Meta:
        model = BuildRequest
        fields = ('business_name', 'name', 'phone', 'email', 'about')
        widgets = {
            'business_name': forms.TextInput(attrs={'placeholder': 'e.g. Mama Ntilie Restaurant'}),
            'name': forms.TextInput(attrs={'placeholder': 'Your full name'}),
            'phone': forms.TextInput(attrs={'placeholder': '0712 345 678', 'inputmode': 'tel'}),
            'email': forms.EmailInput(attrs={'placeholder': 'you@example.com (optional)'}),
            'about': forms.Textarea(attrs={'rows': 5, 'placeholder':
                'What do you sell or do? Where are you? Your prices, opening hours, and anything you want on the website.'}),
        }

    def clean_phone(self):
        import re
        phone = self.cleaned_data['phone'].strip()
        if len(re.sub(r'\D', '', phone)) < 9:
            raise forms.ValidationError('Please write a phone number we can call or WhatsApp.')
        return phone


def _photos(request):
    """Pakia picha (hadi MAX_PHOTOS). Inarudisha (urls, kosa_au_None)."""
    from apps import storage
    files = request.FILES.getlist('photos')[:MAX_PHOTOS]
    if not files:
        return [], None
    if not storage.is_configured():
        return [], None                 # bila storage: ombi linaendelea, picha zitatumwa baadaye
    urls = []
    for f in files:
        if f.size > MAX_PHOTO_BYTES or not (f.content_type or '').startswith('image/'):
            return [], 'Photos must be pictures (JPG, PNG or WebP), up to 8 MB each.'
        r = storage.upload(f, folder='build-requests')
        if r.get('success'):
            urls.append(r['url'])
    return urls, None


def build_for_me(request, slug):
    from apps.chatbot.ratelimit import _hit
    from apps.models import WebsiteTemplate
    from apps.pesapal_models import PesapalTransaction
    from apps.pesapal_views import _start
    from apps.turnstile import get_client_ip, verify_token

    tpl = get_object_or_404(WebsiteTemplate.objects.defer('preview_html'), slug=slug, is_active=True)
    fee = build_fee()
    if not fee:
        return redirect(f'/proposals/?template={tpl.pk}')
    tpl_price = tpl.price if tpl.for_sale else 0
    total = tpl_price + fee

    form = BuildForm(request.POST or None)
    error = None
    if request.method == 'POST':
        ip = get_client_ip(request)
        allowed, _ = _hit(f'buildreq:{ip}', PER_HOUR, 60 * 60)
        ok, _codes = verify_token(request.POST.get('cf-turnstile-response'), ip)
        if not allowed:
            error = 'Too many requests. Please try again in one hour.'
        elif not ok:
            error = 'Please confirm you are not a robot, then try again.'
        elif form.is_valid():
            photos, error = _photos(request)
            if not error:
                br = form.save(commit=False)
                br.template, br.template_name = tpl, tpl.name
                br.template_price, br.build_fee, br.amount = tpl_price, fee, total
                br.photos = photos
                br.save()
                first, _, last = br.name.partition(' ')
                tx = PesapalTransaction(
                    purpose='build_request', target_id=br.token, amount=total, currency='TZS',
                    description=f'We build your website: {tpl.name}'[:200], email=br.email or '',
                    phone=br.phone[:30], first_name=first[:80], last_name=last[:80])
                return _start(tx, request)

    return render(request, 'build_for_me.html', {
        'tpl': tpl, 'form': form, 'error': error, 'fee': fee, 'tpl_price': tpl_price, 'total': total,
        'max_photos': MAX_PHOTOS, 'renew_fee': _renew_fee(),
    })


def build_status(request, token):
    br = get_object_or_404(BuildRequest, token=token)
    return render(request, 'build_status.html', {'br': br})


def fulfill(tx):
    """Inaitwa na apps.pesapal_fulfill (ndani ya lock, mara moja). False = ombi halipo."""
    from django.db import transaction

    br = BuildRequest.objects.select_for_update().filter(token=tx.target_id).first()
    if br is None:
        return False
    if br.status == 'new':
        br.status = 'paid'
    br.paid_at = br.paid_at or timezone.now()
    br.save(update_fields=['status', 'paid_at'])

    def _tell():
        try:
            from apps.notify import notify
            notify(f'🛠️ TUKUTENGENEZEE — AMELIPA TZS {br.amount:,}: {br.business_name} ({br.name}, {br.phone}). '
                   f'Template: {br.template_name}. Anza kazi: Admin → Build requests.')
        except Exception:
            logger.exception('build_request: notify imeshindwa')
        if br.email:
            try:
                from django.core.mail import send_mail
                send_mail(
                    'We received your payment — we are building your website',
                    f'Hello {br.name},\n\nThank you! We received TSh {br.amount:,} for your website '
                    f'({br.template_name}).\n\nOur team will call you on {br.phone} within one working day '
                    f'to start. You can check your request here:\nhttps://www.jamiitek.com/build/{br.token}/\n\n'
                    f'Thank you,\nJamiiTek',
                    settings.DEFAULT_FROM_EMAIL, [br.email])
            except Exception:
                logger.exception('build_request: email imeshindwa')
    transaction.on_commit(_tell)
    return True
