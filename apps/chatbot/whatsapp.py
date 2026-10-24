"""
JamiiTek ChatBot — WhatsApp Cloud API Handler
TOKEN STRATEGY: Uses William's single permanent token (WHATSAPP_MASTER_TOKEN)
from settings.py. Each bot only needs its own Phone Number ID.
"""
import json
import logging
import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('chatbot.whatsapp')

WA_API_BASE = "https://graph.facebook.com/v19.0"


def get_token(bot_config):
    """
    Token priority:
    1. Bot's own token (if set — for bots with their own Meta account)
    2. WHATSAPP_MASTER_TOKEN from settings (William's global token)
    """
    if bot_config.whatsapp_token:
        return bot_config.whatsapp_token
    return getattr(settings, 'WHATSAPP_MASTER_TOKEN', '')


class WhatsAppHandler:
    """Sends and receives WhatsApp messages via Meta Cloud API."""

    def __init__(self, bot_config):
        self.bot      = bot_config
        self.token    = get_token(bot_config)
        self.phone_id = bot_config.whatsapp_phone_id

    def is_configured(self):
        return bool(self.token and self.phone_id)

    def send_text(self, to: str, message: str) -> dict:
        """Send a plain text message."""
        if not self.is_configured():
            logger.warning(f"Bot {self.bot.bot_name}: WhatsApp not configured.")
            return {'success': False, 'error': 'Not configured'}

        url = f"{WA_API_BASE}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": message}
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            data = resp.json()
            if resp.status_code == 200:
                return {'success': True, 'message_id': data.get('messages', [{}])[0].get('id', '')}
            else:
                logger.error(f"WA send failed: {data}")
                return {'success': False, 'error': data.get('error', {}).get('message', 'Unknown')}
        except requests.RequestException as e:
            logger.error(f"WA network error: {e}")
            return {'success': False, 'error': str(e)}

    def send_image(self, to: str, url: str, caption: str = '', jid=None) -> dict:
        """Picha kwa link (bidhaa za duka)."""
        if not self.is_configured():
            return {'success': False, 'error': 'Not configured'}
        try:
            resp = requests.post(f"{WA_API_BASE}/{self.phone_id}/messages", json={
                "messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
                "type": "image", "image": {"link": url, "caption": caption[:1024]},
            }, headers={"Authorization": f"Bearer {self.token}"}, timeout=10)
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            return {'success': False, 'error': str(e)}
        if resp.status_code == 200:
            return {'success': True, 'message_id': data.get('messages', [{}])[0].get('id', '')}
        return {'success': False, 'error': data.get('error', {}).get('message', 'Unknown')}

    def send_interactive_list(self, to: str, header: str, body: str, button_text: str, sections: list) -> dict:
        """Send interactive list message (menu)."""
        if not self.is_configured():
            return {'success': False, 'error': 'Not configured'}

        url = f"{WA_API_BASE}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": header},
                "body": {"text": body},
                "action": {"button": button_text, "sections": sections}
            }
        }
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            data = resp.json()
            if resp.status_code == 200:
                return {'success': True}
            return {'success': False, 'error': data.get('error', {}).get('message', 'Unknown')}
        except requests.RequestException as e:
            return {'success': False, 'error': str(e)}

    def mark_as_read(self, message_id: str) -> dict:
        """Mark a message as read."""
        if not self.is_configured():
            return {'success': False}
        url = f"{WA_API_BASE}/{self.phone_id}/messages"
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=5)
            return {'success': resp.status_code == 200}
        except Exception:
            return {'success': False}

    def send_interactive_buttons(self, to: str, body: str, buttons: list) -> dict:
        """
        Send quick-reply buttons (max 3).
        buttons = [{'id': 'btn_yes', 'title': 'Ndiyo'}, ...]
        """
        if not self.is_configured():
            return {'success': False, 'error': 'Not configured'}
        if len(buttons) > 3:
            buttons = buttons[:3]

        url     = f"{WA_API_BASE}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b['id'], "title": b['title'][:20]}}
                        for b in buttons
                    ]
                }
            }
        }
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            data = resp.json()
            if resp.status_code == 200:
                return {'success': True}
            return {'success': False, 'error': data.get('error', {}).get('message', 'Unknown')}
        except requests.RequestException as e:
            return {'success': False, 'error': str(e)}

    def get_media_url(self, media_id: str) -> str:
        """Retrieve the download URL for a media object (image/audio/etc.)."""
        if not self.is_configured():
            return ''
        url     = f"{WA_API_BASE}/{media_id}"
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('url', '')
        except requests.RequestException:
            pass
        return ''
        """Register webhook for this phone number."""
        if not self.is_configured():
            return {'success': False, 'error': 'Not configured'}
        url = f"{WA_API_BASE}/{self.phone_id}/subscribed_apps"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            resp = requests.post(url, headers=headers, timeout=10)
            return {'success': resp.status_code == 200}
        except Exception as e:
            return {'success': False, 'error': str(e)}

def build_services_menu(bot_config, body_text: str = None) -> dict:
    """
    Build a WhatsApp interactive list payload from bot's active services.
    Returns None if bot has fewer than 2 services (list needs at least 1 item
    but a menu makes sense only with 2+).
    """
    services = list(bot_config.services.filter(is_active=True).order_by('sort_order')[:10])
    if len(services) < 2:
        return None

    items = []
    for svc in services:
        desc = svc.description[:72] if svc.description else ''
        if svc.price:
            desc = f"{desc} — {svc.price}" if desc else svc.price
        item = {"id": f"svc_{svc.id}", "title": svc.name[:24]}
        if desc:
            item["description"] = desc[:72]
        items.append(item)

    return {
        "header":      f"Huduma za {bot_config.business_name}",
        "body":        body_text or "Chagua huduma unayohitaji:",
        "button_text": "Angalia Huduma",
        "sections":    [{"title": "Huduma Zetu", "rows": items}],
    }