import pytest

from findie_ai.ranking import location_tokens, normalize_text, rank_candidates


def candidate(item_id, description):
    return {
        "item_id": item_id, "document_version": 2, "source_id": item_id,
        "source_version": 1, "source_sha256": "a" * 64,
        "location_tokens": location_tokens(description),
    }


def test_vietnamese_accents_and_room_punctuation():
    assert normalize_text("Đại học Sài Gòn; phòng E.205") == "dai hoc sai gon phong e205"
    assert location_tokens("phòng học E.205") == location_tokens("phong E205") == location_tokens("E 205")
    assert location_tokens("Nhặt tại sảnh hội trường A") == location_tokens("sanh hoi truong a") == ["hall:a"]
    assert location_tokens("phòng 205") == ["room:205"]
    assert normalize_text("Ví đen 2 ngăn") == "vi den 2 ngan"
    assert location_tokens("Ví đen 2 ngăn") == []


def test_exact_room_wins_over_similar_embedding_without_losing_source_identity():
    wrong = candidate("wrong", "Ví đen nhặt tại phòng E.206")
    correct = candidate("correct", "Ví đen nhặt tại phòng E.205")
    result = rank_candidates([wrong, correct], [correct, wrong], [correct], location_tokens("vi den E205"))
    assert [row["itemId"] for row in result] == ["correct", "wrong"]
    assert result[0] == {
        "itemId": "correct", "documentVersion": 2, "sourceId": "correct",
        "sourceKind": "text",
        "sourceVersion": 1, "sourceSha256": "a" * 64,
    }


def test_hall_accents_and_candidate_deduplication():
    wrong = candidate("wrong", "Sảnh hội trường B")
    correct = candidate("correct", "Sảnh hội trường A")
    result = rank_candidates([wrong, correct], [correct, wrong], [correct], location_tokens("sanh hoi truong A"), limit=1)
    assert [row["itemId"] for row in result] == ["correct"]


def test_matching_room_does_not_override_agreement_on_the_object():
    wallet = candidate("wallet", "Ví màu đen ở phòng E.206")
    laptop = candidate("laptop", "Máy tính xách tay ở phòng E.205")
    result = rank_candidates([wallet, laptop], [wallet, laptop], [laptop], location_tokens("ví màu đen E205"))
    assert result[0]["itemId"] == "wallet"


def test_rrf_rewards_agreement_and_favors_semantic_on_disagreement():
    keyword_only, semantic_only, shared = [candidate(name, "") for name in ("a", "b", "c")]
    result = rank_candidates([semantic_only, shared], [keyword_only, shared], [], [])
    assert [row["itemId"] for row in result] == ["c", "b", "a"]


@pytest.mark.parametrize(("semantic_weight", "expected"), [(0.3, ["keyword", "semantic"]),
                                                         (0.7, ["semantic", "keyword"])])
def test_rrf_configured_weight_reverses_preference_when_the_channels_disagree(semantic_weight, expected):
    semantic, keyword = [candidate(name, "") for name in ("semantic", "keyword")]
    result = rank_candidates([semantic, keyword], [keyword, semantic], [], [], semantic_weight=semantic_weight)
    assert [row["itemId"] for row in result] == expected


@pytest.mark.parametrize(("semantic_weight", "expected"), [(0, ["keyword", "shared"]),
                                                         (1, ["semantic", "shared"])])
def test_zero_weight_channel_does_not_contribute_candidates_or_replace_source(semantic_weight, expected):
    semantic, keyword, shared = [candidate(name, "") for name in ("semantic", "keyword", "shared")]
    semantic_shared = shared | {"source_id": "semantic-source"}
    keyword_shared = shared | {"source_id": "keyword-source"}
    result = rank_candidates([semantic, semantic_shared], [keyword, keyword_shared], [], [],
                             semantic_weight=semantic_weight)
    assert [row["itemId"] for row in result] == expected
    assert result[1]["sourceId"] == ("semantic-source" if semantic_weight == 1 else "keyword-source")
