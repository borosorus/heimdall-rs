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
    /// @notice The value stored in storage slot 0; exposed by the generated public getter.
    /// @dev Original decompiled name: unresolved_6d4ce63c.
    uint256 public storedValue; // storage slot: 0x00
    
    /// @notice Emitted whenever `storedValue` is updated.
    /// @dev Original decompiled event name: Event_012c78e2.
    event ValueUpdated(uint256 value);
    
    /// @custom:selector    0x60fe47b1
    /// @custom:signature   Unresolved_60fe47b1(uint256 arg0) public payable
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    /// @notice             Stores the supplied value in contract storage and emits an update event.
    function Unresolved_60fe47b1(uint256 arg0) public {
        // `arg0` is the new value to persist in storage. The decompiled calldata
        // length check was redundant because Solidity's ABI decoder already
        // validates that a uint256 argument is present.
        storedValue = arg0;
        
        // Notify off-chain observers of the storage update.
        emit ValueUpdated(arg0);
    }
}
