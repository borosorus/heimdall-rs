// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;

contract DecompiledContract {
    uint256 public count;

    function Unresolved_2a1afcd9() public view returns (bytes memory) {
        return _readStorageBytes(1);
    }

    function Unresolved_4ed3885e(uint256 arg0) public {
        count = 0x01 + (arg0 + arg0);
    }

    function Unresolved_6d4ce63c() public view returns (bytes memory) {
        return _readStorageBytes(1);
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