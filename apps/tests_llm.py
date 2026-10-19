"""Gemini kwanza, Groq akiba — kwa uandishi wote wa JamiiTek (apps/llm.py)."""
import json
from unittest import mock

from django.test import TestCase, override_settings

from apps import llm


def _http(status, body):
    r = mock.Mock(status_code=status, text=json.dumps(body))
    r.json.return_value = body
    return r


GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "Makala safi ya Kiswahili."}]}, "finishReason": "STOP"}]}
MSGS = [{"role": "system", "content": "Wewe ni mwandishi."}, {"role": "user", "content": "Andika."}]


@override_settings(GEMINI_API_KEY="g", GROQ_API_KEY="q")
class LlmShimTests(TestCase):
    def test_sdk_shim_uses_gemini_first(self):
        with mock.patch("apps.llm.requests.post", return_value=_http(200, GEMINI_OK)) as post, \
             mock.patch("groq.Groq") as groq:
            resp = llm.client().chat.completions.create(model="llama-3.3-70b-versatile", messages=MSGS,
                                                        max_tokens=500, response_format={"type": "json_object"})
        self.assertEqual(resp.choices[0].message.content, "Makala safi ya Kiswahili.")
        self.assertEqual(resp.choices[0].finish_reason, "stop")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "Wewe ni mwandishi.")
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertFalse(groq.called)

    def test_gemini_failure_falls_back_to_groq_with_same_request(self):
        with mock.patch("apps.llm.requests.post", return_value=_http(429, {"error": "quota"})), \
             mock.patch("groq.Groq") as groq:
            groq.return_value.chat.completions.create.return_value = "groq-reply"
            out = llm.client().chat.completions.create(model="llama-3.3-70b-versatile", messages=MSGS,
                                                       max_tokens=500, temperature=0.4)
        self.assertEqual(out, "groq-reply")
        kwargs = groq.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual((kwargs["model"], kwargs["max_tokens"]), ("llama-3.3-70b-versatile", 500))
        groq.assert_called_with(api_key="q")

    def test_ai_provider_groq_skips_gemini(self):
        with mock.patch.dict("os.environ", {"AI_PROVIDER": "groq"}), \
             mock.patch("apps.llm.requests.post") as post, mock.patch("groq.Groq") as groq:
            llm.client().chat.completions.create(model="m", messages=MSGS)
            self.assertIsNone(llm.gemini_response({"messages": MSGS}))
        self.assertFalse(post.called)
        self.assertTrue(groq.called)

    def test_raw_shim_returns_groq_shaped_json(self):
        with mock.patch("apps.llm.requests.post", return_value=_http(200, GEMINI_OK)):
            r = llm.gemini_response({"messages": MSGS, "max_tokens": 300})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["choices"][0]["message"]["content"], "Makala safi ya Kiswahili.")

    def test_max_tokens_maps_to_length(self):
        cut = {"candidates": [{"content": {"parts": [{"text": "nusu"}]}, "finishReason": "MAX_TOKENS"}]}
        with mock.patch("apps.llm.requests.post", return_value=_http(200, cut)):
            resp = llm.client().chat.completions.create(model="m", messages=MSGS)
        self.assertEqual(resp.choices[0].finish_reason, "length")

    def test_writers_get_the_shim(self):
        from apps import blog_ai, docs_ai, proposal_ai
        for mod in (blog_ai, docs_ai, proposal_ai):
            self.assertIsInstance(mod._client(), llm._Client, mod.__name__)

    def test_wafanyakazi_writes_with_gemini(self):
        from apps.wafanyakazi import ai
        ai.reset_budget(3)
        with mock.patch("apps.llm.gemini_chat", return_value=("Makala safi ya Kiswahili.", "stop")), \
             mock.patch("requests.post") as groq_post:
            text = ai.write("mfumo", "andika")
        self.assertEqual(text, "Makala safi ya Kiswahili.")
        self.assertFalse(groq_post.called)


