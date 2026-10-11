import json
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.models import Client, Contact, Invoice, ProjectProposal, Proposal, WebsiteType

from . import actions, diana, grace, ibrahimu, mtihani, selvester, william
from .models import Alama, Kazi, Mtihani, Ripoti
from .runner import run_all

TOKEN = 'siri-ya-majaribio'


def _at(hour, day=None):
    day = day or timezone.localdate()
    return timezone.make_aware(timezone.datetime(day.year, day.month, day.day, hour, 0))


# DailyTasksMiddleware inaanzisha thread (yenye muunganisho wake wa database)
# kwa kila ombi la test client — ingeandika nje ya transaction ya test.
@override_settings(GROQ_API_KEY='', MIDDLEWARE=[m for m in settings.MIDDLEWARE
                                                if not m.endswith('DailyTasksMiddleware')])
class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        # Tests za apps nyingine zinapita kwenye middleware, ambayo inaweza
        # kuwa imeendesha timu kwenye thread na kuacha safu zilizo-commit.
        for model in (Kazi, Ripoti, Alama, Mtihani):
            model.objects.all().delete()
        self.env = mock.patch.dict('os.environ', {
            'GROQ_API_KEY': '', 'WILIFE_URL': '', 'WORKERS_API_TOKEN': TOKEN, 'TASKS_TOKEN': 'cron',
            'TELEGRAM_BOT_TOKEN': '', 'GREEN_API_ID': '', 'ALERT_EMAIL': 'boss@example.com'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.now = _at(9)

    def invoice(self, due_days_ago=10, paid=0, status='sent', **kw):
        fields = dict(client_name='Asha Shop', client_email='asha@example.com', title='Tovuti',
                      due_date=self.now.date() - timedelta(days=due_days_ago), status=status,
                      line_items=[{'description': 'Website', 'amount': 500000}], amount_paid=paid)
        fields.update(kw)
        return Invoice.objects.create(**fields)

    def bot(self):
        from apps.chatbot.models import BotConfig, ChatbotClient
        user = User.objects.create_user('jt', 'jt@example.com', 'p')
        client = ChatbotClient.objects.create(user=user, full_name='JamiiTek', business_name='JamiiTek',
                                              email='info@jamiitek.com', phone='0750910158')
        return BotConfig.objects.create(client=client, bot_name='JamiiBot', business_name='JamiiTek',
                                        description='Bot ya JamiiTek', session_name='jamiitek-demo')


class DianaTests(Base):
    def test_overdue_invoice_becomes_reminder_awaiting_approval(self):
        inv = self.invoice(due_days_ago=20)
        diana.run(self.now)
        kazi = Kazi.objects.get(worker='diana')
        self.assertEqual(kazi.status, Kazi.AWAITING)
        self.assertEqual(kazi.priority, 1)
        self.assertEqual(kazi.recipient_email, 'asha@example.com')
        self.assertIn('imechelewa (siku 20)', kazi.title)
        self.assertIn(f'/invoice/{inv.token}/', kazi.draft)
        self.assertIn('Diana', kazi.draft)

    def test_same_invoice_is_one_task_and_paying_closes_it(self):
        inv = self.invoice()
        diana.run(self.now)
        diana.run(self.now)
        self.assertEqual(Kazi.objects.count(), 1)
        inv.status = 'paid'
        inv.save()
        diana.run(self.now)
        self.assertEqual(Kazi.objects.get().status, Kazi.DONE)

    def test_one_reminder_per_client_listing_all_invoices(self):
        a = self.invoice(due_days_ago=58)
        b = self.invoice(due_days_ago=58)
        c = self.invoice(due_days_ago=40)
        self.invoice(due_days_ago=30, client_email='other@example.com', client_name='Other')
        diana.run(self.now)
        self.assertEqual(Kazi.objects.count(), 2)
        kazi = Kazi.objects.get(recipient_email='asha@example.com')
        self.assertIn('invoice 3 zimechelewa (siku 58)', kazi.title)
        self.assertIn('TZS 1,500,000', kazi.title)
        for inv in (a, b, c):
            self.assertIn(f'/invoice/{inv.token}/', kazi.draft)
            self.assertIn(inv.invoice_number, kazi.detail)
        self.assertEqual(kazi.draft.count('Habari Asha Shop'), 1)

        # Moja ikilipwa: ukumbusho mpya wenye invoice 2, wa zamani unafungwa
        c.status = 'paid'
        c.save()
        diana.run(self.now)
        kazi.refresh_from_db()
        self.assertEqual(kazi.status, Kazi.DONE)
        fresh = Kazi.objects.get(recipient_email='asha@example.com', status=Kazi.AWAITING)
        self.assertNotIn(f'/invoice/{c.token}/', fresh.draft)
        self.assertIn('invoice 2 zimechelewa', fresh.title)

    def test_due_soon_and_far_future(self):
        self.invoice(due_days_ago=-2)
        self.invoice(due_days_ago=-30)
        self.invoice(due_days_ago=5, status='draft')
        diana.run(self.now)
        kazi = Kazi.objects.get()
        self.assertEqual(kazi.priority, 3)
        self.assertIn(':soon', kazi.key)

    def test_numbers(self):
        self.invoice(due_days_ago=3)
        n = diana.numbers(self.now)
        self.assertEqual(n['overdue_count'], 1)
        self.assertEqual(n['outstanding'], 500000)


class SelvesterTests(Base):
    def lead(self, email='juma@example.com'):
        client = Client.objects.create(name='Juma', email=email, phone='0712000000')
        kind = WebsiteType.objects.create(name='E-commerce')
        return ProjectProposal.objects.create(client=client, website_type=kind,
                                              requirements={'client_name': 'Juma', 'client_email': email,
                                                            'business': 'Duka la nguo'})

    def test_new_lead_gets_follow_up_and_closes_when_converted(self):
        self.lead()
        selvester.run(timezone.now())
        kazi = Kazi.objects.get(worker='selvester')
        self.assertEqual(kazi.status, Kazi.AWAITING)
        self.assertIn('E-commerce', kazi.title)
        self.assertTrue(kazi.subject)
        Proposal.objects.create(client_email='juma@example.com', client_name='Juma')
        selvester.run(timezone.now())
        kazi.refresh_from_db()
        self.assertEqual(kazi.status, Kazi.DONE)

    def test_contact_form_watermark(self):
        Contact.objects.create(full_name='Old', email='o@example.com', subject='Zamani', message='...')
        selvester.run(timezone.now())
        self.assertFalse(Kazi.objects.filter(key__startswith='selv:contact:').exists())
        Contact.objects.create(full_name='Neema', email='n@example.com', subject='Bei ya tovuti', message='Bei?')
        selvester.run(timezone.now())
        kazi = Kazi.objects.get(key__startswith='selv:contact:')
        self.assertEqual(kazi.recipient_email, 'n@example.com')
        self.assertTrue(kazi.subject.startswith('Re: '))


class IbrahimuTests(Base):
    def test_handoff_gap_and_buyer(self):
        from apps.chatbot.models import Conversation, KnowledgeGap, Message

        bot = self.bot()
        now = timezone.now()
        conv = Conversation.objects.create(bot=bot, customer_phone='255712345678', customer_name='Rehema')
        Conversation.objects.filter(pk=conv.pk).update(is_human_handoff=True, handoff_at=now - timedelta(hours=3),
                                                       handoff_count=1, last_message_at=now)
        KnowledgeGap.objects.create(bot=bot, question='Mnafanya app za simu?', normalized='app simu', times_asked=3)
        Message.objects.create(conversation=conv, role='user', content='Bei ya website ni kiasi gani?')

        result = ibrahimu.run(now)
        self.assertEqual(result['handoffs'], 1)
        handoff = Kazi.objects.get(key__startswith='ibra:handoff:')
        self.assertEqual(handoff.priority, 1)
        gap = Kazi.objects.get(key__startswith='ibra:gap:')
        self.assertEqual(gap.channel, 'faq')
        buyer = Kazi.objects.get(key__startswith='selv:chat:')
        self.assertEqual(buyer.worker, 'selvester')
        self.assertEqual(buyer.channel, 'whatsapp')

        ok, message = actions.approve(gap.pk, draft='Ndiyo, tunatengeneza app za Android na iOS.')
        self.assertTrue(ok, message)
        self.assertTrue(bot.faqs.filter(answer__icontains='Android').exists())

        Conversation.objects.filter(pk=conv.pk).update(is_human_handoff=False)
        ibrahimu.run(now)
        handoff.refresh_from_db()
        self.assertEqual(handoff.status, Kazi.DONE)

    def test_only_the_bot_named_jamiibot(self):
        from apps.chatbot.models import BotConfig, ChatbotClient
        self.assertIn('detail', ibrahimu.run(timezone.now()))
        user = User.objects.create_user('duka', 'd@example.com', 'p')
        client = ChatbotClient.objects.create(user=user, full_name='Duka', business_name='JamiiTek Duka',
                                              email='d@example.com', phone='0700000000')
        BotConfig.objects.create(client=client, bot_name='Amara', business_name='JamiiTek Duka',
                                 description='Bot ya mteja', session_name='duka')
        self.assertFalse(ibrahimu.bots().exists())
        bot = self.bot()
        self.assertEqual(list(ibrahimu.bots()), [bot])


class GraceTests(Base):
    def test_one_post_per_day_after_seven(self):
        self.assertEqual(grace.run(_at(6))['post'], 'bado mapema')
        grace.run(_at(8))
        grace.run(_at(10))
        post = Kazi.objects.get(worker='grace')
        self.assertEqual(post.channel, 'social')
        self.assertIn('🔗 https://', post.draft)

    def test_old_posts_expire(self):
        grace.run(_at(8))
        Kazi.objects.update(created_at=timezone.now() - timedelta(days=3))
        grace.run(_at(8))
        self.assertEqual(Kazi.objects.filter(status=Kazi.DISMISSED).count(), 1)


class ActionTests(Base):
    def test_approve_sends_email_once(self):
        self.invoice()
        diana.run(self.now)
        kazi = Kazi.objects.get()
        ok, message = actions.approve(kazi.pk, draft='Habari Asha,\n\nTafadhali lipa.\n\nDiana')
        self.assertTrue(ok, message)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['asha@example.com'])
        self.assertIn('Tafadhali lipa', mail.outbox[0].alternatives[0][0])
        kazi.refresh_from_db()
        self.assertEqual(kazi.status, Kazi.SENT)
        ok, _ = actions.approve(kazi.pk)
        self.assertFalse(ok)
        self.assertEqual(len(mail.outbox), 1)

    def test_whatsapp_without_bridge_gives_link(self):
        kazi = Kazi.objects.create(worker='selvester', key='x', title='t', channel='whatsapp',
                                   recipient_phone='0712345678', draft='Habari', status=Kazi.AWAITING)
        ok, message = actions.approve(kazi.pk)
        self.assertTrue(ok)
        self.assertIn('https://wa.me/255712345678', message)


class WilliamTests(Base):
    def test_morning_report_once_per_day_with_grace_post(self):
        self.invoice()
        diana.run(self.now)
        grace.run(self.now)
        william.run(self.now)
        william.run(self.now)
        self.assertEqual(len(mail.outbox), 1)
        report = Ripoti.objects.get(kind='asubuhi')
        self.assertEqual(report.delivered, 'email')
        email = mail.outbox[0]
        self.assertEqual(email.to, ['boss@example.com'])
        self.assertNotIn('*', email.subject)
        self.assertTrue(email.subject.startswith('👔 William — Mpango wa leo · '))
        html = email.alternatives[0][0]
        self.assertNotIn('*Diana', html)
        self.assertIn('Diana · Fedha', html)
        self.assertIn('href="https://www.jamiitek.com/manage/wafanyakazi/"', html)
        self.assertIn('William', report.text)
        self.assertIn('Zinasubiri idhini yako (1)', report.text)
        self.assertIn('Grace · Post ya leo', report.text)
        self.assertNotIn('<b>', report.text)

    def test_no_morning_report_in_the_evening(self):
        with mock.patch('apps.notify.notify', return_value=1):
            william.run(_at(19))
        self.assertFalse(Ripoti.objects.filter(kind='asubuhi').exists())
        self.assertEqual(Ripoti.objects.get(kind='jioni').delivered, 'kimya — hakuna jipya')

    def test_reminds_stale_tasks_once_a_day(self):
        kazi = Kazi.objects.create(worker='diana', key='k', title='t')
        Kazi.objects.filter(pk=kazi.pk).update(created_at=timezone.now() - timedelta(days=3))
        william._remind(timezone.now())
        william._remind(timezone.now())
        kazi.refresh_from_db()
        self.assertEqual(kazi.reminders, 1)

    def test_report_goes_to_wilife_when_configured(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {'ok': True}
        with mock.patch.dict('os.environ', {'WILIFE_URL': 'https://wilife.test'}), \
                mock.patch('apps.wafanyakazi.wilife.requests.post', return_value=response) as post:
            william.run(self.now)
        self.assertEqual(len(mail.outbox), 0)
        url = post.call_args[0][0]
        self.assertEqual(url, 'https://wilife.test/agent/jamiitek/')
        self.assertEqual(post.call_args[1]['headers']['X-Workers-Token'], TOKEN)
        self.assertEqual(post.call_args[1]['json']['kind'], 'report')


class RunnerAndApiTests(Base):
    def test_full_run_pushes_approvals_to_wilife(self):
        self.invoice()
        response = mock.Mock(status_code=200)
        response.json.return_value = {'ok': True, 'code': '4821'}
        with mock.patch.dict('os.environ', {'WILIFE_URL': 'https://wilife.test'}), \
                mock.patch('apps.wafanyakazi.wilife.requests.post', return_value=response) as post:
            result = run_all(now=self.now)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['approvals_pushed'], 1)
        kinds = [c[1]['json']['kind'] for c in post.call_args_list]
        self.assertEqual(kinds, ['approval', 'report'])
        kazi = Kazi.objects.get(worker='diana')
        self.assertEqual(kazi.wilife_code, '4821')
        self.assertIn('OK 4821', Ripoti.objects.get().text)
        self.assertTrue(Alama.get('run:last'))

    def test_api_requires_token(self):
        self.assertEqual(self.client.get('/wafanyakazi/api/hali/').status_code, 403)
        r = self.client.get('/wafanyakazi/api/hali/', HTTP_X_WORKERS_TOKEN=TOKEN)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([w['name'] for w in r.json()['team']],
                         ['William', 'Diana', 'Selvester', 'Ibrahimu', 'Grace'])

    def test_api_approve_and_reject(self):
        self.invoice()
        self.invoice(client_email='b@example.com', client_name='B')
        diana.run(self.now)
        first, second = Kazi.objects.order_by('pk')
        r = self.client.post(f'/wafanyakazi/api/kazi/{first.pk}/idhinisha/', data='{}',
                             content_type='application/json', HTTP_X_WORKERS_TOKEN=TOKEN)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(len(mail.outbox), 1)
        r = self.client.post(f'/wafanyakazi/api/kazi/{second.pk}/kataa/', HTTP_X_WORKERS_TOKEN=TOKEN)
        self.assertTrue(r.json()['ok'])
        second.refresh_from_db()
        self.assertEqual(second.status, Kazi.DISMISSED)

    def test_cron_token(self):
        self.assertEqual(self.client.get('/tasks/wafanyakazi/?token=bad').status_code, 403)
        with mock.patch('apps.wafanyakazi.runner.run_in_background') as bg:
            r = self.client.get('/tasks/wafanyakazi/?token=cron')
        self.assertEqual(r.status_code, 200)
        bg.assert_called_once()


class PanelTests(Base):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user('boss', 'b@example.com', 'p', is_staff=True)
        self.client.force_login(self.staff)

    def test_dashboard_and_actions(self):
        self.invoice()
        diana.run(self.now)
        kazi = Kazi.objects.get()
        r = self.client.get('/manage/wafanyakazi/')
        self.assertEqual(r.status_code, 200)
        for name in ('William', 'Ibrahimu', 'Selvester', 'Grace', 'Diana'):
            self.assertContains(r, name)
        self.assertContains(r, kazi.title)
        r = self.client.get('/manage/wafanyakazi/?w=diana&hali=zilizofungwa')
        self.assertEqual(r.status_code, 200)
        r = self.client.post(f'/manage/wafanyakazi/kazi/{kazi.pk}/achana/')
        self.assertEqual(r.status_code, 302)
        kazi.refresh_from_db()
        self.assertEqual(kazi.status, Kazi.DISMISSED)

    def test_anonymous_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.get('/manage/wafanyakazi/').status_code, 302)


