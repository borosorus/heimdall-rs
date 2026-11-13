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
    uint256 public unresolved_1b3ed722; // storage slot: 0x00
    
    event Event_c6d3a874(uint256, uint256);
    
    /// @custom:selector    0x641579a6
    /// @custom:signature   Unresolved_641579a6(uint256 arg0) public payable
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_641579a6(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        unresolved_1b3ed722 = arg0;
    }
    
    /// @custom:selector    0x771602f7
    /// @custom:signature   Unresolved_771602f7(uint256 arg0) public pure
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_771602f7(uint256 arg0) public pure {
        revert();
    }
    
    /// @custom:selector    0xc6888fa1
    /// @custom:signature   Unresolved_c6888fa1(uint256 arg0) public view returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_c6888fa1(uint256 arg0) public  returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        if (((arg0) == 0) || (unresolved_1b3ed722 == arg0 * unresolved_1b3ed722 / arg0)) {
            emit Event_c6d3a874(arg0, arg0 * unresolved_1b3ed722);
            return arg0 * unresolved_1b3ed722;
        }
    }
}