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

    /// @custom:selector    0x01ef8faa
    /// @custom:signature   Unresolved_01ef8faa(address arg0) public payable
    /// @param              newTarget ["address", "uint160", "bytes20", "int160"]
    /// @notice Sets the target address used for external calls.
    function Unresolved_01ef8faa(address newTarget) public payable {
        // Original code performed a read-modify-write on slot 4 to preserve the
        // upper 96 bits. Since only the address is used elsewhere, assigning the
        // address directly is equivalent.
        callTarget = newTarget;
    }

    function Unresolved_12a7b914() public view returns (bool) {
    return (packedSlot1 & 0xff) != 0;
}

    function Unresolved_1e26fd33(uint256 value) public payable {
    require(value <= 1);
    packedSlot1 = value | (packedSlot1 & ~uint256(0xff));
}

    function Unresolved_349a0054(
    uint256 storedValueArg,
    uint256 packedValue,
    uint256 dataOffset,
    address newStoredAddress
) public payable {
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
}

    function Unresolved_3fb5c1cb(uint256 value) public payable {
    storedValue = value;
}

    /// @custom:selector    0x575f4505
    /// @custom:signature   Unresolved_575f4505(uint256 arg0) public payable returns (uint256)
    /// @param              callArg ["uint256", "bytes32", "int256"]
    /// @notice Forwards a call to the stored target and returns its uint256 result.
    function Unresolved_575f4505(uint256 callArg) public payable returns (uint256) {
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

    function Unresolved_7fcaf666(uint256 dataOffset) public payable {
        require(dataOffset <= 0xffffffffffffffff, "Offset too large");
        require(4 + dataOffset + 32 <= msg.data.length, "Invalid offset");

        uint256 dataLength;
        assembly {
            dataLength := calldataload(add(4, dataOffset))
        }
        require(dataLength <= 0xffffffffffffffff, "Length too large");
        require(4 + dataOffset + 32 + dataLength <= msg.data.length, "Data out of bounds");

        bytes memory data = msg.data[4 + dataOffset + 32 : 4 + dataOffset + 32 + dataLength];
        storedData = data;

        emit Event_d8247311(0x20, dataLength);
    }

    /// @custom:selector    0x8d5d4de7
    /// @custom:signature   Unresolved_8d5d4de7() public view returns (address)
    /// @notice Returns the stored external call target address.
    function Unresolved_8d5d4de7() public view returns (address) {
        return callTarget;
    }

    function Unresolved_981f5499() public view returns (bytes memory) {
        // The decompiler inferred a bool return type, but the original
        // implementation returned packed bytes. The selector is unaffected by
        // the return type.
        return abi.encodePacked(
            storedValue,
            uint8(packedSlot1 & 0xff),
            uint256(0x80),
            storedAddress,
            storedData
        );
    }

    /// @custom:selector    0xd0da9af5
    /// @custom:signature   Unresolved_d0da9af5(uint256 arg0) public payable returns (uint256)
    /// @param              delegateArg ["uint256", "bytes32", "int256"]
    /// @notice Delegate-calls the stored target and returns the supplied argument on success.
    function Unresolved_d0da9af5(uint256 delegateArg) public payable returns (uint256) {
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

    function Unresolved_e30081a0(address newStoredAddress) public payable {
        storedAddress = newStoredAddress;
        emit Event_88749aed(newStoredAddress);
    }
}
