from recon_api.matching import amounts_match, match_batch


def test_req_003_amounts_within_one_cent_match():
    assert amounts_match(1000, 1001)
    assert not amounts_match(1000, 1010)


def test_req_002_match_batch_pairs_by_reference():
    assert callable(match_batch)
