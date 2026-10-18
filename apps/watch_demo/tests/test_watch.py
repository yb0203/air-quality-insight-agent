import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from watch_demo.app import create_app
from watch_demo.client import FixtureAgentClient, HttpAgentClient
from watch_demo.scenarios import load_scenarios

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "data" / "fixtures"  # hand-written test fixtures; the app ships real replay fixtures
SCENARIOS = load_scenarios(ROOT / "tests" / "data" / "scenarios.yaml")
IDS = [s.id for s in SCENARIOS]


@pytest.fixture(scope="module")
def web():
    return TestClient(create_app(FixtureAgentClient(FIXTURES), SCENARIOS))


class Cards(HTMLParser):
    """Collects each notification card's text and its action chips."""

    def __init__(self):
        super().__init__()
        self.cards, self.chips, self._in_card, self._in_action = [], [], 0, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "").split()
        if tag == "a" and "card" in cls:
            self.cards.append({"href": a["href"], "actions": [], "text": ""})
            self._in_card = 1
        elif tag == "a" and "chip" in cls:
            self.chips.append({"href": a["href"], "active": "active" in cls})
        elif self._in_card and tag == "span" and "action" in cls:
            self._in_action = True
            self.cards[-1]["actions"].append("")

    def handle_endtag(self, tag):
        if tag == "span":
            self._in_action = False
        if tag == "a" and self._in_card:
            self._in_card = 0

    def handle_data(self, data):
        if self._in_card:
            self.cards[-1]["text"] += data
            if self._in_action:
                self.cards[-1]["actions"][-1] += data.strip()


def parse(html: str) -> Cards:
    p = Cards()
    p.feed(html)
    return p


# WD-01: every scenario renders inside the watch, with the demo chips outside it.
@pytest.mark.parametrize("scenario_id", IDS)
def test_every_scenario_renders(web, scenario_id):
    r = web.get("/", params={"scenario": scenario_id})
    assert r.status_code == 200
    html = r.text
    assert 'class="watch"' in html
    watch_start, watch_end = html.index('class="watch"'), html.index("</main>")
    assert html.index('class="chips"') < watch_start, "chips must sit outside the watch"
    assert html.index("replay of real OpenAQ data") > watch_end, "data caption must sit outside the watch"


# WD-02: each card carries exactly one action, and the body is short and never a bare status.
@pytest.mark.parametrize("scenario_id", ["delhi-smog-night", "back-to-normal", "helsinki-smoke"])
def test_card_has_exactly_one_action(web, scenario_id):
    cards = parse(web.get("/", params={"scenario": scenario_id}).text).cards
    assert cards
    for card in cards:
        assert len(card["actions"]) == 1 and card["actions"][0]


def test_fixture_messages_follow_the_message_rules():
    for path in (FIXTURES / "feeds").glob("*.json"):
        for n in json.loads(path.read_text()):
            assert len(n["body"]) <= 220
            assert n["next_action"].strip()
            assert not re.search(r"AQI is now", n["body"], re.I)


# WD-03: feed is newest first and `limit` keeps only the newest.
def test_delhi_feed_newest_first_and_back_to_normal_alone(web):
    night = parse(web.get("/", params={"scenario": "delhi-smog-night"}).text).cards
    assert [c["href"].split("?")[0] for c in night] == ["/why/ntf_arjun_1700", "/why/ntf_arjun_0630"]
    alone = parse(web.get("/", params={"scenario": "back-to-normal"}).text).cards
    assert len(alone) == 1 and "eased after a rough 16 hours" in alone[0]["text"]


# WD-04: tapping a card opens the Why view, built from the explain payload.
def test_why_view_renders_from_explain(web):
    r = web.get("/why/ntf_arjun_0630", params={"scenario": "delhi-smog-night"})
    assert r.status_code == 200
    html = r.text
    assert "Why you got this" in html
    assert "Climbing since 1am" in html
    assert "Well above a normal Delhi morning" in html
    assert "Held overnight (quiet hours), sent at your 06:30 check-in" in html
    assert 'href="/?scenario=delhi-smog-night"' in html  # back link
    assert "SENT_CHECK_IN" in html.split("</main>")[1], "reason code belongs in the demo frame"


def test_why_view_for_helsinki_uses_local_baseline_and_sensitivity(web):
    html = web.get("/why/ntf_aino_0900", params={"scenario": "helsinki-smoke"}).text
    assert "Climbing since 3am" in html
    assert "6× a usual Helsinki morning (27 vs 4)" in html
    assert "Your high sensitivity lowers the bar" in html


