"""
JamiiTek SEO — JSON-LD Structured Data helpers
These make Google understand WHO you are and WHAT you offer.
"""
import json


SITE_URL = "https://www.jamiitek.com"
SITE_NAME = "JamiiTek"
SITE_LOGO = "https://www.jamiitek.com/static/images/logo.png"
from apps.contact import contact as _contact
PHONE = _contact()["phone"]          # apps/contact.py — namba moja kila mahali
EMAIL = "info@jamiitek.com"
ADDRESS = "Dar es Salaam, Tanzania"
FOUNDING_YEAR = "2020"


YOUTUBE_CHANNEL_ID_URL = "https://www.youtube.com/channel/UCc3sqibSgctHd2gshbb_vOg"


def _social_profiles():
    from django.conf import settings
    links = [u for u in getattr(settings, 'SOCIAL_LINKS', {}).values() if u]
    # Anwani ya kudumu ya channel (haibadiliki hata handle ikibadilika)
    return links + [YOUTUBE_CHANNEL_ID_URL]


def organization_schema():
    """Main Organization schema — appears in Google Knowledge Panel."""
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": f"{SITE_URL}/#organization",
        "name": SITE_NAME,
        # Jina la kisheria na usajili wa BRELA (apps/contact.py)
        "legalName": _contact()["legal_name"],
        "identifier": {"@type": "PropertyValue", "propertyID": "BRELA Business Name Registration",
                       "value": _contact()["reg_no"]},
        "url": SITE_URL,
        "logo": SITE_LOGO,
        "foundingDate": FOUNDING_YEAR,
        "description": (
            "JamiiTek is a leading web development company in Tanzania offering "
            "website development, mobile apps, web hosting, domain registration, "
            "AI WhatsApp bots (JamiiBot), and digital solutions for businesses "
            "across Tanzania and East Africa."
        ),
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Dar es Salaam",
            "addressCountry": "TZ",
            "addressRegion": "Dar es Salaam"
        },
        "contactPoint": [
            {
                "@type": "ContactPoint",
                "telephone": PHONE,
                "contactType": "customer service",
                "availableLanguage": ["English", "Swahili"]
            }
        ],
        # Wasifu rasmi wa kampuni kwenye mitandao (YouTube, n.k.) — Google inaviunganisha na website
        "sameAs": [
            f"https://wa.me/{_contact()['wa']}",
            *_social_profiles(),
        ],
        "areaServed": {
            "@type": "GeoCircle",
            "geoMidpoint": {"@type": "GeoCoordinates", "latitude": -6.3690, "longitude": 34.8888},
            "geoRadius": "2000000"
        },
        "knowsAbout": [
            "Website Development", "Web Design", "Mobile App Development",
            "WhatsApp Chatbot", "AI Chatbot", "Web Hosting", "Domain Registration",
            "Email Hosting", "UI UX Design", "Django Development",
            "Tanzania Web Developer", "Swahili AI Bot"
        ]
    }


def website_schema():
    """WebSite schema — enables Google Sitelinks Search Box."""
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": f"{SITE_URL}/#website",
        "url": SITE_URL,
        "name": SITE_NAME,
        "description": "Modern web development, AI WhatsApp bots, and digital solutions in Tanzania",
        "publisher": {"@id": f"{SITE_URL}/#organization"},
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{SITE_URL}/service/?q={{search_term_string}}"
            },
            "query-input": "required name=search_term_string"
        },
        "inLanguage": ["en", "sw"]
    }