class NoKeysTests(TestCase):
    @override_settings(GEMINI_API_KEY="", GROQ_API_KEY="")
    def test_no_keys(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "", "GROQ_API_KEY": ""}):
            self.assertIsNone(llm.client())
            self.assertIsNone(llm.gemini_response({"messages": MSGS}))


@override_settings(GEMINI_API_KEY="g", GROQ_API_KEY="q")
class AiHealthWarningTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _fail(self, status=429, body=None):
        with mock.patch("apps.llm.requests.post", return_value=_http(status, body or {"error": "RESOURCE_EXHAUSTED"})), \
             mock.patch("groq.Groq"):
            llm.client().chat.completions.create(model="m", messages=MSGS)

    def test_failure_is_recorded_and_cleared_by_success(self):
        self.assertIsNone(llm.health())
        self._fail()
        self._fail()
        h = llm.health()
        self.assertEqual(h["level"], "fallback")
        self.assertIn("Groq ndiyo inaandika", h["title"])
        self.assertIn("Kikomo cha bure", h["reason"])
        self.assertEqual(h["count"], 2)
        with mock.patch("apps.llm.requests.post", return_value=_http(200, GEMINI_OK)):
            llm.gemini_chat(MSGS)
        self.assertIsNone(llm.health())

    def test_bad_key_reason(self):
        self._fail(400, {"error": {"message": "API key not valid. Please pass a valid API key."}})
        self.assertIn("GEMINI_API_KEY haikubaliki", llm.health()["reason"])

    @override_settings(GEMINI_API_KEY="")
    def test_missing_key_warns(self):
        self.assertIn("Gemini haijawekwa", llm.health()["title"])

    @mock.patch.dict("os.environ", {"STAFF_2FA_REQUIRED": "false"})
    def test_staff_see_warning_on_manage_and_ai_admin(self):
        from django.contrib.auth.models import User
        self._fail()
        staff = User.objects.create_superuser("boss", "b@x.com", "x")
        self.client.force_login(staff)
        from apps.two_factor import SESSION_FLAG
        session = self.client.session
        session[SESSION_FLAG] = True
        session.save()
        for url in ("/manage/", "/admin/apps/blogpost/"):
            r = self.client.get(url, secure=True, follow=True)
            self.assertContains(r, "Gemini imeshindwa", msg_prefix=url)

    def test_non_staff_do_not_get_it(self):
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        from apps.context_processors import ai_health
        req = RequestFactory().get("/")
        req.user = AnonymousUser()
        self.assertEqual(ai_health(req), {})


@override_settings(GEMINI_API_KEY="g", GROQ_API_KEY="q")
class GeminiModelReplacementTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_model_suggested_by_google_is_used_and_remembered(self):
        gone = _http(404, {"error": {"message": "This model models/gemini-2.5-flash is no longer available to new "
                                                "users. Please update your code to use models/gemini-3.8-flash for "
                                                "the latest features."}})
        listing = _http(200, {"models": []})
        with mock.patch("apps.llm.requests.post", side_effect=[gone, _http(200, GEMINI_OK)]) as post, \
             mock.patch("apps.llm.requests.get", return_value=listing):
            text, _ = llm.gemini_chat(MSGS)
        self.assertEqual(text, "Makala safi ya Kiswahili.")
        self.assertIn("gemini-3.8-flash:generateContent", post.call_args.args[0])
        with mock.patch("apps.llm.requests.post", return_value=_http(200, GEMINI_OK)) as post:
            llm.gemini_chat(MSGS)
        self.assertIn("gemini-3.8-flash:generateContent", post.call_args.args[0])

    def test_newest_listed_model_of_same_family(self):
        listing = _http(200, {"models": [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]}
                                         for n in ("gemini-2.5-flash", "gemini-3.1-flash", "gemini-3.1-flash-lite",
                                                   "gemini-3.1-pro")]})
        with mock.patch("apps.llm.requests.get", return_value=listing):
            self.assertEqual(llm.replacement_models("gemini-2.5-flash")[0], "gemini-3.1-flash")