def test_why_lines_are_three_or_four(web):
    for nid, sc in [("ntf_arjun_0630", "delhi-smog-night"), ("ntf_arjun_1700", "back-to-normal"), ("ntf_aino_0900", "helsinki-smoke")]:
        html = web.get(f"/why/{nid}", params={"scenario": sc}).text
        block = html.split('class="why-lines"')[1].split("</ul>")[0]
        assert 3 <= block.count("<li>") <= 4


def test_why_for_notification_outside_scenario_is_404(web):
    assert web.get("/why/ntf_arjun_0630", params={"scenario": "helsinki-smoke"}).status_code == 404


# WD-05: empty state reads like a calm watch face with a reason for the silence.
def test_empty_state_quiet_night(web):
    html = web.get("/", params={"scenario": "quiet-night"}).text
    assert "All clear in Bengaluru" in html
    assert "Your 06:30 check-in found nothing worth saying" in html
    assert not parse(html).cards


def test_empty_state_glitch_ignored(web):
    html = web.get("/", params={"scenario": "glitch-ignored"}).text
    assert "All clear in Mumbai" in html
    assert "A 1-hour sensor glitch was ignored" in html


# WD-06: chip links switch scenario.
def test_chip_links_switch_scenario(web):
    chips = parse(web.get("/").text).chips
    assert [c["href"] for c in chips] == [f"/?scenario={i}" for i in IDS]
    assert [c["active"] for c in chips] == [True] + [False] * (len(IDS) - 1)
    for chip in chips:
        page = parse(web.get(chip["href"]).text)
        active = [c["href"] for c in page.chips if c["active"]]
        assert active == [chip["href"]]
    assert "All clear in Mumbai" in web.get("/?scenario=glitch-ignored").text
    assert web.get("/?scenario=nope").status_code == 404


# WD-07: the HTTP client parses contract-shaped JSON and sends the agreed query params.
def test_http_client_parses_contract_json():
    feed = json.loads((FIXTURES / "feeds" / "arjun__demo-delhi-2026-10.json").read_text())
    users = json.loads((FIXTURES / "users.json").read_text())
    explain = json.loads((FIXTURES / "explain" / "ntf_arjun_0630.json").read_text())
    decisions = json.loads((FIXTURES / "decisions" / "rohan__demo-mumbai-2026-10.json").read_text())
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        routes = {
            "/users": users,
            "/users/arjun/feed": feed,
            "/notifications/ntf_arjun_0630/explain": explain,
            "/decisions": decisions,
        }
        return httpx.Response(200, json=routes[request.url.path])

    client = HttpAgentClient("http://core.test", transport=httpx.MockTransport(handler))
    until = datetime(2026, 10, 9, 11, 40, tzinfo=timezone.utc)

    assert {u.id for u in client.users()} >= {"arjun", "aino", "rohan", "meera"}
    items = client.feed("arjun", "demo-delhi-2026-10", until)
    assert items[0].kind == "cleared" and items[0].band == "usg" and items[0].event_kind == "climb"
    ex = client.explain("ntf_arjun_0630")
    assert ex.decision.reason_code == "SENT_CHECK_IN" and ex.layer("D8").reason_code == "HELD_RELEASED"
    ds = client.decisions("rohan", until, until, replay_run="demo-mumbai-2026-10")
    assert any(d.reason_code == "DQ_SUSPECT" for d in ds)

    feed_url = next(u for u in seen if u.path == "/users/arjun/feed")
    assert feed_url.params["replay_run"] == "demo-delhi-2026-10"
    assert feed_url.params["until"] == "2026-10-09T11:40:00Z"
    dec_url = next(u for u in seen if u.path == "/decisions")
    assert dec_url.params["user_id"] == "rohan" and "outcome" not in dec_url.params


def test_fixture_client_filters_feed_by_until():
    client = FixtureAgentClient(FIXTURES)
    before_clear = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
    assert [n.id for n in client.feed("arjun", "demo-delhi-2026-10", before_clear)] == ["ntf_arjun_0630"]


def test_unreachable_core_shows_calm_error():
    def down(request):
        raise httpx.ConnectError("refused")

    app = create_app(HttpAgentClient("http://core.test", transport=httpx.MockTransport(down)), SCENARIOS)
    r = TestClient(app).get("/")
    assert r.status_code == 200 and "Can't reach the agent" in r.text


