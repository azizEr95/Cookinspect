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


def test_banner_questions_and_code_r_on_the_second_layer(monkeypatch):
    # asked while the banner is visible: 2nd layer, V3, pay option, way to reject; then Enter = proposal
    left = answers(monkeypatch, ["j", "j", "?", "n", "2", ""])
    code, label = semi_automatic.choose_code(semi_automatic.ask_banner())
    assert left == []
    assert code == "r"
    assert label == {"outcome": "rejected", "settings_layer_available": True, "purposes_preselected": True,
                     "vendors_preselected": None, "cookiewall_seen": False, "reject_level": 2,
                     "privacy_policy_searched": False}


def test_cookiewall_without_free_rejection_is_proposed_as_w(monkeypatch):
    answers(monkeypatch, ["n", "j", "n", ""])
    code, label = semi_automatic.choose_code(semi_automatic.ask_banner())
    assert code == "w"
    assert label == {"outcome": "w", "settings_layer_available": False, "cookiewall_seen": True,
                     "reject_level": None, "privacy_policy_searched": False}


def test_cookiewall_with_free_rejection_is_r_and_marked(monkeypatch):
    # pay option and a free way to reject on the 2nd layer: code r with layer 2 (Matte, Appendix D),
    # and the site is marked as cookiewall as well
    answers(monkeypatch, ["j", "n", "n", "j", "2", ""])
    code, label = semi_automatic.choose_code(semi_automatic.ask_banner())
    assert (code, label["outcome"], label["reject_level"], label["cookiewall_seen"]) == ("r", "rejected", 2, True)


def test_no_way_to_reject_is_proposed_as_n(monkeypatch):
    answers(monkeypatch, ["?", "n", "n", ""])
    code, label = semi_automatic.choose_code(semi_automatic.ask_banner())
    assert (code, label["settings_layer_available"], label["reject_level"]) == ("n", None, None)


def test_person_overrides_the_proposal(monkeypatch):
    # proposal n, the person enters x (banner broken)
    answers(monkeypatch, ["n", "n", "n", "x"])
    assert semi_automatic.choose_code(semi_automatic.ask_banner())[0] == "x"
    # proposal n, the person enters r: the layer is asked
    answers(monkeypatch, ["n", "n", "n", "r", "1"])
    code, label = semi_automatic.choose_code(semi_automatic.ask_banner())
    assert (code, label["reject_level"]) == ("r", 1)
    # proposal r, the person enters w: no layer, pay option set
    answers(monkeypatch, ["n", "n", "1", "w"])
    code, label = semi_automatic.choose_code(semi_automatic.ask_banner())
    assert (code, label["reject_level"], label["cookiewall_seen"]) == ("w", None, True)


def test_timer_in_the_question_about_rejecting(monkeypatch):
    shown = []
    monkeypatch.setattr(semi_automatic, "countdown", lambda seconds: shown.append(seconds))
    answers(monkeypatch, ["t", "n"])
    assert semi_automatic.ask_reject_way() == (None, True)
    assert shown == [10]


def test_closing_questions(monkeypatch):
    answers(monkeypatch, ["Alle ablehnen", ""])
    assert semi_automatic.ask_closing("r") == {"closed_with": "Alle ablehnen", "note": None}
    answers(monkeypatch, ["lädt nicht"])
    assert semi_automatic.ask_closing("x") == {"note": "lädt nicht"}


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
