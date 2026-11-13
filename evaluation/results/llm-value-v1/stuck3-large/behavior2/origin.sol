// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;

contract DecompiledContract {
    uint256 var_c;
    address store_h;
    bytes32 store_f;
    uint256 public unresolved_ddca3f43;
    uint256 store_c;
    uint256 store_d;
    bytes public unresolved_06fdde03;
    bytes32 store_e;

    mapping(address => uint256) public unresolved_70a08231;
    mapping(address => mapping(address => uint256)) storage_map_b;

    error CustomError_f4d678b8();
    error CustomError_d92e233d();
    error CustomError_9e87fac8();
    error CustomError_3261c792();
    error CustomError_30cd7471();
    error CustomError_0dc149f0();
    error CustomError_00000000();
    event Event_47374573(uint256, uint256);
    event Event_6bbc5748(uint256);
    event Event_8be0079c(address indexed, address indexed);
    event Event_8c5be1e5(address indexed, address indexed, uint256);
    event Event_908408e3(address indexed);
    event Event_d83d5281(uint256);
    event Event_ddf252ad(address indexed, address indexed, uint256);

    function Unresolved_095ea7b3(address arg0, uint256 arg1) public payable returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        storage_map_b[msg.sender][arg0] = arg1;
        emit Event_8c5be1e5(msg.sender, arg0, arg1);
        return true;
    }

    function Unresolved_0b663fe2(uint256 arg0) public view returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        if (arg0 < store_c) {
            return arg0 >= store_c;
        } else {
            return arg0 <= store_d;
        }
    }

    function Unresolved_18160ddd() public view returns (uint256) {
        return uint256(store_e);
    }

    function Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public view {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);
        require(unresolved_70a08231[arg0] >= arg2);
    }

    function Unresolved_2e1a7d4d(address arg0) public view returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(uint8(uint256(store_f) / 0x010000000000000000000000000000000000000000) == 0, CustomError_9e87fac8());
        require(unresolved_70a08231[msg.sender] >= uint256(uint160(arg0)), CustomError_f4d678b8());
        return unresolved_70a08231[arg0];
    }

    function Unresolved_3f4ba83a() public payable {
        require(msg.sender == store_h, CustomError_30cd7471());
        store_f = bytes32((0 * 0x010000000000000000000000000000000000000000) | (0xffffffffffffffffffffff00ffffffffffffffffffffffffffffffffffffffff & uint256(store_f)));
        emit Event_d83d5281(0);
    }

    function Unresolved_40c10f19(address arg0, address arg1) public view returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        require(msg.sender == store_h, CustomError_30cd7471());
        require(arg0 != address(0), CustomError_d92e233d());
        return storage_map_b[arg0][arg1];
    }

    function Unresolved_42966c68(address arg0) public view returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(unresolved_70a08231[msg.sender] >= uint256(uint160(arg0)), CustomError_f4d678b8());
        return unresolved_70a08231[arg0];
    }

    function Unresolved_69fe0e2d(address arg0) public payable returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(msg.sender == store_h, CustomError_30cd7471());
        require(uint160(arg0) <= 0x2710, CustomError_3261c792());
        unresolved_ddca3f43 = uint256(uint160(arg0));
        emit Event_6bbc5748(uint256(uint160(arg0)));
        return unresolved_70a08231[arg0];
    }

    function Unresolved_8456cb59() public payable {
        require(msg.sender == store_h, CustomError_30cd7471());
        store_f = bytes32(0x010000000000000000000000000000000000000000 | (0xffffffffffffffffffffff00ffffffffffffffffffffffffffffffffffffffff & uint256(store_f)));
        emit Event_d83d5281(0x01);
    }

    function Unresolved_860aefcf() public view returns (bytes memory) {
        return abi.encodePacked(store_c, store_d);
    }

    function Unresolved_8da5cb5b() public view returns (address) {
        return store_h;
    }

    function Unresolved_a9059cbb(address arg0, uint256 arg1) public payable returns (bool) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
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
        return false;
    }

    function Unresolved_b187bd26() public view returns (bool) {
        return uint8(uint256(store_f) / 0x010000000000000000000000000000000000000000) != 0;
    }

    function Unresolved_b6b55f25(address arg0) public view returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(uint8(uint256(store_f) / 0x010000000000000000000000000000000000000000) == 0, CustomError_9e87fac8());
        require(uint256(uint160(arg0)) >= store_c, CustomError_3261c792());
        return unresolved_70a08231[arg0];
    }

    function Unresolved_c23f85d6(address arg0) public view returns (bytes memory) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        return abi.encodePacked(unresolved_70a08231[arg0], store_e, unresolved_ddca3f43, uint8(uint256(store_f) / 0x010000000000000000000000000000000000000000));
    }

    function Unresolved_c4590d3f(address arg0) public view returns (uint256) {
        return unresolved_70a08231[arg0];
    }

    function Unresolved_c47f0027(address arg0) public payable returns (uint256) {
        uint256 a = uint256(uint160(arg0));
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(a <= 0xffffffffffffffff);
        require(0x04 + a + 0x1f < 0x04 + (msg.data.length - 0x04));
        require(uint8(msg.data[0x04 + a]) <= 0xff, CustomError_30cd7471());
        require(0x04 + a + 0x20 + uint8(msg.data[0x04 + a]) <= 0x04 + (msg.data.length - 0x04));
        require(msg.sender == store_h, CustomError_30cd7471());
        uint256 len = uint8(msg.data[0x04 + a]);
        if (len <= 0x1f) {
            bytes memory tmp = new bytes(len);
            for (uint256 i = 0; i < len; ++i) {
                tmp[i] = msg.data[0x24 + a + i];
            }
            unresolved_06fdde03 = tmp;
        } else {
            bytes memory tmp = new bytes(len);
            for (uint256 i = 0; i < len; ++i) {
                tmp[i] = msg.data[0x24 + a + i];
            }
            unresolved_06fdde03 = tmp;
        }
        emit Event_47374573(0x20, len);
        return unresolved_70a08231[arg0];
    }

    function Unresolved_c4d66de8(address arg0) public payable returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(uint8(uint256(store_f) / 0x01000000000000000000000000000000000000000000) == 0, CustomError_0dc149f0());
        require(arg0 != address(0), CustomError_d92e233d());
        store_f = bytes32(uint256(0x01000000000000000000000000000000000000000000) | (uint256(0xffffffffffffffffffff00ffffffffffffffffffffffffffffffffffffffffff) & uint256(store_f)));
        store_f = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_f)));
        emit Event_908408e3(arg0);
        return unresolved_70a08231[arg0];
    }

    function Unresolved_dd62ed3e(address arg0, address arg1) public view returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);
        return storage_map_b[arg0][arg1];
    }

    function Unresolved_ef8b30f7(uint256 arg0) public view returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(arg0 >= store_c, CustomError_3261c792());
        if ((arg0 == 0) || (unresolved_ddca3f43 == arg0 * unresolved_ddca3f43 / arg0 && arg0 - arg0 * unresolved_ddca3f43 / 0x2710 <= arg0)) {
            return arg0 - arg0 * unresolved_ddca3f43 / 0x2710;
        }
        revert();
    }

    function Unresolved_f2fde38b(address arg0) public payable returns (uint256) {
        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);
        require(msg.sender == store_h, CustomError_30cd7471());
        require(arg0 != address(0), CustomError_d92e233d());
        store_f = bytes32(uint256(uint160(arg0)) | (uint256(0xffffffffffffffffffffffff0000000000000000000000000000000000000000) & uint256(store_f)));
        emit Event_8be0079c(store_h, arg0);
        return unresolved_70a08231[arg0];
    }
}