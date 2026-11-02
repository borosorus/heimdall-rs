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
    // Slot 0: general stored value.
    uint256 public storedValue; // was unresolved_f2c9ecd8

    // Slot 1: packed storage. The low byte is exposed as a boolean flag,
    // the remaining bits hold another value.
    uint256 private packedSlot1; // was store_c (upper bits) and store_b (low byte)

    // Slot 2: dynamic bytes payload.
    bytes public storedData; // was unresolved_89ea642f

    // Slot 3: address stored in the lower 160 bits.
    address public storedAddress; // was unresolved_38cc4831 / store_h

    // Slot 4: target address used for external calls.
    address private callTarget; // was store_f / store_a

    event Event_88749aed(address addr);
    event Event_9d164645(uint256 value);
    event Event_9ec82549(uint256 value);
    event Event_b26b3b59(uint256 value);
    event Event_c3e10738(uint256 valueA, uint256 valueB, uint256 dataOffset, address addr, bytes data);
    event Event_d31368d6(uint256 value);
    event Event_d8247311(uint256 dataOffset, uint256 dataLength);

    function Unresolved_01ef8faa(address newTarget) public {
    callTarget = newTarget;
}

    function Unresolved_12a7b914() public view returns (bool) {
    return (packedSlot1 & 0xff) != 0;
}

    function Unresolved_1e26fd33(uint256 value) public {
    packedSlot1 = value | (packedSlot1 & ~uint256(0xff));
    emit Event_d31368d6(value);
}

    function Unresolved_349a0054(
    uint256 storedValueArg,
    uint256 packedValue,
    uint256 dataOffset,
    address newStoredAddress
) public {
    require(dataOffset <= 0xffffffffffffffff, "Offset too large");
    require(4 + dataOffset + 32 <= msg.data.length, "Invalid offset");

    uint256 dataLength;
    assembly {
        dataLength := calldataload(add(4, dataOffset))
    }
    require(dataLength <= 0xffffffffffffffff, "Length too large");
    require(4 + dataOffset + 32 + dataLength <= msg.data.length, "Data out of bounds");

    bytes memory data = msg.data[4 + dataOffset + 32 : 4 + dataOffset + 32 + dataLength];

    Unresolved_3fb5c1cb(storedValueArg);
    Unresolved_1e26fd33(packedValue);
    Unresolved_7fcaf666(dataOffset);
    Unresolved_e30081a0(newStoredAddress);

    emit Event_c3e10738(storedValueArg, packedValue, 0x80, newStoredAddress, data);
}

    function Unresolved_3fb5c1cb(uint256 value) public {
    storedValue = value;
    emit Event_9ec82549(value);
}

    function Unresolved_575f4505(uint256 callArg) public returns (uint256) {
    (bool success, bytes memory result) = callTarget.call(
        abi.encodeWithSelector(bytes4(0xc6888fa1), callArg)
    );
    require(success, "Call failed");
    require(result.length >= 32, "Invalid return data");

    uint256 returnValue;
    assembly {
        returnValue := mload(add(result, 32))
    }

    emit Event_9d164645(returnValue);
    return returnValue;
}

    function Unresolved_7fcaf666(uint256 dataOffset) public {
    require(dataOffset <= 0xffffffffffffffff, "Offset too large");
    require(4 + dataOffset + 32 <= msg.data.length, "Invalid offset");

    uint256 dataLength;
    assembly {
        dataLength := calldataload(add(4, dataOffset))
    }
    require(dataLength <= 0xffffffffffffffff, "Length too large");
    require(4 + dataOffset + 32 + dataLength <= msg.data.length, "Data out of bounds");

    bytes memory data = new bytes(dataLength);
    assembly {
        calldatacopy(add(data, 32), add(4, add(dataOffset, 32)), dataLength)
    }
    storedData = data;

    emit Event_d8247311(0x20, dataLength);
}

    function Unresolved_8d5d4de7() public view returns (address) {
    return callTarget;
}

    function Unresolved_981f5499() public view returns (uint256, uint256, bytes memory, address) {
    return (storedValue, packedSlot1 & 0xff, storedData, storedAddress);
}

    function Unresolved_d0da9af5(uint256 delegateArg) public returns (uint256) {
    bytes memory callData = msg.data[4:];
    (bool success, bytes memory result) = callTarget.delegatecall(callData);

    if (result.length == 0) {
        require(success, "Delegate call failed");
        emit Event_b26b3b59(delegateArg);
        return delegateArg;
    } else {
        revert("Delegate call failed");
    }
}

    function Unresolved_e30081a0(address newStoredAddress) public {
    storedAddress = newStoredAddress;
    emit Event_88749aed(newStoredAddress);
}
}
