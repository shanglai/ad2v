from recon_api.classify import classify_unmatched
from recon_api.routes import start_run


def test_req_001_start_run_returns_run_result():
    assert callable(start_run)


def test_req_004_unmatched_rows_get_a_label():
    assert classify_unmatched([]) == []
