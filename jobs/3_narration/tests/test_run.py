"""run.py end to end with a fake Gemini client: the article and page steps via the
Batch API, the synchronous fallback for a failed batch item, the article-step
cache (hits, fingerprint misses), dropped non-articles and empty pages.

The fake "model" answers from the request itself: the article step echoes the likely
headline (an empty summary for anything containing ANZEIGE, i.e. "not a
real article"), the page step writes one sentence per article it's given."""

import datetime
import json
import re
from types import SimpleNamespace

import pytest
from google import genai

import run
from models import Article, BBox, PageReport
from narration import PageSummary
from source_info import Rights, SourceInfo

RUN_ID = "paper-morning-1926-10-08"


class FakeGemini:
    """Stands in for genai.Client(): records every request, answers from
    `answer`. `fail_in_batch`: substrings of user content whose batch item
    comes back as an error (forcing the synchronous fallback)."""

    def __init__(self) -> None:
        self.batch_requests: list[list[dict]] = []
        self.sync_requests: list[str] = []
        self.fail_in_batch: set[str] = set()
        self._jobs: dict[str, list[dict]] = {}
        self.batches = SimpleNamespace(create=self._create, get=self._get)
        self.models = SimpleNamespace(generate_content=self._generate)

    def __call__(self):  # genai.Client() returns this same instance
        return self

    @staticmethod
    def answer(system: str, user: str) -> str:
        if user.startswith("Likely headline:"):
            headline = user.split("\n", 1)[0].removeprefix("Likely headline: ")
            summary = "" if "ANZEIGE" in user else f"Summary of {headline}."
            return json.dumps({"headline": headline, "summary": summary, "category": "local_news"})
        idxs = [int(i) for i in re.findall(r"\[article_idx=(\d+)", user)]
        tone = "brief" if "brief and dense" in system else "other"
        return json.dumps({"sentences": [{"sentence": f"{tone} sentence on {i}.", "article_idx": i} for i in idxs]})

    def _create(self, model, src, config):
        name = f"batches/job{len(self._jobs)}"
        self._jobs[name] = src
        self.batch_requests.append(src)
        return SimpleNamespace(name=name)

    def _get(self, name):
        def item(request):
            user = request["contents"][0]["parts"][0]["text"]
            if any(s in user for s in self.fail_in_batch):
                return SimpleNamespace(error="INTERNAL", response=None)
            text = self.answer(request["config"]["system_instruction"], user)
            return SimpleNamespace(error=None, response=SimpleNamespace(text=text))

        responses = [item(r) for r in self._jobs[name]]
        return SimpleNamespace(
            state=SimpleNamespace(name="JOB_STATE_SUCCEEDED"),
            error=None,
            dest=SimpleNamespace(inlined_responses=responses),
        )

    def _generate(self, model, contents, config):
        self.sync_requests.append(contents)
        return SimpleNamespace(text=self.answer(config["system_instruction"], contents))


def _article(idx: int, headline: str, text: str) -> Article:
    return Article(
        article_idx=idx, headline_guess=headline, text=text, bbox_union=BBox(x0=0, y0=0, x1=1, y1=1), columns=[0]
    )


PAGES = [
    PageReport(
        page=1,
        images=[],
        articles=[
            _article(0, "Neue Brücke", "Der Rat beschließt den Bau."),
            _article(1, "Kleinanzeige", "ANZEIGE Zimmer zu vermieten."),
            _article(2, "Konzert im Park", "Am Sonntag spielt die Kapelle."),
        ],
    ),
    PageReport(page=2, images=[], articles=[_article(0, "Anzeigen", "ANZEIGE Pelze billig.")]),
]


@pytest.fixture
def gemini(tmp_path, monkeypatch) -> FakeGemini:
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("NARRATION_TONE", raising=False)
    fake = FakeGemini()
    monkeypatch.setattr(genai, "Client", fake)
    return fake


def _write_run(tmp_path, pages=PAGES, **paper) -> None:
    rd = tmp_path / "issues" / RUN_ID
    (rd / "02_articles").mkdir(parents=True, exist_ok=True)
    (rd / "02_articles" / "report.json").write_text(json.dumps([p.model_dump(mode="json") for p in pages]))
    info = SourceInfo(
        paper="paper",
        paper_title="Paper",
        edition="morning",
        date=datetime.date(1926, 10, 8),
        provider="ddb",
        provider_item_id="ITEM",
        landing_url=None,
        text_source="alto",
        rights=Rights(statement_url=None, label=None, holder=None, open=True),
        attribution="",
        pages=[],
        **paper,
    )
    (rd / "00_source.json").write_text(info.model_dump_json())


