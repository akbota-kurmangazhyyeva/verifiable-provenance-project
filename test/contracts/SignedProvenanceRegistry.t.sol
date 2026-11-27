// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {SignedProvenanceRegistry} from "../../src/contracts/SignedProvenanceRegistry.sol";

contract SignedProvenanceRegistryTest is Test {
    SignedProvenanceRegistry reg;

    uint256 authorKey = 0xA11CE;
    uint256 copierKey = 0xB0B;
    address author;
    address copier;
    address relayer = makeAddr("relayer");

    bytes32 constant MODEL = keccak256("anthropic/claude-sonnet-5-5");
    bytes32 constant FAKE_MODEL = keccak256("made-up-model");
    bytes32 constant C1 = keccak256("record 1");
    bytes32 constant C2 = keccak256("record 2");
    bytes32 constant C3 = keccak256("record 3");

    function setUp() public {
        reg = new SignedProvenanceRegistry();
        author = vm.addr(authorKey);
        copier = vm.addr(copierKey);
    }

    function _sign(SignedProvenanceRegistry r, uint256 key, bytes32 c, bytes32 m) internal view returns (bytes memory) {
        (uint8 v, bytes32 rr, bytes32 s) = vm.sign(key, r.digestOf(c, m));
        return abi.encodePacked(rr, s, v);
    }

    function test_CommitStoresSignerAsAuthor() public {
        vm.warp(1_760_000_000);
        vm.roll(9_000_000);
        bytes memory sig = _sign(reg, authorKey, C1, MODEL);

        vm.prank(relayer);
        address recovered = reg.commitSigned(C1, MODEL, sig);

        assertEq(recovered, author);
        SignedProvenanceRegistry.Record memory r = reg.getRecord(author, C1);
        assertEq(r.author, author);
        assertEq(r.timestamp, 1_760_000_000);
        assertEq(r.blockNumber, 9_000_000);
        assertEq(r.modelId, MODEL);
        assertFalse(reg.isCommitted(relayer, C1));
        assertEq(reg.count(), 1);
    }

    function test_RevertWhen_ZeroCommitment() public {
        bytes memory sig = _sign(reg, authorKey, bytes32(0), MODEL);
        vm.expectRevert(SignedProvenanceRegistry.ZeroCommitment.selector);
        reg.commitSigned(bytes32(0), MODEL, sig);
    }

    function test_RevertWhen_SignatureIsGarbage() public {
        vm.expectRevert();
        reg.commitSigned(C1, MODEL, hex"1234");
    }

    function test_CopiedTransactionStillRecordsTheAuthor() public {
        bytes memory sig = _sign(reg, authorKey, C1, MODEL);

        vm.prank(copier);
        reg.commitSigned(C1, MODEL, sig);

        vm.prank(author);
        vm.expectRevert(abi.encodeWithSelector(SignedProvenanceRegistry.AlreadyCommitted.selector, author, C1));
        reg.commitSigned(C1, MODEL, sig);

        assertEq(reg.getRecord(author, C1).author, author);
        assertFalse(reg.isCommitted(copier, C1));
    }

    function test_CopierSigningTheSameCommitmentGetsOwnEntryOnly() public {
        vm.prank(copier);
        reg.commitSigned(C1, MODEL, _sign(reg, copierKey, C1, MODEL));
        reg.commitSigned(C1, MODEL, _sign(reg, authorKey, C1, MODEL));

        assertEq(reg.getRecord(author, C1).author, author);
        assertEq(reg.getRecord(copier, C1).author, copier);
        assertEq(reg.count(), 2);
    }

    function test_ChangingTheModelLabelChangesTheSigner() public {
        bytes memory sig = _sign(reg, authorKey, C1, MODEL);
        address recovered = reg.commitSigned(C1, FAKE_MODEL, sig);

        assertTrue(recovered != author);
        assertFalse(reg.isCommitted(author, C1));
    }

    function test_SignatureForAnotherRegistryDoesNotWorkHere() public {
        SignedProvenanceRegistry other = new SignedProvenanceRegistry();
        bytes memory sigForOther = _sign(other, authorKey, C1, MODEL);

        address recovered = reg.commitSigned(C1, MODEL, sigForOther);
        assertTrue(recovered != author);
        assertFalse(reg.isCommitted(author, C1));
    }

    function test_DigestMatchesEIP712() public view {
        bytes32 domain = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("SignedProvenanceRegistry"),
                keccak256("1"),
                block.chainid,
                address(reg)
            )
        );
        bytes32 structHash = keccak256(abi.encode(reg.COMMIT_TYPEHASH(), C1, MODEL));
        assertEq(reg.digestOf(C1, MODEL), keccak256(abi.encodePacked("\x19\x01", domain, structHash)));
    }

    function testFuzz_RecoversWhoeverSigned(uint256 key, bytes32 c) public {
        key = bound(key, 1, 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364140);
        vm.assume(c != bytes32(0));
        address recovered = reg.commitSigned(c, MODEL, _sign(reg, key, c, MODEL));
        assertEq(recovered, vm.addr(key));
        assertTrue(reg.isCommitted(vm.addr(key), c));
    }

    function _leaf(bytes32 c) internal pure returns (bytes32) {
        return keccak256(abi.encode(c));
    }

    function _hashPair(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return a < b ? keccak256(abi.encode(a, b)) : keccak256(abi.encode(b, a));
    }

    function test_VerifyInclusion_OnlyUnderTheSigner() public {
        bytes32 n12 = _hashPair(_leaf(C1), _leaf(C2));
        bytes32 root = _hashPair(n12, _leaf(C3));
        reg.commitSigned(root, MODEL, _sign(reg, authorKey, root, MODEL));

        bytes32[] memory p3 = new bytes32[](1);
        p3[0] = n12;
        assertTrue(reg.verifyInclusion(author, root, C3, p3));
        assertFalse(reg.verifyInclusion(copier, root, C3, p3));
    }
}
