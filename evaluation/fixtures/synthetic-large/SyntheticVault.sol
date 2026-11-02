// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @notice Synthetic, constructor-independent fixture for chunked decompilation experiments.
/// @dev State is initialized through `initialize` and setters so the deployed runtime can be
/// exercised directly at a fixed address. No external contracts are required.
contract SyntheticVault {
    error AlreadyInitialized();
    error NotOwner();
    error Paused();
    error LimitExceeded();
    error InsufficientBalance();
    error AllowanceExceeded();
    error InvalidLimits();
    error ZeroAddress();

    event Initialized(address indexed owner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event PausedChanged(bool paused);
    event FeeChanged(uint256 feeBps);
    event LimitsChanged(uint256 minDeposit, uint256 maxDeposit);
    event NameChanged(string name);
    event Deposit(address indexed account, uint256 amount, uint256 credited);
    event Withdrawal(address indexed account, uint256 amount);
    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);
    event Mint(address indexed account, uint256 amount);
    event Burn(address indexed account, uint256 amount);

    address private _owner;
    bool private _paused;
    bool private _initialized;
    uint256 private _feeBps;
    uint256 private _minDeposit;
    uint256 private _maxDeposit;
    string private _name;

    uint256 public totalSupply;
    mapping(address => uint256) private _balances;
    mapping(address => mapping(address => uint256)) private _allowances;

    function initialize(address initialOwner) external {
        if (_initialized) revert AlreadyInitialized();
        if (initialOwner == address(0)) revert ZeroAddress();
        _initialized = true;
        _owner = initialOwner;
        emit Initialized(initialOwner);
    }

    function owner() external view returns (address) {
        return _owner;
    }

    function transferOwnership(address newOwner) external {
        _requireOwner();
        if (newOwner == address(0)) revert ZeroAddress();
        address previous = _owner;
        _owner = newOwner;
        emit OwnershipTransferred(previous, newOwner);
    }

    function pause() external {
        _requireOwner();
        _paused = true;
        emit PausedChanged(true);
    }

    function unpause() external {
        _requireOwner();
        _paused = false;
        emit PausedChanged(false);
    }

    function isPaused() external view returns (bool) {
        return _paused;
    }

    function fee() external view returns (uint256) {
        return _feeBps;
    }

    function setFee(uint256 newFeeBps) external {
        _requireOwner();
        if (newFeeBps > 10_000) revert LimitExceeded();
        _feeBps = newFeeBps;
        emit FeeChanged(newFeeBps);
    }

    function limits() external view returns (uint256 minDeposit, uint256 maxDeposit) {
        return (_minDeposit, _maxDeposit);
    }

    function setLimits(uint256 newMinDeposit, uint256 newMaxDeposit) external {
        _requireOwner();
        if (newMinDeposit > newMaxDeposit) revert InvalidLimits();
        _minDeposit = newMinDeposit;
        _maxDeposit = newMaxDeposit;
        emit LimitsChanged(newMinDeposit, newMaxDeposit);
    }

    function setName(string calldata newName) external {
        _requireOwner();
        _name = newName;
        emit NameChanged(newName);
    }

    function name() external view returns (string memory) {
        return _name;
    }

    function balanceOf(address account) public view returns (uint256) {
        return _balances[account];
    }

    function allowance(address account, address spender) external view returns (uint256) {
        return _allowances[account][spender];
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        _allowances[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function deposit(uint256 amount) external {
        _requireUnpaused();
        if (amount < _minDeposit || amount > _maxDeposit) revert LimitExceeded();
        uint256 credited = _feeFor(amount);
        _balances[msg.sender] += credited;
        totalSupply += credited;
        emit Deposit(msg.sender, amount, credited);
    }

    function withdraw(uint256 amount) external {
        _requireUnpaused();
        if (_balances[msg.sender] < amount) revert InsufficientBalance();
        _balances[msg.sender] -= amount;
        totalSupply -= amount;
        emit Withdrawal(msg.sender, amount);
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _move(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        if (from != msg.sender) {
            uint256 available = _allowances[from][msg.sender];
            if (available < amount) revert AllowanceExceeded();
            _allowances[from][msg.sender] = available - amount;
        }
        _move(from, to, amount);
        return true;
    }

    function mint(address account, uint256 amount) external {
        _requireOwner();
        if (account == address(0)) revert ZeroAddress();
        _balances[account] += amount;
        totalSupply += amount;
        emit Mint(account, amount);
    }

    function burn(uint256 amount) external {
        if (_balances[msg.sender] < amount) revert InsufficientBalance();
        _balances[msg.sender] -= amount;
        totalSupply -= amount;
        emit Burn(msg.sender, amount);
    }

    function getStats(address account)
        external
        view
        returns (uint256 balance, uint256 supply, uint256 feeBps, bool paused)
    {
        return (balanceOf(account), totalSupply, _feeBps, _paused);
    }

    function previewDeposit(uint256 amount) external view returns (uint256) {
        if (amount < _minDeposit || amount > _maxDeposit) revert LimitExceeded();
        return _feeFor(amount);
    }

    function isWithinLimits(uint256 amount) external view returns (bool) {
        return amount >= _minDeposit && amount <= _maxDeposit;
    }

    function _move(address from, address to, uint256 amount) private {
        if (to == address(0)) revert ZeroAddress();
        if (_balances[from] < amount) revert InsufficientBalance();
        _balances[from] -= amount;
        _balances[to] += amount;
        emit Transfer(from, to, amount);
    }

    function _feeFor(uint256 amount) private view returns (uint256) {
        return amount - (amount * _feeBps) / 10_000;
    }

    function _requireOwner() private view {
        if (msg.sender != _owner) revert NotOwner();
    }

    function _requireUnpaused() private view {
        if (_paused) revert Paused();
    }
}
