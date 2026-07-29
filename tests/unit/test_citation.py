from ai.citation import verify_citations


def test_single_cited_claim_is_valid() -> None:
    result = verify_citations("Product X lists acetaminophen as active. [1]", evidence_count=2)
    assert result.valid
    assert result.cited_numbers == frozenset({1})
    assert result.reason is None


def test_multiple_lines_each_cited_is_valid() -> None:
    answer = "Product X lists acetaminophen as active. [1]\nNo recall found for this product. [2]"
    result = verify_citations(answer, evidence_count=2)
    assert result.valid
    assert result.cited_numbers == frozenset({1, 2})


def test_multi_number_citation_group_is_valid() -> None:
    result = verify_citations("Two sources agree on this. [1, 2]", evidence_count=2)
    assert result.valid
    assert result.cited_numbers == frozenset({1, 2})


def test_uncited_line_is_invalid() -> None:
    result = verify_citations("Product X lists acetaminophen as active.", evidence_count=2)
    assert not result.valid
    assert result.reason is not None
    assert "uncited" in result.reason


def test_one_uncited_line_among_cited_lines_invalidates_whole_answer() -> None:
    answer = "Product X lists acetaminophen as active. [1]\nThis is definitely true."
    result = verify_citations(answer, evidence_count=2)
    assert not result.valid


def test_citation_number_out_of_range_is_invalid() -> None:
    result = verify_citations("Product X lists acetaminophen as active. [5]", evidence_count=2)
    assert not result.valid
    assert result.reason is not None
    assert "out of range" in result.reason


def test_citation_number_zero_is_invalid() -> None:
    result = verify_citations("Some claim. [0]", evidence_count=2)
    assert not result.valid


def test_empty_answer_is_invalid() -> None:
    result = verify_citations("", evidence_count=2)
    assert not result.valid
    assert result.reason == "empty answer"


def test_whitespace_only_answer_is_invalid() -> None:
    result = verify_citations("   \n  \n", evidence_count=2)
    assert not result.valid


def test_blank_lines_between_claims_are_ignored_not_treated_as_uncited() -> None:
    answer = "Claim one. [1]\n\nClaim two. [2]"
    result = verify_citations(answer, evidence_count=2)
    assert result.valid
    assert result.cited_numbers == frozenset({1, 2})


def test_zero_evidence_count_means_any_citation_is_out_of_range() -> None:
    result = verify_citations("Some claim. [1]", evidence_count=0)
    assert not result.valid