class MtihaniTests(Base):
    def groq(self, text):
        response = mock.Mock(status_code=200, text='')
        response.json.return_value = {'choices': [{'message': {'content': text}}]}
        return mock.patch('apps.wafanyakazi.ai.requests.post', return_value=response)

    def test_exam_writes_samples_but_keeps_and_sends_nothing(self):
        self.invoice()
        Kazi.objects.create(worker='diana', key='zamani', title='Kazi ya zamani')
        with mock.patch.dict('os.environ', {'GROQ_API_KEY': 'k'}), \
                self.groq('Habari Asha Shop,\n\nTunakukumbusha invoice yako ya TZS 999,999 kwa heshima.'), \
                mock.patch('apps.notify.notify') as notify:
            exam = mtihani.run(now=self.now)
        notify.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(list(Kazi.objects.values_list('key', flat=True)), ['zamani'])
        self.assertFalse(Ripoti.objects.exists())
        self.assertEqual(exam.status, Mtihani.DONE)

        workers = {w['slug']: w for w in exam.result['workers']}
        sample = workers['diana']['samples'][0]
        checks = {c['text']: c['ok'] for c in sample['checks']}
        self.assertTrue(checks['Imeandikwa na AI'])
        self.assertTrue(checks['Ina link ya invoice'])
        self.assertTrue(checks['Inamtaja Asha'])
        self.assertFalse(checks['Kiasi kisichotoka kwenye data: 999999'])
        self.assertIn('William', exam.result['william'])
        self.assertTrue(exam.result['score']['total'] > 0)

    def test_template_drafts_are_marked(self):
        self.invoice()
        exam = mtihani.run(now=self.now)
        sample = exam.result['workers'][0]['samples'][0]
        self.assertIn('Template ya kawaida (AI haikuandika)', [c['text'] for c in sample['checks']])
        self.assertIn('Hakuna kiasi kilichobuniwa', [c['text'] for c in sample['checks']])
        self.assertFalse(exam.result['groq'])

    def test_page(self):
        staff = User.objects.create_user('boss', 'b@example.com', 'p', is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get('/manage/wafanyakazi/mtihani/'), 'Bado hakuna mtihani')
        mtihani.run(now=self.now)
        r = self.client.get('/manage/wafanyakazi/mtihani/')
        self.assertContains(r, 'Mpango wa asubuhi ungekuwa hivi')
        with mock.patch('apps.wafanyakazi.mtihani.run_in_background') as bg:
            self.client.post('/manage/wafanyakazi/mtihani/')
        bg.assert_called_once()


class OfisiTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_user('boss', 'b@example.com', 'p', is_staff=True))

    def test_office_shows_people_their_work_and_the_feed(self):
        self.invoice()
        run_all(now=self.now)
        # "online" = mzunguko ndani ya dakika 50 zilizopita. Ukurasa ukisoma saa
        # halisi, test ingepita asubuhi tu (kabla ya 09:50) — tunaibana saa.
        with mock.patch('apps.wafanyakazi.ofisi.timezone.now', return_value=self.now + timedelta(minutes=10)):
            r = self.client.get('/manage/wafanyakazi/')
        self.assertEqual(r.status_code, 200)
        for slug in ('william', 'ibrahimu', 'selvester', 'grace', 'diana'):
            self.assertContains(r, f'wafanyakazi/team/{slug}')
        self.assertContains(r, 'William anasema')
        self.assertContains(r, 'Anasubiri idhini yako')          # Diana ana rasimu
        self.assertContains(r, 'ameandaa rasimu')                # shughuli za ofisi
        self.assertContains(r, 'Mezani kwako')
        team = {w['slug']: w for w in r.context['team']}
        self.assertTrue(team['diana']['online'])
        self.assertEqual(team['diana']['state'], 'waiting')

    def test_desk_of_one_worker(self):
        r = self.client.get('/manage/wafanyakazi/?w=grace')
        self.assertContains(r, 'Meza ya Grace')

    def test_zamani(self):
        from .templatetags.ofisi import zamani
        now = timezone.now()
        self.assertEqual(zamani(now), 'sasa hivi')
        self.assertEqual(zamani(now - timedelta(minutes=5)), 'dakika 5 zilizopita')
        self.assertEqual(zamani(now - timedelta(hours=3)), 'saa 3 zilizopita')
        self.assertEqual(zamani(now - timedelta(days=1, hours=2)), 'jana')
        self.assertEqual(zamani(now - timedelta(days=4)), 'siku 4 zilizopita')
