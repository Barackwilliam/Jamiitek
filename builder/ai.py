"""
AI Assistant (Groq) — inamsaidia mteja kutengeneza content na HTML sections.
Weka GEMINI_API_KEY (mkuu) na/au GROQ_API_KEY (akiba) kwenye environment variables za Render.
    pip install groq
"""
import os
import json
import logging
from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from .models import AiUsageLog, ClientWebsite

logger = logging.getLogger(__name__)


def _groq_client():
    # Gemini kwanza, Groq akiba (apps/llm.py)
    from apps.llm import client
    c = client()
    if c is None:
        return None, 'No AI key is configured on the server (GEMINI_API_KEY or GROQ_API_KEY).'
    return c, None

GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
AI_DAILY_LIMIT = int(os.getenv('BUILDER_AI_DAILY_LIMIT', '25'))

SYSTEM_PROMPT = """You are a senior web designer and conversion copywriter building pages for
businesses in Tanzania and East Africa. Your work must look like it came from a top
international agency — the quality of Stripe, Apple or Airbnb — never like a template.

1. WEBSITE SECTIONS — when asked for a section (hero, services, pricing, about,
   testimonials, gallery, FAQ, contact, call-to-action, team, stats…):
   - Return CLEAN HTML ONLY: no ```html fences, no explanation, no <html>/<head>/<body>,
     no <script>, no external CSS files. Style everything with inline styles.
   - One <section> per request (or several if asked), each with padding
     clamp(64px,9vw,120px) 20px and an inner wrapper max-width:1160px;margin:0 auto.
   - Typography: headline font-size:clamp(32px,5vw,56px);line-height:1.08;
     letter-spacing:-.03em;font-weight:800. A small uppercase kicker above it
     (12px, letter-spacing:.16em, the brand colour). Body text 16-18px,
     line-height 1.7, colour #475569, max-width ~620px for readability.
   - Colour: use var(--accent) for the brand colour (buttons, kickers, icons,
     highlights). Neutrals: #0f172a headings, #475569 text, #f8fafc / #ffffff
     backgrounds, 1px borders #e2e8f0. For dark sections use #0b0f19 with
     #f4f6fa text.
   - Layout: CSS grid or flex with gap 20-32px;
     grid-template-columns:repeat(auto-fit,minmax(260px,1fr)) so it stacks on
     phones by itself. Nothing may overflow at 360px wide.
   - Cards: background #fff, border 1px solid #e2e8f0, border-radius 20px,
     padding 28-32px, box-shadow 0 20px 50px rgba(15,23,42,.06).
   - Buttons: <a> with display:inline-block;padding:15px 28px;border-radius:12px;
     font-weight:700;text-decoration:none; primary = var(--accent) background with
     white text; secondary = transparent with a 1.5px border. Link WhatsApp buttons
     to [[site:whatsapp]] and phone buttons to tel: with the business phone.
   - Images: only if the user gives URLs; otherwise design without images
     (large numbers, simple inline SVG icons, coloured shapes, gradients).
   - Copy: specific to THIS business, benefit-led, confident and warm. Realistic
     local details (TZS prices, places, WhatsApp-first). Never lorem ipsum, never
     "Your text here", no emojis in headings.
2. TEXT ONLY — if asked for text (descriptions, taglines, about us), return plain
   text without HTML: tight, specific, persuasive.
3. Reply in the language the user wrote in (English or Swahili).
4. Content must match the business context provided."""


def _check_rate_limit(user):
    since = timezone.now() - timedelta(days=1)
    used = AiUsageLog.objects.filter(user=user, created_at__gte=since).count()
    return used < AI_DAILY_LIMIT, AI_DAILY_LIMIT - used


@login_required
@require_POST
def ai_assist(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request.'}, status=400)

    prompt = (payload.get('prompt') or '').strip()
    website_id = payload.get('website_id')
    if not prompt:
        return JsonResponse({'error': 'Please describe what you need first.'}, status=400)
    if len(prompt) > 2000:
        return JsonResponse({'error': 'Your request is too long (max 2000 characters).'}, status=400)

    ok, remaining = _check_rate_limit(request.user)
    if not ok:
        return JsonResponse(
            {'error': f'You have reached the limit of {AI_DAILY_LIMIT} requests per day. Try again tomorrow.'},
            status=429,
        )

    website = ClientWebsite.objects.filter(id=website_id, owner=request.user).first()
    context = ''
    if website:
        context = (f'\n\nBUSINESS CONTEXT: name "{website.site_name}", '
                   f'website type: {website.website_type}, '
                   f'tagline: "{website.tagline}".')

    try:
        client, client_err = _groq_client()
        if client is None:
            return JsonResponse({'error': client_err}, status=500)
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT + context},
                {'role': 'user', 'content': prompt},
            ],
            max_tokens=3500,
            temperature=0.65,
        )
        result = completion.choices[0].message.content.strip()
        # Ondoa markdown fences kama model imeziweka
        if result.startswith('```'):
            result = result.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    except KeyError:
        return JsonResponse({'error': 'GROQ_API_KEY is not configured on the server.'}, status=500)
    except Exception:
        logger.exception('Groq API error')
        return JsonResponse({'error': 'The AI is unavailable right now. Please try again later.'}, status=502)

    AiUsageLog.objects.create(user=request.user, website=website)
    is_html = result.lstrip().startswith('<')
    return JsonResponse({'result': result, 'is_html': is_html, 'remaining': remaining - 1})
