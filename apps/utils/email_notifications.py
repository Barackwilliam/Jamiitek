# apps/utils/email_notifications.py
"""
JamiiTek Email Notification System
=====================================
Central module for all automated emails sent to clients.

USAGE:
    from apps.utils.email_notifications import (
        send_hosting_expiry_warning,
        send_website_suspended,
        send_website_restored,
        send_payment_received,
        send_domain_expiry_warning,
        send_welcome_email,
        send_bulk_expiry_warnings,
    )
"""

import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
FROM_EMAIL   = getattr(settings, 'DEFAULT_FROM_EMAIL', 'JamiiTek <noreply@jamiitek.com>')
PORTAL_URL   = getattr(settings, 'PORTAL_BASE_URL', 'https://jamiitek.com/portal/')


def _send(subject: str, template: str, context: dict, to_email: str) -> bool:
    """
    Core send helper. Renders HTML template, generates plain-text fallback,
    sends via Django's email backend. Returns True on success, False on failure.
    NEVER raises — all exceptions are caught and logged.
    """
    if not to_email:
        logger.warning(f"[Email] No recipient for: {subject}")
        return False

    context.setdefault('subject', subject)
    context.setdefault('portal_url', PORTAL_URL)

    try:
        html_body  = render_to_string(f'emails/{template}', context)
        plain_body = strip_tags(html_body)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_body,
            from_email=FROM_EMAIL,
            to=[to_email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=True)

        logger.info(f"[Email ✅] '{subject}' → {to_email}")
        return True

    except Exception as e:
        logger.error(f"[Email ❌] '{subject}' → {to_email} | Error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 1. HOSTING EXPIRY WARNING
# ══════════════════════════════════════════════════════════════════════════════

# Hatua za onyo: siku 7 (kirafiki), 3 (haraka), 1 (mwisho).
# Kila hatua ina template yake — barua isiseme "siku 3" wakati imebaki moja.
WARNING_STAGES = (
    (7, 'hosting_7days_warning.html', '⏰ Hosting Expiry Notice — {site} expires in {days} {dw}'),
    (3, 'hosting_3days_warning.html', '🚨 URGENT — {site} suspends in {days} {dw}. Renew now'),
    (1, 'hosting_1day_warning.html',  '🔴 FINAL NOTICE — {site} suspends {when}'),
)


def stage_for(days_left: int):
    """Hatua inayostahili kwa siku zilizobaki, au None ikiwa bado ni mapema.

    Tunatumia MADIRISHA (<=), si usawa kamili. Awali ilikuwa
    `raw_days == 7`; kazi ya siku moja ikikosa kukimbia, siku inayofuata
    ni 6 na onyo hilo halikutumwa kamwe. Sasa siku 6 bado inaingia
    kwenye dirisha la 7.
    """
    if days_left <= 0:
        return None          # imeshaisha — hii ni kazi ya kusitisha, si onyo
    for stage, _tpl, _subj in reversed(WARNING_STAGES):   # 1, 3, 7
        if days_left <= stage:
            return stage
    return None


def send_hosting_expiry_warning(website, days: int = None) -> bool:
    """Tuma onyo la kuisha kwa hosting kwa hatua sahihi."""
    client = website.client
    raw_days = (website.hosting_end_date - timezone.now().date()).days
    if days is None:
        days = raw_days
    days = max(int(days), 0)

    stage = stage_for(days) or WARNING_STAGES[-1][0]
    template, subject_fmt = next(
        (t, subj) for st, t, subj in WARNING_STAGES if st == stage)

    dw = 'day' if days == 1 else 'days'
    when = 'today' if days <= 0 else ('tomorrow' if days == 1 else f'in {days} days')
    subject = subject_fmt.format(site=website.name, days=days, dw=dw, when=when)

    return _send(
        subject=subject,
        template=template,
        context={
            'client_name':  client.name,
            'website_name': website.name,
            'website_url':  website.url,
            'expiry_date':  website.hosting_end_date.strftime('%d %B %Y'),
            'days_left':    days,
            'monthly_cost': website.monthly_cost,
        },
        to_email=client.email,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. WEBSITE SUSPENDED
# ══════════════════════════════════════════════════════════════════════════════

def send_website_suspended(website, reason: str = 'Hosting payment overdue') -> bool:
    """Send suspension notice with full restore instructions."""
    client = website.client
    return _send(
        subject=f"🔒 SUSPENDED — {website.name} is now offline | Pay to restore",
        template='website_suspended.html',
        context={
            'client_name':        client.name,
            'website_name':       website.name,
            'website_url':        website.url,
            'reason':             reason,
            'suspended_date':     timezone.now().strftime('%d %B %Y'),
            'suspension_message': getattr(website, 'suspension_message', ''),
            'monthly_cost':       website.monthly_cost,
        },
        to_email=client.email,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3. WEBSITE RESTORED
# ══════════════════════════════════════════════════════════════════════════════

def send_website_restored(website) -> bool:
    """Send restoration confirmation when website is brought back online."""
    client = website.client
    return _send(
        subject=f"✅ Your website '{website.name}' is back online!",
        template='website_restored.html',
        context={
            'client_name':      client.name,
            'website_name':     website.name,
            'website_url':      website.url,
            'restored_date':    timezone.now().strftime('%d %B %Y'),
            'new_expiry_date':  website.hosting_end_date.strftime('%d %B %Y'),
        },
        to_email=client.email,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. PAYMENT RECEIVED
# ══════════════════════════════════════════════════════════════════════════════

def send_payment_received(payment) -> bool:
    """
    Send payment receipt after recording a new HostingPayment.
    Pass the HostingPayment instance.
    """
    website = payment.website
    client  = website.client
    return _send(
        subject=f"💰 Payment Received — TZS {payment.amount:,.0f} for {website.name}",
        template='payment_received.html',
        context={
            'client_name':      client.name,
            'website_name':     website.name,
            'amount':           payment.amount,
            'payment_date':     payment.payment_date.strftime('%d %B %Y'),
            'months_covered':   payment.months_covered,
            'payment_method':   payment.payment_method or 'N/A',
            'transaction_ref':  payment.transaction_ref,
            'new_expiry_date':  website.hosting_end_date.strftime('%d %B %Y'),
        },
        to_email=client.email,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 5. DOMAIN EXPIRY WARNING
# ══════════════════════════════════════════════════════════════════════════════

def send_domain_expiry_warning(domain) -> bool:
    """Send domain expiry warning. Pass DomainRecord instance."""
    client = domain.website.client
    return _send(
        subject=f"⚠ Domain Expiry Notice — {domain.domain_name} expires in {domain.days_until_expiry} days",
        template='domain_expiry_warning.html',
        context={
            'client_name':    client.name,
            'domain_name':    domain.domain_name,
            'registrar':      domain.get_registrar_display(),
            'expiry_date':    domain.expiry_date.strftime('%d %B %Y'),
            'days_left':      domain.days_until_expiry,
            'renewal_cost':   domain.renewal_cost,
        },
        to_email=client.email,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 6. WELCOME EMAIL
# ══════════════════════════════════════════════════════════════════════════════

def send_welcome_email(client) -> bool:
    """Send welcome email when a client portal account is created."""
    return _send(
        subject="Welcome to JamiiTek Client Portal 🚀",
        template='welcome.html',
        context={
            'client_name':  client.name,
            'client_email': client.email,
        },
        to_email=client.email,
    )


def send_blog_review_reminder(posts, to_email=None, subject=None) -> bool:
    """
    Arifa mmiliki kuwa AI imeandaa rasimu za habari za kukagua na kuthibitisha.
    `posts` = orodha ya BlogPost (drafts). Rudisha True ikitumwa.
    """
    from django.conf import settings as _s
    to = to_email or getattr(_s, 'BLOG_REVIEW_EMAIL', None) \
        or getattr(_s, 'PAYMENTS_OWNER_EMAIL', 'info@jamiitek.com')
    base = getattr(_s, 'SITE_BASE_URL', 'https://www.jamiitek.com').rstrip('/')

    rows = []
    for p in posts:
        rows.append({
            'title': p.title,
            'category': p.category.name if p.category else '—',
            'source': p.source_name or '',
            'edit_url': f'{base}/admin/apps/blogpost/{p.pk}/change/',
        })

    return _send(
        subject=subject or f'📝 {len(rows)} news drafts ready for your review — JamiiTek',
        template='blog_review.html',
        context={
            'count': len(rows),
            'rows': rows,
            'review_all_url': f'{base}/admin/apps/blogpost/?status__exact=draft',
        },
        to_email=to,
    )


def _owner_email():
    from django.conf import settings as _s
    return (getattr(_s, 'BLOG_REVIEW_EMAIL', None)
            or getattr(_s, 'PAYMENTS_OWNER_EMAIL', 'info@jamiitek.com'))


def _site_base():
    from django.conf import settings as _s
    return getattr(_s, 'SITE_BASE_URL', 'https://www.jamiitek.com').rstrip('/')


def send_news_run_report(result) -> bool:
    """AI newsroom haikuandaa rasimu — mweleze mmiliki sababu."""
    return _send(
        subject='⚠️ AI newsroom: no drafts created today — JamiiTek',
        template='blog_news_report.html',
        context={
            'errors': result.get('errors') or ['No new stories found.'],
            'skipped': result.get('skipped', 0),
            'admin_url': f'{_site_base()}/admin/apps/blogpost/',
        },
        to_email=_owner_email(),
    )


def send_blog_comment_notice(comment) -> bool:
    """Maoni mapya kwenye makala — mmiliki ajibu au aifiche."""
    base = _site_base()
    return _send(
        subject=f'💬 New comment on "{comment.post.title[:60]}"',
        template='blog_comment.html',
        context={
            'name': comment.name,
            'body': comment.body,
            'is_reply': bool(comment.parent_id),
            'post_title': comment.post.title,
            'post_url': f'{base}/blog/{comment.post.slug}/#comment-{comment.pk}',
            'moderate_url': f'{base}/admin/apps/blogcomment/{comment.pk}/change/',
        },
        to_email=_owner_email(),
    )


def send_new_proposal_notice(proposal, rows, total) -> bool:
    """Proposal mpya kutoka /proposals/ — timu ya JamiiTek imjibu mteja haraka."""
    base = _site_base()
    ref = (proposal.requirements or {}).get('reference_template') if isinstance(proposal.requirements, dict) else None
    c = proposal.client
    return _send(
        subject=f'📝 New proposal JT-{proposal.pk}: {proposal.website_type.name} — {c.name or c.email}',
        template='new_proposal.html',
        context={
            'proposal': proposal, 'client': c, 'rows': rows, 'total': total, 'ref': ref,
            'preview_url': f'{base}/proposals/preview/{proposal.pk}/',
            'admin_url': f'{base}/admin/apps/projectproposal/{proposal.pk}/change/',
            'wa_phone': ''.join(ch for ch in (c.phone or '') if ch.isdigit()),
        },
        to_email=_owner_email(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 7. BULK — Run all expiry checks (call from management command or cron)
# ══════════════════════════════════════════════════════════════════════════════

def send_bulk_expiry_warnings():
    """
    Check ALL active websites and email plans and send warnings / auto-suspend.
    Call this daily via management command or cron-job.org.

    Auto-suspend triggers when days_until_expiry <= 0 (today OR past).
    Warning emails sent at: warning_days_before, 3, 1 days.

    Returns dict with counts: { sent, skipped, errors, suspended }
    """
    from apps.models import ManagedWebsite, DomainRecord, EmailHostingPlan

    sent = skipped = errors = suspended = 0
    today = timezone.now().date()

    # ══════════════════════════════════════════════════════════════
    # WEBSITE HOSTING
    # ══════════════════════════════════════════════════════════════

    active_sites = ManagedWebsite.objects.filter(
        status='active',
    ).select_related('client')

    for site in active_sites:
        raw_days = (site.hosting_end_date - today).days  # real delta, can be negative

        # ── Auto-suspend: day 0 or past ───────────────────────────
        if raw_days <= 0 and site.auto_suspend_on_expiry:
            site.status = 'suspended'
            site.suspension_reason = 'Hosting expired'
            site.suspension_message = (
                'Your hosting has expired. Please make a payment to restore your website.'
            )
            # Barua ya kusitishwa inatumwa na signal (apps/signals.py)
            # mara tu status inapobadilika — bila kujali njia iliyotumika.
            site.save(update_fields=['status', 'suspension_reason', 'suspension_message'])
            suspended += 1
            sent += 1
            logger.info(f"[AutoSuspend] {site.name} — expired {site.hosting_end_date}")
            continue

        # ── Onyo kwa tovuti zilizo hai bado ────────────────────────
        # Madirisha, si usawa kamili: siku 6 bado ni dirisha la 7.
        # `last_warning_stage` inazuia onyo lile lile kurudiwa kila siku.
        if not site.send_expiry_warnings:
            skipped += 1
            continue

        stage = stage_for(raw_days)
        if stage is None:
            # Bado ni mapema (au imeshaisha). Tovuti ikilipiwa na tarehe
            # kusogezwa mbele, kumbukumbu inafutwa ili mzunguko ujao
            # uanze upya.
            if site.last_warning_stage is not None and raw_days > WARNING_STAGES[0][0]:
                site.last_warning_stage = None
                site.last_warning_at = None
                site.save(update_fields=['last_warning_stage', 'last_warning_at'])
            skipped += 1
            continue

        # Tuma hatua ya kwanza, au hatua yenye uharaka ZAIDI kuliko
        # iliyotumwa mwisho (7 -> 3 -> 1). Hatua ile ile hairudiwi.
        already = site.last_warning_stage
        if already is not None and stage >= already:
            skipped += 1
            continue

        ok = send_hosting_expiry_warning(site, days=raw_days)
        if ok:
            site.last_warning_stage = stage
            site.last_warning_at = timezone.now()
            site.save(update_fields=['last_warning_stage', 'last_warning_at'])
            sent += 1
        else:
            errors += 1

    # ══════════════════════════════════════════════════════════════
    # EMAIL HOSTING
    # ══════════════════════════════════════════════════════════════

    active_email = EmailHostingPlan.objects.filter(
        status='active',
    ).select_related('client')

    for plan in active_email:
        raw_days = (plan.end_date - today).days

        # ── Auto-suspend: day 0 or past ───────────────────────────
        if raw_days <= 0 and plan.auto_suspend_on_expiry:
            plan.status = 'suspended'
            plan.suspension_message = (
                'Your email hosting has expired. Please make a payment to restore your service.'
            )
            plan.save(update_fields=['status', 'suspension_message'])
            # Send suspension notification
            try:
                from apps.utils.customer_email import send_customer_email
                send_customer_email(
                    plan.client.email, f'🔒 Email Hosting Suspended — {plan.email_domain}',
                    f'Dear {plan.client.name},\n\nYour email hosting for {plan.email_domain} has been '
                    'suspended due to non-payment.\n\nPlease contact JamiiTek to restore your service.',
                    alert={'kind': 'danger', 'title': 'Suspended', 'text': f'{plan.email_domain} email is paused.'},
                    button=('Open your portal', PORTAL_URL), category='suspension',
                )
            except Exception as e:
                logger.error(f"[EmailSuspend] {plan.email_domain} — {e}")
            suspended += 1
            logger.info(f"[AutoSuspend-Email] {plan.email_domain} — expired {plan.end_date}")
            continue

        # ── Expiry warnings ───────────────────────────────────────
        if plan.send_expiry_warnings:
            if raw_days in [plan.warning_days_before, 7, 3, 1]:
                # Basic expiry warning email for email hosting
                try:
                    from apps.utils.customer_email import send_customer_email
                    send_customer_email(
                        plan.client.email,
                        f'⚠ Email Hosting Expiry — {plan.email_domain} expires in {raw_days} '
                        f'day{"" if raw_days == 1 else "s"}',
                        f'Dear {plan.client.name},\n\nYour email hosting for {plan.email_domain} expires soon. '
                        'Please make a payment to avoid service interruption.',
                        rows=[('Domain', plan.email_domain), ('Expires on', plan.end_date.strftime('%d %B %Y')),
                              ('Days left', raw_days)],
                        button=('Renew now', PORTAL_URL), category='expiry_warning',
                    )
                    sent += 1
                except Exception as e:
                    logger.error(f"[EmailWarning] {plan.email_domain} — {e}")
                    errors += 1
            else:
                skipped += 1

    # ══════════════════════════════════════════════════════════════
    # DOMAIN warnings
    # ══════════════════════════════════════════════════════════════

    domains = DomainRecord.objects.filter(
        status='active',
        send_renewal_warnings=True
    ).select_related('website__client')

    for domain in domains:
        raw_days = (domain.expiry_date - today).days
        if raw_days in [domain.warning_days_before, 14, 7, 3, 1]:
            ok = send_domain_expiry_warning(domain)
            sent += 1 if ok else 0
            errors += 0 if ok else 1
        else:
            skipped += 1

    logger.info(f"[BulkEmail] Done — sent:{sent} suspended:{suspended} skipped:{skipped} errors:{errors}")
    return {'sent': sent, 'skipped': skipped, 'errors': errors, 'suspended': suspended}