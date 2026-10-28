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


def test_rrf_rewards_agreement_and_ties_are_deterministic():
    first, second, shared = [candidate(name, "") for name in ("a", "b", "c")]
    result = rank_candidates([first, shared], [second, shared], [], [])
    assert [row["itemId"] for row in result] == ["c", "a", "b"]
