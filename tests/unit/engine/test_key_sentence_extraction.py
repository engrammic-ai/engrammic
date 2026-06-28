from context_service.engine.key_sentence_extraction import extract_key_sentences, score_sentence


def test_short_content_unchanged():
    content = "This is short."
    assert extract_key_sentences(content) == content


def test_long_content_extracted():
    content = "First sentence. " + "Filler sentence. " * 50 + "Key finding: the API uses OAuth2."
    result = extract_key_sentences(content, budget=200)
    assert len(result) <= 200
    assert "First" in result or "Key finding" in result


def test_score_sentence_cue_phrases():
    assert score_sentence("Found the bug in auth.", 0.5) > score_sentence("Nothing here.", 0.5)


def test_score_sentence_code_specificity():
    assert score_sentence("Check `config.py` for settings.", 0.5) > score_sentence(
        "Check the config.", 0.5
    )
