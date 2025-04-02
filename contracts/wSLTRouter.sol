// SPDX-License-Identifier: MIT
pragma solidity 0.8.19;

import {Math} from "@openzeppelin/contracts@4.9.3/utils/math/Math.sol";
import {Ownable2Step} from "@openzeppelin/contracts@4.9.3/access/Ownable2Step.sol";
import {Clones} from "@openzeppelin/contracts@4.9.3/proxy/Clones.sol";
import {IFactoryRegistry, IPoolFactory, IPool} from "./interfaces/AerodromeInterfaces.sol";
import {IERC20, IWETH, IBMX, VaultAPI, IShareHelper} from "./interfaces/BMXInterfaces.sol";

/**
 * @title wSLT Router
 * @notice This contract simplifies zapping in and out of wSLT.
 */

contract wSLTRouter is Ownable2Step {
    IWETH public constant weth =
        IWETH(0x039e2fB66102314Ce7b64Ce5Ce3E5183bc94aD38);
    uint256 internal immutable PRICE_PRECISION;
    uint256 internal immutable BASIS_POINTS_DIVISOR;

    /// @notice The tokens currently approved for deposit to BLT.
    address[] public bltTokens;

    // contracts used for wBLT mint/burn
    VaultAPI internal constant wBLT =
        VaultAPI(0x2dDCF85D3Cf27DEA338e0371D38409Ba80058630);

    IBMX internal constant sBLT =
        IBMX(0x47cd080014fF0ebB097F49cF1303ad088eBFCFcb);

    IBMX internal constant rewardRouter =
        IBMX(0x0DF4DbeB0aeABbBB95cC600E7a268125A0Bb8064);

    IBMX internal constant morphexVault =
        IBMX(0x9cC4E8e60a2c9a67Ac7D20f54607f98EfBA38AcF);

    IBMX internal constant bltManager =
        IBMX(0xC608188e753b1e9558731724b7F7Cdde40c3b174);

    IBMX internal constant vaultUtils =
        IBMX(0x5174c02f20fe8b2da3E3A64FA7df5596cEF9BaD2);

    IShareHelper internal constant shareValueHelper =
        IShareHelper(0x4AEb2138203b6DDAF52Cc3Ff64d7ad156482B2aa);

    constructor() {
        // do approvals for wBLT
        sBLT.approve(address(wBLT), type(uint256).max);

        // update our allowances
        updateAllowances();

        PRICE_PRECISION = morphexVault.PRICE_PRECISION();
        BASIS_POINTS_DIVISOR = morphexVault.BASIS_POINTS_DIVISOR();
    }

    // only accept ETH via fallback from the WETH contract
    receive() external payable {
        assert(msg.sender == address(weth));
    }

    /* ========== NEW/MODIFIED FUNCTIONS ========== */

    /**
     * @notice Checks for current tokens in BLT, approves them, and updates our stored array.
     * @dev This is may only be called by owner.
     */
    function updateAllowances() public onlyOwner {
        // first, set all of our allowances to zero
        for (uint256 i = 0; i < bltTokens.length; ++i) {
            IERC20 token = IERC20(bltTokens[i]);
            token.approve(address(bltManager), 0);
        }

        // clear out our saved array
        delete bltTokens;

        // add our new tokens
        uint256 tokensCount = morphexVault.whitelistedTokenCount();
        for (uint256 i = 0; i < tokensCount; ++i) {
            IERC20 token = IERC20(morphexVault.allWhitelistedTokens(i));
            token.approve(address(bltManager), type(uint256).max);
            bltTokens.push(address(token));
        }
    }

    /**
     * @notice Check how much wBLT we get from a given amount of underlying.
     * @dev Since this uses minPrice, we likely underestimate wBLT received. By using normal solidity division, we are
     *  also truncating (rounding down) all operations.
     * @param _token The token to deposit to wBLT.
     * @param _amount The amount of the token to deposit.
     * @return wrappedBLTMintAmount Amount of wBLT received.
     */
    function getMintAmountWrappedBLT(
        address _token,
        uint256 _amount
    ) public view returns (uint256 wrappedBLTMintAmount) {
        require(_amount > 0, "invalid _amount");

        // calculate aum before buyUSDG
        (uint256 aumInUsdg, uint256 bltSupply) = _getBltInfo(true);
        uint256 price = morphexVault.getMinPrice(_token);

        // save some gas
        uint256 _precision = PRICE_PRECISION;
        uint256 _divisor = BASIS_POINTS_DIVISOR;

        uint256 usdgAmount = (_amount * price) / _precision;
        usdgAmount = morphexVault.adjustForDecimals(
            usdgAmount,
            _token,
            morphexVault.usdg()
        );

        uint256 feeBasisPoints = vaultUtils.getBuyUsdgFeeBasisPoints(
            _token,
            usdgAmount
        );
        uint256 afterFeeAmount = (_amount * (_divisor - feeBasisPoints)) /
            _divisor;

        uint256 usdgMintAmount = (afterFeeAmount * price) / _precision;
        usdgMintAmount = morphexVault.adjustForDecimals(
            usdgMintAmount,
            _token,
            morphexVault.usdg()
        );
        uint256 BLTMintAmount = aumInUsdg == 0
            ? usdgMintAmount
            : (usdgMintAmount * bltSupply) / aumInUsdg;

        // convert our BLT amount to wBLT
        wrappedBLTMintAmount = shareValueHelper.amountToShares(
            address(wBLT),
            BLTMintAmount,
            false
        );
    }

    /**
     * @notice Check how much underlying we get from redeeming a given amount of wBLT.
     * @dev By default we round down and use getMaxPrice to underestimate underlying received. This is important so that
     *  we don't ever revert in a swap due to overestimation, as getAmountsOut calls this function.
     * @param _tokenOut The token to withdraw from wBLT.
     * @param _amount The amount of wBLT to burn.
     * @param _roundUp Whether we round up or not.
     * @return underlyingReceived Amount of underlying token received.
     */
    function getRedeemAmountWrappedBLT(
        address _tokenOut,
        uint256 _amount,
        bool _roundUp
    ) public view returns (uint256 underlyingReceived) {
        require(_amount > 0, "invalid _amount");

        // convert our wBLT amount to BLT
        _amount = shareValueHelper.sharesToAmount(
            address(wBLT),
            _amount,
            _roundUp
        );

        // convert our BLT to bUSD (USDG)
        (uint256 aumInUsdg, uint256 bltSupply) = _getBltInfo(false);
        uint256 usdgAmount;

        // round up if needed
        if (_roundUp) {
            usdgAmount = Math.ceilDiv((_amount * aumInUsdg), bltSupply);
        } else {
            usdgAmount = (_amount * aumInUsdg) / bltSupply;
        }

        // use min or max price depending on how we want to estimate
        uint256 price;
        if (_roundUp) {
            price = morphexVault.getMinPrice(_tokenOut);
        } else {
            price = morphexVault.getMaxPrice(_tokenOut);
        }

        // convert USDG to _tokenOut amounts. no need to round this one since we adjust decimals and compensate below
        uint256 redeemAmount = (usdgAmount * PRICE_PRECISION) / price;

        redeemAmount = morphexVault.adjustForDecimals(
            redeemAmount,
            morphexVault.usdg(),
            _tokenOut
        );

        // add one wei to compensate for truncating when adjusting decimals
        if (_roundUp) {
            redeemAmount += 1;
        }

        // calculate our fees
        uint256 feeBasisPoints = vaultUtils.getSellUsdgFeeBasisPoints(
            _tokenOut,
            usdgAmount
        );

        // save some gas
        uint256 _divisor = BASIS_POINTS_DIVISOR;

        // adjust for fees, round up if needed
        if (_roundUp) {
            underlyingReceived = Math.ceilDiv(
                (redeemAmount * (_divisor - feeBasisPoints)),
                _divisor
            );
        } else {
            underlyingReceived = ((redeemAmount * (_divisor - feeBasisPoints)) /
                _divisor);
        }
    }

    /**
     * @notice Check how much wBLT we need to redeem for a given amount of underlying.
     * @dev Here we do everything we can, including adding an additional Wei of Defeat, to ensure that our estimated
     *  wBLT amount always provides enough underlying.
     * @param _underlyingToken The token to withdraw from wBLT.
     * @param _amount The amount of underlying we need.
     * @return wBLTAmount Amount of wBLT needed.
     */
    function quoteRedeemAmountBLT(
        address _underlyingToken,
        uint256 _amount
    ) external view returns (uint256 wBLTAmount) {
        require(_amount > 0, "invalid _amount");

        // add an additional wei to our input amount because of persistent rounding issues, AKA the Wei of Defeat
        _amount += 1;

        // get our info for BLT
        (uint256 aumInUsdg, uint256 bltSupply) = _getBltInfo(false);

        // convert our underlying amount to USDG
        uint256 underlyingPrice = morphexVault.getMaxPrice(_underlyingToken);
        uint256 usdgNeeded = Math.ceilDiv(
            (_amount * underlyingPrice),
            PRICE_PRECISION
        );

        // convert USDG needed to BLT. no need for rounding here since we will truncate in the next step anyway
        uint256 bltAmount = (usdgNeeded * bltSupply) / aumInUsdg;

        bltAmount = morphexVault.adjustForDecimals(
            bltAmount,
            morphexVault.usdg(),
            _underlyingToken
        );

        // add one wei since adjustForDecimals truncates instead of rounding up
        bltAmount += 1;

        // save some gas
        uint256 _divisor = BASIS_POINTS_DIVISOR;

        // check current fees
        uint256 feeBasisPoints = vaultUtils.getSellUsdgFeeBasisPoints(
            _underlyingToken,
            usdgNeeded
        );

        // adjust for fees
        bltAmount = Math.ceilDiv(
            (bltAmount * _divisor),
            (_divisor - feeBasisPoints)
        );

        // convert our BLT to wBLT
        wBLTAmount = shareValueHelper.amountToShares(
            address(wBLT),
            bltAmount,
            true
        );
    }

    /**
     * @notice Check how much underlying we need to mint a given amount of wBLT.
     * @dev Since this uses minPrice, we likely overestimate underlying needed. To be cautious of rounding down, use
     *  ceiling division.
     * @param _underlyingToken The token to deposit to wBLT.
     * @param _amount The amount of wBLT we need.
     * @return startingTokenAmount Amount of underlying token needed.
     */
    function quoteMintAmountBLT(
        address _underlyingToken,
        uint256 _amount
    ) public view returns (uint256 startingTokenAmount) {
        require(_amount > 0, "invalid _amount");

        // convert our wBLT amount to BLT
        _amount = shareValueHelper.sharesToAmount(address(wBLT), _amount, true);

        // convert our BLT to bUSD (USDG)
        // maximize here to use max BLT price, to make sure we get enough BLT out
        (uint256 aumInUsdg, uint256 bltSupply) = _getBltInfo(true);
        uint256 usdgAmount = Math.ceilDiv((_amount * aumInUsdg), bltSupply);

        // price is returned in 1e30 from vault
        uint256 tokenPrice = morphexVault.getMinPrice(_underlyingToken);

        startingTokenAmount = Math.ceilDiv(
            usdgAmount * PRICE_PRECISION,
            tokenPrice
        );

        startingTokenAmount = morphexVault.adjustForDecimals(
            startingTokenAmount,
            morphexVault.usdg(),
            _underlyingToken
        );

        // add one wei since adjustForDecimals truncates instead of rounding up
        startingTokenAmount += 1;

        // calculate extra needed due to fees
        uint256 feeBasisPoints = vaultUtils.getBuyUsdgFeeBasisPoints(
            _underlyingToken,
            usdgAmount
        );

        // save some gas
        uint256 _divisor = BASIS_POINTS_DIVISOR;

        startingTokenAmount = Math.ceilDiv(
            startingTokenAmount * _divisor,
            (_divisor - feeBasisPoints)
        );
    }

    // standard data needed to calculate BLT pricing
    function _getBltInfo(
        bool _maximize
    ) internal view returns (uint256 aumInUsdg, uint256 bltSupply) {
        bltSupply = sBLT.totalSupply();
        aumInUsdg = bltManager.getAumInUsdg(_maximize);
    }

    // check if a token is in BLT
    function _isBLTToken(address _tokenToCheck) internal view returns (bool) {
        for (uint256 i = 0; i < bltTokens.length; ++i) {
            if (bltTokens[i] == _tokenToCheck) {
                return true;
            }
        }
        return false;
    }

    // withdraw all of the wBLT we have to a given underlying token
    function _withdrawFromWrappedBLT(
        address _targetToken
    ) internal returns (uint256) {
        if (!_isBLTToken(_targetToken)) {
            revert("Token not in wBLT");
        }

        // withdraw from the vault first, make sure it comes here
        uint256 toWithdraw = wBLT.withdraw(type(uint256).max, address(this));

        // withdraw our targetToken
        return
            rewardRouter.unstakeAndRedeemSlt(
                _targetToken,
                toWithdraw,
                0,
                address(this)
            );
    }

    /**
     * @notice Withdraws a specified amount of wBLT to a target underlying token.
     * @param _receiver The address to receive underlying tokens to.
     * @param _targetToken The address of the target token to which the wBLT is withdrawn.
     * @param _amount The amount of wBLT to withdraw.
     * @return amountWithdrawn The amount of target tokens received from the withdrawal.
     */
    function withdrawFromWrappedBLT(
        address _receiver,
        address _targetToken,
        uint256 _amount
    ) external returns (uint256) {
        // Transfer wBLT from the user to the router
        _safeTransferFrom(address(wBLT), msg.sender, address(this), _amount);

        if (!_isBLTToken(_targetToken)) {
            revert("Token not in wBLT");
        }

        // withdraw from the vault first, make sure it comes here
        uint256 toWithdraw = wBLT.withdraw(type(uint256).max, address(this));

        // withdraw our targetToken
        return
            rewardRouter.unstakeAndRedeemSlt(
                _targetToken,
                toWithdraw,
                0,
                _receiver
            );
    }

    // deposit all of the underlying we have to wBLT
    function _depositToWrappedBLT(
        address _fromToken
    ) internal returns (uint256 tokens) {
        if (!_isBLTToken(_fromToken)) {
            revert("Token not in wBLT");
        }

        // deposit to BLT and then the vault
        IERC20 token = IERC20(_fromToken);
        uint256 newMlp = rewardRouter.mintAndStakeSlt(
            address(_fromToken),
            token.balanceOf(address(this)),
            0,
            0
        );

        // specify that router should get the vault tokens
        tokens = wBLT.deposit(newMlp, address(this));
    }

    /**
     * @notice Deposits a specified amount of an underlying token to wBLT.
     * @param _receiver The address to receive underlying tokens to.
     * @param _fromToken The address of the token to be deposited to wBLT.
     * @param _amount The amount of the token to deposit.
     * @return amountReceived The amount of wBLT received from the deposit.
     */
    function depositToWrappedBLT(
        address _receiver,
        address _fromToken,
        uint256 _amount
    ) external returns (uint256 amountReceived) {
        // Transfer the _fromToken from the user to the contract
        _safeTransferFrom(_fromToken, msg.sender, address(this), _amount);

        if (!_isBLTToken(_fromToken)) {
            revert("Token not in wBLT");
        }

        // deposit to BLT and then the vault
        IERC20 token = IERC20(_fromToken);
        uint256 newMlp = rewardRouter.mintAndStakeSlt(
            address(_fromToken),
            token.balanceOf(address(this)),
            0,
            0
        );

        // specify that user should get the vault tokens
        amountReceived = wBLT.deposit(newMlp, _receiver);
    }

    /* ========== UNMODIFIED FUNCTIONS ========== */

    function _safeTransferFrom(
        address _token,
        address _from,
        address _to,
        uint256 _value
    ) internal {
        require(_token.code.length > 0);
        (bool success, bytes memory data) = _token.call(
            abi.encodeWithSelector(
                IERC20.transferFrom.selector,
                _from,
                _to,
                _value
            )
        );
        require(success && (data.length == 0 || abi.decode(data, (bool))));
    }
}
