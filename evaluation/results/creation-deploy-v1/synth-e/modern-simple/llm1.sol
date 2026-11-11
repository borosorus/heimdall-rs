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
    uint256 public unresolved_6d4ce63c; // storage slot: 0x00
    constructor(uint256 arg0) {
        unresolved_6d4ce63c = arg0;
    }

    
    event Event_012c78e2(uint256);
    
    /// @custom:selector    0x60fe47b1
    /// @custom:signature   Unresolved_60fe47b1(uint256 arg0) public payable
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_60fe47b1(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        unresolved_6d4ce63c = arg0;
        emit Event_012c78e2(arg0);
    }
}