# WD-08: a chart of the real readings sits beside the watch, outside it, with one mark per decision.
@pytest.mark.parametrize("scenario_id", IDS)
def test_chart_renders_beside_the_watch(web, scenario_id):
    html = web.get("/", params={"scenario": scenario_id}).text
    assert html.index('class="chart-panel"') < html.index('class="watch"'), "chart is demo frame, not product"
    pm = re.search(r'class="pm" d="([^"]*)"', html).group(1)
    assert pm.startswith("M") and pm.count("L") >= 8
    assert re.search(r'class="usual" d="M', html)
    assert html.count('class="mark mark-') >= 10


def test_delhi_chart_marks_the_story(web):
    html = web.get("/", params={"scenario": "delhi-smog-night"}).text
    assert html.count('class="mark mark-sent"') == 2
    assert html.count('class="mark mark-held"') == 1
    assert "QUIET_HOURS_HELD" in html and "SENT_CHECK_IN" in html


def test_glitch_chart_shows_the_ignored_reading(web):
    html = web.get("/", params={"scenario": "glitch-ignored"}).text
    assert "980 ignored" in html
    assert 'class="mark mark-ignored"' in html


# WD-09: clicking an hour moves the watch to that moment.
def test_scrub_to_held_hour_shows_quiet_hours(web):
    html = web.get("/", params={"scenario": "delhi-smog-night", "t": "2026-10-08T19:30:00Z"}).text
    assert not parse(html).cards
    assert "Quiet hours" in html and "Something is being held until morning" in html
    assert "QUIET_HOURS_HELD</code> at 1am" in html


def test_scrub_to_check_in_shows_only_that_message(web):
    html = web.get("/", params={"scenario": "delhi-smog-night", "t": "2026-10-09T01:00:00Z"}).text
    cards = parse(html).cards
    assert [c["href"] for c in cards] == ["/why/ntf_arjun_0630?scenario=delhi-smog-night&t=2026-10-09T01%3A00%3A00Z"]
    assert ">now<" in html and ">06:30<" in html


def test_before_the_episode_watch_is_all_clear(web):
    html = web.get("/", params={"scenario": "delhi-smog-night", "t": "2026-10-08T14:30:00Z"}).text
    assert "All clear in Delhi" in html


def test_chart_hour_links_work(web):
    html = web.get("/", params={"scenario": "helsinki-smoke"}).text
    hrefs = set(re.findall(r'<a href="(/\?scenario=helsinki-smoke[^"]*)"', html))
    assert len(hrefs) >= 20
    for href in sorted(hrefs)[:5]:
        assert web.get(href.replace("&amp;", "&")).status_code == 200


def test_why_keeps_the_moment(web):
    html = web.get("/why/ntf_arjun_0630", params={"scenario": "delhi-smog-night", "t": "2026-10-09T02:00:00Z"}).text
    assert 'href="/?scenario=delhi-smog-night&amp;t=2026-10-09T02%3A00%3A00Z"' in html
    assert "1h ago" in html


def test_bad_or_out_of_range_time(web):
    assert web.get("/", params={"scenario": "quiet-night", "t": "yesterday"}).status_code == 400
    late = web.get("/", params={"scenario": "quiet-night", "t": "2030-01-01T00:00:00Z"}).text
    assert "07:10" in late  # clamped to the scenario's `until`


def test_http_client_reads_readings():
    rows = json.loads((FIXTURES / "readings" / "4712609.json").read_text())
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=rows)

    client = HttpAgentClient("http://core.test", transport=httpx.MockTransport(handler))
    start, end = datetime(2026, 10, 8, 11, 40, tzinfo=timezone.utc), datetime(2026, 10, 9, 11, 40, tzinfo=timezone.utc)
    got = client.readings(4712609, start, end)
    assert len(got) == len(rows) and got[0].typical_pm25 is not None
    assert seen[0].path == "/stations/4712609/readings"
    assert seen[0].params["start"] == "2026-10-08T11:40:00Z" and seen[0].params["end"] == "2026-10-09T11:40:00Z"


def test_why_view_focuses_the_chart_on_that_notice(web):
    html = web.get("/why/ntf_arjun_0630", params={"scenario": "delhi-smog-night"}).text
    assert html.count('class="focus-ring"') == 1
    assert "SENT_CHECK_IN</code> at 6:30am" in html
