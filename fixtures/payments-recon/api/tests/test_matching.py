from recon_api.matching import amounts_match


def test_req_003_amounts_within_one_cent_match():
    assert amounts_match(1000, 1001)
    assert not amounts_match(1000, 1002)
