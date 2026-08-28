from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGES = [
    "index.html",
    "consult.html",
    "chat.html",
    "wiki.html",
    "emergency.html",
    "toxin.html",
]


class LocalReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        key = "href" if tag in {"a", "link"} else "src" if tag in {"img", "script"} else None
        if key and values.get(key):
            self.references.append(values[key])


class StaticPageTest(unittest.TestCase):
    def test_pages_and_local_assets_exist(self):
        for page_name in PAGES:
            with self.subTest(page=page_name):
                page = ROOT / page_name
                self.assertTrue(page.exists())
                parser = LocalReferenceParser()
                parser.feed(page.read_text(encoding="utf-8"))
                for ref in parser.references:
                    if ref.startswith(("http://", "https://", "#", "mailto:", "tel:", "javascript:")):
                        continue
                    target = (page.parent / ref.split("?", 1)[0]).resolve()
                    self.assertTrue(target.exists(), f"{page_name} 引用了不存在的文件：{ref}")

    def test_every_page_declares_mobile_viewport(self):
        for page_name in PAGES:
            html = (ROOT / page_name).read_text(encoding="utf-8")
            self.assertIn('name="viewport"', html, page_name)


if __name__ == "__main__":
    unittest.main()
