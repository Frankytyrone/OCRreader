import unittest
import types
import sys

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub

if "pdf2image" not in sys.modules:
    pdf2image_stub = types.ModuleType("pdf2image")
    pdf2image_stub.convert_from_path = lambda *args, **kwargs: []
    sys.modules["pdf2image"] = pdf2image_stub

from convert_bulletin import build_html_content, linkify


class LinkifyTests(unittest.TestCase):
    def test_linkify_email_url_and_phone(self):
        text = (
            "Email: parishofmevagh@gmail.com Website: www.killybegsparish.com "
            "Tel: 074-9541135 Mobile: 087 4758009"
        )
        linked = linkify(text)
        self.assertIn(
            '<a href="mailto:parishofmevagh@gmail.com">parishofmevagh@gmail.com</a>',
            linked,
        )
        self.assertIn(
            '<a href="https://www.killybegsparish.com" target="_blank" rel="noopener noreferrer">www.killybegsparish.com</a>',
            linked,
        )
        self.assertIn('<a href="tel:+353749541135">074-9541135</a>', linked)
        self.assertIn('<a href="tel:+353874758009">087 4758009</a>', linked)

    def test_linkify_handles_plus353_with_optional_zero(self):
        linked = linkify("Parish office: +353 (0)74 9548902")
        self.assertIn('<a href="tel:+353749548902">+353 (0)74 9548902</a>', linked)

    def test_build_html_content_escapes_then_linkifies(self):
        html = build_html_content([["Website: www.example.com & <safe>"]])
        self.assertIn("&amp;", html)
        self.assertIn("&lt;safe&gt;", html)
        self.assertIn(
            '<a href="https://www.example.com" target="_blank" rel="noopener noreferrer">www.example.com</a>',
            html,
        )


if __name__ == "__main__":
    unittest.main()
