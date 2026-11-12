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
    uint256 var_e;
    uint256 var_f;
    uint256 var_h;
    bytes store_a;     function Unresolved_2a1afcd9() public view returns (bytes memory) {
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

    
        function Unresolved_4ed3885e(uint256 arg0) public {
        assembly {
            let offset := calldataload(0x04)
            let loc := add(0x04, offset)
            let n := calldataload(loc)
            switch lt(n, 0x20)
            case 1 {
                let v := 0
                let i := 0
                for { } lt(i, n) { i := add(i, 0x01) } {
                    v := add(v, shl(mul(8, sub(31, i)), byte(i, calldataload(add(loc, 0x20)))))
                }
                sstore(0x00, or(v, add(shl(0x01, n), 0x01)))
            }
            default {
                sstore(0x00, shl(0x01, n))
                mstore(0x00, 0x00)
                let dst := keccak256(0x00, 0x20)
                let words := shr(0x05, add(n, 0x1f))
                let i := 0
                for { } lt(i, words) { i := add(i, 0x01) } {
                    sstore(add(dst, i), calldataload(add(loc, add(0x20, mul(0x20, i)))))
                }
            }
        }
    }

    
        function Unresolved_6d4ce63c() public view returns (bytes memory) {
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

}