def _narration(tmp_path, page: int) -> PageSummary:
    path = tmp_path / "issues" / RUN_ID / "03_rewritten" / f"page{page}.narration.json"
    return PageSummary.model_validate_json(path.read_text())


def test_issue_narrated_and_non_articles_dropped(tmp_path, gemini):
    _write_run(tmp_path)
    run.run(RUN_ID)

    # One article-step batch over all four articles, one page-step batch for page 1 only.
    assert [len(r) for r in gemini.batch_requests] == [4, 1]
    page1 = _narration(tmp_path, 1)
    assert [(a.article_idx, a.headline) for a in page1.articles] == [(0, "Neue Brücke"), (2, "Konzert im Park")]
    assert [s.sentence for s in page1.sentences] == ["other sentence on 0.", "other sentence on 2."]
    assert page1.tone == "colloquial"
    assert not (tmp_path / "issues" / RUN_ID / "03_rewritten" / "page2.narration.json").exists()
    status = json.loads((tmp_path / "issues" / RUN_ID / "status.json").read_text())
    assert status["status"] == "succeeded"


def test_rerun_uses_the_cache_and_misses_only_changed_articles(tmp_path, gemini):
    _write_run(tmp_path)
    run.run(RUN_ID)
    gemini.batch_requests.clear()

    run.run(RUN_ID)
    assert [len(r) for r in gemini.batch_requests] == [1]  # the page step only

    gemini.batch_requests.clear()
    changed = PAGES[0].model_copy(deep=True)
    changed.articles[2] = _article(2, "Konzert fällt aus", "Regen.")
    _write_run(tmp_path, [changed, PAGES[1]])
    run.run(RUN_ID)
    c1c2 = gemini.batch_requests[0]
    assert [r["contents"][0]["parts"][0]["text"].split("\n")[0] for r in c1c2] == ["Likely headline: Konzert fällt aus"]
    assert [a.headline for a in _narration(tmp_path, 1).articles] == ["Neue Brücke", "Konzert fällt aus"]


def test_failed_batch_item_falls_back_to_a_synchronous_call(tmp_path, gemini):
    gemini.fail_in_batch = {"Am Sonntag spielt"}  # that article's article step only
    _write_run(tmp_path)
    run.run(RUN_ID)
    assert len(gemini.sync_requests) == 1 and "Am Sonntag spielt" in gemini.sync_requests[0]
    assert [a.headline for a in _narration(tmp_path, 1).articles] == ["Neue Brücke", "Konzert im Park"]


def test_page_that_lost_its_articles_loses_its_old_narration(tmp_path, gemini):
    _write_run(tmp_path)
    run.run(RUN_ID)
    ads_only = PageReport(page=1, images=[], articles=[_article(0, "Anzeigen", "ANZEIGE")])
    _write_run(tmp_path, [ads_only, PAGES[1]])
    run.run(RUN_ID)
    assert not list((tmp_path / "issues" / RUN_ID / "03_rewritten").glob("*.narration.json"))


def test_paper_tone_and_tone_prompt_reach_c3(tmp_path, gemini, monkeypatch):
    _write_run(tmp_path, narration_tone="brief", tone_prompt="Ab und zu ein Berliner Wort.")
    run.run(RUN_ID)
    page1 = _narration(tmp_path, 1)
    assert page1.tone == "brief"
    assert page1.sentences[0].sentence == "brief sentence on 0."
    c3_prompt = gemini.batch_requests[-1][0]["config"]["system_instruction"]
    assert c3_prompt.endswith("Ab und zu ein Berliner Wort.")

    monkeypatch.setenv("NARRATION_TONE", "formal")
    run.run(RUN_ID)
    assert _narration(tmp_path, 1).tone == "formal"


def test_interrupted_run_resumes_the_same_batch_job(tmp_path, gemini, monkeypatch):
    _write_run(tmp_path)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt  # e.g. Ctrl-C while polling

    real_get = gemini.batches.get
    monkeypatch.setattr(gemini.batches, "get", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run.run(RUN_ID)
    assert len(gemini.batch_requests) == 1

    monkeypatch.setattr(gemini.batches, "get", real_get)
    run.run(RUN_ID)
    # The article-step job was resumed, not resubmitted; only the page step was new.
    assert len(gemini.batch_requests) == 2