@override_settings(GEMINI_API_KEY="g", GROQ_API_KEY="q")
class AiChoiceTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_default_is_gemini_flash(self):
        self.assertEqual(llm.selected(), "gemini-flash")
        self.assertTrue(llm.gemini_first())

    def test_groq_choice_goes_groq_first_system_wide(self):
        llm.choose("groq")
        self.assertFalse(llm.gemini_first())
        self.assertIsNone(llm.gemini_response({"messages": MSGS}))
        with mock.patch("apps.llm.requests.post") as post, mock.patch("groq.Groq") as groq:
            groq.return_value.chat.completions.create.return_value = "groq-reply"
            out = llm.client().chat.completions.create(model="llama-3.3-70b-versatile", messages=MSGS)
        self.assertEqual(out, "groq-reply")
        self.assertFalse(post.called)

    def test_groq_failure_falls_back_to_gemini(self):
        llm.choose("groq")
        with mock.patch("apps.llm.requests.post", return_value=_http(200, GEMINI_OK)), \
             mock.patch("groq.Groq") as groq:
            groq.return_value.chat.completions.create.side_effect = RuntimeError("rate limit")
            out = llm.client().chat.completions.create(model="m", messages=MSGS)
        self.assertEqual(out.choices[0].message.content, "Makala safi ya Kiswahili.")

    def test_post_shim_groq_error_falls_back_to_gemini(self):
        llm.choose("groq")
        with mock.patch("apps.llm.requests.post",
                        side_effect=[_http(429, {"error": "limit"}), _http(200, GEMINI_OK)]):
            r = llm.post("https://api.groq.com/openai/v1/chat/completions", json={"messages": MSGS})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["choices"][0]["message"]["content"], "Makala safi ya Kiswahili.")

    def test_pro_choice_uses_pro_model(self):
        llm.choose("gemini-pro")
        with mock.patch("apps.llm.requests.post", return_value=_http(200, GEMINI_OK)) as post:
            llm.gemini_chat(MSGS)
        self.assertIn("gemini-2.5-pro:generateContent", post.call_args.args[0])

    @mock.patch.dict("os.environ", {"STAFF_2FA_REQUIRED": "false"})
    def test_manage_page_switches_and_tests(self):
        from django.contrib.auth.models import User
        from apps.models import AIConfig
        from apps.two_factor import SESSION_FLAG
        staff = User.objects.create_superuser("boss", "b@x.com", "x")
        self.client.force_login(staff)
        session = self.client.session
        session[SESSION_FLAG] = True
        session.save()
        r = self.client.get("/manage/ai/", secure=True)
        self.assertContains(r, "Gemini Flash")
        # kitufe cha Jaribu kinazimwa kikibonyezwa, kwa hiyo "action" lazima iwe hidden input
        self.assertContains(r, '<input type="hidden" name="action" value="test">', count=3)
        self.client.post("/manage/ai/", {"choice": "groq"}, secure=True)   # bila action: haibadilishi
        self.assertEqual(AIConfig.load().choice, "gemini-flash")
        self.assertContains(r, "Tumia hii")
        self.client.post("/manage/ai/", {"choice": "groq", "action": "choose"}, secure=True)
        self.assertEqual(AIConfig.load().choice, "groq")
        self.assertEqual(llm.selected(), "groq")
        self.client.post("/manage/ai/", {"choice": "evil", "action": "choose"}, secure=True)
        self.assertEqual(AIConfig.load().choice, "groq")
        with mock.patch("apps.llm.requests.post", return_value=_http(200, GEMINI_OK)):
            r = self.client.post("/manage/ai/", {"choice": "gemini-flash", "action": "test"}, secure=True, follow=True)
        self.assertContains(r, "Makala safi ya Kiswahili.")
        self.assertEqual(AIConfig.load().choice, "groq")   # kujaribu hakubadili chaguo


