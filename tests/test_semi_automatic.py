"""Semi-automatic mode without a browser: sites per person, questions of the label, the 10-s timer,
blind output in a crosscheck."""
import pytest

import semi_automatic


def answers(monkeypatch, values):
    values = list(values)
    monkeypatch.setattr(semi_automatic, "ask", lambda prompt: values.pop(0))
    return values


def test_sites_of_the_person_from_site_assignment(tmp_path):
    path = tmp_path / "site_assignment.csv"
    path.write_text("rank,domain,url,cmp_id,first_operator\n1,a.de,https://www.a.de,6,ae\n2,b.de,https://www.b.de,6,xy\n")
    assert [s["domain"] for s in semi_automatic.read_sites(path, "ae", "primary")] == ["a.de"]
    assert [s["domain"] for s in semi_automatic.read_sites(path, "xy", "primary")] == ["b.de"]


def test_crosscheck_needs_the_examination_it_checks(tmp_path):
    path = tmp_path / "crosscheck.csv"
    path.write_text("domain,examination_id\na.de,abc\nb.de,\n")
    with pytest.raises(SystemExit, match="examination_id"):
        semi_automatic.read_sites(path, "xy", "crosscheck")


def test_label_after_rejecting_on_the_second_layer(monkeypatch):
    answers(monkeypatch, ["2", "n", "j", "j", "?", "Auswahl speichern", "Schalter einzeln"])
    assert semi_automatic.ask_label("r", searched=False) == {
        "outcome": "rejected", "privacy_policy_searched": False, "reject_level": 2, "cookiewall_seen": False,
        "settings_layer_available": True, "purposes_preselected": True, "vendors_preselected": None,
        "closed_with": "Auswahl speichern", "note": "Schalter einzeln"}


def test_label_cookiewall_without_free_rejection(monkeypatch):
    # code w: no free way to reject; the pay option is not asked again, it is set
    answers(monkeypatch, ["n", "Akzeptieren", ""])
    assert semi_automatic.ask_label("w", searched=False) == {
        "outcome": "w", "privacy_policy_searched": False, "cookiewall_seen": True,
        "settings_layer_available": False, "closed_with": "Akzeptieren", "note": None}


def test_label_cookiewall_with_free_rejection_on_the_second_layer(monkeypatch):
    # pay option and a free way to reject on the 2nd layer: code r with layer 2 (Matte, Appendix D),
    # and the site is marked as cookiewall as well
    answers(monkeypatch, ["2", "j", "j", "n", "n", "Auswahl speichern", ""])
    label = semi_automatic.ask_label("r", searched=False)
    assert (label["outcome"], label["reject_level"], label["cookiewall_seen"]) == ("rejected", 2, True)


def test_wrong_input_is_asked_again(monkeypatch):
    left = answers(monkeypatch, ["q", "R"])
    assert semi_automatic.ask_choice("Code", semi_automatic.CODE_TEXT) == "r"
    assert left == []


def test_timer_marks_the_search_in_the_privacy_policy(monkeypatch):
    shown = []
    monkeypatch.setattr(semi_automatic, "countdown", lambda seconds: shown.append(seconds))
    answers(monkeypatch, ["t", ""])
    assert semi_automatic.wait_for_person("Ablehnen") is True
    assert shown == [10]
    answers(monkeypatch, [""])
    assert semi_automatic.wait_for_person("Ablehnen") is False


def test_blind_output_only_after_the_label(capsys):
    output = semi_automatic.Output(blind=True)
    output.show("vorher: Zwecke {}")
    assert capsys.readouterr().out == ""
    output.release()
    assert "vorher: Zwecke {}" in capsys.readouterr().out
    output.show("nach Akzeptieren")
    assert "nach Akzeptieren" in capsys.readouterr().out
