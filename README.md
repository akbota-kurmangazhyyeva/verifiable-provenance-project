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
