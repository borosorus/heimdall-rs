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
    fallback(bytes calldata) external payable returns (bytes memory) {
        require(msg.data.length >= 0x04);
        require(uint32(bytes4(msg.data[0:4])) == 0x819439);
        return abi.encodePacked(block.number, block.timestamp, address(block.coinbase), block.basefee);
    }
    
}