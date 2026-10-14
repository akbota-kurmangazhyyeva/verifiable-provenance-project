"""Command-line tools for committing and checking provenance records."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .commitment import commit, model_id, new_salt, verify_opening
from .record import GenerationRecord


def _hex(value: bytes) -> str:
    return "0x" + value.hex()


def _run_cast(arguments: list[str]) -> str:
    completed = subprocess.run(["cast", *arguments], check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _json_cast(arguments: list[str]) -> object:
    return json.loads(_run_cast([*arguments, "--json"]))


def _transaction_hash(result: object) -> str:
    if isinstance(result, dict):
        for key in ("transactionHash", "transaction_hash", "hash"):
            if key in result:
                return result[key]
    raise ValueError("cast did not return a transaction hash")


def _record_from_receipt(receipt: dict) -> GenerationRecord:
    return GenerationRecord.from_json(json.dumps(receipt["record"], separators=(",", ":"), ensure_ascii=False))


def commit_command(args: argparse.Namespace) -> int:
    prompt = Path(args.prompt_file).read_bytes().decode("utf-8")
    output = Path(args.output_file).read_bytes().decode("utf-8")
    record = GenerationRecord(
        model=args.model,
        prompt=prompt,
        output=output,
        params=json.loads(args.params),
        created_at=args.created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    salt = new_salt()
    commitment = commit(record, salt)
    result = _json_cast([
        "send", args.registry, "commit(bytes32,bytes32)", _hex(commitment), _hex(model_id(args.model)),
        "--rpc-url", args.rpc_url, "--private-key", args.private_key,
    ])
    receipt = {
        "record": json.loads(record.to_json()),
        "salt": _hex(salt),
        "commitment": _hex(commitment),
        "tx_hash": _transaction_hash(result),
        "registry": args.registry,
        "rpc_url": args.rpc_url,
    }
    Path(args.receipt).write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(receipt["tx_hash"])
    return 0


def _is_committed(registry: str, commitment: str, rpc_url: str) -> bool:
    value = _run_cast([
        "call", registry, "isCommitted(bytes32)", commitment, "--rpc-url", rpc_url,
    ])
    # cast represents a Boolean return as an ABI word, for example 0x...01.
    return int(value, 16) == 1


def _get_record(registry: str, commitment: str, rpc_url: str) -> tuple[int, int, int, int]:
    encoded = _run_cast([
        "call", registry, "getRecord(bytes32)", commitment, "--rpc-url", rpc_url,
    ]).removeprefix("0x")
    if len(encoded) != 256:
        raise ValueError("registry returned an invalid record")
    return tuple(int(encoded[index:index + 64], 16) for index in range(0, 256, 64))


def verify_command(args: argparse.Namespace) -> int:
    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    record = _record_from_receipt(receipt)
    salt = bytes.fromhex(receipt["salt"].removeprefix("0x"))
    claimed = bytes.fromhex(receipt["commitment"].removeprefix("0x"))
    if not verify_opening(record, salt, claimed):
        print("Verification failed: the receipt record and salt do not open its commitment.", file=sys.stderr)
        return 1

    registry = args.registry or receipt["registry"]
    rpc_url = args.rpc_url or receipt.get("rpc_url", "http://127.0.0.1:8545")
    if not _is_committed(registry, receipt["commitment"], rpc_url):
        print("Verification failed: this commitment is not recorded by the registry.", file=sys.stderr)
        return 1
    _, timestamp, block_number, _ = _get_record(registry, receipt["commitment"], rpc_url)
    print(f"Proven: this exact text existed no later than block {block_number} (timestamp {timestamp}).")
    print("Not proven: which model wrote it.")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Commit and verify provenance records.")
    commands = result.add_subparsers(dest="command", required=True)

    commit_parser = commands.add_parser("commit")
    commit_parser.add_argument("prompt_file")
    commit_parser.add_argument("output_file")
    commit_parser.add_argument("model")
    commit_parser.add_argument("--registry", required=True)
    commit_parser.add_argument("--receipt", required=True)
    commit_parser.add_argument("--rpc-url", default="http://127.0.0.1:8545")
    commit_parser.add_argument("--private-key", default=os.environ.get("ANVIL_PRIVATE_KEY"), required=os.environ.get("ANVIL_PRIVATE_KEY") is None)
    commit_parser.add_argument("--params", default="{}")
    commit_parser.add_argument("--created-at")
    commit_parser.set_defaults(handler=commit_command)

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("receipt")
    verify_parser.add_argument("--registry")
    verify_parser.add_argument("--rpc-url")
    verify_parser.set_defaults(handler=verify_command)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
