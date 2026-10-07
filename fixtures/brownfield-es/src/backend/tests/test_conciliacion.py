from app.conciliacion import emparejar, exportar_csv


def test_rf_002_empareja_por_referencia():
    assert emparejar({"referencia": "x"}) == "conciliado"


def test_rf_003_sin_referencia_queda_pendiente():
    assert emparejar({}) == "pendiente"


def test_exporta_encabezado():
    assert exportar_csv("c1").startswith("movimiento")
