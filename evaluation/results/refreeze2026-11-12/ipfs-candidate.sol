// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;

/// @title            Decompiled Contract
/// @author           Jonathan Becker <jonathan@jbecker.dev>
/// @custom:version   heimdall-rs v0.9.2
///
/// @notice           This contract was decompiled using the heimdall-rs decompiler.
///                     It was generated directly by tracing the EVM opcodes from this contract.
///                     As a result, it may not compile or even be valid solidity code.
///                     Despite this, it should be obvious what each function does. Overall
///                     logic should have been preserved throughout decompiling.
///
/// @custom:github    You can find the open-source decompiler here:
///                       https://heimdall.rs

contract DecompiledContract {
    uint256 var_g;
    uint256 var_i;
    uint256 var_m;
    bytes public unresolved_8191745f; // storage slot: 0x00
    bytes public unresolved_8bf421ee;     function Unresolved_6d4ce63c() public view returns (bytes memory, bytes memory) {
        uint256 lenA;
        uint256 lenB;
        bytes memory payloadA;
        bytes memory payloadB;
        assembly {
            let vA := sload(0x00)
            switch and(vA, 0x01)
            case 1 { lenA := shr(0x01, and(vA, 0xff)) }
            default { lenA := shr(0x01, vA) }
            let vB := sload(0x01)
            switch and(vB, 0x01)
            case 1 { lenB := shr(0x01, and(vB, 0xff)) }
            default { lenB := shr(0x01, vB) }
            let base := mload(0x40)
            let wordsA := shr(0x05, add(lenA, 0x1f))
            let offB := add(0x60, mul(0x20, wordsA))
            mstore(base, 0x40)
            mstore(add(base, 0x20), offB)
            payloadA := add(base, 0x40)
            mstore(payloadA, lenA)
            let dataA := add(payloadA, 0x20)
            switch lenA
            case 0 { }
            default {
                switch and(vA, 0x01)
                case 1 {
                    let i := 0
                    for { } lt(i, lenA) { i := add(i, 0x01) } {
                        mstore8(add(dataA, i), byte(i, vA))
                    }
                }
                default {
                    mstore(0x00, 0x00)
                    let src := keccak256(0x00, 0x20)
                    let i := 0
                    for { } lt(i, wordsA) { i := add(i, 0x01) } {
                        mstore(add(dataA, mul(0x20, i)), sload(add(src, i)))
                    }
                }
            }
            payloadB := add(base, offB)
            mstore(payloadB, lenB)
            let dataB := add(payloadB, 0x20)
            switch lenB
            case 0 { }
            default {
                switch and(vB, 0x01)
                case 1 {
                    let i := 0
                    for { } lt(i, lenB) { i := add(i, 0x01) } {
                        mstore8(add(dataB, i), byte(i, vB))
                    }
                }
                default {
                    mstore(0x00, 0x01)
                    let src := keccak256(0x00, 0x20)
                    let wordsB := shr(0x05, add(lenB, 0x1f))
                    let i := 0
                    for { } lt(i, wordsB) { i := add(i, 0x01) } {
                        mstore(add(dataB, mul(0x20, i)), sload(add(src, i)))
                    }
                }
            }
            mstore(0x40, add(add(payloadB, 0x20), mul(0x20, shr(0x05, add(lenB, 0x1f)))))
        }
        return (payloadA, payloadB);
    }

    function Description() public view returns (bytes memory) {
        uint256 len;
        bytes memory payload;
        assembly {
            let v := sload(0x00)
            switch and(v, 0x01)
            case 1 { len := shr(0x01, and(v, 0xff)) }
            default { len := shr(0x01, v) }
            let data := add(mload(0x40), 0x20)
            payload := mload(0x40)
            mstore(payload, len)
            switch len
            case 0 {
                mstore(0x40, add(data, 0x20))
            }
            default {
                switch and(v, 0x01)
                case 1 {
                    let i := 0
                    for { } lt(i, len) { i := add(i, 0x01) } {
                        mstore8(add(data, i), byte(i, v))
                    }
                }
                default {
                    mstore(0x00, 0x00)
                    let src := keccak256(0x00, 0x20)
                    let full := shr(0x05, add(len, 0x1f))
                    let i := 0
                    for { } lt(i, full) { i := add(i, 0x01) } {
                        mstore(add(data, mul(0x20, i)), sload(add(src, i)))
                    }
                }
                mstore(0x40, add(data, mul(0x20, shr(0x05, add(len, 0x1f)))))
            }
        }
        return payload;
    }

    function IpfsHash() public view returns (bytes memory) {
        uint256 len;
        bytes memory payload;
        assembly {
            let v := sload(0x01)
            switch and(v, 0x01)
            case 1 { len := shr(0x01, and(v, 0xff)) }
            default { len := shr(0x01, v) }
            let data := add(mload(0x40), 0x20)
            payload := mload(0x40)
            mstore(payload, len)
            switch len
            case 0 {
                mstore(0x40, add(data, 0x20))
            }
            default {
                switch and(v, 0x01)
                case 1 {
                    let i := 0
                    for { } lt(i, len) { i := add(i, 0x01) } {
                        mstore8(add(data, i), byte(i, v))
                    }
                }
                default {
                    mstore(0x00, 0x01)
                    let src := keccak256(0x00, 0x20)
                    let full := shr(0x05, add(len, 0x1f))
                    let i := 0
                    for { } lt(i, full) { i := add(i, 0x01) } {
                        mstore(add(data, mul(0x20, i)), sload(add(src, i)))
                    }
                }
                mstore(0x40, add(data, mul(0x20, shr(0x05, add(len, 0x1f)))))
            }
        }
        return payload;
    }

}