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
