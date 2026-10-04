from app.export import export_orders


def test_orderexport_1_header_only_when_empty():
    # A test name refers to the requirement level (ORDEREXPORT-1); criteria are linked by annotations.
    assert export_orders([]).strip() == "order,amount_cents"
