// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;

/// @title            Decompiled Contract (cleaned)
/// @author           Jonathan Becker <jonathan@jbecker.dev>
/// @custom:version   heimdall-rs v0.9.2
///
/// @notice           This contract was decompiled using the heimdall-rs decompiler.
///                     It has been postprocessed for readability.
///
/// @custom:github    You can find the open-source decompiler here:
///                       https://heimdall.rs

contract DecompiledContract {
    // Likely the stored count / primary state variable (slot 0)
    uint256 public count; // storage slot: 0x00

    /// @custom:selector    0x2a1afcd9
    /// @custom:signature   Unresolved_2a1afcd9() public view returns (bytes memory)
    /// @notice             Reads a dynamic-length bytes/string from storage slot 1 and ABI-encodes it.
    function Unresolved_2a1afcd9() public view returns (bytes memory) {
        return _readStorageBytes(1);
    }

    /// @custom:selector    0x4ed3885e
    /// @custom:signature   Unresolved_4ed3885e(uint256 arg0) public
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    /// @notice             Sets the stored count to twice the input plus one.
    function Unresolved_4ed3885e(uint256 arg0) public {
        count = 0x01 + (arg0 + arg0);
    }

    /// @custom:selector    0x6d4ce63c
    /// @custom:signature   Unresolved_6d4ce63c() public view returns (bytes memory)
    /// @notice             Retrieves the stored dynamic bytes value (likely a `get` accessor).
    function Unresolved_6d4ce63c() public view returns (bytes memory) {
        return _readStorageBytes(1);
    }

    /// @notice             Helper to read a dynamic-length bytes/string from a storage slot.
    function _readStorageBytes(uint256 slot) internal view returns (bytes memory) {
        uint256 length;
        uint256 data;
        assembly {
            let packed := sload(slot)
            // If lowest bit is set, length is stored in the same slot (short data)
            if and(packed, 0x1) {
                length := shr(0x1, packed)
                data := shr(0x8, packed)
            } else {
                length := sload(add(slot, 0x1))
                data := sload(add(slot, 0x2))
            }
        }
        if (!(0x1f & length)) {
            return abi.encodePacked(0x20, length);
        } else {
            return abi.encodePacked(0x20, length, ~(0x0100 ** (0x20 - (0x1f & length)) - 0x01) & data);
        }
    }
}