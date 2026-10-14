import json

from provenance import cli


def test_commit_writes_receipt_and_tampered_text_fails_verification(tmp_path, monkeypatch, capsys):
    prompt = tmp_path / "prompt.txt"
    output = tmp_path / "output.txt"
    receipt = tmp_path / "receipt.json"
    prompt.write_text("Name a moon.", encoding="utf-8")
    output.write_text("Europa", encoding="utf-8")

    monkeypatch.setattr(cli, "new_salt", lambda: bytes(range(32)))
    monkeypatch.setattr(cli, "_json_cast", lambda arguments: {"transactionHash": "0xabc"})
    assert cli.main([
        "commit", str(prompt), str(output), "example/model", "--registry", "0x0000000000000000000000000000000000000001",
        "--receipt", str(receipt), "--private-key", "0x01", "--created-at", "2026-10-14T00:00:00Z",
    ]) == 0

    contents = json.loads(receipt.read_text(encoding="utf-8"))
    assert contents["tx_hash"] == "0xabc"
    contents["record"]["output"] = "Europb"
    receipt.write_text(json.dumps(contents), encoding="utf-8")
    assert cli.main(["verify", str(receipt)]) == 1
    assert "do not open" in capsys.readouterr().err
