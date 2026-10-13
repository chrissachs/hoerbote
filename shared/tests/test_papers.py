"""The paper config: the committed file, the local one on top, and the
default issue date."""

import datetime

import pytest
from pydantic import ValidationError

from papers import Paper, load_papers

PAPER = """
[paper]
title = "Paper"
provider = "url"
years_back = 100
editions = { daily = "" }
params = { pdf_url = "https://example.org/{date:%Y%m%d}.pdf" }
"""


def test_local_papers_are_added_and_win(tmp_path):
    (tmp_path / "papers.toml").write_text(PAPER)
    (tmp_path / "papers_local.toml").write_text(PAPER.replace("[paper]", "[local]") + 'speech_style = "leise"\n')
    assert load_papers(tmp_path).keys() == {"paper", "local"}
    assert load_papers(tmp_path)["local"].speech_style == "leise"
    (tmp_path / "papers_local.toml").write_text(PAPER.replace("years_back = 100", "years_back = 0"))
    assert load_papers(tmp_path)["paper"].years_back == 0


def test_a_typo_is_an_error(tmp_path):
    (tmp_path / "papers.toml").write_text(PAPER + 'speech_stlye = "leise"\n')
    with pytest.raises(ValidationError):
        load_papers(tmp_path)


def test_the_repos_config_loads():
    assert "berliner-tageblatt" in load_papers()


def test_default_date():
    paper = load_papers()["berliner-tageblatt"]
    assert isinstance(paper, Paper)
    assert paper.default_date(datetime.date(2026, 10, 8)) == datetime.date(1926, 10, 8)
    assert paper.default_date(datetime.date(2028, 2, 29)) == datetime.date(1928, 2, 29)
    leap_less = paper.model_copy(update={"years_back": 101})
    assert leap_less.default_date(datetime.date(2028, 2, 29)) == datetime.date(1927, 2, 28)
