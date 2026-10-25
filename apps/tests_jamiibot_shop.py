"""JamiiBot duka: katalogi -> oda -> malipo kwa Lipa Namba ya mmiliki (apps/chatbot/shop.py)."""
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase


class Rec:
    """Handler ya majaribio: inarekodi kila kinachotumwa (kama BaileysHandler)."""

    def __init__(self):
        self.sent, self.images, self.paused = [], [], False

    def send_text(self, to, message, jid=None):
        self.sent.append((to, message))
        return {'success': True}

    def send_image(self, to, url, caption='', jid=None):
        self.images.append((to, url, caption))
        return {'success': True}

    def mark_as_read(self, message_id):
        return {'success': True}

    def send_interactive_list(self, to, header, body, button_text, sections):
        return self.send_text(to, header)

    def to_customer(self):
        return [m for to, m in self.sent if to == CUSTOMER]

    def to_owner(self):
        return [m for to, m in self.sent if to == OWNER]


CUSTOMER, OWNER = '255700000001', '255754111226'


class JamiiBotShopTest(TestCase):

    def setUp(self):
        from apps.chatbot.models import BotConfig, BotSubscription, ChatbotClient, Product, SubscriptionPlan
        cache.clear()
        plan = SubscriptionPlan.objects.filter(is_active=True).order_by('price_tzs').first()
        self.user = User.objects.create_user('mamaduka', 'md@x.com', 'Sahihi-Kabisa-2026')
        cl = ChatbotClient.objects.create(user=self.user, full_name='Mama Duka',
                                          business_name='Duka la Mama', email='md@x.com')
        self.bot = BotConfig.objects.create(
            client=cl, bot_name='DukaBot', business_name='Duka la Mama', description='Duka',
            status='active', is_active=True, owner_whatsapp=OWNER, collect_name=False,
            shop_enabled=True, payment_instructions='Lipa Namba: 555777 (M-Pesa)\nJina: Duka la Mama')
        BotSubscription.objects.create(bot=self.bot, plan=plan, status='active')
        self.shoes = Product.objects.create(bot=self.bot, name='Viatu vya ngozi', price=25000,
                                            image_url='https://cdn.x/viatu.jpg', sort_order=1)
        self.shirt = Product.objects.create(bot=self.bot, name='Shati', price=15000, sort_order=2)
        self.ai = mock.patch('apps.chatbot.views.BotAIEngine')
        engine = self.ai.start()
        engine.return_value.get_response.return_value = {
            'content': 'Jibu la AI', 'success': True, 'tokens': 5, 'model': 'x', 'latency_ms': 1}
        self.addCleanup(self.ai.stop)
        self.n = 0

    def say(self, text, msg_type='text', **extra):
        from apps.chatbot.views import _process_message
        self.n += 1
        wa = Rec()
        _process_message(self.bot, {'from': CUSTOMER, 'text': text, 'message_id': f'm{self.n}',
                                    'jid': f'{CUSTOMER}@s.whatsapp.net', 'msg_type': msg_type, **extra},
                         handler=wa)
        return wa

    def conv(self):
        return self.bot.conversations.get(customer_phone=CUSTOMER)

    def test_full_order_and_payment_without_ai(self):
        from apps.chatbot.models import Order
        wa = self.say('bidhaa')
        menu = wa.to_customer()[-1]
        self.assertIn('1. *Viatu vya ngozi* — TZS 25,000', menu)
        self.assertIn('2. *Shati* — TZS 15,000', menu)

        wa = self.say('1')
        self.assertEqual(wa.images[0][1], 'https://cdn.x/viatu.jpg')         # picha ya bidhaa
        self.assertIn('TZS 25,000', wa.images[0][2])
        self.assertIn('Unataka ngapi', wa.to_customer()[-1])

        wa = self.say('mbili')                                               # idadi kwa maneno
        self.assertIn('Jumla: TZS 50,000', wa.to_customer()[-1])
        self.say('1')                                                        # ongeza nyingine
        self.say('2')                                                        # shati
        self.say('1')
        wa = self.say('2')                                                   # maliza
        self.assertIn('mahali', wa.to_customer()[-1])
        wa = self.say('Sinza Mori, Dar')
        summary = wa.to_customer()[-1]
        self.assertIn('Jumla: TZS 65,000', summary)
        self.assertIn('Sinza Mori, Dar', summary)

        wa = self.say('1')                                                   # thibitisha
        order = Order.objects.get()
        self.assertEqual((order.total, order.status, order.delivery), (65000, 'new', 'Sinza Mori, Dar'))
        self.assertEqual([(i['name'], i['qty']) for i in order.items], [('Viatu vya ngozi', 2), ('Shati', 1)])
        reply = wa.to_customer()[-1]
        self.assertIn(f'Oda #{order.code} imepokelewa', reply)
        self.assertIn('Lipa Namba: 555777', reply)
        self.assertIn(f'Oda mpya #{order.code}', wa.to_owner()[0])           # mmiliki ameambiwa

        wa = self.say('Nimelipa, muamala ni QWE12345RT')
        order.refresh_from_db()
        self.assertEqual((order.status, order.payment_ref), ('payment_sent', 'QWE12345RT'))
        self.assertIn('QWE12345RT', wa.to_owner()[0])
        self.assertEqual(self.conv().metadata['state'], 'chat')
        from apps.chatbot import views
        views.BotAIEngine.return_value.get_response.assert_not_called()      # hakuna AI hata mara moja

    def test_payment_screenshot_counts_as_payment(self):
        from apps.chatbot.models import Order
        for t in ('bidhaa', '2', '1', '2', 'nitachukua', '1'):
            self.say(t)
        order = Order.objects.get()
        self.assertEqual(order.delivery, 'Atakuja kuchukua mwenyewe')
        wa = self.say('[Picha]', msg_type='image')
        order.refresh_from_db()
        self.assertEqual(order.status, 'payment_sent')
        self.assertIn('picha', order.payment_ref)
        self.assertTrue(wa.to_owner())

    def test_question_mid_order_goes_to_ai_and_cart_is_kept(self):
        from apps.chatbot import views
        self.say('bidhaa')
        self.say('1')
        self.say('3')
        wa = self.say('Mnafunguliwa saa ngapi?')
        self.assertEqual(wa.to_customer(), ['Jibu la AI'])
        self.assertEqual(self.conv().metadata['state'], 'chat')
        wa = self.say('bidhaa')
        self.assertIn('Kikapu chako bado kipo', wa.to_customer()[-1])
        self.assertIn('3 × Viatu vya ngozi', wa.to_customer()[-1])
        self.assertEqual(views.BotAIEngine.return_value.get_response.call_count, 1)

    def test_out_of_stock_cancel_and_disabled_shop(self):
        self.shoes.in_stock = False
        self.shoes.save()
        self.say('bidhaa')
        wa = self.say('1')
        self.assertIn('imeisha', wa.to_customer()[-1])
        wa = self.say('ghairi')
        self.assertIn('imeghairiwa', wa.to_customer()[-1])

        self.bot.shop_enabled = False
        self.bot.save()
        wa = self.say('bidhaa')
        self.assertEqual(wa.to_customer(), ['Jibu la AI'])                   # duka limezimwa: AI ya kawaida

    def test_price_always_comes_from_the_database(self):
        from apps.chatbot.models import Order
        for t in ('bidhaa', '2', '2'):
            self.say(t)
        self.shirt.price = 18000                                             # mmiliki amebadilisha bei
        self.shirt.save()
        for t in ('2', 'Mbezi', '1'):
            self.say(t)
        self.assertEqual(Order.objects.get().total, 36000)

    def test_web_chat_shows_product_image(self):
        from apps.chatbot.views import _process_message
        from apps.chatbot.webchat import WebHandler
        replies = []
        for t in ('bidhaa', '1'):
            wa = WebHandler(self.bot, 'web_abc')
            _process_message(self.bot, {'from': 'web_abc', 'text': t, 'message_id': f'w{t}',
                                        'channel': 'web'}, handler=wa)
            replies += wa.replies
        self.assertTrue(any(r.startswith('[[img:https://cdn.x/viatu.jpg]]') for r in replies))

    def test_dashboard_products_settings_and_orders(self):
        from apps.chatbot.models import Order, Product
        self.client.force_login(self.user)
        self.client.post('/chatbot/shop/product/', {'name': 'Kofia', 'price': '7,500', 'category': 'Nguo'})
        self.assertEqual(Product.objects.get(name='Kofia').price, 7500)
        r = self.client.post('/chatbot/shop/product/', {'name': 'Bila bei', 'price': 'bure'}, follow=True)
        self.assertIn('Enter a product name and a price', ' '.join(str(m) for m in r.context['messages']))
        self.assertFalse(Product.objects.filter(name='Bila bei').exists())
        self.client.post('/chatbot/shop/settings/', {'payment_instructions': 'Lipa Namba 999'})
        self.bot.refresh_from_db()
        self.assertEqual((self.bot.shop_enabled, self.bot.payment_instructions), (False, 'Lipa Namba 999'))
        page = self.client.get('/chatbot/shop/').content.decode()
        self.assertIn('Kofia', page)
        self.assertIn('Your products', page)
        self.assertIn('<i class="fas fa-receipt"></i> Orders', page)

        # Oda ya mteja wa WhatsApp: mmiliki anathibitisha malipo, mteja anaarifiwa
        self.bot.shop_enabled = True
        self.bot.save()
        for t in ('bidhaa', '1', '1', '2', 'Kariakoo', '1'):
            self.say(t)
        order = Order.objects.get()
        self.assertIn('<span class="sb-count">1</span>', self.client.get('/chatbot/orders/').content.decode())
        with mock.patch('apps.chatbot.bridge._request', return_value={'success': True}) as req, \
                mock.patch('apps.chatbot.bridge.is_configured', return_value=True):
            self.client.post(f'/chatbot/orders/{order.id}/', {'status': 'paid'})
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')
        self.assertIsNotNone(order.paid_at)
        payload = req.call_args.kwargs['json']
        self.assertEqual(payload['jid'], f'{CUSTOMER}@s.whatsapp.net')
        self.assertIn(f'#{order.code}', payload['text'])

        # Mteja mwingine hawezi kugusa oda hii
        other = User.objects.create_user('mwingine', 'o@x.com', 'Sahihi-Kabisa-2026')
        from apps.chatbot.models import ChatbotClient
        ChatbotClient.objects.create(user=other, full_name='O', business_name='O', email='o@x.com')
        self.client.force_login(other)
        self.assertEqual(self.client.post(f'/chatbot/orders/{order.id}/', {'status': 'cancelled'}).status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')

    def test_replies_follow_the_bot_language(self):
        from apps.chatbot.models import Order
        # Swahili + English: lugha aliyotumia mteja kufungua duka
        wa = self.say('products')
        self.assertIn('Duka la Mama — products', wa.to_customer()[-1])
        self.assertIn('Reply with a *number*', wa.to_customer()[-1])
        wa = self.say('1')
        self.assertIn('How many would you like', wa.to_customer()[-1])
        for t in ('two', '2', 'pickup', '1'):
            wa = self.say(t)
        order = Order.objects.get()
        self.assertEqual((order.lang, order.delivery), ('en', 'Atakuja kuchukua mwenyewe'))
        self.assertIn(f'Order #{order.code} received', wa.to_customer()[-1])
        self.assertIn('How to pay', wa.to_customer()[-1])
        self.assertIn('Oda mpya', wa.to_owner()[0])                          # mmiliki: lugha ya bot

        # English only: hata "bidhaa" inajibiwa kwa English, na mmiliki pia
        self.bot.language = 'en'
        self.bot.save()
        Order.objects.all().delete()
        self.bot.conversations.all().delete()
        wa = self.say('bidhaa')
        self.assertIn('— products', wa.to_customer()[-1])
        for t in ('1', '1', '2', 'Mbezi', '1'):
            wa = self.say(t)
        self.assertIn('New order #', wa.to_owner()[0])
        wa = self.say('cancel')                     # baada ya kuthibitisha: oda inaghairiwa kweli
        self.assertIn('the order is cancelled', wa.to_customer()[-1])
        self.assertEqual(Order.objects.get().status, 'cancelled')
        self.assertIn('Order #', wa.to_owner()[0])
        self.assertIn('was cancelled', wa.to_owner()[0])

        # Swahili only: "products" inajibiwa kwa Kiswahili
        self.bot.language = 'sw'
        self.bot.save()
        wa = self.say('products')
        self.assertIn('Bidhaa za Duka la Mama', wa.to_customer()[-1])


class JamiiBotPaymentMethodsTest(TestCase):
    """Njia za malipo zilizopangwa: Lipa Namba, namba za simu, benki. Mmiliki anathibitisha mwenyewe."""
    setUp = JamiiBotShopTest.setUp
    say = JamiiBotShopTest.say

    def test_clean_method_validates_each_kind(self):
        from apps.chatbot.shop import clean_method
        m, err = clean_method('mobile', 'airtel', '+255 688 123 456', ' Asha  Juma ')
        self.assertIsNone(err)
        self.assertEqual(m, {'kind': 'mobile', 'provider': 'airtel', 'number': '0688 123 456', 'name': 'Asha Juma'})
        self.assertEqual(clean_method('lipa', 'mpesa', '555 777', 'Duka')[0]['number'], '555777')
        self.assertEqual(clean_method('bank', 'CRDB', '0150 1234 5678', 'Duka Ltd')[0]['provider'], 'CRDB')
        for bad in (('mobile', 'airtel', '12345', 'A'), ('lipa', 'mpesa', 'abc', 'A'),
                    ('lipa', 'tpesa', '555777', 'A'), ('bank', '', '01501234', 'A'),
                    ('mobile', 'mpesa', '0754123456', ''), ('card', 'mpesa', '1', 'A')):
            self.assertIsNone(clean_method(*bad)[0], bad)

    def test_customer_sees_every_method_and_owner_confirms(self):
        from apps.chatbot.models import Order
        self.bot.payment_instructions = ''
        self.bot.payment_methods = [
            {'kind': 'lipa', 'provider': 'mpesa', 'number': '555777', 'name': 'Duka la Mama'},
            {'kind': 'mobile', 'provider': 'airtel', 'number': '0688 123 456', 'name': 'Asha Juma'},
            {'kind': 'bank', 'provider': 'CRDB', 'number': '0150 1234 5678', 'name': 'Duka la Mama Ltd'},
        ]
        self.bot.save()
        for t in ('bidhaa', '2', '1', '2', 'nitachukua'):
            self.say(t)
        wa = self.say('1')
        order = Order.objects.get()
        reply = wa.to_customer()[-1]
        for text in ('Jinsi ya kulipa — TZS 15,000', '1️⃣ *Lipa Namba (M-Pesa)*', '*555777*',
                     '2️⃣ *Airtel Money — namba ya simu*', '*0688 123 456*', 'Jina: Asha Juma',
                     '3️⃣ *Benki — CRDB*', '*0150 1234 5678*', f'*{order.code}*', 'namba ya muamala'):
            self.assertIn(text, reply)
        self.say('Nimelipa QWE12345RT')
        order.refresh_from_db()
        self.assertEqual(order.status, 'payment_sent')        # mteja amesema — si "paid" mpaka mmiliki athibitishe

    def test_note_only_still_works(self):
        self.bot.payment_methods = []
        self.bot.save()
        for t in ('bidhaa', '2', '1', '2', 'nitachukua'):
            self.say(t)
        reply = self.say('1').to_customer()[-1]
        self.assertIn('Lipa Namba: 555777 (M-Pesa)', reply)
        self.assertNotIn('Kwenye maelezo ya malipo', reply)

    def test_dashboard_adds_and_removes_methods(self):
        self.client.force_login(self.user)
        r = self.client.post('/chatbot/shop/payment/', {'kind': 'mobile', 'network': 'mpesa',
                                                        'number': '0754 111 222', 'name': 'Mama Duka'})
        self.assertRedirects(r, '/chatbot/shop/#pay', fetch_redirect_response=False)
        self.client.post('/chatbot/shop/payment/', {'kind': 'bank', 'bank': 'NMB',
                                                    'number': '2041 0000 111', 'name': 'Duka la Mama'})
        r = self.client.post('/chatbot/shop/payment/', {'kind': 'mobile', 'network': 'mpesa',
                                                        'number': '999', 'name': 'X'}, follow=True)
        self.assertIn('valid phone number', ' '.join(str(m) for m in r.context['messages']))
        self.bot.refresh_from_db()
        self.assertEqual([m['provider'] for m in self.bot.payment_methods], ['mpesa', 'NMB'])
        page = self.client.get('/chatbot/shop/').content.decode()
        self.assertIn('M-Pesa — phone number', page)
        self.assertIn('Bank — NMB', page)
        self.assertIn('How to pay — TZS 45,000', page)          # muonekano kwa mteja
        self.client.post('/chatbot/shop/payment/', {'action': 'delete', 'index': '0'})
        self.bot.refresh_from_db()
        self.assertEqual([m['provider'] for m in self.bot.payment_methods], ['NMB'])
        self.client.post('/chatbot/shop/payment/', {'action': 'delete', 'index': '9'})   # haipo — hakuna kosa
        self.bot.refresh_from_db()
        self.assertEqual(len(self.bot.payment_methods), 1)
