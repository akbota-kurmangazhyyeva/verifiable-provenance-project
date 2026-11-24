"""Start a throwaway Anvil node and deploy contracts to it, for the experiments.

Uses Anvil's first default account. Its key is public and only ever holds
test ether on a local chain; never use it anywhere else.
"""

import json
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
HARD_FORK = "prague"


@contextmanager
def anvil(port: int = 8546) -> Iterator[str]:
    """Run Anvil on `port` for the duration of the block and yield its RPC URL.

    Uses 8546 by default so it does not clash with a node you already run on
    8545 or with measure_gas.py.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))  # fails early if the port is taken
    node = subprocess.Popen(["anvil", "--port", str(port), "--hardfork", HARD_FORK], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while True:
            if node.poll() is not None:
                raise RuntimeError("anvil exited before becoming ready")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("anvil did not start within ten seconds")
                time.sleep(0.1)
        yield f"http://127.0.0.1:{port}"
    finally:
        node.terminate()
        node.wait(timeout=5)


def deploy(contract: str, rpc_url: str, private_key: str = ANVIL_KEY) -> str:
    created = subprocess.run(
        ["forge", "create", "--broadcast", "--json", contract, "--rpc-url", rpc_url, "--private-key", private_key],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return json.loads(created.stdout)["deployedTo"]


def call(address: str, signature: str, *arguments: str, rpc_url: str) -> str:
    return subprocess.run(["cast", "call", address, signature, *arguments, "--rpc-url", rpc_url], check=True, capture_output=True, text=True).stdout.strip()
