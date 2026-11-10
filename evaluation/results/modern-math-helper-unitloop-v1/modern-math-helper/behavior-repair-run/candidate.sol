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

    /// @custom:selector    0x641579a6
    /// @custom:signature   Unresolved_641579a6(uint256 arg0) public payable
    /// @param              newValue ["uint256", "bytes32", "int256"]
    /// @notice             Stores `newValue` as the contract's current stored value.
    function Unresolved_641579a6(uint256 newValue) public payable {
    // The original calldata-length check was redundant with ABI decoding.
    require(msg.value == 0);
    storedValue = newValue;
}

    /// @custom:selector    0x771602f7
    /// @custom:signature   Unresolved_771602f7(uint256 arg0) public pure
    /// @param              unusedValue ["uint256", "bytes32", "int256"]
    /// @notice             Unconditionally reverts; this function is not usable.
    function Unresolved_771602f7(uint256 unusedValue) public pure {
        revert();
    }

    /// @custom:selector    0xc6888fa1
    /// @custom:signature   Unresolved_c6888fa1(uint256 arg0) public view returns (uint256)
    /// @param              value ["uint256", "bytes32", "int256"]
    /// @notice             Multiplies `value` by the stored value, emits the result, and returns it when the multiplication does not overflow.
    // Note: mutability changed from `view` to non-view because this function emits an event.
    function Unresolved_c6888fa1(uint256 value) public returns (uint256) {
        uint256 product = value * storedValue;
        if (value != 0 && product / value != storedValue) {
            assembly {
                let ptr := mload(0x40)
                mstore(ptr, 0x4e487b7100000000000000000000000000000000000000000000000000000000)
                mstore(add(ptr, 0x04), 0x11)
                revert(ptr, 0x24)
            }
        }
        emit Event_c6d3a874(value, product);
        return product;
    }
}
