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
    bytes public unresolved_8bf421ee; // storage slot: 0x01
    
    
    /// @custom:selector    0x6d4ce63c
    /// @custom:signature   Unresolved_6d4ce63c() public view returns (bytes memory)
    function Unresolved_6d4ce63c() public view returns (bytes memory) {
        uint256 var_a;
        var_a = 0x20 + (var_a + 0x20 * (((unresolved_8bf421ee & type(uint256).max + 0x0100 * ((unresolved_8bf421ee & 0x01) == 0)) / 0x02 + 0x1f) / 0x20));
        if((0x1f & var_g) == 0)) {
            return abi.encodePacked(0x20 + (0x20 + var_a) - var_a, 0x20 + (var_g + (0x20 + (0x20 + (0x20 + var_a))) - (0x1f & var_g)) - var_a, var_g, ~(0x0100 ** (0x20 - (0x1f & var_g)) - 0x01) & var_i, var_g);
        } else {
            return abi.encodePacked(0x20 + (0x20 + var_a) - var_a, 0x20 + (var_g + (0x20 + (0x20 + (0x20 + var_a))) - (0x1f & var_g)) - var_a, var_g, ~(0x0100 ** (0x20 - (0x1f & var_g)) - 0x01) & var_i, var_g, ~(0x0100 ** (0x20 - (0x1f & var_g)) - 0x01) & var_m);
        }
    }
}