def _with_fernet(test_case):
    """Weka FERNET_KEY ya majaribio ili ai_secrets ziweze kuhifadhiwa."""
    from cryptography.fernet import Fernet
    from apps import crypto
    patcher = mock.patch.dict("os.environ", {"FERNET_KEY": Fernet.generate_key().decode(),
                                             "STAFF_2FA_REQUIRED": "false"})
    patcher.start()
    test_case.addCleanup(patcher.stop)
    crypto._CHECKED, crypto._FERNET = False, None
    test_case.addCleanup(lambda: setattr(crypto, "_CHECKED", False))


GROQ_OK = {"choices": [{"message": {"content": "Jibu la Groq"}}], "usage": {"total_tokens": 9}}


@override_settings(GEMINI_API_KEY="system-key", GROQ_API_KEY="q")
class JamiiBotModelChoiceTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        from django.contrib.auth.models import User
        from apps.chatbot.models import BotConfig, ChatbotClient, Conversation
        cache.clear()
        _with_fernet(self)
        self.owner = User.objects.create_user("mteja", "m@x.com", "x")
        self.boss = User.objects.create_superuser("bossbot", "bb@x.com", "x")
        cl = ChatbotClient.objects.create(user=self.owner, full_name="B", business_name="Biz", email="m@x.com")
        self.bot = BotConfig.objects.create(client=cl, bot_name="DukaBot", business_name="Duka",
                                            status="active", is_active=True)
        self.conv = Conversation.objects.create(bot=self.bot, customer_phone="255700000000")

    def _reply(self, post_side_effect):
        from apps.chatbot.ai_engine import BotAIEngine
        # apps.llm na ai_engine zinashiriki requests.post moja
        with mock.patch("requests.post", side_effect=post_side_effect) as post:
            return BotAIEngine(self.bot).get_response(self.conv, "Bei ya website ni ngapi?"), post

    def _give_key(self, key="AIzaMtejaKey123"):
        with mock.patch("requests.get", return_value=_http(200, {"models": []})):
            ok, _ = self.bot.set_gemini_key(key)
        self.assertTrue(ok)
        self.bot.refresh_from_db()

    def test_default_bot_stays_on_groq(self):
        res, _ = self._reply([_http(200, GROQ_OK)])
        self.assertEqual(res["content"], "Jibu la Groq")
        self.assertEqual(res["model"], "llama-3.3-70b-versatile")

    def test_gemini_bot_uses_the_clients_own_key(self):
        self._give_key()
        self.bot.ai_model = "gemini"
        self.bot.save()
        self.bot.refresh_from_db()
        self.assertEqual(self.bot.gemini_key, "AIzaMtejaKey123")   # encrypted round-trip
        res, post = self._reply([_http(200, GEMINI_OK)])
        self.assertEqual(res["content"], "Makala safi ya Kiswahili.")
        self.assertEqual(res["model"], "gemini")
        self.assertEqual(post.call_args.kwargs["params"]["key"], "AIzaMtejaKey123")
        self.assertIn("gemini-2.5-flash:generateContent", post.call_args.args[0])

    def test_gemini_bot_without_key_never_uses_system_key(self):
        self.bot.ai_model = "gemini"
        self.bot.save()
        res, post = self._reply([_http(200, GROQ_OK)])
        self.assertEqual(res["content"], "Jibu la Groq")
        self.assertEqual(post.call_count, 1)
        self.assertIn("groq.com", post.call_args.args[0])

    def test_client_key_failure_falls_back_to_groq_without_system_warning(self):
        from apps import llm
        self._give_key()
        self.bot.ai_model = "gemini"
        self.bot.save()
        res, post = self._reply([_http(429, {"error": "quota"}), _http(200, GROQ_OK)])
        self.assertEqual(res["content"], "Jibu la Groq")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "llama-3.3-70b-versatile")
        self.assertIsNone(llm.health())   # key ya mteja haiwashi onyo la /manage

    def test_bad_key_is_rejected(self):
        with mock.patch("requests.get", return_value=_http(400, {"error": "API key not valid"})):
            ok, msg = self.bot.set_gemini_key("AIzaMbaya")
        self.assertFalse(ok)
        self.bot.refresh_from_db()
        self.assertEqual(self.bot.gemini_key, "")

    def test_client_portal_ai_tab(self):
        self.client.force_login(self.owner)
        r = self.client.get("/chatbot/config/")
        self.assertContains(r, "aistudio.google.com/apikey")
        self.assertContains(r, "Create API key")
        self.assertContains(r, "Groq (Default)")
        self.assertContains(r, "Gemini (Custom)")
        with mock.patch("requests.get", return_value=_http(200, {"models": []})):
            self.client.post("/chatbot/config/", {"section": "ai", "ai_engine": "gemini",
                                                  "gemini_api_key": " AIzaYangu999 "})
        self.bot.refresh_from_db()
        self.assertEqual(self.bot.ai_model, "gemini")
        self.assertEqual(self.bot.gemini_key, "AIzaYangu999")
        r = self.client.get("/chatbot/config/")
        self.assertNotContains(r, "AIzaYangu999")          # key haionyeshwi tena
        self.assertContains(r, "AIza")                     # ila iliyofichwa (mask)
        self.client.post("/chatbot/config/", {"section": "ai", "ai_engine": "groq", "delete_key": "on"})
        self.bot.refresh_from_db()
        self.assertEqual(self.bot.ai_model, "")
        self.assertEqual(self.bot.gemini_key, "")

    def test_manage_page_sets_bot_model(self):
        self.client.force_login(self.boss)
        url = f"/manage/chatbot/bots/{self.bot.id}/"
        self.assertContains(self.client.get(url, secure=True), "Gemini Flash")
        self.client.post(url + "action/", {"action": "set_model", "ai_model": "gemini"}, secure=True)
        self.bot.refresh_from_db()
        self.assertEqual(self.bot.ai_model, "gemini")
        self.client.post(url + "action/", {"action": "set_model", "ai_model": "evil"}, secure=True)
        self.bot.refresh_from_db()
        self.assertEqual(self.bot.ai_model, "gemini")


