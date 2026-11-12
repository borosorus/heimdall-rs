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
    uint256 var_h;
    uint256 var_i;
    bytes store_a; // storage slot: 0x00
    address store_b; // storage slot: 0x02 * arg0 + keccak256(0) + 0x01
    bytes32 store_c; // storage slot: store_a * 0x02 + 0x290decd9548b62a8d60345a988386fc84ba6bc95484008f6362f93160ef3e563
    uint256 store_d;     function Unresolved_88702ee9(uint256 arg0) public view returns (address, string memory) {
        uint256 len;
        address who;
        string memory payload;
        assembly {
            let scratch := mload(0x40)
            mstore(scratch, 0x00)
            let base := keccak256(scratch, 0x20)
            len := sload(0x00)
            if iszero(lt(arg0, len)) {
                invalid()
            }
            let wslot := add(base, add(mul(2, arg0), 0))
            let dslot := add(base, add(mul(2, arg0), 1))
            who := and(sload(wslot), 0xffffffffffffffffffffffffffffffffffffffff)
            let v := sload(dslot)
            let n := 0
            switch and(v, 0x01)
            case 0 { n := shr(0x01, v) }
            default { n := shr(0x01, and(v, 0xff)) }
            let data := add(mload(0x40), 0x20)
            payload := mload(0x40)
            mstore(payload, n)
            switch n
            case 0 {
                mstore(0x40, add(data, 0x20))
            }
            default {
                switch and(v, 0x01)
                case 1 {
                    let i := 0
                    for { } lt(i, n) { i := add(i, 0x01) } {
                        mstore8(add(data, i), byte(i, v))
                    }
                    mstore(0x40, add(data, 0x20))
                }
                default {
                    let full := shr(0x05, add(n, 0x1f))
                    mstore(add(data, mul(0x20, full)), dslot)
                    let src := keccak256(add(data, mul(0x20, full)), 0x20)
                    let i := 0
                    for { } lt(i, full) { i := add(i, 0x01) } {
                        mstore(add(data, mul(0x20, i)), sload(add(src, i)))
                    }
                    mstore(0x40, add(data, mul(0x20, add(full, 0x01))))
                }
            }
        }
        return (who, payload);
    }

    
        function Unresolved_cf62fd39(uint256 arg0, uint256 arg1) public returns (uint256) {
        uint256 len;
        assembly {
            let scratch := mload(0x40)
            mstore(scratch, 0x00)
            let base := keccak256(scratch, 0x20)
            len := sload(0x00)
            let idx := len
            let wslot := add(base, add(mul(2, idx), 0))
            let dslot := add(base, add(mul(2, idx), 1))
            sstore(0x00, add(len, 0x01))
            sstore(wslot, and(calldataload(0x04), 0xffffffffffffffffffffffffffffffffffffffff))
            let d := add(0x04, calldataload(0x24))
            let n := calldataload(d)
            switch lt(n, 0x20)
            case 1 {
                let v := 0
                let i := 0
                for { } lt(i, n) { i := add(i, 0x01) } {
                    v := add(v, shl(mul(8, sub(31, i)), byte(i, calldataload(add(d, 0x20)))))
                }
                v := or(v, add(shl(0x01, n), 0x01))
                sstore(dslot, v)
            }
            default {
                sstore(dslot, shl(0x01, n))
                mstore(scratch, dslot)
                let src := keccak256(scratch, 0x20)
                let words := shr(0x05, add(n, 0x1f))
                let i := 0
                for { } lt(i, words) { i := add(i, 0x01) } {
                    sstore(add(src, i), calldataload(add(d, add(0x20, mul(0x20, i)))))
                }
            }
        }
        return len;
    }

    
        function Unresolved_de8fa431() public view returns (uint256) {
        uint256 v;
        assembly {
            v := sload(0x00)
        }
        return v;
    }

}