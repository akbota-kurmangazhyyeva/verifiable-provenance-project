// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

/// @title ProvenanceRegistry: timestamped commitments to LLM generations
/// @notice Stores a 32-byte commitment to one generation record (prompt, output,
///         model, parameters), or a Merkle root over a batch of such commitments.
///         The contract never sees the text itself, only digests computed off chain.
/// @dev What a stored record proves: `submitter` knew the committed data no later
///      than block `blockNumber`. It does not prove which model produced the data,
///      and it does not prove the data is true (the oracle problem).
///      Known limitation: a commitment is visible in the mempool before it is mined,
///      so someone can copy it and get it included first. They learn nothing about
///      the content (it is salted off chain) but they become the recorded submitter.
contract ProvenanceRegistry {
    struct Record {
        address submitter; // 20 bytes \
        uint48 timestamp; //   6 bytes  > packed into one storage slot
        uint48 blockNumber; // 6 bytes /
        bytes32 modelId; // keccak256 of the model identifier string, second slot
    }

    mapping(bytes32 commitment => Record) private _records;
    uint256 public count;

    event Committed(bytes32 indexed commitment, address indexed submitter, bytes32 indexed modelId);

    error ZeroCommitment();
    error AlreadyCommitted(bytes32 commitment, address firstSubmitter);

    /// @notice Record a commitment. The first submission wins and is never overwritten,
    ///         otherwise a later caller could replace the original timestamp.
    function commit(bytes32 commitment, bytes32 modelId) external {
        if (commitment == bytes32(0)) revert ZeroCommitment();
        address first = _records[commitment].submitter;
        if (first != address(0)) revert AlreadyCommitted(commitment, first);

        _records[commitment] = Record(msg.sender, uint48(block.timestamp), uint48(block.number), modelId);
        count += 1;
        emit Committed(commitment, msg.sender, modelId);
    }

    function getRecord(bytes32 commitment) external view returns (Record memory) {
        return _records[commitment];
    }

    function isCommitted(bytes32 commitment) public view returns (bool) {
        return _records[commitment].submitter != address(0);
    }

    /// @notice True if `commitment` is a leaf of the batch whose Merkle `root` was committed.
    /// @dev Leaves are keccak256(abi.encode(commitment)), so a leaf preimage is 32 bytes
    ///      while an inner node preimage is 64 bytes; an inner node cannot be passed off
    ///      as a leaf. Pairs are hashed in sorted order, as OpenZeppelin's MerkleProof
    ///      expects, so the proof does not need left/right flags.
    function verifyInclusion(bytes32 root, bytes32 commitment, bytes32[] calldata proof) external view returns (bool) {
        if (!isCommitted(root)) return false;
        bytes32 leaf = keccak256(abi.encode(commitment));
        return MerkleProof.verifyCalldata(proof, root, leaf);
    }
}