def _clear_caches():
    from django.core.cache import caches
    for alias in caches:
        caches[alias].clear()


class JamiiLiteAnnouncementTests(TestCase):
    def setUp(self):
        _clear_caches()

    def test_homepage_shows_announcement_and_service(self):
        from apps.models import Service
        svc = Service.objects.get(service_type__startswith="JamiiLite")   # data migration 0057
        self.assertTrue(svc.show_on_home)
        self.assertEqual(svc.icon, "network")
        r = self.client.get("/")
        self.assertContains(r, 'id="jamiilite"')
        self.assertContains(r, "Coming soon · JamiiLite 5G")
        self.assertContains(r, "subject=JamiiLite%205G")
        self.assertContains(r, svc.service_type)


class HomepageServiceArtTests(TestCase):
    def setUp(self):
        _clear_caches()
        self.addCleanup(_clear_caches)   # homepage imehifadhiwa (cache) — isivuje kwenye majaribio mengine

    def test_first_service_card_uses_its_own_art(self):
        from apps.models import Service
        Service.objects.update(show_on_home=False)
        Service.objects.create(service_type="Website Development", description="Websites", show_on_home=True, order=0)
        body = self.client.get("/").content.decode()
        self.assertIn('class="wb"', body)            # tovuti inajengwa live
        self.assertNotIn('class="orb"', body)
        Service.objects.update(show_on_home=False)
        Service.objects.create(service_type="AI WhatsApp Bot", description="JamiiBot", icon="bot",
                               show_on_home=True, order=0)
        _clear_caches()
        body = self.client.get("/").content.decode()
        self.assertNotIn('class="wb"', body)
        self.assertIn('class="svc__art"', body)       # mchoro wa huduma husika
        self.assertIn("css/jt-art", body)
