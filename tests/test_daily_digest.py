"""London-school tests for scripts/daily_digest.py.

Collaborators (requests, fetch_page, send_email) are replaced by mocks so the
tests verify the conversation between units; no real network is used.
"""
import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

import daily_digest as dd

SOURCE_URL = "https://www.resmigazete.gov.tr/eskiler/2026/11/20261118.htm"

GAZETTE_HTML = """
<html><body>
  <h1>RESMİ GAZETE</h1>
  <a href="#top">Başa dön</a>
  <p><strong>YÜRÜTME VE İDARE BÖLÜMÜ</strong></p>
  <div>
    <a href="20261118-1.htm">Ticaret Bakanlığına Ait Yönetmelik</a>
  </div>
  <div>
    <a href="/eskiler/2026/11/20261118-2.htm">Gümrük Tebliği (Seri No: 5)</a>
  </div>
  <a href="javascript:void(0)">Yazdır sayfayı</a>
  <a href="mailto:info@example.org">E-posta gönder</a>
  <a href="20261118-1.htm">Ticaret Bakanlığına Ait Yönetmelik (tekrar)</a>
  <a href="x.htm">Kıs</a>
  <b>İLAN BÖLÜMÜ</b>
  <a href="https://ilan.example.org/ilan/123.htm">Yargı İlanları</a>
</body></html>
"""

EMPTY_HTML = "<html><body><h2>RESMİ GAZETE</h2><p>Bugün yayım yok.</p></body></html>"


def _tag(markup):
    return BeautifulSoup(markup, "html.parser").find()


# --------------------------------------------------------------- gazette_url_for
class TestGazetteUrlFor:
    def test_builds_archive_url_with_zero_padded_parts(self):
        assert dd.gazette_url_for(datetime(2026, 1, 5)) == (
            "https://www.resmigazete.gov.tr/eskiler/2026/01/20260105.htm"
        )

    def test_uses_gazette_base(self):
        assert dd.gazette_url_for(datetime(2026, 11, 18)).startswith(dd.GAZETTE_BASE)


# ----------------------------------------------------------- _looks_like_heading
class TestLooksLikeHeading:
    @pytest.mark.parametrize(
        "markup",
        [
            "<p>YÜRÜTME VE İDARE BÖLÜMÜ</p>",
            "<strong>İLAN BÖLÜMÜ</strong>",
            "<b>YARGI BÖLÜMÜ</b>",
            "<div>  ATAMA KARARLARI  </div>",
            "<span>TEBLİĞLER</span>",
        ],
    )
    def test_accepts_short_uppercase_blocks(self, markup):
        assert dd._looks_like_heading(_tag(markup)) is True

    @pytest.mark.parametrize(
        "markup,reason",
        [
            ("<td>YÜRÜTME VE İDARE BÖLÜMÜ</td>", "tag name not allowed"),
            ("<p>Yürütme ve İdare Bölümü</p>", "not upper case"),
            ("<p><a href='x'>İLAN BÖLÜMÜ</a></p>", "contains a link"),
            ("<p>ABCD</p>", "too short"),
            ("<p>" + "A" * 101 + "</p>", "too long"),
            ("<p>   </p>", "empty"),
        ],
    )
    def test_rejects(self, markup, reason):
        assert dd._looks_like_heading(_tag(markup)) is False, reason

    def test_length_boundaries_are_inclusive(self):
        assert dd._looks_like_heading(_tag("<p>ABCDE</p>")) is True
        assert dd._looks_like_heading(_tag("<p>" + "A" * 100 + "</p>")) is True

    def test_known_risk_digit_only_text_counts_as_heading(self):
        # Documents current behaviour: "18.11.2026".upper() == itself, so dates
        # / issue numbers in bold become category headings (see report).
        assert dd._looks_like_heading(_tag("<b>18.11.2026</b>")) is True


# ----------------------------------------------------------------- parse_gazette
class TestParseGazette:
    def test_groups_links_under_preceding_headings(self):
        day = dd.parse_gazette(GAZETTE_HTML, SOURCE_URL, "18.11.2026")

        assert day.date == "18.11.2026"
        assert day.source_url == SOURCE_URL
        assert list(day.categories) == ["YÜRÜTME VE İDARE BÖLÜMÜ", "İLAN BÖLÜMÜ"]

        yurutme = day.categories["YÜRÜTME VE İDARE BÖLÜMÜ"]
        assert [i.title for i in yurutme] == [
            "Ticaret Bakanlığına Ait Yönetmelik",
            "Gümrük Tebliği (Seri No: 5)",
        ]
        assert day.item_count == 3

    def test_resolves_relative_and_root_relative_urls(self):
        day = dd.parse_gazette(GAZETTE_HTML, SOURCE_URL, "18.11.2026")
        urls = [i.url for items in day.categories.values() for i in items]
        assert urls == [
            "https://www.resmigazete.gov.tr/eskiler/2026/11/20261118-1.htm",
            "https://www.resmigazete.gov.tr/eskiler/2026/11/20261118-2.htm",
            "https://ilan.example.org/ilan/123.htm",
        ]

    def test_skips_anchor_js_mailto_duplicate_and_short_links(self):
        day = dd.parse_gazette(GAZETTE_HTML, SOURCE_URL, "18.11.2026")
        titles = {i.title for items in day.categories.values() for i in items}
        assert "Başa dön" not in titles
        assert "Yazdır sayfayı" not in titles
        assert "E-posta gönder" not in titles
        assert "Ticaret Bakanlığına Ait Yönetmelik (tekrar)" not in titles
        assert "Kıs" not in titles

    def test_links_before_any_heading_go_to_genel(self):
        day = dd.parse_gazette('<a href="a.htm">Önceki madde</a>', SOURCE_URL, "d")
        assert list(day.categories) == ["Genel"]

    def test_empty_page_has_no_items(self):
        day = dd.parse_gazette(EMPTY_HTML, SOURCE_URL, "18.11.2026")
        assert day.categories == {}
        assert day.item_count == 0


