"""
Dashboard ya duka: Bidhaa (na jinsi ya kulipa) + Oda.
Mantiki ya chat iko apps/chatbot/shop.py.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import shop
from .models import Order, Product
from .views import _own_bot

LOGIN = '/chatbot/login/'


def _bot_or_wizard(request):
    bot = _own_bot(request)
    return bot, (None if bot else redirect('chatbot_setup_wizard'))


def _price(raw):
    digits = ''.join(ch for ch in str(raw or '') if ch.isdigit())
    return int(digits) if digits and len(digits) <= 10 else None


@login_required(login_url=LOGIN)
def chatbot_shop(request):
    bot, go = _bot_or_wizard(request)
    if go:
        return go
    edit = None
    if request.GET.get('edit'):
        edit = Product.objects.filter(bot=bot, id=request.GET['edit']).first()
    products = bot.products.all()
    return render(request, 'chatbot/portal/shop.html', {
        'client': bot.client,
        'bot': bot,
        'products': products,
        'active_count': products.filter(is_active=True).count(),
        'edit': edit,
        'categories': sorted({p.category for p in products if p.category}),
    })


@login_required(login_url=LOGIN)
@require_POST
def chatbot_shop_settings(request):
    bot, go = _bot_or_wizard(request)
    if go:
        return go
    bot.shop_enabled = request.POST.get('shop_enabled') == 'on'
    bot.payment_instructions = request.POST.get('payment_instructions', '').strip()[:1000]
    bot.save(update_fields=['shop_enabled', 'payment_instructions'])
    if bot.shop_enabled and not bot.products.filter(is_active=True).exists():
        messages.warning(request, "Duka limewashwa, lakini ongeza angalau bidhaa moja ili wateja waione.")
    else:
        messages.success(request, "Mipangilio ya duka imehifadhiwa.")
    return redirect('chatbot_shop')


@login_required(login_url=LOGIN)
@require_POST
def chatbot_product_save(request):
    bot, go = _bot_or_wizard(request)
    if go:
        return go
    pid = request.POST.get('product_id')
    product = get_object_or_404(Product, id=pid, bot=bot) if pid else Product(bot=bot)

    if request.POST.get('action') == 'delete' and pid:
        product.delete()
        messages.success(request, "Bidhaa imeondolewa.")
        return redirect('chatbot_shop')
    if request.POST.get('action') == 'stock' and pid:
        product.in_stock = not product.in_stock
        product.save(update_fields=['in_stock'])
        return redirect('chatbot_shop')

    name = request.POST.get('name', '').strip()[:120]
    price = _price(request.POST.get('price'))
    if not name or price is None:
        messages.error(request, "Weka jina la bidhaa na bei (namba tu, mf. 25000).")
        return redirect(reverse('chatbot_shop') + (f'?edit={pid}' if pid else ''))

    image_url = request.POST.get('image_url', '').strip()[:500]
    upload = request.FILES.get('image')
    if upload:
        from apps import storage
        res = storage.upload(upload, folder='products')
        if not res.get('success'):
            messages.error(request, f"Picha haikupakiwa: {res.get('error')}")
            return redirect('chatbot_shop')
        image_url = res['url']
    if image_url and not image_url.startswith('https://'):
        messages.error(request, "Link ya picha lazima ianze na https://")
        return redirect('chatbot_shop')

    product.name = name
    product.price = price
    product.description = request.POST.get('description', '').strip()[:300]
    product.category = request.POST.get('category', '').strip()[:60]
    product.image_url = image_url
    product.in_stock = request.POST.get('in_stock', 'on') == 'on'
    product.save()
    messages.success(request, f"{name} imehifadhiwa.")
    return redirect('chatbot_shop')


@login_required(login_url=LOGIN)
def chatbot_orders(request):
    bot, go = _bot_or_wizard(request)
    if go:
        return go
    tab = request.GET.get('tab', 'open')
    orders = bot.orders.all()
    groups = {
        'open': orders.filter(status__in=('new', 'payment_sent', 'paid')),
        'done': orders.filter(status='delivered'),
        'cancelled': orders.filter(status='cancelled'),
    }
    return render(request, 'chatbot/portal/orders.html', {
        'client': bot.client,
        'bot': bot,
        'tab': tab if tab in groups else 'open',
        'orders': groups.get(tab, groups['open'])[:200],
        'counts': {k: v.count() for k, v in groups.items()},
    })


@login_required(login_url=LOGIN)
@require_POST
def chatbot_order_status(request, order_id):
    bot, go = _bot_or_wizard(request)
    if go:
        return go
    order = get_object_or_404(Order, id=order_id, bot=bot)
    status = request.POST.get('status')
    if status not in dict(Order.STATUS_CHOICES):
        return redirect('chatbot_orders')
    shop.mark(order, status)
    messages.success(request, f"Oda #{order.code}: {order.get_status_display()}.")
    return redirect(reverse('chatbot_orders') + f"?tab={request.POST.get('tab', 'open')}")
