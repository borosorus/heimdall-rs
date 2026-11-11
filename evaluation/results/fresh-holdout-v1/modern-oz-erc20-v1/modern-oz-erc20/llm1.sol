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
    uint256 public constant unresolved_313ce567 = 18;
    
    uint256 public unresolved_18160ddd; // storage slot: 0x02
    string public unresolved_06fdde03; // storage slot: 0x03
    string public unresolved_95d89b41; // storage slot: 0x04
    
    mapping(address => uint256) public unresolved_70a08231; // storage slot: 0x00
    mapping(address => mapping(address => uint256)) storage_map_b; // storage slot: 0x01
    
    error CustomError_ec442f05();
    error CustomError_e602df05();
    error CustomError_e450d38c();
    error CustomError_96c6fd1e();
    error CustomError_94280d62();
    error CustomError_00000000();
    event Event_8c5be1e5(address, address, uint256);
    event Event_ddf252ad(address, address, uint256);
    
    /// @custom:selector    0x095ea7b3
    /// @custom:signature   Unresolved_095ea7b3(address arg0, uint256 arg1) public payable returns (bool)
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_095ea7b3(address arg0, uint256 arg1) public payable returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        require(true);
        require(msg.sender != address(0), CustomError_e602df05());
        require(arg0 != address(0), CustomError_94280d62());
        storage_map_b[msg.sender][arg0] = arg1;
        if(true) {
            emit Event_8c5be1e5(msg.sender, arg0, arg1);
        }
        return true;
    }
    
    /// @custom:selector    0x23b872dd
    /// @custom:signature   Unresolved_23b872dd(address arg0) public pure
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public pure {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);
        require(true);
    }
    
    /// @custom:selector    0xa9059cbb
    /// @custom:signature   Unresolved_a9059cbb(address arg0, uint256 arg1) public payable returns (bool)
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_a9059cbb(address arg0, uint256 arg1) public payable returns (bool) {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40) {
            require(msg.sender != address(0), CustomError_96c6fd1e());
            require(arg0 != address(0), CustomError_ec442f05());
            if(msg.sender != address(0)) {
                require(unresolved_70a08231[msg.sender] >= arg1, CustomError_e450d38c());
                unresolved_70a08231[msg.sender] -= arg1;
                if(arg0 != address(0)) {
                    unresolved_70a08231[arg0] += arg1;
                } else {
                    unresolved_18160ddd -= arg1;
                }
                emit Event_ddf252ad(msg.sender, arg0, arg1);
                return true;
            }
        }
        revert();
    }
    
    /// @custom:selector    0xdd62ed3e
    /// @custom:signature   Unresolved_dd62ed3e(address arg0) public pure
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_dd62ed3e(address arg0, uint256 arg1) public pure {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        require(true);
    }
}