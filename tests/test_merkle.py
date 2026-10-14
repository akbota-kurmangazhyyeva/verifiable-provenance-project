import math
import random

import pytest

from provenance import MerkleTree, keccak256, verify
from provenance.merkle import hash_pair, leaf_hash

SEED = 435


def commitments(n, rng):
    return [rng.randbytes(32) for _ in range(n)]


def test_root_matches_solidity_test_vector():
    # same tree as _batch() in test/contracts/ProvenanceRegistry.t.sol
    tree = MerkleTree([keccak256(f"record {i}".encode()) for i in (1, 2, 3)])
    assert tree.root.hex() == "afd0cec88b49eff5faf50f62db47175b79ed74335420cad1b57b2e233ef0e9e5"


def test_single_leaf():
    c = keccak256(b"only")
    tree = MerkleTree([c])
    assert tree.root == leaf_hash(c)
    assert tree.proof(0) == []
    assert verify(tree.root, c, [])


@pytest.mark.parametrize("n", [2, 3, 4, 5, 7, 8, 9, 16, 33, 100])
def test_every_leaf_verifies(n):
    rng = random.Random(SEED + n)
    cs = commitments(n, rng)
    tree = MerkleTree(cs)
    for i, c in enumerate(cs):
        proof = tree.proof(i)
        assert len(proof) <= math.ceil(math.log2(n))
        assert verify(tree.root, c, proof)


def test_wrong_leaf_or_proof_fails():
    rng = random.Random(SEED)
    cs = commitments(8, rng)
    tree = MerkleTree(cs)
    assert not verify(tree.root, rng.randbytes(32), tree.proof(0))
    assert not verify(tree.root, cs[0], tree.proof(1))


def test_inner_node_is_not_a_leaf():
    cs = [keccak256(f"record {i}".encode()) for i in (1, 2, 3)]
    tree = MerkleTree(cs)
    inner = hash_pair(leaf_hash(cs[0]), leaf_hash(cs[1]))
    assert not verify(tree.root, inner, [leaf_hash(cs[2])])


def test_empty_tree_rejected():
    with pytest.raises(ValueError):
        MerkleTree([])


def test_proof_index_out_of_range():
    tree = MerkleTree([keccak256(b"a"), keccak256(b"b")])
    with pytest.raises(IndexError):
        tree.proof(2)
