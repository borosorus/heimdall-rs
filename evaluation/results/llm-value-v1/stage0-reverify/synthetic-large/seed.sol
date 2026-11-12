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
    uint256 var_c;
    address store_h; // storage slot: 0x00
    bytes32 store_f; // storage slot: 0x00
    uint256 public unresolved_ddca3f43; // storage slot: 0x01
    bytes store_c; // storage slot: 0x02
    bytes store_d; // storage slot: 0x03
    string public unresolved_06fdde03; // storage slot: 0x04
    bytes32 store_e; // storage slot: 0x05
    
    mapping(address => uint256) public unresolved_70a08231; // storage slot: 0x06
    mapping(address => mapping(address => uint256)) storage_map_b; // storage slot: 0x07
    
    error CustomError_f4d678b8();
    error CustomError_d92e233d();
    error CustomError_9e87fac8();
    error CustomError_3261c792();
    error CustomError_30cd7471();
    error CustomError_0dc149f0();
    error CustomError_00000000();
    event Event_47374573(uint256, uint256);
    event Event_6bbc5748(uint256);
    event Event_8be0079c(address, address);
    event Event_8c5be1e5(address, address, uint256);
    event Event_908408e3(address);
    event Event_d83d5281(uint256);
    event Event_ddf252ad(address, address, uint256);
    
    /// @custom:selector    0x095ea7b3
    /// @custom:signature   Unresolved_095ea7b3(address arg0, uint256 arg1) public payable returns (bool)
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_095ea7b3(address arg0, uint256 arg1) public payable returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        require(true);
        storage_map_b[msg.sender][arg0] = arg1;
        emit Event_8c5be1e5(msg.sender, arg0, arg1);
        return true;
    }
    
    /// @custom:selector    0x0b663fe2
    /// @custom:signature   Unresolved_0b663fe2(uint256 arg0) public view returns (bool)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_0b663fe2(uint256 arg0) public view returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        if (arg0 < store_c) {
            return arg0 >= store_c;
        } else {
            return arg0 <= store_d;
        }
    }
    
    /// @custom:selector    0x18160ddd
    /// @custom:signature   Unresolved_18160ddd() public view returns (uint256)
    function Unresolved_18160ddd() public view returns (uint256) {
        return store_e;
    }
    
    /// @custom:selector    0x23b872dd
    /// @custom:signature   Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public view
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public view {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);
        require(true);
        require(unresolved_70a08231[arg0] >= arg2);
    }
    
    /// @custom:selector    0x2e1a7d4d
    /// @custom:signature   Unresolved_2e1a7d4d(address arg0) public view returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_2e1a7d4d(address arg0) public view returns (uint256) {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20) {
            require(!uint8(store_f / 0x010000000000000000000000000000000000000000), CustomError_9e87fac8());
            require(unresolved_70a08231[msg.sender] >= arg0, CustomError_f4d678b8());
        }
        revert();
    
        return unresolved_70a08231[arg0];}
    
    /// @custom:selector    0x3f4ba83a
    /// @custom:signature   Unresolved_3f4ba83a() public payable
    function Unresolved_3f4ba83a() public payable {
        require(msg.sender == store_h, CustomError_30cd7471());
        store_f = 0 * 0x010000000000000000000000000000000000000000 | 0xffffffffffffffffffffff00ffffffffffffffffffffffffffffffffffffffff & store_f;
        emit Event_d83d5281(0);
    }
    
    /// @custom:selector    0x40c10f19
    /// @custom:signature   Unresolved_40c10f19(address arg0, address arg1) public view returns (uint256)
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_40c10f19(address arg0, address arg1) public view returns (uint256) {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40) {
            require(msg.sender == store_h, CustomError_30cd7471());
            require(arg0 != address(0), CustomError_d92e233d());
        }
        revert();
    
        return storage_map_b[arg0][arg1];}
    
    /// @custom:selector    0x42966c68
    /// @custom:signature   Unresolved_42966c68(address arg0) public view returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_42966c68(address arg0) public view returns (uint256) {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20) {
            require(unresolved_70a08231[msg.sender] >= arg0, CustomError_f4d678b8());
        }
        revert();
    
        return unresolved_70a08231[arg0];}
    
    /// @custom:selector    0x69fe0e2d
    /// @custom:signature   Unresolved_69fe0e2d(address arg0) public payable returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_69fe0e2d(address arg0) public payable returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(msg.sender == store_h, CustomError_30cd7471());
        require(arg0 <= 0x2710, CustomError_3261c792());
        unresolved_ddca3f43 = arg0;
        emit Event_6bbc5748(arg0);
    
        return unresolved_70a08231[arg0];}
    
    /// @custom:selector    0x8456cb59
    /// @custom:signature   Unresolved_8456cb59() public payable
    function Unresolved_8456cb59() public payable {
        require(msg.sender == store_h, CustomError_30cd7471());
        store_f = 0x010000000000000000000000000000000000000000 | 0xffffffffffffffffffffff00ffffffffffffffffffffffffffffffffffffffff & store_f;
        emit Event_d83d5281(0x01);
    }
    
    /// @custom:selector    0x860aefcf
    /// @custom:signature   Unresolved_860aefcf() public view returns (bytes memory)
    function Unresolved_860aefcf() public view returns (bytes memory) {
        return abi.encodePacked(store_c, store_d);
    }
    
    /// @custom:selector    0x8da5cb5b
    /// @custom:signature   Unresolved_8da5cb5b() public view returns (address)
    function Unresolved_8da5cb5b() public view returns (address) {
        return store_h;
    }
    
    /// @custom:selector    0xa9059cbb
    /// @custom:signature   Unresolved_a9059cbb(address arg0, uint256 arg1) public payable returns (bool)
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_a9059cbb(address arg0, uint256 arg1) public payable returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        require(true);
        require(arg0 != address(0), CustomError_d92e233d());
        require(unresolved_70a08231[msg.sender] >= arg1, CustomError_f4d678b8());
        if (unresolved_70a08231[msg.sender] - arg1 <= unresolved_70a08231[msg.sender]) {
            unresolved_70a08231[msg.sender] -= arg1;
            if (unresolved_70a08231[arg0] <= unresolved_70a08231[arg0] + arg1) {
                unresolved_70a08231[arg0] += arg1;
                emit Event_ddf252ad(msg.sender, arg0, arg1);
                return true;
            }
        }
    }
    
    /// @custom:selector    0xb187bd26
    /// @custom:signature   Unresolved_b187bd26() public view returns (bool)
    function Unresolved_b187bd26() public view returns (bool) {
        return uint8(store_f / 0x010000000000000000000000000000000000000000);
    }
    
    /// @custom:selector    0xb6b55f25
    /// @custom:signature   Unresolved_b6b55f25(address arg0) public view returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_b6b55f25(address arg0) public view returns (uint256) {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20) {
            require(!uint8(store_f / 0x010000000000000000000000000000000000000000), CustomError_9e87fac8());
            require(arg0 >= store_c, CustomError_3261c792());
        }
        revert();
    
        return unresolved_70a08231[arg0];}
    
    /// @custom:selector    0xc23f85d6
    /// @custom:signature   Unresolved_c23f85d6(address arg0) public view returns (bool)
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_c23f85d6(address arg0) public view returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(true);
        return abi.encodePacked(unresolved_70a08231[arg0], store_e, unresolved_ddca3f43, uint8(store_f / 0x010000000000000000000000000000000000000000));
    }
    
    /// @custom:selector    0xc4590d3f
    /// @custom:signature   Unresolved_c4590d3f(address arg0) public view returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_c4590d3f(address arg0) public view returns (uint256) {
        revert();
    
        return unresolved_70a08231[arg0];}
    
    /// @custom:selector    0xc47f0027
    /// @custom:signature   Unresolved_c47f0027(address arg0) public payable returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_c47f0027(address arg0) public payable returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(arg0 <= 0xffffffffffffffff);
        require(0x04 + arg0 + 0x1f < 0x04 + (msg.data.length - 0x04));
        require(msg.data[0x04 + arg0] <= 0xffffffffffffffff);
        require(0x04 + arg0 + 0x20 + msg.data[0x04 + arg0] <= 0x04 + (msg.data.length - 0x04));
        require(msg.sender == store_h, CustomError_30cd7471());
        if (msg.data[0x04 + arg0] <= 0xffffffffffffffff && (unresolved_06fdde03 & 0x01) - (unresolved_06fdde03 / 0x02 < 0x20)) {
            if (msg.data[0x04 + arg0] > 0x1f == 0x01) {
                if ((msg.data[0x04 + arg0] & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0) < msg.data[0x04 + arg0]) {
                    unresolved_06fdde03[0] = msg.data[0x04 + arg0 + 0x20] & ~(type(uint256).max >> 0x08 * (msg.data[0x04 + arg0] & 0x1f));
                }
                unresolved_06fdde03 = msg.data[0x04 + arg0] * 0x02 + 0x01;
            } else {
                if (!msg.data[0x04 + arg0]) {
                    unresolved_06fdde03 = 0 & ~(type(uint256).max >> 0x08 * msg.data[0x04 + arg0]) | 0x02 * msg.data[0x04 + arg0];
                } else {
                    unresolved_06fdde03 = msg.data[0x04 + arg0 + 0x20] & ~(type(uint256).max >> 0x08 * msg.data[0x04 + arg0]) | 0x02 * msg.data[0x04 + arg0];
                }
            }
            emit Event_47374573(var_c + 0x20 - var_c, msg.data[0x04 + arg0]);
        }
    
        return unresolved_70a08231[arg0];}
    
    /// @custom:selector    0xc4d66de8
    /// @custom:signature   Unresolved_c4d66de8(address arg0) public payable returns (uint256)
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_c4d66de8(address arg0) public payable returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(true);
        require(!uint8(store_f / 0x01000000000000000000000000000000000000000000), CustomError_0dc149f0());
        require(arg0 != address(0), CustomError_d92e233d());
        store_f = 0x01000000000000000000000000000000000000000000 | 0xffffffffffffffffffff00ffffffffffffffffffffffffffffffffffffffffff & store_f;
        store_f = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_f)));
        emit Event_908408e3(arg0);
    
        return unresolved_70a08231[arg0];}
    
    /// @custom:selector    0xdd62ed3e
    /// @custom:signature   Unresolved_dd62ed3e(address arg0, address arg1) public view returns (uint256)
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_dd62ed3e(address arg0, address arg1) public view returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        require(true);
    
        return storage_map_b[arg0][arg1];}
    
    /// @custom:selector    0xef8b30f7
    /// @custom:signature   Unresolved_ef8b30f7(uint256 arg0) public view returns (uint256)
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_ef8b30f7(uint256 arg0) public view returns (uint256) {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20) {
            require(arg0 >= store_c, CustomError_3261c792());
            if (((arg0) == 0) | unresolved_ddca3f43 == arg0 * unresolved_ddca3f43 / arg0 && arg0 - arg0 * unresolved_ddca3f43 / 0x2710 <= arg0) {
                return arg0 - arg0 * unresolved_ddca3f43 / 0x2710;
            }
        }
        revert();
    }
    
    /// @custom:selector    0xf2fde38b
    /// @custom:signature   Unresolved_f2fde38b(address arg0) public payable returns (uint256)
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_f2fde38b(address arg0) public payable returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(true);
        require(msg.sender == store_h, CustomError_30cd7471());
        require(arg0 != address(0), CustomError_d92e233d());
        store_f = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_f)));
        emit Event_8be0079c(store_h, arg0);
    
        return unresolved_70a08231[arg0];}
}