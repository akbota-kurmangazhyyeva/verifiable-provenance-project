// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {ProvenanceRegistry} from "../../src/contracts/ProvenanceRegistry.sol";
import {KeyedProvenanceRegistry} from "../../src/contracts/KeyedProvenanceRegistry.sol";

contract KeyedProvenanceRegistryTest is Test {
    KeyedProvenanceRegistry keyed;
    ProvenanceRegistry original;

    address author = makeAddr("author");
    address copier = makeAddr("copier");
    bytes32 constant MODEL = keccak256("anthropic/claude-sonnet-5-5");
    bytes32 constant FAKE_MODEL = keccak256("made-up-model");
    bytes32 constant C1 = keccak256("record 1");
    bytes32 constant C2 = keccak256("record 2");
    bytes32 constant C3 = keccak256("record 3");

    function setUp() public {
        keyed = new KeyedProvenanceRegistry();
        original = new ProvenanceRegistry();
    }

    function test_CommitStoresRecordUnderSubmitter() public {
        vm.warp(1_760_000_000);
        vm.roll(9_000_000);
        vm.prank(author);
        keyed.commit(C1, MODEL);

        KeyedProvenanceRegistry.Record memory r = keyed.getRecord(author, C1);
        assertEq(r.submitter, author);
        assertEq(r.timestamp, 1_760_000_000);
        assertEq(r.blockNumber, 9_000_000);
        assertEq(r.modelId, MODEL);
        assertTrue(keyed.isCommitted(author, C1));
        assertFalse(keyed.isCommitted(copier, C1));
        assertEq(keyed.count(), 1);
    }

    function test_KeyIsHashOf52Bytes() public view {
        bytes memory packed = abi.encodePacked(author, C1);
        assertEq(packed.length, 52);
        assertEq(keyed.keyOf(author, C1), keccak256(packed));
    }

    function test_RevertWhen_ZeroCommitment() public {
        vm.expectRevert(KeyedProvenanceRegistry.ZeroCommitment.selector);
        keyed.commit(bytes32(0), MODEL);
    }

    function test_RevertWhen_SameSubmitterCommitsTwice() public {
        vm.warp(1000);
        vm.prank(author);
        keyed.commit(C1, MODEL);

        vm.warp(2000);
        vm.prank(author);
        vm.expectRevert(abi.encodeWithSelector(KeyedProvenanceRegistry.AlreadyCommitted.selector, author, C1));
        keyed.commit(C1, FAKE_MODEL);

        assertEq(keyed.getRecord(author, C1).timestamp, 1000);
        assertEq(keyed.getRecord(author, C1).modelId, MODEL);
    }

    function test_OriginalRegistry_CopierWinsAndAuthorReverts() public {
        vm.prank(copier);
        original.commit(C1, MODEL);

        vm.prank(author);
        vm.expectRevert(abi.encodeWithSelector(ProvenanceRegistry.AlreadyCommitted.selector, C1, copier));
        original.commit(C1, MODEL);

        assertEq(original.getRecord(C1).submitter, copier);
    }

    function test_KeyedRegistry_BothEntriesExistAndAuthorKeepsTheirs() public {
        vm.prank(copier);
        keyed.commit(C1, MODEL);

        vm.prank(author);
        keyed.commit(C1, MODEL);

        assertEq(keyed.getRecord(author, C1).submitter, author);
        assertEq(keyed.getRecord(copier, C1).submitter, copier);
        assertEq(keyed.count(), 2);
    }

    function testFuzz_DifferentSubmittersNeverBlockEachOther(address a, address b, bytes32 c) public {
        vm.assume(a != b && a != address(0) && b != address(0) && c != bytes32(0));
        vm.prank(a);
        keyed.commit(c, MODEL);
        vm.prank(b);
        keyed.commit(c, MODEL);
        assertTrue(keyed.isCommitted(a, c));
        assertTrue(keyed.isCommitted(b, c));
    }

    function _leaf(bytes32 c) internal pure returns (bytes32) {
        return keccak256(abi.encode(c));
    }

    function _hashPair(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return a < b ? keccak256(abi.encode(a, b)) : keccak256(abi.encode(b, a));
    }

    function test_VerifyInclusion_OnlyUnderTheSubmitterOfTheRoot() public {
        bytes32 n12 = _hashPair(_leaf(C1), _leaf(C2));
        bytes32 root = _hashPair(n12, _leaf(C3));
        vm.prank(author);
        keyed.commit(root, MODEL);

        bytes32[] memory p3 = new bytes32[](1);
        p3[0] = n12;
        assertTrue(keyed.verifyInclusion(author, root, C3, p3));
        assertFalse(keyed.verifyInclusion(copier, root, C3, p3));
    }
}
