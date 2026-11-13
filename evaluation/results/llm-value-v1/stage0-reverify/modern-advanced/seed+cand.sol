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
    uint256 var_e;
    uint256 var_g;
    uint256 var_h;
    uint256 public unresolved_f2c9ecd8; // storage slot: 0x00
    bytes32 store_c; // storage slot: 0x01
    uint8 store_b; // storage slot: 0x01
    bytes public unresolved_89ea642f; // storage slot: 0x02
    address public unresolved_38cc4831; // storage slot: 0x03
    bytes32 store_h; // storage slot: 0x03
    address store_f; // storage slot: 0x04
    bytes32 store_a; // storage slot: 0x04
    
    event Event_88749aed(address);
    event Event_9d164645(uint256);
    event Event_9ec82549(uint256);
    event Event_b26b3b59(uint256);
    event Event_c3e10738(uint256, uint256, uint256, address, uint256);
    event Event_d31368d6(uint256);
    event Event_d8247311(uint256, uint256);
    
    /// @custom:selector    0x01ef8faa
    /// @custom:signature   Unresolved_01ef8faa(address arg0) public payable
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_01ef8faa(address arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(true);
        store_a = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_a)));
    }
    
    /// @custom:selector    0x12a7b914
    /// @custom:signature   Unresolved_12a7b914() public view returns (bool)
    function Unresolved_12a7b914() public view returns (bool) {
        return store_b;
    }
    
    /// @custom:selector    0x1e26fd33
    /// @custom:signature   Unresolved_1e26fd33(uint256 arg0) public payable
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_1e26fd33(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        store_c = arg0 | 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff00 & store_c;
        emit Event_d31368d6(arg0);
    }
    
    /// @custom:selector    0x349a0054
    /// @custom:signature   Unresolved_349a0054(uint256 arg0, uint256 arg1, uint256 arg2, address arg3) public payable
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    /// @param              arg2 ["uint256", "bytes32", "int256"]
    /// @param              arg3 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_349a0054(uint256 arg0, uint256 arg1, uint256 arg2, address arg3) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x80);
        require(arg2 <= 0xffffffffffffffff);
        require(0x04 + arg2 + 0x1f < 0x04 + (msg.data.length - 0x04));
        if (msg.data[0x04 + arg2] <= 0xffffffffffffffff && !(var_a + ((msg.data[0x04 + arg2] + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) + 0x20 + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) > 0xffffffffffffffff | var_a + ((msg.data[0x04 + arg2] + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) + 0x20 + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) < var_a)) {
            uint256 var_a;
            var_a = var_a + ((msg.data[0x04 + arg2] + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) + 0x20 + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0);
            require(0x04 + arg2 + 0x20 + msg.data[0x04 + arg2] <= 0x04 + (msg.data.length - 0x04));
            require(true);
            require((address(this).code.length) != 0);
            (bool success, bytes memory ret0) = address(address(this)).Unresolved_3fb5c1cb(arg0); // call
            require(success);
            require((address(this).code.length) != 0);
            (bool success, bytes memory ret0) = address(address(this)).Unresolved_1e26fd33(arg1); // call
            require(success);
            require((address(this).code.length) != 0);
            (bool success, bytes memory ret0) = address(address(this)).Unresolved_7fcaf666(0x04 + var_a + 0x20 - (0x04 + var_a)); // call
            require(success);
            require((address(this).code.length) != 0);
            (bool success, bytes memory ret0) = address(address(this)).Unresolved_e30081a0(arg3); // call
            require(success);
            emit Event_c3e10738(arg0, arg1, var_a + 0x80 - var_a, arg3, var_g);
        }
    }
    
    /// @custom:selector    0x3fb5c1cb
    /// @custom:signature   Unresolved_3fb5c1cb(uint256 arg0) public payable
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_3fb5c1cb(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        unresolved_f2c9ecd8 = arg0;
        emit Event_9ec82549(arg0);
    }
    
    /// @custom:selector    0x575f4505
    /// @custom:signature   Unresolved_575f4505(uint256 arg0) public payable returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_575f4505(uint256 arg0) public payable returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        (bool success, bytes memory ret0) = address(store_f).Unresolved_c6888fa1(arg0); // call
        require(success);
        uint256 var_c;
        var_c = var_c + (ret0.length + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0);
        require(var_c + ret0.length - var_c >= 0x20);
        emit Event_9d164645(var_e);
        return var_e;
    }
    
    /// @custom:selector    0x7fcaf666
    /// @custom:signature   Unresolved_7fcaf666(uint256 arg0) public payable
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_7fcaf666(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(arg0 <= 0xffffffffffffffff);
        require(0x04 + arg0 + 0x1f < 0x04 + (msg.data.length - 0x04));
        if (msg.data[0x04 + arg0] <= 0xffffffffffffffff && !(var_a + ((msg.data[0x04 + arg0] + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) + 0x20 + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) > 0xffffffffffffffff | var_a + ((msg.data[0x04 + arg0] + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) + 0x20 + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) < var_a)) {
            uint256 var_a;
            var_a = var_a + ((msg.data[0x04 + arg0] + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) + 0x20 + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0);
            require(0x04 + arg0 + 0x20 + msg.data[0x04 + arg0] <= 0x04 + (msg.data.length - 0x04));
            uint256 var_c = msg.data[0x04 + arg0 + 0x20:0x04 + arg0 + 0x20 + msg.data[0x04 + arg0]];
            if (var_e <= 0xffffffffffffffff && (unresolved_89ea642f & 0x01) - (unresolved_89ea642f / 0x02 < 0x20)) {
                if (var_e > 0x1f == 0x01) {
                    if ((var_e & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) < var_e) {
                        unresolved_89ea642f[0] = var_c & ~(type(uint256).max >> 0x08 * (var_e & 0x1f));
                    }
                    unresolved_89ea642f = var_e * 0x02 + 0x01;
                } else {
                    if (((var_e) == 0)) {
                        unresolved_89ea642f = 0 & ~(type(uint256).max >> 0x08 * var_e) | 0x02 * var_e;
                    } else {
                        unresolved_89ea642f = var_c & ~(type(uint256).max >> 0x08 * var_e) | 0x02 * var_e;
                    }
                }
                emit Event_d8247311(var_a + 0x20 - var_a, var_e);
            }
        }
    }
    
    /// @custom:selector    0x8d5d4de7
    /// @custom:signature   Unresolved_8d5d4de7() public view returns (address)
    function Unresolved_8d5d4de7() public view returns (address) {
        return store_f;
    }
    
    /// @custom:selector    0x981f5499
    /// @custom:signature   Unresolved_981f5499() public view returns (bool)
    function Unresolved_981f5499() public view returns (bool) {
        if ((unresolved_89ea642f & 0x01) - (unresolved_89ea642f / 0x02 < 0x20)) {
            uint256 var_a;
            var_a = var_a + (0x20 + (0x1f + unresolved_89ea642f / 0x02) / 0x20 * 0x20);
            if ((unresolved_89ea642f & 0x01) - (unresolved_89ea642f / 0x02 < 0x20)) {
                return abi.encodePacked(unresolved_f2c9ecd8, store_b, var_a + 0x80 - var_a, unresolved_38cc4831, var_g);
            }
        }
    }
    
    /// @custom:selector    0xd0da9af5
    /// @custom:signature   Unresolved_d0da9af5(uint256 arg0) public payable returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_d0da9af5(uint256 arg0) public payable returns (uint256) {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20) {
            uint256 var_b = 0x24 + var_c + 0x20 - var_c - 0x20;
            uint256 var_c;
            var_c = 0x24 + var_c + 0x20;
            (bool success, bytes memory ret0) = address(store_f).Unresolved_(memory[var_c:var_c + (var_c + var_g - var_c)]); // delegatecall
            if (ret0.length == 0) {
                require(success, "Delegate call failed");
                require(0x80 + var_h - 0x80 >= 0x20);
                emit Event_b26b3b59(var_b);
                return var_b;
            } else {
                uint256 var_c = var_c + (ret0.length + 0x3f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0);
                revert("Delegate call failed");
            }
        }
        revert();
    }
    
    /// @custom:selector    0xe30081a0
    /// @custom:signature   Unresolved_e30081a0(address arg0) public payable
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_e30081a0(address arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(true);
        store_h = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_h)));
        emit Event_88749aed(arg0);
    }
}