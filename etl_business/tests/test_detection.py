from shop_data_extractor.access import detect_table

def test_exact_normalized():
    assert detect_table(["tblProduct", "Customers"], ["customers"]) == "Customers"

def test_substring_fallback():
    assert detect_table(["tbl_ProductMaster"], ["product"]) == "tbl_ProductMaster"
