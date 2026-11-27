// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

contract SignedProvenanceRegistry is EIP712 {
    struct Record {
        address author;
        uint48 timestamp;
        uint48 blockNumber;
        bytes32 modelId;
    }

    bytes32 public constant COMMIT_TYPEHASH = keccak256("Commit(bytes32 commitment,bytes32 modelId)");

    mapping(bytes32 key => Record) private _records;
    uint256 public count;

    event Committed(bytes32 indexed commitment, address indexed author, bytes32 indexed modelId, address relayer);

    error ZeroCommitment();
    error AlreadyCommitted(address author, bytes32 commitment);

    constructor() EIP712("SignedProvenanceRegistry", "1") {}

    function keyOf(address author, bytes32 commitment) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(author, commitment));
    }

    function digestOf(bytes32 commitment, bytes32 modelId) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(COMMIT_TYPEHASH, commitment, modelId)));
    }

    function commitSigned(bytes32 commitment, bytes32 modelId, bytes calldata signature) external returns (address author) {
        if (commitment == bytes32(0)) revert ZeroCommitment();
        author = ECDSA.recover(digestOf(commitment, modelId), signature);
        bytes32 key = keyOf(author, commitment);
        if (_records[key].author != address(0)) revert AlreadyCommitted(author, commitment);

        // forge-lint: disable-next-line(unsafe-typecast)
        _records[key] = Record(author, uint48(block.timestamp), uint48(block.number), modelId);
        count += 1;
        emit Committed(commitment, author, modelId, msg.sender);
    }

    function getRecord(address author, bytes32 commitment) external view returns (Record memory) {
        return _records[keyOf(author, commitment)];
    }

    function isCommitted(address author, bytes32 commitment) public view returns (bool) {
        return _records[keyOf(author, commitment)].author != address(0);
    }

    function verifyInclusion(address author, bytes32 root, bytes32 commitment, bytes32[] calldata proof)
        external
        view
        returns (bool)
    {
        if (!isCommitted(author, root)) return false;
        bytes32 leaf = keccak256(abi.encode(commitment));
        return MerkleProof.verifyCalldata(proof, root, leaf);
    }
}