def local_business_schema():
    """LocalBusiness — appears in Google Maps + local search."""
    return {
        "@context": "https://schema.org",
        "@type": ["LocalBusiness", "ProfessionalService", "TechCompany"],
        "@id": f"{SITE_URL}/#localbusiness",
        "name": SITE_NAME,
        "image": SITE_LOGO,
        "url": SITE_URL,
        "telephone": PHONE,
        "email": EMAIL,
        "priceRange": "TZS 150,000 - TZS 5,000,000",
        "currenciesAccepted": "TZS",
        "paymentAccepted": "NMB Bank, M-Pesa, Airtel Money, Tigo Pesa",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "Dar es Salaam",
            "addressLocality": "Dar es Salaam",
            "addressRegion": "Dar es Salaam Region",
            "postalCode": "11001",
            "addressCountry": "TZ"
        },
        "geo": {
            "@type": "GeoCoordinates",
            "latitude": -6.7924,
            "longitude": 39.2083
        },
        "openingHoursSpecification": [
            {"@type": "OpeningHoursSpecification", "dayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday"], "opens": "08:00", "closes": "18:00"},
            {"@type": "OpeningHoursSpecification", "dayOfWeek": "Saturday", "opens": "09:00", "closes": "15:00"}
        ],
        "hasOfferCatalog": {
            "@type": "OfferCatalog",
            "name": "Digital Services",
            "itemListElement": [
                {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Website Development", "description": "Professional website development in Tanzania"}},
                {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "AI WhatsApp Bot", "description": "JamiiBot - AI-powered WhatsApp chatbot for businesses in Tanzania"}},
                {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Web Hosting", "description": "Reliable web hosting services in Tanzania"}},
                {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Domain Registration", "description": "Domain registration and management services"}},
                {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Mobile App Development", "description": "Android and iOS mobile app development"}},
            ]
        },
        # Hakuna aggregateRating: Google inakataza rating zisizotoka kwa reviews
        # halisi (na self-serving reviews kwenye LocalBusiness). Weka tu zikiwa
        # zinatoka kwenye data halisi ya wateja.
    }


def jamiibot_product_schema(plans=None):
    """Product/SoftwareApplication schema for JamiiBot.

    `plans` (SubscriptionPlan) zikitolewa, bei zinatoka database — si namba
    zilizoandikwa kwa mkono ambazo zinaweza kutofautiana na ukurasa.
    """
    data = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "@id": f"{SITE_URL}/bot/#jamiibot",
        "name": "JamiiBot",
        "alternateName": ["WhatsApp AI Bot Tanzania", "Swahili WhatsApp Chatbot", "AI Bot Tanzania"],
        "applicationCategory": "BusinessApplication",
        "operatingSystem": "WhatsApp",
        "url": f"{SITE_URL}/bot/",
        "description": (
            "JamiiBot is an AI-powered WhatsApp chatbot for businesses in Tanzania. "
            "It responds to customer questions automatically in Swahili and English, "
            "24 hours a day. Set up in 10 minutes, no coding required. "
            "Used by businesses across Tanzania for customer service automation."
        ),
        "featureList": [
            "Responds in Swahili and English automatically",
            "Available 24/7 without interruption",
            "Setup in 10 minutes with simple wizard",
            "Custom services and FAQ knowledge base",
            "Live conversation dashboard",
            "Message analytics and reports",
            "Powered by Groq AI (llama-3.3-70b)"
        ],
        "offers": [
            {
                "@type": "Offer",
                "name": "Starter Plan",
                "price": "15000",
                "priceCurrency": "TZS",
                "billingIncrement": "P1M",
                "description": "5,000 messages per month",
                "url": f"{SITE_URL}/chatbot/register/"
            },
            {
                "@type": "Offer",
                "name": "Business Plan",
                "price": "30000",
                "priceCurrency": "TZS",
                "billingIncrement": "P1M",
                "description": "10,000 messages per month — Most Popular",
                "url": f"{SITE_URL}/chatbot/register/?plan=pro"
            },
            {
                "@type": "Offer",
                "name": "Enterprise Plan",
                "price": "60000",
                "priceCurrency": "TZS",
                "billingIncrement": "P1M",
                "description": "Unlimited messages per month",
                "url": f"{SITE_URL}/chatbot/register/?plan=enterprise"
            }
        ],
        "provider": {"@id": f"{SITE_URL}/#organization"},
        "inLanguage": ["en", "sw"],
        "countriesSupported": "TZ",
        "availableOnDevice": "WhatsApp"
    }
    if plans:
        data["offers"] = [{
            "@type": "Offer",
            "name": f"{p.name} Plan" if 'plan' not in p.name.lower() else p.name,
            "price": str(p.price_tzs),
            "priceCurrency": "TZS",
            "description": ("Unlimited messages per month" if not p.msg_limit
                            else f"{p.msg_limit:,} messages per month"),
            "url": f"{SITE_URL}/chatbot/register/?plan={p.slug}",
        } for p in plans]
    return data


def faq_schema(faqs):
    """FAQ schema — shows answers directly in Google search results."""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a}
            }
            for q, a in faqs
        ]
    }


def breadcrumb_schema(items):
    """Breadcrumb schema — shows page path in search results."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": name,
                "item": f"{SITE_URL}{url}"
            }
            for i, (name, url) in enumerate(items)
        ]
    }


def render_schemas(*schemas):
    """Render multiple schemas as a single JSON-LD script tag."""
    combined = [json.dumps(s, ensure_ascii=False) for s in schemas]
    scripts = "\n".join(
        f'<script type="application/ld+json">{s}</script>'
        for s in combined
    )
    return scripts