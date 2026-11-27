"""Small helpers shared by measure_fixes.py and exp_recommit.py.

Talks to a local Anvil node over JSON-RPC and deploys the three registries:
  original = ProvenanceRegistry        (key: commitment)
  keyed    = KeyedProvenanceRegistry   (key: sender + commitment)
  signed   = SignedProvenanceRegistry  (key: signer + commitment, EIP-712 signature)
"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from provenance.commitment import keccak256

PORT = 8545
RPC_URL = f"http://127.0.0.1:{PORT}"
HARD_FORK = "prague"
CHAIN_ID = 31337

AUTHOR = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
COPIER = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"

CONTRACTS = {
    "original": "ProvenanceRegistry",
    "keyed": "KeyedProvenanceRegistry",
    "signed": "SignedProvenanceRegistry",
}


def rpc(method: str, params: list) -> object:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(RPC_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        reply = json.load(response)
    if "error" in reply:
        raise RuntimeError(f"{method} failed: {reply['error']}")
    return reply["result"]


def _word(value: bytes | str | int) -> bytes:
    if isinstance(value, int):
        return value.to_bytes(32, "big")
    if isinstance(value, str):
        return bytes(12) + bytes.fromhex(value.removeprefix("0x"))
    return value


def encode(signature: str, *static: bytes | str | int, dynamic: bytes | list[bytes] | None = None) -> str:
    """ABI-encode a call whose arguments are static words, optionally followed by
    one dynamic argument (`bytes` or `bytes32[]`) as the last parameter."""
    head = [_word(a) for a in static]
    tail = b""
    if dynamic is not None:
        head.append(_word(32 * (len(static) + 1)))
        if isinstance(dynamic, list):
            tail = _word(len(dynamic)) + b"".join(dynamic)
        else:
            padded = dynamic + bytes(-len(dynamic) % 32)
            tail = _word(len(dynamic)) + padded
    return "0x" + (keccak256(signature.encode())[:4] + b"".join(head) + tail).hex()


def send(sender: str, to: str | None, data: str) -> dict:
    transaction = {"from": sender, "data": data, "gas": hex(3_000_000)}
    if to is not None:
        transaction["to"] = to
    tx = rpc("eth_sendTransaction", [transaction])
    for _ in range(100):
        receipt = rpc("eth_getTransactionReceipt", [tx])
        if receipt is not None:
            return receipt
        time.sleep(0.05)
    raise RuntimeError(f"no receipt for {tx}")


def call(to: str, data: str) -> bytes:
    return bytes.fromhex(rpc("eth_call", [{"to": to, "data": data}, "latest"])[2:])


def estimate(to: str, data: str) -> int:
    return int(rpc("eth_estimateGas", [{"to": to, "data": data}]), 16)


def deploy(name: str) -> str:
    artifact = json.loads((ROOT / "out" / f"{name}.sol" / f"{name}.json").read_text())
    return send(AUTHOR, None, artifact["bytecode"]["object"])["contractAddress"]


def sign_commit(registry: str, signer: str, commitment: bytes, model: bytes) -> bytes:
    """EIP-712 signature by `signer` (an unlocked Anvil account) over Commit(commitment, modelId)."""
    typed = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Commit": [{"name": "commitment", "type": "bytes32"}, {"name": "modelId", "type": "bytes32"}],
        },
        "primaryType": "Commit",
        "domain": {"name": "SignedProvenanceRegistry", "version": "1", "chainId": CHAIN_ID, "verifyingContract": registry},
        "message": {"commitment": "0x" + commitment.hex(), "modelId": "0x" + model.hex()},
    }
    return bytes.fromhex(rpc("eth_signTypedData_v4", [signer, json.dumps(typed)])[2:])


def commit_calldata(design: str, registry: str, signer: str, commitment: bytes, model: bytes) -> str:
    if design == "signed":
        signature = sign_commit(registry, signer, commitment, model)
        return encode("commitSigned(bytes32,bytes32,bytes)", commitment, model, dynamic=signature)
    return encode("commit(bytes32,bytes32)", commitment, model)


def commit_as(design: str, registry: str, sender: str, commitment: bytes, model: bytes) -> dict:
    """`sender` commits (and, for the signed registry, also signs) the commitment."""
    receipt = send(sender, registry, commit_calldata(design, registry, sender, commitment, model))
    if receipt["status"] != "0x1":
        raise RuntimeError(f"{design} commit reverted")
    return receipt


def entry(design: str, registry: str, who: str, commitment: bytes) -> tuple[str, int] | None:
    """(submitter, block number) stored for this commitment, or None.
    For keyed and signed the lookup is under `who`; the original ignores `who`."""
    if design == "original":
        raw = call(registry, encode("getRecord(bytes32)", commitment))
    else:
        raw = call(registry, encode("getRecord(address,bytes32)", who, commitment))
    submitter = "0x" + raw[12:32].hex()
    if int(submitter, 16) == 0:
        return None
    block_number = int.from_bytes(raw[64:96], "big")  # words: submitter, timestamp, blockNumber, modelId
    return submitter, block_number


def inclusion_calldata(design: str, author: str, root: bytes, commitment: bytes, proof: list[bytes]) -> str:
    if design == "original":
        return encode("verifyInclusion(bytes32,bytes32,bytes32[])", root, commitment, dynamic=proof)
    return encode("verifyInclusion(address,bytes32,bytes32,bytes32[])", author, root, commitment, dynamic=proof)


def anvil_version() -> str:
    return subprocess.run(["anvil", "--version"], capture_output=True, text=True).stdout.splitlines()[0]


@contextmanager
def anvil():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", PORT))
    node = subprocess.Popen(
        ["anvil", "--port", str(PORT), "--hardfork", HARD_FORK],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            if node.poll() is not None:
                raise RuntimeError("anvil exited before becoming ready")
            try:
                with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("anvil did not start within ten seconds")
                time.sleep(0.1)
        yield
    finally:
        node.terminate()
        node.wait(timeout=5)
