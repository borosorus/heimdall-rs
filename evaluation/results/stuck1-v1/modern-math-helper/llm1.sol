// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;

/// @title            Decompiled Contract
/// @author           Jonathan Becker <jonathan@jbecker.dev>
///
/// @notice           This contract was decompiled using the heimdall-rs decompiler.

contract DecompiledContract {
    uint256 public unresolved_1b3ed722; // storage slot: 0x00

    event Event_c6d3a874(uint256, uint256);

    /// @custom:selector    0x641579a6
    function Unresolved_641579a6(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        unresolved_1b3ed722 = arg0;
    }

    /// @custom:selector    0x771602f7
    function Unresolved_771602f7(uint256) public pure {
        revert();
    }

    /// @custom:selector    0xc6888fa1
    function Unresolved_c6888fa1(uint256 arg0) public returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        if ((arg0 == 0) || (unresolved_1b3ed722 == arg0 * unresolved_1b3ed722 / arg0)) {
            emit Event_c6d3a874(arg0, arg0 * unresolved_1b3ed722);
            return arg0 * unresolved_1b3ed722;
        }
        return 0;
    }
}
