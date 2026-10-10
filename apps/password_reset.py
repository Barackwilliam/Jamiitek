"""
"Forgot password" kwa akaunti zote za JamiiTek (apps/password_reset.py).

Akaunti moja inatumika Client Portal, JamiiBot na Web Builder (angalia
apps/accounts_link.py), kwa hiyo kuna ukurasa mmoja: /account/password-reset/.

Inajengwa juu ya views za Django (tokens zinazotumika mara moja, zinazokufa
nywila ikibadilika au baada ya PASSWORD_RESET_TIMEOUT), pamoja na:
  • ujumbe ule ule kama email ipo au haipo — mtu hawezi kujua nani ana akaunti
  • kikomo: maombi 5 kwa saa kwa email, 20 kwa saa kwa IP (email bombing)
  • nywila mpya inapita AUTH_PASSWORD_VALIDATORS
  • baada ya kubadilisha: kufuli ya login (apps/security.py) inaondolewa,
    sessions nyingine zote zinakufa, na mwenye akaunti anapata email ya taarifa
"""
import logging

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.core.cache import cache
from django.core.mail import send_mail
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme

from apps.turnstile import get_client_ip

log = logging.getLogger('apps.security')

LOGIN_PAGES = {
    'portal': ('/portal/login/', 'Client Portal'),
    'bot': ('/chatbot/login/', 'JamiiBot'),
    'builder': ('/builder/login/', 'Web Builder'),
    'staff': ('/manage/login/', 'Staff panel'),
}


def _came_from(request):
    """Mtu alitoka login ipi — ili 'Back to sign in' imrudishe huko."""
    key = request.GET.get('from') or request.POST.get('from') or request.session.get('pw_reset_from')
    return key if key in LOGIN_PAGES else 'portal'


def _hit(key, limit, seconds):
    cache.add(key, 0, seconds)
    try:
        return cache.incr(key) <= limit
    except ValueError:
        cache.set(key, 1, seconds)
        return True


class JamiiPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update(
            {'class': 'in', 'autocomplete': 'email', 'placeholder': 'you@example.com', 'autofocus': True})


def _site():
    """Domain ya link ya email inatoka kwenye settings, SI Host header ya ombi
    (vinginevyo mshambulizi angetuma Host bandia na link ingeelekea kwake)."""
    from urllib.parse import urlparse
    u = urlparse(getattr(settings, 'SITE_BASE_URL', '') or 'https://www.jamiitek.com')
    return u.netloc or 'www.jamiitek.com', u.scheme == 'https'


class RequestView(auth_views.PasswordResetView):
    template_name = 'account/password_reset_form.html'
    email_template_name = 'account/email/password_reset.txt'
    html_email_template_name = 'account/email/password_reset.html'
    subject_template_name = 'account/email/password_reset_subject.txt'
    form_class = JamiiPasswordResetForm
    success_url = reverse_lazy('password_reset_done')

    def dispatch(self, request, *args, **kwargs):
        request.session['pw_reset_from'] = _came_from(request)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        key = _came_from(self.request)
        ctx['back_url'], ctx['back_label'] = LOGIN_PAGES[key]
        return ctx

    def form_valid(self, form):
        email = (form.cleaned_data.get('email') or '').strip().lower()
        ip = get_client_ip(self.request) or 'unknown'
        if not (_hit(f'sec:pwreset:email:{email}', 5, 3600) and _hit(f'sec:pwreset:ip:{ip}', 20, 3600)):
            # Jibu lile lile — si kosa, ili kisitumike kuchunguza
            log.warning('Password reset: kikomo kimefikiwa (email=%s ip=%s)', email, ip)
            from django.shortcuts import redirect
            return redirect(self.get_success_url())
        log.info('Password reset imeombwa: email=%s ip=%s', email, ip)
        return super().form_valid(form)

    @property
    def extra_email_context(self):
        return {'support_email': getattr(settings, 'PAYMENTS_OWNER_EMAIL', 'info@jamiitek.com'),
                'minutes': settings.PASSWORD_RESET_TIMEOUT // 60,
                # Domain na protocol za link zinatoka settings, si Host header
                'domain': _site()[0],
                'protocol': 'https' if _site()[1] else 'http'}


class DoneView(auth_views.PasswordResetDoneView):
    template_name = 'account/password_reset_done.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['back_url'], ctx['back_label'] = LOGIN_PAGES[_came_from(self.request)]
        ctx['minutes'] = settings.PASSWORD_RESET_TIMEOUT // 60
        return ctx


class JamiiSetPasswordForm(SetPasswordForm):
    """SetPasswordForm tayari inaendesha validators; tunaongeza tu placeholders."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].widget.attrs.update(
            {'class': 'in', 'autocomplete': 'new-password', 'placeholder': 'At least 8 characters'})
        self.fields['new_password2'].widget.attrs.update(
            {'class': 'in', 'autocomplete': 'new-password', 'placeholder': 'Type it again'})


class ConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'account/password_reset_confirm.html'
    form_class = JamiiSetPasswordForm
    success_url = reverse_lazy('password_reset_complete')
    post_reset_login = False

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        # Nywila mpya → ondoa kufuli ya login iliyosababishwa na majaribio mabaya
        from apps.security import _key
        cache.delete(_key('user', user.get_username()))
        if user.email:
            cache.delete(_key('user', user.email))
        # Sessions nyingine zote za mtumiaji huyu zinakufa: session hash
        # inatokana na nywila, kwa hiyo Django inazikataa zenyewe.
        log.warning('Password reset imekamilika: user=%s ip=%s', user, get_client_ip(self.request))
        _notify_changed(user, self.request)
        return response


class CompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'account/password_reset_complete.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['back_url'], ctx['back_label'] = LOGIN_PAGES[_came_from(self.request)]
        return ctx


def _notify_changed(user, request):
    """Taarifa kwa mwenye akaunti — kama si yeye aliyebadilisha, ajue mara moja."""
    if not user.email:
        return
    try:
        from django.utils import timezone
        when = timezone.localtime().strftime('%d %b %Y, %H:%M')
        send_mail(
            'Your JamiiTek password was changed',
            (f'Hello {user.get_full_name() or user.get_username()},\n\n'
             f'The password for your JamiiTek account ({user.get_username()}) was changed on {when} (EAT).\n\n'
             'If this was you, no action is needed.\n'
             'If it was NOT you, reset your password immediately at '
             f'{getattr(settings, "SITE_BASE_URL", "https://www.jamiitek.com")}/account/password-reset/ '
             'and contact us at info@jamiitek.com.\n\n— JamiiTek Security'),
            None, [user.email], fail_silently=True,
        )
    except Exception:
        log.exception('Password changed notice haikutumwa')


def help_center(request):
    """Msaada wa akaunti: kuingia, nywila, two-step verification, mawasiliano.
    Unafunguka hata katikati ya hatua ya 2FA (angalia apps/two_factor.py)."""
    from django.shortcuts import render
    from apps.contact import contact
    return render(request, 'account/help.html', {'c': contact()})
