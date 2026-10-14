"""Merkle tree over commitments, matching ProvenanceRegistry.verifyInclusion.

- leaf = keccak256(commitment), equal to Solidity keccak256(abi.encode(bytes32))
- inner node = keccak256 of the two children in sorted order, as in
  OpenZeppelin MerkleProof, so a proof is just a list of sibling hashes
- if a level has an odd number of nodes, the last one moves up unchanged
  (it is not duplicated)
"""

from .commitment import keccak256


def leaf_hash(commitment: bytes) -> bytes:
    if len(commitment) != 32:
        raise ValueError("commitment must be 32 bytes")
    return keccak256(commitment)


def hash_pair(a: bytes, b: bytes) -> bytes:
    return keccak256(a + b) if a < b else keccak256(b + a)


class MerkleTree:
    def __init__(self, commitments: list[bytes]):
        if not commitments:
            raise ValueError("cannot build a tree with no leaves")
        self.levels = [[leaf_hash(c) for c in commitments]]
        while len(self.levels[-1]) > 1:
            level = self.levels[-1]
            parents = [hash_pair(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
            if len(level) % 2 == 1:
                parents.append(level[-1])
            self.levels.append(parents)

    @property
    def root(self) -> bytes:
        return self.levels[-1][0]

    def __len__(self) -> int:
        return len(self.levels[0])

    def proof(self, index: int) -> list[bytes]:
        if not 0 <= index < len(self):
            raise IndexError(index)
        proof = []
        for level in self.levels[:-1]:
            sibling = index ^ 1
            if sibling < len(level):  # no sibling means the node was carried up
                proof.append(level[sibling])
            index //= 2
        return proof


def verify(root: bytes, commitment: bytes, proof: list[bytes]) -> bool:
    node = leaf_hash(commitment)
    for sibling in proof:
        node = hash_pair(node, sibling)
    return node == root
