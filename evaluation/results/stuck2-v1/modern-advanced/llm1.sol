// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;

contract DecompiledContract {
    uint256 public var_e;
    uint256 internal var_g;
    uint256 internal var_h;
    bytes public unresolved_89ea642f;
    address public unresolved_38cc4831;
    address internal store_f;
    bytes32 internal store_a;
    bytes32 internal store_c;
    bytes32 internal store_h;
    uint8 internal store_b;

    event Event_88749aed(address);
    event Event_9d164645(uint256);
    event Event_9ec82549(uint256);
    event Event_b26b3b59(uint256);
    event Event_c3e10738(uint256, uint256, uint256, address, uint256);
    event Event_d31368d6(uint256);
    event Event_d8247311(uint256, uint256);

    function Unresolved_01ef8faa(address arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        store_a = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_a)));
    }

    function Unresolved_12a7b914() public view returns (bool) {
        return store_b != 0;
    }

    function Unresolved_1e26fd33(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        store_c = bytes32(uint256(store_c) & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff00 | arg0);
        emit Event_d31368d6(arg0);
    }

    function Unresolved_349a0054(uint256 arg0, uint256 arg1, uint256 arg2, address arg3) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x80);
        require(arg2 <= 0xffffffffffffffff);
        require(0x04 + arg2 + 0x1f < 0x04 + (msg.data.length - 0x04));
        uint256 var_a = 0;
        uint256 len = uint256(uint256(bytes32(msg.data[0x04 + arg2])));
        uint256 var_c = len;
        require(0x04 + arg2 + 0x20 + len <= 0x04 + (msg.data.length - 0x04));
        require(address(this).code.length != 0);
        (bool success1, bytes memory ret0_1) = address(this).call(abi.encodeWithSignature("Unresolved_3fb5c1cb(uint256)", arg0));
        require(success1);
        require(address(this).code.length != 0);
        (bool success2, bytes memory ret0_2) = address(this).call(abi.encodeWithSignature("Unresolved_1e26fd33(uint256)", arg1));
        require(success2);
        require(address(this).code.length != 0);
        (bool success3, bytes memory ret0_3) = address(this).call(abi.encodeWithSignature("Unresolved_7fcaf666(uint256)", var_c));
        require(success3);
        require(address(this).code.length != 0);
        (bool success4, bytes memory ret0_4) = address(this).call(abi.encodeWithSignature("Unresolved_e30081a0(address)", arg3));
        require(success4);
        emit Event_c3e10738(arg0, arg1, var_a + 0x80 - var_a, arg3, var_g);
    }

    function Unresolved_3fb5c1cb(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        var_e = arg0;
        emit Event_9ec82549(arg0);
    }

    function Unresolved_575f4505(uint256 arg0) public payable returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        (bool success, bytes memory ret0) = store_f.call(abi.encodeWithSignature("Unresolved_c6888fa1(uint256)", arg0));
        require(success);
        uint256 var_c;
        unchecked { var_c = var_c + (ret0.length + 0x1f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0); }
        require(var_c + ret0.length - var_c >= 0x20);
        emit Event_9d164645(var_e);
        return var_e;
    }

    function Unresolved_7fcaf666(uint256 arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(arg0 <= 0xffffffffffffffff);
        require(0x04 + arg0 + 0x1f < 0x04 + (msg.data.length - 0x04));
        uint256 var_a = 0;
        uint256 len = uint256(uint256(bytes32(msg.data[0x04 + arg0])));
        require(0x04 + arg0 + 0x20 + len <= 0x04 + (msg.data.length - 0x04));
        uint256 var_c = uint256(bytes32(msg.data[0x04 + arg0 + 0x20]));
        uint256 var_e_local = var_e;
        if (var_e_local <= 0xffffffffffffffff && (unresolved_89ea642f.length >= 0x20)) {
            if (var_e_local > 0x1f) {
                bytes memory tmp = new bytes(var_e_local);
                for (uint256 i = 0; i < var_e_local && (i < 32); i++) {
                    tmp[i] = bytes1(uint8(uint256(var_c) >> (0x08 * i)));
                }
                unresolved_89ea642f = tmp;
            } else if (var_e_local == 0) {
                unresolved_89ea642f = new bytes(0);
            } else {
                bytes memory tmp2 = new bytes(var_e_local);
                for (uint256 j = 0; j < var_e_local; j++) {
                    tmp2[j] = bytes1(uint8(uint256(var_c) >> (0x08 * j)));
                }
                unresolved_89ea642f = tmp2;
            }
            emit Event_d8247311(var_a + 0x20 - var_a, var_e_local);
        }
    }

    function Unresolved_8d5d4de7() public view returns (address) {
        return store_f;
    }

    function Unresolved_981f5499() public view returns (bytes memory) {
        if (unresolved_89ea642f.length >= 0x20) {
            uint256 var_a = 0x20 + (0x1f + unresolved_89ea642f.length) / 0x20 * 0x20;
            if (unresolved_89ea642f.length >= 0x20) {
                return abi.encodePacked(var_e, uint256(store_b), var_a + 0x80 - var_a, uint256(uint160(unresolved_38cc4831)), var_g);
            }
        }
        return "";
    }

    function Unresolved_d0da9af5(uint256 arg0) public payable returns (uint256) {
        if (0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20) {
            uint256 var_c = 0x24;
            uint256 var_b = 0x24 + 0x20 - var_c - 0x20 + 0x20;
            (bool success, bytes memory ret0) = store_f.delegatecall(abi.encode(arg0));
            if (ret0.length == 0) {
                require(success, "Delegate call failed");
                require(0x80 + var_h - 0x80 >= 0x20);
                emit Event_b26b3b59(var_b);
                return var_b;
            } else {
                uint256 var_c2 = var_c + (ret0.length + 0x3f & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0);
                var_c = var_c2;
                revert("Delegate call failed");
            }
        }
        revert();
    }

    function Unresolved_e30081a0(address arg0) public payable {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        store_h = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_h)));
        emit Event_88749aed(arg0);
    }
}
