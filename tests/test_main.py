import json

from src.main import main


def test_cli_json_output(capsys):
    exit_code = main(["--json"])

    output = capsys.readouterr().out
    data = json.loads(output)

    assert exit_code == 0
    assert data["summary"]["facilities_analyzed"] == 12
    assert data["governance"]["human_review_required"] is True


def test_cli_human_readable_output(capsys):
    exit_code = main([])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "INVENTORY RISK ANALYSIS" in output
    assert "DECISION SUPPORT SUMMARY" in output
    assert "Governance:" in output
