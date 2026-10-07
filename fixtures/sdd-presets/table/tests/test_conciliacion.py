from app.conciliacion import exportar_csv, iniciar_conciliacion


def test_rf_001_inicia_una_corrida():
    assert iniciar_conciliacion([{}])["movimientos"] == 1


def test_exp_1_escribe_un_csv():
    assert exportar_csv({}).startswith("id")
