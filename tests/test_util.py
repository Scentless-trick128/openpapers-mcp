"""Unit tests for helpers (offline)."""

from openpapers.services.util import (
    join_names,
    normalize_doi,
    reconstruct_abstract,
)


def test_normalize_doi_bare():
    assert normalize_doi("10.1038/nature12373") == "10.1038/nature12373"


def test_normalize_doi_url():
    assert normalize_doi("https://doi.org/10.1038/nature12373") == "10.1038/nature12373"


def test_normalize_doi_dx_url():
    assert normalize_doi("http://dx.doi.org/10.1038/nature12373") == "10.1038/nature12373"


def test_normalize_doi_prefix():
    assert normalize_doi("doi:10.1038/nature12373") == "10.1038/nature12373"


def test_normalize_doi_trailing_punct():
    assert normalize_doi("10.1109/iccv48922.2021.00986.,);]") == "10.1109/iccv48922.2021.00986"


def test_normalize_doi_embedded_in_text():
    assert (
        normalize_doi("see https://doi.org/10.1038/nature12373 for details")
        == "10.1038/nature12373"
    )


def test_normalize_doi_invalid():
    assert normalize_doi("") is None
    assert normalize_doi(None) is None
    assert normalize_doi("not a doi") is None


def test_reconstruct_abstract_basic():
    idx = {"Hello": [0], "world": [1]}
    assert reconstruct_abstract(idx) == "Hello world"


def test_reconstruct_abstract_reorders():
    idx = {"second": [1], "first": [0], "third": [2]}
    assert reconstruct_abstract(idx) == "first second third"


def test_reconstruct_abstract_repeated_words():
    idx = {"the": [0, 3], "cat": [1], "sat": [2], "mat": [4]}
    assert reconstruct_abstract(idx) == "the cat sat the mat"


def test_reconstruct_abstract_none():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_join_names_extracts_display_name():
    authorships = [
        {"author": {"display_name": "Alice Smith"}},
        {"author": {"display_name": "Bob Jones"}, "raw_author_name": "B. Jones"},
    ]
    assert join_names(authorships) == ["Alice Smith", "Bob Jones"]


def test_join_names_handles_empty():
    assert join_names([]) == []
    assert join_names(None) == []
