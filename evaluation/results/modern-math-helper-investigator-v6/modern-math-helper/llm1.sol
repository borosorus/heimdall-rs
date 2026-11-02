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
    // Value stored in slot 0. Originally named `unresolved_1b3ed722`.
    uint256 public storedValue; // storage slot: 0x00

    // Emitted by the multiplication function. The decompiler omitted the event parameters.
    event Event_c6d3a874(uint256 value, uint256 product);

    function Unresolved_641579a6(uint256 newValue) public {
    storedValue = newValue;
}

    function Unresolved_771602f7(uint256 unusedValue) public pure {
    revert();
}

    function Unresolved_c6888fa1(uint256 value) public view returns (uint256) {
    return value * storedValue;
}
}
