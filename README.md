# Verifiable provenance of LLM outputs on-chain

CSCI 435 Blockchain and Cryptocurrencies, research track project.

The system records a cryptographic commitment to an LLM generation (prompt,
output, model and parameters) on an Ethereum chain, so that the integrity of a
generated artifact and the time it was committed can be checked later by
anyone. The paper also measures what this can and cannot guarantee: a hash on
chain proves that *someone committed this exact text no later than block T*, it
does not prove *which model* produced it.

## Repository layout

| Path               | Contents                                                    |
|--------------------|-------------------------------------------------------------|
| `src/contracts/`   | Solidity contracts                                          |
| `src/provenance/`  | Python library: canonical records, commitments, Merkle tree |
| `test/contracts/`  | Foundry tests for the contracts                             |
| `tests/`           | pytest tests for the Python library                         |
| `scripts/`         | Measurement and plotting scripts                            |
| `data/`            | Generated measurement data (CSV)                            |
| `figures/`         | Figures, produced only by scripts in `scripts/`             |
| `notebooks/`       | Exploratory analysis                                        |
| `lib/`             | Git submodules: forge-std, OpenZeppelin Contracts           |

## Requirements

Versions we use; others may work but the gas numbers in the paper were
produced with exactly these.

- Foundry 1.8.5 (`forge`, `anvil`, `cast`), install with
  `curl -L https://foundry.paradigm.xyz | bash && foundryup -i 1.8.5`
- solc 0.8.37 (Foundry downloads it automatically, see `foundry.toml`)
- Python 3.12 and the packages in `requirements.txt`

## Setup

```bash
git clone --recursive https://github.com/akbota-kurmangazhyyeva/verifiable-provenance-project.git
cd verifiable-provenance-project
# if you cloned without --recursive:
git submodule update --init --recursive

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

forge build
```

## Tests

```bash
forge test          # contracts (fuzz seed fixed in foundry.toml)
python -m pytest    # Python library (random seeds fixed in the tests)
```

Both suites check the same Merkle root (`test_RootMatchesPythonImplementation`
and `test_root_matches_solidity_test_vector`), so a proof built in Python is
accepted by the contract.

## Reproducing the results

With the virtual environment from Setup active, generate the measurements and
the figure with:

```bash
python scripts/measure_gas.py
python scripts/plot_gas.py
```

The first command starts and stops its own local node. It writes
`data/gas_single.csv`, `data/gas_batch.csv`, and `gas_meta.json`; the second
writes `figures/gas_per_record.pdf`.

To create and check a single record yourself, use a separate local node:

```bash
export ANVIL_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
anvil --port 8545 --hardfork prague
```

In another terminal:

```bash
export ANVIL_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
export REGISTRY=$(forge create --broadcast --json src/contracts/ProvenanceRegistry.sol:ProvenanceRegistry --rpc-url http://127.0.0.1:8545 --private-key "$ANVIL_PRIVATE_KEY" | python -c 'import json, sys; print(json.load(sys.stdin)["deployedTo"])')
printf 'Name a moon.\n' > prompt.txt
printf 'Europa\n' > output.txt
PYTHONPATH=src python -m provenance.cli commit prompt.txt output.txt example/model --registry "$REGISTRY" --receipt receipt.json
PYTHONPATH=src python -m provenance.cli verify receipt.json
```

## Commitment scheme

```
content_hash = keccak256(canonical_json(record))
commitment   = keccak256(salt || content_hash)      salt: 32 random bytes
```

`record` holds model, prompt, output, generation parameters and creation time
(`src/provenance/record.py`). The salt stops anyone from confirming a guessed
prompt or output against the chain. To prove provenance later, the owner
publishes the record and the salt; anyone can recompute the commitment and look
it up in `ProvenanceRegistry`.

## Contracts

- `ProvenanceRegistry` stores one record per commitment: submitter, block
  timestamp, block number and a model id. The first submission wins and cannot
  be overwritten. A commitment can also be the Merkle root of a batch;
  `verifyInclusion` checks that a single commitment belongs to a committed batch.
- `ProvenanceLog` is the cheaper baseline: it only emits an event, so other
  contracts cannot read it and duplicates are not rejected.

## Third-party code

| Component                                                                  | Version | Licence | Used for                     |
|----------------------------------------------------------------------------|---------|---------|------------------------------|
| [OpenZeppelin Contracts](https://github.com/OpenZeppelin/openzeppelin-contracts) | 5.6.1   | MIT     | `MerkleProof` library        |
| [forge-std](https://github.com/foundry-rs/forge-std)                      | 1.17.0  | MIT / Apache-2.0 | Foundry test helpers |
| [PyCryptodome](https://www.pycryptodome.org/)                              | 3.23.0  | BSD-2 / Public domain | Keccak-256 in Python |

Their licence files are kept in `lib/` and in the installed packages. All
other code in this repository is ours.

## Licence

MIT, see `LICENSE`.
