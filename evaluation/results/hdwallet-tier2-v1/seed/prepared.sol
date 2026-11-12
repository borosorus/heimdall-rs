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
    bytes store_a; // storage slot: 0x00
    
    
    /// @custom:selector    0x2a1afcd9
    /// @custom:signature   Unresolved_2a1afcd9() public view returns (bytes memory)
    function Unresolved_2a1afcd9() public view returns (bytes memory) {
        if((0x1f & var_f) == 0)) {
            return abi.encodePacked(uint256(0x20), var_f);
        } else {
            return abi.encodePacked(uint256(0x20), var_f, ~(0x0100 ** (0x20 - (0x1f & var_f)) - 0x01) & var_h);
        }
    }
    
    /// @custom:selector    0x4ed3885e
    /// @custom:signature   Unresolved_4ed3885e(uint256 arg0) public
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_4ed3885e(uint256 arg0) public {
        store_a = 0x01 + (var_e + var_e);
    }
    
    /// @custom:selector    0x6d4ce63c
    /// @custom:signature   Unresolved_6d4ce63c() public view returns (bytes memory)
    function Unresolved_6d4ce63c() public view returns (bytes memory) {
        if((0x1f & var_f) == 0)) {
            return abi.encodePacked(uint256(0x20), var_f);
        } else {
            return abi.encodePacked(uint256(0x20), var_f, ~(0x0100 ** (0x20 - (0x1f & var_f)) - 0x01) & var_h);
        }
    }
}