# -------------------------------------------------------------- build_email_html
class TestBuildEmailHtml:
    def _day(self, **cats):
        return dd.GazetteDay(date="18.11.2026", source_url=SOURCE_URL, categories=cats)

    def test_subject_and_items_rendered(self):
        day = self._day(**{"İLAN BÖLÜMÜ": [dd.GazetteItem("Yargı İlanları", "https://x/1.htm")]})
        subject, body = dd.build_email_html(day)
        assert subject == "Resmi Gazete - 18.11.2026"
        assert "<h3>İLAN BÖLÜMÜ</h3>" in body
        assert '<li><a href="https://x/1.htm">Yargı İlanları</a></li>' in body
        assert f'href="{SOURCE_URL}"' in body
        assert "1 madde" in body

    def test_escapes_titles_urls_and_categories(self):
        day = self._day(
            **{"<script>X</script>": [
                dd.GazetteItem('<b>Kötü</b> & "tırnak"', 'https://x/?a=1&b="2"')
            ]}
        )
        _, body = dd.build_email_html(day)
        assert "<script>" not in body and "<b>Kötü</b>" not in body
        assert "&lt;script&gt;X&lt;/script&gt;" in body
        assert "&lt;b&gt;Kötü&lt;/b&gt; &amp; &quot;tırnak&quot;" in body
        assert 'href="https://x/?a=1&amp;b=&quot;2&quot;"' in body

    def test_empty_day_renders_not_found_message(self):
        subject, body = dd.build_email_html(self._day())
        assert subject == "Resmi Gazete - 18.11.2026"
        assert "bulunamadı" in body
        assert f'<a href="{SOURCE_URL}">{SOURCE_URL}</a>' in body
        assert "<ul>" not in body


# -------------------------------------------------------------------- send_email
@pytest.fixture
def email_env(monkeypatch):
    monkeypatch.setenv("TO_EMAIL", "to@example.com")
    monkeypatch.setenv("FROM_EMAIL", "from@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")


class TestSendEmail:
    def test_posts_to_resend_with_auth_and_payload(self, monkeypatch, email_env):
        post = MagicMock(return_value=MagicMock(status_code=200, text="ok"))
        monkeypatch.setattr(dd.requests, "post", post)

        dd.send_email("Konu", "<p>gövde</p>")

        post.assert_called_once()
        args, kwargs = post.call_args
        assert args == ("https://api.resend.com/emails",)
        assert kwargs["headers"]["Authorization"] == "Bearer re_test_key"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["json"] == {
            "from": "from@example.com",
            "to": ["to@example.com"],
            "subject": "Konu",
            "html": "<p>gövde</p>",
        }
        assert kwargs["timeout"] == 30

    def test_raises_on_api_error(self, monkeypatch, email_env):
        monkeypatch.setattr(
            dd.requests, "post",
            MagicMock(return_value=MagicMock(status_code=422, text="bad from")),
        )
        with pytest.raises(RuntimeError, match="422.*bad from"):
            dd.send_email("s", "b")

    def test_missing_env_raises_before_any_request(self, monkeypatch):
        monkeypatch.delenv("TO_EMAIL", raising=False)
        post = MagicMock()
        monkeypatch.setattr(dd.requests, "post", post)
        with pytest.raises(KeyError):
            dd.send_email("s", "b")
        post.assert_not_called()


# -------------------------------------------------------------------------- main
class TestMain:
    @pytest.fixture
    def collaborators(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # main() writes gazette_items.json to cwd
        monkeypatch.setenv("GAZETTE_DATE", "2026-11-18")
        fetch = MagicMock()
        send = MagicMock()
        monkeypatch.setattr(dd, "fetch_page", fetch)
        monkeypatch.setattr(dd, "send_email", send)
        return fetch, send, tmp_path

    def test_fetches_parses_and_emails_digest(self, collaborators):
        fetch, send, tmp_path = collaborators
        fetch.return_value = MagicMock(status_code=200, text=GAZETTE_HTML)

        assert dd.main() == 0

        fetch.assert_called_once_with(SOURCE_URL)
        send.assert_called_once()
        subject, body = send.call_args.args
        assert subject == "Resmi Gazete - 18.11.2026"
        assert "Gümrük Tebliği (Seri No: 5)" in body

        dumped = json.loads((tmp_path / "gazette_items.json").read_text("utf-8"))
        assert dumped["date"] == "18.11.2026"
        assert len(dumped["categories"]["YÜRÜTME VE İDARE BÖLÜMÜ"]) == 2

    def test_404_sends_empty_digest_without_parsing(self, collaborators, monkeypatch):
        fetch, send, _ = collaborators
        resp = MagicMock(status_code=404)
        fetch.return_value = resp
        parse = MagicMock()
        monkeypatch.setattr(dd, "parse_gazette", parse)

        assert dd.main() == 0

        parse.assert_not_called()
        resp.raise_for_status.assert_not_called()
        assert "bulunamadı" in send.call_args.args[1]

    def test_server_error_propagates_and_no_email_sent(self, collaborators):
        fetch, send, _ = collaborators
        resp = MagicMock(status_code=500)
        resp.raise_for_status.side_effect = dd.requests.HTTPError("500")
        fetch.return_value = resp

        with pytest.raises(dd.requests.HTTPError):
            dd.main()
        send.assert_not_called()
