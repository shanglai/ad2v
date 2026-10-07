from app.reportes import descargar_reporte, exportar


def test_hu_001_exporta_las_parejas():
    assert exportar({}).startswith("pareja")


def test_us_001_devuelve_un_pdf():
    assert descargar_reporte({}).startswith(b"%PDF")
