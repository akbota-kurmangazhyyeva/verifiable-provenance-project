// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {ProvenanceRegistry} from "../../src/contracts/ProvenanceRegistry.sol";
import {ProvenanceLog} from "../../src/contracts/ProvenanceLog.sol";

contract ProvenanceRegistryTest is Test {
    event Committed(bytes32 indexed commitment, address indexed submitter, bytes32 indexed modelId);

    ProvenanceRegistry registry;

    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    bytes32 constant MODEL = keccak256("anthropic/claude-sonnet-5-5");
    bytes32 constant C1 = keccak256("record 1");
    bytes32 constant C2 = keccak256("record 2");
    bytes32 constant C3 = keccak256("record 3");

    function setUp() public {
        registry = new ProvenanceRegistry();
    }

    // ---- single commitments ----

    function test_CommitStoresRecord() public {
        vm.warp(1_760_000_000);
        vm.roll(9_000_000);
        vm.prank(alice);
        registry.commit(C1, MODEL);

        ProvenanceRegistry.Record memory r = registry.getRecord(C1);
        assertEq(r.submitter, alice);
        assertEq(r.timestamp, 1_760_000_000);
        assertEq(r.blockNumber, 9_000_000);
        assertEq(r.modelId, MODEL);
        assertTrue(registry.isCommitted(C1));
        assertEq(registry.count(), 1);
    }

    function test_CommitEmitsEvent() public {
        vm.expectEmit(true, true, true, true, address(registry));
        emit Committed(C1, alice, MODEL);
        vm.prank(alice);
        registry.commit(C1, MODEL);
    }

    function test_UnknownCommitmentIsEmpty() public view {
        ProvenanceRegistry.Record memory r = registry.getRecord(C1);
        assertEq(r.submitter, address(0));
        assertEq(r.timestamp, 0);
        assertFalse(registry.isCommitted(C1));
    }

    function test_RevertWhen_ZeroCommitment() public {
        vm.expectRevert(ProvenanceRegistry.ZeroCommitment.selector);
        registry.commit(bytes32(0), MODEL);
    }

    function test_RevertWhen_AlreadyCommitted_FirstSubmitterKept() public {
        vm.warp(1000);
        vm.prank(alice);
        registry.commit(C1, MODEL);

        vm.warp(2000);
        vm.prank(bob);
        vm.expectRevert(abi.encodeWithSelector(ProvenanceRegistry.AlreadyCommitted.selector, C1, alice));
        registry.commit(C1, bytes32(0));

        ProvenanceRegistry.Record memory r = registry.getRecord(C1);
        assertEq(r.submitter, alice);
        assertEq(r.timestamp, 1000);
        assertEq(r.modelId, MODEL);
        assertEq(registry.count(), 1);
    }

    function testFuzz_CommitAnyNonZero(bytes32 c, bytes32 model, address who) public {
        vm.assume(c != bytes32(0) && who != address(0));
        vm.prank(who);
        registry.commit(c, model);
        assertEq(registry.getRecord(c).submitter, who);
        assertEq(registry.getRecord(c).modelId, model);
    }

    // ---- Merkle batches ----
    // Tree over [C1, C2, C3]. With an odd count the last node is carried up unchanged:
    //   root = H(H(l1, l2), l3)   where li = keccak256(abi.encode(Ci)), H = sorted-pair keccak

    function _leaf(bytes32 c) internal pure returns (bytes32) {
        return keccak256(abi.encode(c));
    }

    function _hashPair(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return a < b ? keccak256(abi.encode(a, b)) : keccak256(abi.encode(b, a));
    }

    function _batch() internal pure returns (bytes32 root, bytes32 n12) {
        n12 = _hashPair(_leaf(C1), _leaf(C2));
        root = _hashPair(n12, _leaf(C3));
    }

    function test_RootMatchesPythonImplementation() public pure {
        // MerkleTree([keccak256(b"record 1"), ..., keccak256(b"record 3")]).root
        // from src/provenance/merkle.py; the same value is asserted in tests/test_merkle.py
        (bytes32 root,) = _batch();
        assertEq(root, 0xafd0cec88b49eff5faf50f62db47175b79ed74335420cad1b57b2e233ef0e9e5);
    }

    function test_VerifyInclusion_AllLeaves() public {
        (bytes32 root, bytes32 n12) = _batch();
        registry.commit(root, MODEL);

        bytes32[] memory p1 = new bytes32[](2);
        p1[0] = _leaf(C2);
        p1[1] = _leaf(C3);
        assertTrue(registry.verifyInclusion(root, C1, p1));

        bytes32[] memory p2 = new bytes32[](2);
        p2[0] = _leaf(C1);
        p2[1] = _leaf(C3);
        assertTrue(registry.verifyInclusion(root, C2, p2));

        bytes32[] memory p3 = new bytes32[](1);
        p3[0] = n12;
        assertTrue(registry.verifyInclusion(root, C3, p3));
    }

    function test_VerifyInclusion_FalseWhenRootNotCommitted() public view {
        (bytes32 root, bytes32 n12) = _batch();
        bytes32[] memory p3 = new bytes32[](1);
        p3[0] = n12;
        assertFalse(registry.verifyInclusion(root, C3, p3));
    }

    function test_VerifyInclusion_FalseForLeafNotInBatch() public {
        (bytes32 root, bytes32 n12) = _batch();
        registry.commit(root, MODEL);
        bytes32[] memory p = new bytes32[](1);
        p[0] = n12;
        assertFalse(registry.verifyInclusion(root, keccak256("record 4"), p));
    }

    function test_VerifyInclusion_InnerNodeIsNotALeaf() public {
        (bytes32 root,) = _batch();
        registry.commit(root, MODEL);
        // n12 is a real node of the tree; it must not verify as if it were a commitment
        bytes32[] memory p = new bytes32[](1);
        p[0] = _leaf(C3);
        bytes32 n12 = _hashPair(_leaf(C1), _leaf(C2));
        assertFalse(registry.verifyInclusion(root, n12, p));
    }
}

contract ProvenanceLogTest is Test {
    event Committed(bytes32 indexed commitment, address indexed submitter, bytes32 indexed modelId);

    function test_CommitEmitsEventAndAllowsDuplicates() public {
        ProvenanceLog log = new ProvenanceLog();
        bytes32 c = keccak256("record 1");
        bytes32 model = keccak256("anthropic/claude-sonnet-5-5");

        vm.expectEmit(true, true, true, true, address(log));
        emit Committed(c, address(this), model);
        log.commit(c, model);

        // no storage, so no duplicate check: the second call succeeds too
        log.commit(c, model);
    }
}
