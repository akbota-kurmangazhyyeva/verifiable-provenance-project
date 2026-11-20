// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

contract KeyedProvenanceRegistry {
    struct Record {
        address submitter;
        uint48 timestamp;
        uint48 blockNumber;
        bytes32 modelId;
    }

    mapping(bytes32 key => Record) private _records;
    uint256 public count;

    event Committed(bytes32 indexed commitment, address indexed submitter, bytes32 indexed modelId);

    error ZeroCommitment();
    error AlreadyCommitted(address submitter, bytes32 commitment);

    function keyOf(address submitter, bytes32 commitment) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(submitter, commitment));
    }

    function commit(bytes32 commitment, bytes32 modelId) external {
        if (commitment == bytes32(0)) revert ZeroCommitment();
        bytes32 key = keyOf(msg.sender, commitment);
        if (_records[key].submitter != address(0)) revert AlreadyCommitted(msg.sender, commitment);

        // forge-lint: disable-next-line(unsafe-typecast)
        _records[key] = Record(msg.sender, uint48(block.timestamp), uint48(block.number), modelId);
        count += 1;
        emit Committed(commitment, msg.sender, modelId);
    }

    function getRecord(address submitter, bytes32 commitment) external view returns (Record memory) {
        return _records[keyOf(submitter, commitment)];
    }

    function isCommitted(address submitter, bytes32 commitment) public view returns (bool) {
        return _records[keyOf(submitter, commitment)].submitter != address(0);
    }

    function verifyInclusion(address submitter, bytes32 root, bytes32 commitment, bytes32[] calldata proof)
        external
        view
        returns (bool)
    {
        if (!isCommitted(submitter, root)) return false;
        bytes32 leaf = keccak256(abi.encode(commitment));
        return MerkleProof.verifyCalldata(proof, root, leaf);
    }
}
