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
    
    /// @custom:selector    0x570e1a36
    /// @custom:signature   Unresolved_570e1a36(uint256 arg0, uint256 arg1) public payable returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_570e1a36(uint256 arg0, uint256 arg1) public payable returns (uint256) {
        require(msg.data.length + 0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc >= 0x20);
        require(arg0 <= 0xffffffffffffffff);
        require(arg0 + 0x23 < msg.data.length);
        require(uint256(uint8(msg.data[0x04 + arg0])) <= 0xffffffffffffffff);
        require(arg0 + uint256(uint8(msg.data[0x04 + arg0])) + 0x24 <= msg.data.length);
        require(0x14 <= uint256(uint8(msg.data[0x04 + arg0])));
        if (uint256(uint8(msg.data[0x04 + arg0])) + 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffec <= 0xffffffffffffffff && !(0x80 + (((uint256(uint8(msg.data[0x04 + arg0])) + 0x0b) & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) + 0x3f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) > 0xffffffffffffffff || 0x80 + (((uint256(uint8(msg.data[0x04 + arg0])) + 0x0b) & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) + 0x3f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) < 0x80)) {
            uint256 var_d = uint256(uint8(msg.data[0x04 + arg0])) + 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffec;
            bool success = true;
        if (!success) {
                return 0;
            } else {
                return uint256(uint160(address(uint160(uint256(0x4e487b71) * 2 ** 160))));
            }
        }
    }
}