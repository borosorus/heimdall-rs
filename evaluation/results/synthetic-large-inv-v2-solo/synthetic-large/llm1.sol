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
        storage_map_b[msg.sender][arg0] = arg1;
        emit Event_8c5be1e5(msg.sender, arg0, arg1);
        return true;
    }
    
    function Unresolved_0b663fe2(uint256 arg0) public view returns (bool) {
        if (arg0 < store_c.length) {
            return arg0 >= store_c.length;
        } else {
            return arg0 <= store_d.length;
        }
    }
    
    function Unresolved_18160ddd() public view returns (uint256) {
        return var_c;
    }
    
    function Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public pure {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);
    }
    
    function Unresolved_2e1a7d4d(uint256 arg0) public view {
        require(uint8(uint256(store_f) / 0x010000000000000000000000000000000000000000) == 0, CustomError_9e87fac8());
        require(unresolved_70a08231[msg.sender] >= arg0, CustomError_f4d678b8());
        revert();
    }
    
    function Unresolved_3f4ba83a() public {
        require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
        store_f = bytes32(uint256(0 * 0x010000000000000000000000000000000000000000) | (uint256(0xffffffffffffffffffffff00ffffffffffffffffffffffffffffffffffffffff) & uint256(store_f)));
        emit Event_d83d5281(0);
    }
    
    /// @custom:selector    0x40c10f19
    /// @custom:signature   Unresolved_40c10f19(address arg0, uint256 arg1) public view
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_40c10f19(address arg0, uint256 arg1) public view {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40) {
            require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
            require(arg0 != address(0), CustomError_d92e233d());
        }
        revert();
    }
    
    /// @custom:selector    0x42966c68
    /// @custom:signature   Unresolved_42966c68(uint256 arg0) public view
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_42966c68(uint256 arg0) public view {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20) {
            require(unresolved_70a08231[msg.sender] >= arg0, CustomError_f4d678b8());
        }
        revert();
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
        store_f = bytes32(uint256(store_f) & 0xffffffffffffffffffffff00ffffffffffffffffffffffffffffffffffffffff | 0x010000000000000000000000000000000000000000);
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
    
    function Unresolved_b6b55f25(uint256 arg0) public view {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x10) {
            require(uint8(uint256(store_f) / 0x010000000000000000000000000000000000000000) == 0, CustomError_9e87fac8());
            require(arg0 >= uint256(store_c.length), CustomError_3261c792());
        }
        revert();
    }
    
    function Unresolved_c23f85d6(address arg0) public view returns (bool, uint256, uint256, uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        return (unresolved_70a08231[arg0] != 0, unresolved_ddca3f43, var_c, 0);
    }
    
    function Unresolved_c4590d3f(uint256 arg0) public pure {
    revert();
}
    
    function Unresolved_c47f0027(uint256 arg0) public {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(arg0 <= 0xffffffffffffffff);
        require(0x04 + arg0 + 0x1f < 0x04 + (msg.data.length - 0x04));
        uint256 len = uint256(uint8(msg.data[0x04 + arg0]));
        require(len <= 0xffffffffffffffff);
        require(0x04 + arg0 + 0x20 + len <= 0x04 + (msg.data.length - 0x04));
        require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
        if (len <= 0xffffffffffffffff && bytes(unresolved_06fdde03).length < 0x20) {
            bytes calldata data = msg.data;
            if (len > 0x1f) {
                if ((len & ~uint256(0x1f)) < len) {
                    bytes storage s = bytes(unresolved_06fdde03);
                    assembly {
                        calldatacopy(0x00, add(add(data.offset, 0x20), arg0), 0x20)
                        sstore(add(s.slot, 0), and(mload(0x00), not(shl(mul(0x08, and(len, 0x1f)), sub(shl(0x100, 1), 1)))))
                    }
                }
                unresolved_06fdde03 = string(abi.encodePacked(uint256(len * 0x02 + 0x01)));
            } else {
                if (len == 0) {
                    unresolved_06fdde03 = string(abi.encodePacked(uint256(0 & ~(type(uint256).max >> 0x08 * len) | 0x02 * len)));
                } else {
                    bytes storage s2 = bytes(unresolved_06fdde03);
                    assembly {
                        calldatacopy(0x00, add(add(data.offset, 0x20), arg0), 0x20)
                        sstore(add(s2.slot, 0), or(and(mload(0x00), not(shl(mul(0x08, len), sub(shl(0x100, 1), 1)))), mul(0x02, len)))
                    }
                }
            }
            emit Event_47374573(var_c + 0x20 - var_c, len);
        }
    }
    
    function Unresolved_c4d66de8(address arg0) public {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(store_f[21] == 0, CustomError_0dc149f0());
        require(uint160(arg0) != 0, CustomError_d92e233d());
        store_f = bytes32(uint256(0x01)) | (bytes32(~uint256(0xff) << 160) & store_f);
        store_f = bytes32(uint256(uint160(arg0))) | (bytes32(uint256(0xffffffffffffffffffffffff) << 160) & store_f);
        emit Event_908408e3(arg0);
    }
    
    function Unresolved_dd62ed3e(address arg0, uint256 arg1) public pure {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
    }
    
    function Unresolved_ef8b30f7(uint256 arg0) public view returns (uint256) {
    require(arg0 < store_c.length, CustomError_3261c792());
    uint256 fee = unresolved_ddca3f43;
    return arg0 - ((arg0 * fee) / 10000);
}
    
    function Unresolved_f2fde38b(address arg0) public {
    require(msg.sender == address(uint160(uint256(store_f))), CustomError_30cd7471());
    require(arg0 != address(0), CustomError_d92e233d());
    store_f = bytes32(uint256(uint160(arg0)));
}
}