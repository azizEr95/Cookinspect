from run_list import read_domains


def test_csv_with_domain_column(tmp_path):
    path = tmp_path / "list.csv"
    path.write_text("rank,domain\n1,google.de\n2,amazon.de\n")
    assert read_domains(path) == ["google.de", "amazon.de"]


def test_plain_list(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("# comment\ngoogle.de\n\namazon.de\n")
    assert read_domains(path) == ["google.de", "amazon.de"]
