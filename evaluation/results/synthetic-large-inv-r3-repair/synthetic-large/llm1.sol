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
    
    function Unresolved_095ea7b3(address arg0, uint256 arg1) public payable returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        require(true);
        storage_map_b[msg.sender][arg0] = arg1;
        emit Event_8c5be1e5(msg.sender, arg0, arg1);
        return true;
    }
    
    function Unresolved_0b663fe2(uint256 arg0) public view returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        if (arg0 < uint256(store_c.length)) {
            return arg0 >= uint256(store_c.length);
        } else {
            return arg0 <= uint256(store_d.length);
        }
    }
    
    function Unresolved_18160ddd() public view returns (uint256) {
        return var_c;
    }
    
    function Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public pure {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);
        require(true);
    }
    
    function Unresolved_2e1a7d4d(uint256 arg0) public {
        require(uint8(uint256(store_f) / 0x010000000000000000000000000000000000000000) == 0, CustomError_9e87fac8());
        require(unresolved_70a08231[msg.sender] >= arg0, CustomError_f4d678b8());
        unchecked {
            uint256 balance = unresolved_70a08231[msg.sender] - arg0;
            unresolved_70a08231[msg.sender] = balance;
            var_c = var_c - arg0;
        }
        emit Event_ddf252ad(msg.sender, address(0), arg0);
    }
    
    function Unresolved_3f4ba83a() public {
        require(msg.sender == store_h, CustomError_30cd7471());
        store_f = bytes32(uint256(0 * 0x010000000000000000000000000000000000000000) | (uint256(0xffffffffffffffffffffff00ffffffffffffffffffffffffffffffffffffffff) & uint256(store_f)));
        emit Event_d83d5281(0);
    }
    
    function Unresolved_40c10f19(address arg0, uint256 arg1) public {
        require(msg.sender == store_h, CustomError_30cd7471());
        require(arg0 != address(0), CustomError_d92e233d());
        uint256 balance = unresolved_70a08231[arg0];
        uint256 newBalance;
        uint256 newSupply;
        unchecked {
            newBalance = balance + arg1;
            newSupply = unresolved_ddca3f43 + arg1;
        }
        require(newBalance >= balance && newSupply >= unresolved_ddca3f43, CustomError_00000000());
        unresolved_70a08231[arg0] = newBalance;
        unresolved_ddca3f43 = newSupply;
        emit Event_ddf252ad(address(0), arg0, arg1);
    }
    
    function Unresolved_42966c68(uint256 arg0) public {
        require(unresolved_70a08231[msg.sender] >= arg0, CustomError_f4d678b8());
        uint256 newBalance;
        uint256 newSupply;
        unchecked {
            newBalance = unresolved_70a08231[msg.sender] - arg0;
            newSupply = unresolved_ddca3f43 - arg0;
        }
        require(newBalance <= unresolved_70a08231[msg.sender] && newSupply <= unresolved_ddca3f43, CustomError_00000000());
        unresolved_70a08231[msg.sender] = newBalance;
        unresolved_ddca3f43 = newSupply;
        emit Event_ddf252ad(msg.sender, address(0), arg0);
    }
    
    function Unresolved_69fe0e2d(uint256 arg0) public {
        require(msg.sender == store_h, CustomError_30cd7471());
        require(arg0 <= 0x2710, CustomError_3261c792());
        unresolved_ddca3f43 = arg0;
        emit Event_6bbc5748(arg0);
    }
    
    function Unresolved_8456cb59() public {
        require(msg.sender == store_h, CustomError_30cd7471());
        store_f = bytes32(uint256(store_f) | 0x010000000000000000000000000000000000000000);
        emit Event_d83d5281(0x01);
    }
    
    function Unresolved_860aefcf() public view returns (bytes memory) {
        return abi.encodePacked(store_c, store_d);
    }
    
    function Unresolved_8da5cb5b() public view returns (address) {
        return store_h;
    }
    
    function Unresolved_a9059cbb(address arg0, uint256 arg1) public returns (bool) {
        require(uint160(arg0) != 0, CustomError_d92e233d());
        require(unresolved_70a08231[msg.sender] >= arg1, CustomError_f4d678b8());
        unresolved_70a08231[msg.sender] -= arg1;
        unresolved_70a08231[arg0] += arg1;
        emit Event_ddf252ad(msg.sender, arg0, arg1);
        return true;
    }
    
    function Unresolved_b187bd26() public view returns (bool) {
        return uint256(store_f) / 0x0100000000000000000000000000000000000000000000000000000000000000 == 1;
    }
    
    function Unresolved_b6b55f25(uint256 arg0) public view {
        require(uint8(uint256(store_f) / 0x010000000000000000000000000000000000000000) == 0, CustomError_9e87fac8());
        require(arg0 >= uint256(store_c.length), CustomError_3261c792());
        revert();
    }
    
    function Unresolved_c23f85d6(address arg0) public view returns (uint256, uint256, uint256, uint256) {
        return (unresolved_70a08231[arg0], unresolved_ddca3f43, 100, 0);
    }
    
    function Unresolved_c4590d3f(uint256 arg0) public pure {
        revert();
    }
    
    function Unresolved_c47f0027(uint256 arg0) public payable {
        require(arg0 <= 0xffffffffffffffff);
        require(0x04 + arg0 + 0x1f < 0x04 + (msg.data.length - 0x04));
        uint256 len = uint256(uint8(msg.data[0x04 + arg0]));
        require(len <= 0xffffffffffffffff);
        require(0x04 + arg0 + 0x20 + len <= 0x04 + (msg.data.length - 0x04));
        require(msg.sender == store_h, CustomError_30cd7471());
        if (len <= 0xffffffffffffffff && bytes(unresolved_06fdde03).length < 0x20) {
            bytes memory data = new bytes(len);
            for (uint256 i = 0; i < len; i++) {
                data[i] = bytes1(msg.data[0x04 + arg0 + 0x20 + i]);
            }
            unresolved_06fdde03 = string(data);
            emit Event_47374573(0x20, len);
        }
    }
    
    function Unresolved_c4d66de8(address arg0) public payable {
        require(store_f[21] == 0, CustomError_0dc149f0());
        require(uint160(arg0) != 0, CustomError_d92e233d());
        store_h = arg0;
        emit Event_908408e3(arg0);
    }
    
    function Unresolved_dd62ed3e(address arg0, uint256 arg1) public pure {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        require(true);
    }
    
    function Unresolved_ef8b30f7(uint256 arg0) public view returns (uint256) {
        require(arg0 < store_c.length, CustomError_3261c792());
        uint256 fee = unresolved_ddca3f43;
        return arg0 - ((arg0 * fee) / 10000);
    }
    
    function Unresolved_f2fde38b(address arg0) public {
        require(msg.sender == store_h, CustomError_30cd7471());
        require(arg0 != address(0), CustomError_d92e233d());
        store_h = arg0;
    }
}