// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;

contract DecompiledContract {
    uint256 public count;

    function Unresolved_2a1afcd9() public view returns (bytes memory) {
        return _readStorageBytes(1);
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

    function Unresolved_6d4ce63c() public view returns (bytes memory b) {
        uint256 len = count;
        b = new bytes(len);
        assembly {
            mstore(0x00, 0)
            let src := keccak256(0x00, 0x20)
            let dst := add(b, 0x20)
            for { let i := 0 } lt(i, len) { i := add(i, 0x20) } {
                mstore(add(dst, i), sload(add(src, div(i, 0x20))))
            }
            mstore(0x40, add(dst, and(add(len, 31), not(31))))
        }
    }

    function _readStorageBytes(uint256 slot) internal view returns (bytes memory) {
        uint256 length;
        uint256 data;
        assembly {
            let packed := sload(slot)
            switch and(packed, 0x1)
            case 0 {
                length := sload(add(slot, 0x1))
                data := sload(add(slot, 0x2))
            }
            default {
                length := shr(0x1, packed)
                data := shr(0x8, packed)
            }
        }
        if ((0x1f & length) == 0) {
            return abi.encodePacked(uint256(0x20), length);
        } else {
            uint256 mask = ~(0x0100 ** (0x20 - (0x1f & length)) - 0x01);
            return abi.encodePacked(uint256(0x20), length, mask & data);
        }
    }
}