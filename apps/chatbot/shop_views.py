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
        'methods': [dict(m, i=i, label=shop.method_label(m)) for i, m in enumerate(bot.payment_methods or [])],
        'networks': shop.NETWORKS.items(),
        'max_methods': shop.MAX_METHODS,
        'preview': shop.payment_text(bot, 'en', 'K7Q2', 45000),
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
        messages.warning(request, "Shop is on, but add at least one product so customers can see it.")
    else:
        messages.success(request, "Shop settings saved.")
    return redirect('chatbot_shop')


@login_required(login_url=LOGIN)
@require_POST
def chatbot_payment_method(request):
    """Ongeza au futa njia ya malipo (Lipa Namba / namba ya simu / benki)."""
    bot, go = _bot_or_wizard(request)
    if go:
        return go
    methods = list(bot.payment_methods or [])
    back = reverse('chatbot_shop') + '#pay'
    if request.POST.get('action') == 'delete':
        try:
            removed = methods.pop(int(request.POST.get('index', '')))
        except (ValueError, IndexError):
            return redirect(back)
        bot.payment_methods = methods
        bot.save(update_fields=['payment_methods'])
        messages.success(request, f"{shop.method_label(removed)} removed.")
        return redirect(back)
    if len(methods) >= shop.MAX_METHODS:
        messages.error(request, f"You can add up to {shop.MAX_METHODS} payment methods.")
        return redirect(back)
    kind = request.POST.get('kind')
    provider = request.POST.get('bank' if kind == 'bank' else 'network')
    method, error = shop.clean_method(kind, provider, request.POST.get('number'), request.POST.get('name'))
    if error:
        messages.error(request, error)
        return redirect(back)
    if any(m['kind'] == method['kind'] and m['number'] == method['number'] for m in methods):
        messages.info(request, "That payment method is already on the list.")
        return redirect(back)
    methods.append(method)
    bot.payment_methods = methods
    bot.save(update_fields=['payment_methods'])
    messages.success(request, f"{shop.method_label(method)} added.")
    return redirect(back)


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
        messages.success(request, "Product removed.")
        return redirect('chatbot_shop')
    if request.POST.get('action') == 'stock' and pid:
        product.in_stock = not product.in_stock
        product.save(update_fields=['in_stock'])
        return redirect('chatbot_shop')

    name = request.POST.get('name', '').strip()[:120]
    price = _price(request.POST.get('price'))
    if not name or price is None:
        messages.error(request, "Enter a product name and a price (numbers only, e.g. 25000).")
        return redirect(reverse('chatbot_shop') + (f'?edit={pid}' if pid else ''))

    image_url = request.POST.get('image_url', '').strip()[:500]
    upload = request.FILES.get('image')
    if upload:
        from apps import storage
        res = storage.upload(upload, folder='products')
        if not res.get('success'):
            messages.error(request, f"Image upload failed: {res.get('error')}")
            return redirect('chatbot_shop')
        image_url = res['url']
    if image_url and not image_url.startswith('https://'):
        messages.error(request, "The image link must start with https://")
        return redirect('chatbot_shop')

    product.name = name
    product.price = price
    product.description = request.POST.get('description', '').strip()[:300]
    product.category = request.POST.get('category', '').strip()[:60]
    product.image_url = image_url
    product.in_stock = request.POST.get('in_stock', 'on') == 'on'
    product.save()
    messages.success(request, f"{name} saved.")
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
    messages.success(request, f"Order #{order.code}: {order.get_status_display()}.")
    return redirect(reverse('chatbot_orders') + f"?tab={request.POST.get('tab', 'open')}")
