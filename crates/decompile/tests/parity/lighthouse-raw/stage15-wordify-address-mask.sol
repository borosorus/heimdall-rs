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
    uint256 var_b;
    uint256 var_d;
    address public unresolved_8da5cb5b; // storage slot: 0x00
    bytes32 store_h; // storage slot: 0x00
    address store_f; // storage slot: 0x01
    bytes32 store_b; // storage slot: 0x01
    address store_g; // storage slot: 0x02
    bytes32 store_i; // storage slot: 0x02
    uint128 store_e; // storage slot: 0x03
    uint256 store_c; // storage slot: 0x03
    uint256 store_d; // storage slot: 0x04
    
    
    /// @custom:selector    0x22969eac
    /// @custom:signature   Unresolved_22969eac(address arg0) public
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_22969eac(address arg0) public {
        if (msg.sender == unresolved_8da5cb5b) {
            store_b = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_b)));
        } else {
            uint256 var_d;
            var_d = var_d;
            revert("Unauthorised access");
        }
    }
    
    /// @custom:selector    0x420b81f6
    /// @custom:signature   Unresolved_420b81f6() public view returns (bool)
    function Unresolved_420b81f6() public view returns (bool) {
        if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d) {
            if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) >= store_d) {
                return abi.encodePacked(store_e, block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d);
            } else {
                return abi.encodePacked(store_e, store_c);
            }
        } else {
            if(store_d != 0) {
                return abi.encodePacked(store_e, ((store_d) == 0));
            } else {
                return abi.encodePacked(store_e, store_c);
            }
        }
    }
    
    /// @custom:selector    0x57de26a4
    /// @custom:signature   Unresolved_57de26a4() public view returns (address)
    function Unresolved_57de26a4() public view returns (address) {
        if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d) {
            if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) >= store_d) {
                require(block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d, "Invalid data stored");
            } else {
                require(store_c != 0, "Invalid data stored");
            }
            return store_e;
        }
    }
    
    /// @custom:selector    0x59e02dd7
    /// @custom:signature   Unresolved_59e02dd7() public view returns (bool)
    function Unresolved_59e02dd7() public view returns (bool) {
        if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d) {
            if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) >= store_d) {
                return abi.encodePacked(store_e, block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d);
            } else {
                return abi.encodePacked(store_e, store_c);
            }
        } else {
            if(store_d != 0) {
                return abi.encodePacked(store_e, ((store_d) == 0));
            } else {
                return abi.encodePacked(store_e, store_c);
            }
        }
    }
    
    /// @custom:selector    0x5ae28fc9
    /// @custom:signature   Unresolved_5ae28fc9(uint256 arg0) public
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    function Unresolved_5ae28fc9(uint256 arg0) public {
        if (msg.sender == unresolved_8da5cb5b) {
            store_d = arg0;
        } else {
            uint256 var_d;
            var_d = var_d;
            revert("Unauthorised access");
        }
    }
    
    /// @custom:selector    0x9c0e3f7a
    /// @custom:signature   Unresolved_9c0e3f7a(uint256 arg0, uint256 arg1) public
    /// @param              arg0 ["uint256", "bytes32", "int256"]
    /// @param              arg1 ["uint256", "bytes32", "int256"]
    function Unresolved_9c0e3f7a(uint256 arg0, uint256 arg1) public {
        if (msg.sender == store_f) {
            require(((arg0 / 0x0100000000000000000000000000000000) == 0), "Value too large");
            require(((arg1 / 0x0100000000) == 0), "Nonce too large");
            store_c = block.timestamp * 0x0100000000000000000000000000000000 + (arg0 + arg1 * 0x01000000000000000000000000000000000000000000000000);
            if(store_g != address(0)) {
                require(store_g.code.length != 0);
                (bool success, bytes memory ret0) = address(store_g).Unresolved_18178358{ value: 0 }(var_b); // call
                require(success);
            }
        } else {
            uint256 var_e;
            var_e = var_e;
            revert("Unauthorised access");
        }
    }
    
    /// @custom:selector    0xa6f9dae1
    /// @custom:signature   Unresolved_a6f9dae1(address arg0) public
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_a6f9dae1(address arg0) public {
        if (msg.sender == unresolved_8da5cb5b) {
            store_h = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_h)));
        } else {
            uint256 var_d;
            var_d = var_d;
            revert("Unauthorised access");
        }
    }
    
    /// @custom:selector    0xbdf384a8
    /// @custom:signature   Unresolved_bdf384a8() public view returns (bool)
    function Unresolved_bdf384a8() public view returns (bool) {
        if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d) {
            if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) >= store_d) {
                return abi.encodePacked(uint32(store_c / 0x0100000000000000000000000000000000), block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d);
            } else {
                return abi.encodePacked(uint32(store_c / 0x0100000000000000000000000000000000), store_c);
            }
        } else {
            if(store_d != 0) {
                return abi.encodePacked(uint32(store_c / 0x0100000000000000000000000000000000), ((store_d) == 0));
            } else {
                return abi.encodePacked(uint32(store_c / 0x0100000000000000000000000000000000), store_c);
            }
        }
    }
    
    /// @custom:selector    0xbecfbf69
    /// @custom:signature   Unresolved_becfbf69() public view returns (bool)
    function Unresolved_becfbf69() public view returns (bool) {
        if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d) {
            if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) >= store_d) {
                return abi.encodePacked(uint32(store_c / 0x01000000000000000000000000000000000000000000000000), block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d);
            } else {
                return abi.encodePacked(uint32(store_c / 0x01000000000000000000000000000000000000000000000000), store_c);
            }
        } else {
            if(store_d != 0) {
                return abi.encodePacked(uint32(store_c / 0x01000000000000000000000000000000000000000000000000), ((store_d) == 0));
            } else {
                return abi.encodePacked(uint32(store_c / 0x01000000000000000000000000000000000000000000000000), store_c);
            }
        }
    }
    
    /// @custom:selector    0xd6e848ac
    /// @custom:signature   Unresolved_d6e848ac(address arg0) public
    /// @param              arg0 ["address", "uint160", "bytes20", "int160"]
    function Unresolved_d6e848ac(address arg0) public {
        if (msg.sender == unresolved_8da5cb5b) {
            store_i = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_i)));
            require((address(uint160(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_i)))).code.length) != 0);
            (bool success, bytes memory ret0) = address(address(uint160(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_i))))).Unresolved_eeb72866{ value: 0 }(var_b); // call
            require(success);
            require(ret0.length >= 0x20);
            require(0x0da4b055 == var_d, "invalid searcher");
        } else {
            uint256 var_g;
            var_g = var_g;
            revert("Unauthorised access");
        }
    }
    
    /// @custom:selector    0xde9375f2
    /// @custom:signature   Unresolved_de9375f2() public view returns (address)
    function Unresolved_de9375f2() public view returns (address) {
        return store_f;
    }
    
    /// @custom:selector    0xe2f90632
    /// @custom:signature   Unresolved_e2f90632() public view returns (bool)
    function Unresolved_e2f90632() public view returns (bool) {
        if (block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d) {
            return block.timestamp - uint64(store_c / 0x0100000000000000000000000000000000) < store_d;
        } else {
            return ((store_d) == 0);
        }
    }
}