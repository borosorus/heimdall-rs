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
    uint256 store_d; // storage slot: 0x290decd9548b62a8d60345a988386fc84ba6bc95484008f6362f93160ef3e564 + store_a * 0x02
    
    
    /// @custom:selector    0x88702ee9
    /// @custom:signature   Unresolved_88702ee9(uint256 arg0) public view returns (bytes memory)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_88702ee9(uint256 arg0) public view returns (bytes memory) {
        if (arg0 < store_a) {
            uint256 var_b;
            var_b = 0x20 + (var_b + 0x20 * (((store_b & 0x0100 * ((store_b & 0x01) == 0) + type(uint256).max) / 0x02 + 0x1f) / 0x20));
            if((0x1f & var_g) == 0)) {
                return abi.encodePacked(store_b[0x02 * arg0].field_0.field_0.field_0, 0x20 + (0x20 + var_b) - var_b, var_g);
            } else {
                return abi.encodePacked(store_b[0x02 * arg0].field_0.field_0.field_0, 0x20 + (0x20 + var_b) - var_b, var_g, ~(0x0100 ** (0x20 - (0x1f & var_g)) - 0x01) & var_i);
            }
        }
    }
    
    /// @custom:selector    0xcf62fd39
    /// @custom:signature   Unresolved_cf62fd39(uint256 arg0, uint256 arg1) public returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_cf62fd39(uint256 arg0, uint256 arg1) public returns (uint256) {
        uint256 var_a;
        var_a = 0x40 + var_a;
        store_a += 0x01;
        store_c = address(var_g) | 0xffffffffffffffffffffffff0000000000000000000000000000000000000000 & store_c;
        store_d = 0x01 + (var_h + var_h);
        return store_a + 0x01 - 0x01;
    }
    
    /// @custom:selector    0xde8fa431
    /// @custom:signature   Unresolved_de8fa431() public view returns (uint256)
    function Unresolved_de8fa431() public view returns (uint256) {
        return store_a;
    }
}