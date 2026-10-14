// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @title ProvenanceLog: event-only baseline for ProvenanceRegistry
/// @notice Writes the commitment to a log instead of storage. The block that contains
///         the log gives the timestamp. This is much cheaper, but logs live in receipts:
///         other contracts cannot read them, and nothing stops the same commitment being
///         logged twice, so "who was first" has to be worked out off chain.
contract ProvenanceLog {
    event Committed(bytes32 indexed commitment, address indexed submitter, bytes32 indexed modelId);

    function commit(bytes32 commitment, bytes32 modelId) external {
        emit Committed(commitment, msg.sender, modelId);
    }
}
