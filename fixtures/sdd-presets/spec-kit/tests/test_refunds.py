from app.payments import refund


def test_refunds_fr_002_records_the_agent():
    # The test name names the feature (refunds), so FR-002 resolves to 002-refunds:FR-002.
    assert refund("o1", 500, 300, "ana") == 300
