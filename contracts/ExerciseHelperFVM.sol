// SPDX-License-Identifier: AGPL-3.0
pragma solidity 0.8.17;

import "@openzeppelin/contracts/access/Ownable2Step.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

interface IoToken is IERC20 {
    function exercise(
        uint256 _amount,
        uint256 _maxPaymentAmount,
        address _recipient
    ) external returns (uint256);

    function getDiscountedPrice(
        uint256 _amount
    ) external view returns (uint256);
}

interface IBalancer {
    function flashLoan(
        address recipient,
        address[] memory tokens,
        uint256[] memory amounts,
        bytes memory userData
    ) external;
}

interface IRouter {
    struct route {
        address from;
        address to;
        bool stable;
    }

    function swapExactTokensForTokens(
        uint amountIn,
        uint amountOutMin,
        route[] calldata routes,
        address to,
        uint deadline
    ) external returns (uint[] memory amounts);

    function getAmountsOut(
        uint amountIn,
        route[] memory routes
    ) external view returns (uint[] memory amounts);
}

/**
 * @title Exercise Helper FVM
 * @notice This contract easily converts oFVM to WFTM using flash loans.
 */

contract ExerciseHelperFVM is Ownable2Step {
    /// @notice Option token address
    IoToken public constant oFVM =
        IoToken(0xF9EDdca6B1e548B0EC8cDDEc131464F462b8310D);

    /// @notice WFTM, payment token
    IERC20 public constant wftm =
        IERC20(0x21be370D5312f44cB42ce377BC9b8a0cEF1A4C83);

    /// @notice FVM, sell this for WFTM
    IERC20 public constant fvm =
        IERC20(0x07BB65fAaC502d4996532F834A1B7ba5dC32Ff96);

    /// @notice Flashloan from Beethoven (Balancer) vault
    IBalancer public constant balancerVault =
        IBalancer(0x20dd72Ed959b6147912C2e529F0a0C651c33c9ce);

    /// @notice FVM router for swaps
    IRouter constant router =
        IRouter(0x2E14B53E2cB669f3A974CeaF6C735e134F3Aa9BC);

    /// @notice Check whether we are in the middle of a flashloan (used for callback)
    bool public flashEntered;

    /// @notice Where we send our 0.25% fee
    address public constant feeAddress =
        0x58761D6C6bF6c4bab96CaE125a2e5c8B1859b48a;

    /// @notice Route for selling FVM -> WFTM
    IRouter.route[] public fvmToWftm;

    constructor(IRouter.route[] memory _fvmToWftm) {
        // create our swap route
        for (uint i; i < _fvmToWftm.length; ++i) {
            fvmToWftm.push(_fvmToWftm[i]);
        }

        // do necessary approvals
        fvm.approve(address(router), type(uint256).max);
        wftm.approve(address(oFVM), type(uint256).max);
    }

    /**
     * @notice Exercise our oFVM for WFTM.
     * @param _amount The amount of oFVM to exercise to WFTM.
     */
    function exercise(uint256 _amount) external {
        if (_amount == 0) {
            revert("Can't exercise zero");
        }

        // transfer option token to this contract
        _safeTransferFrom(address(oFVM), msg.sender, address(this), _amount);

        // figure out how much WFTM we need for our oFVM amount
        uint256 paymentTokenNeeded = oFVM.getDiscountedPrice(_amount);

        // get our flash loan started
        _borrowPaymentToken(paymentTokenNeeded);

        // send remaining profit back to user
        _safeTransfer(address(wftm), msg.sender, wftm.balanceOf(address(this)));
    }

    /**
     * @notice Flash loan our WFTM from Balancer.
     * @param _amountNeeded The amount of WFTM needed.
     */
    function _borrowPaymentToken(uint256 _amountNeeded) internal {
        // change our state
        flashEntered = true;

        // create our input args
        address[] memory tokens = new address[](1);
        tokens[0] = address(wftm);

        uint256[] memory amounts = new uint256[](1);
        amounts[0] = _amountNeeded;

        bytes memory userData = abi.encode(_amountNeeded);

        // call the flash loan
        balancerVault.flashLoan(address(this), tokens, amounts, userData);
    }

    /**
     * @notice Fallback function used during flash loans.
     * @dev May only be called by balancer vault as part of
     *  flash loan callback.
     * @param _tokens The tokens we are swapping (in our case, only WFTM).
     * @param _amounts The amounts of said tokens.
     * @param _feeAmounts The fee amounts for said tokens.
     * @param _userData Payment token amount passed from our flash loan.
     */
    function receiveFlashLoan(
        address[] memory _tokens,
        uint256[] memory _amounts,
        uint256[] memory _feeAmounts,
        bytes memory _userData
    ) external {
        // only balancer vault may call this, during a flash loan
        if (msg.sender != address(balancerVault)) {
            revert("Only balancer vault can call");
        }
        if (!flashEntered) {
            revert("Flashloan not in progress");
        }

        // pull our option info from the userData
        uint256 paymentTokenNeeded = abi.decode(_userData, (uint256));

        // exercise our option with our new WFTM, swap all FVM to WFTM
        uint256 optionTokenBalance = oFVM.balanceOf(address(this));
        _exerciseAndSwap(optionTokenBalance, paymentTokenNeeded);

        uint256 payback = _amounts[0] + _feeAmounts[0];
        _safeTransfer(address(wftm), address(balancerVault), payback);

        // check our profit and take fees
        uint256 profit = wftm.balanceOf(address(this));
        _takeFees(profit);
        flashEntered = false;
    }

    /**
     * @notice Exercise our oFVM, then swap FVM to WFTM.
     * @param _optionTokenAmount Amount of oFVM to exercise.
     * @param _paymentTokenAmount Amount of WFTM needed to pay for exercising.
     */
    function _exerciseAndSwap(
        uint256 _optionTokenAmount,
        uint256 _paymentTokenAmount
    ) internal {
        oFVM.exercise(_optionTokenAmount, _paymentTokenAmount, address(this));
        uint256 fvmReceived = fvm.balanceOf(address(this));

        // use our router to swap from FVM to WFTM
        router.swapExactTokensForTokens(
            fvmReceived,
            0,
            fvmToWftm,
            address(this),
            block.timestamp
        );
    }

    /**
     * @notice Apply fees to our profit amount.
     * @param _profitAmount Amount to apply 0.25% fee to.
     */
    function _takeFees(uint256 _profitAmount) internal {
        uint256 toSend = (_profitAmount * 25) / 10_000;
        _safeTransfer(address(wftm), feeAddress, toSend);
    }

    /**
     * @notice Sweep out tokens accidentally sent here.
     * @dev May only be called by owner.
     * @param _tokenAddress Address of token to sweep.
     * @param _tokenAmount Amount of tokens to sweep.
     */
    function recoverERC20(
        address _tokenAddress,
        uint256 _tokenAmount
    ) external onlyOwner {
        _safeTransfer(_tokenAddress, owner(), _tokenAmount);
    }

    /* ========== HELPER FUNCTIONS ========== */

    function _safeTransfer(address token, address to, uint256 value) internal {
        require(token.code.length > 0);
        (bool success, bytes memory data) = token.call(
            abi.encodeWithSelector(IERC20.transfer.selector, to, value)
        );
        require(success && (data.length == 0 || abi.decode(data, (bool))));
    }

    function _safeTransferFrom(
        address token,
        address from,
        address to,
        uint256 value
    ) internal {
        require(token.code.length > 0);
        (bool success, bytes memory data) = token.call(
            abi.encodeWithSelector(
                IERC20.transferFrom.selector,
                from,
                to,
                value
            )
        );
        require(success && (data.length == 0 || abi.decode(data, (bool))));
    }
}
