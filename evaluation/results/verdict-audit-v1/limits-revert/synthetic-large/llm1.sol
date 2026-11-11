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
    bytes32 store_f; // storage slot: 0x00
    uint256 public unresolved_ddca3f43; // storage slot: 0x01
    uint256 store_c; // storage slot: 0x02
    uint256 store_d; // storage slot: 0x03
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
    
    function Unresolved_095ea7b3(address arg0, uint256 arg1) public payable returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        storage_map_b[msg.sender][arg0] = arg1;
        emit Event_8c5be1e5(msg.sender, arg0, arg1);
        return true;
    }
    
    function Unresolved_0b663fe2(uint256 arg0) public view returns (bool) {
        if (arg0 < store_c) {
            return arg0 >= store_c;
        } else {
            return arg0 <= store_d;
        }
    }
    
    function Unresolved_18160ddd() public view returns (uint256) {
        return var_c;
    }
    
    function Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);
        require(unresolved_70a08231[arg0] >= arg2, CustomError_f4d678b8());
        require(storage_map_b[arg0][msg.sender] >= arg2, CustomError_f4d678b8());
        storage_map_b[arg0][msg.sender] -= arg2;
        unresolved_70a08231[arg0] -= arg2;
        unresolved_70a08231[address(uint160(arg1))] += arg2;
        emit Event_ddf252ad(arg0, address(uint160(arg1)), arg2);
    }
    
    function Unresolved_2e1a7d4d(uint256 arg0) public {
        require(uint8(uint256(store_f) / 0x010000000000000000000000000000000000000000) == 0, CustomError_9e87fac8());
        require(unresolved_70a08231[msg.sender] >= arg0, CustomError_f4d678b8());
        unresolved_70a08231[msg.sender] = unresolved_70a08231[msg.sender] - arg0;
        var_c -= arg0;
        emit Event_ddf252ad(msg.sender, address(0), arg0);
    }
    
    function Unresolved_3f4ba83a() public {
        require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
        store_f = bytes32(uint256(store_f) & 0x00ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff);
        emit Event_d83d5281(0x00);
    }
    
    /// @custom:selector    0x40c10f19
    /// @custom:signature   Unresolved_40c10f19(address arg0, uint256 arg1) public view
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_40c10f19(address arg0, uint256 arg1) public {
        require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
        require(arg0 != address(0), CustomError_d92e233d());
        unresolved_70a08231[arg0] += arg1; var_c += arg1;
        emit Event_ddf252ad(address(0), arg0, arg1);
    }
    
    /// @custom:selector    0x42966c68
    /// @custom:signature   Unresolved_42966c68(uint256 arg0) public view
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_42966c68(uint256 arg0) public {
        require(unresolved_70a08231[msg.sender] >= arg0, CustomError_f4d678b8());
        unresolved_70a08231[msg.sender] -= arg0;
        var_c -= arg0;
        emit Event_ddf252ad(msg.sender, address(0), arg0);
    }
    
    /// @custom:selector    0x69fe0e2d
    /// @custom:signature   Unresolved_69fe0e2d(uint256 arg0) public payable
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_69fe0e2d(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
        require(arg0 <= 0x2710, CustomError_3261c792());
        unresolved_ddca3f43 = arg0;
        emit Event_6bbc5748(arg0);
    }
    
    /// @custom:selector    0x8456cb59
    /// @custom:signature   Unresolved_8456cb59() public payable
    function Unresolved_8456cb59() public payable {
        require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
        store_f = bytes32(uint256(store_f) | 0x0100000000000000000000000000000000000000000000000000000000000000);
        emit Event_d83d5281(0x01);
    }
    
    /// @custom:selector    0x860aefcf
    /// @custom:signature   Unresolved_860aefcf() public view returns (bytes memory)
    function Unresolved_860aefcf() public view returns (uint256, uint256) {
        revert CustomError_3261c792();
    }
    
    /// @custom:selector    0x8da5cb5b
    /// @custom:signature   Unresolved_8da5cb5b() public view returns (address)
    function Unresolved_8da5cb5b() public view returns (address) {
        return address(uint160(uint256(store_f)));
    }
    
    /// @custom:selector    0xa9059cbb
    /// @custom:signature   Unresolved_a9059cbb(address arg0, uint256 arg1) public returns (bool)
    function Unresolved_a9059cbb(address arg0, uint256 arg1) public returns (bool) {
        require(uint160(arg0) != 0, CustomError_d92e233d());
        require(unresolved_70a08231[msg.sender] >= arg1, CustomError_f4d678b8());
        unchecked {
            unresolved_70a08231[msg.sender] = unresolved_70a08231[msg.sender] - arg1;
            unresolved_70a08231[arg0] = unresolved_70a08231[arg0] + arg1;
        }
        emit Event_ddf252ad(msg.sender, arg0, arg1);
        return true;
    }
    
    /// @custom:selector    0xb187bd26
    /// @custom:signature   Unresolved_b187bd26() public view returns (bool)
    function Unresolved_b187bd26() public view returns (bool) {
        return uint256(store_f) / 0x0100000000000000000000000000000000000000000000000000000000000000 == 1;
    }
    
    function Unresolved_b6b55f25(uint256 arg0) public {
        if (store_c > arg0 || arg0 > store_d) { revert CustomError_3261c792(); }
        if (uint256(store_f) / 0x0100000000000000000000000000000000000000000000000000000000000000 == 1) { revert CustomError_3261c792(); }
        uint256 net = arg0 - (arg0 * unresolved_ddca3f43) / 10000;
        unresolved_70a08231[msg.sender] += net;
        var_c += net;
    }
    
    function Unresolved_c23f85d6(address arg0) public view returns (uint256, uint256, uint256, uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        return (unresolved_70a08231[arg0], var_c, unresolved_ddca3f43, 0);
    }
    
    function Unresolved_c4590d3f(uint256 arg0) public {
        require(arg0 == 1);
        store_c = arg0;
        store_d = uint256(bytes32(msg.data[0x24:0x44]));
        emit Event_d83d5281(arg0);
    }
    
    function Unresolved_c47f0027(uint256 arg0) public {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
        uint256 len = uint256(uint8(msg.data[0x24 + 0x1f]));
        bytes memory s = new bytes(len);
        for (uint256 k = 0; k < len; k++) { s[k] = msg.data[0x44 + k]; }
        unresolved_06fdde03 = string(s);
        emit Event_d83d5281(arg0);
    }
    
    function Unresolved_c4d66de8(address arg0) public {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(store_f[21] == 0, CustomError_0dc149f0());
        require(uint160(arg0) != 0, CustomError_d92e233d());
        store_f = bytes32(uint256(0x01)) | (bytes32(~uint256(0xff) << 160) & store_f);
        store_f = bytes32(uint256(uint160(arg0))) | (bytes32(uint256(0xffffffffffffffffffffffff) << 160) & store_f);
        emit Event_908408e3(arg0);
    }
    
    function Unresolved_dd62ed3e(address arg0, uint256 arg1) public view returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        return storage_map_b[arg0][address(uint160(arg1))];
    }
    
    function Unresolved_ef8b30f7(uint256 arg0) public view returns (uint256) {
    if (store_c > arg0 || arg0 > store_d) { revert CustomError_3261c792(); }
    return arg0 - ((arg0 * unresolved_ddca3f43) / 10000);
}
    
    function Unresolved_f2fde38b(address arg0) public {
    require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
    require(arg0 != address(0), CustomError_d92e233d());
    store_f = bytes32(uint256(uint160(arg0)));
}
}