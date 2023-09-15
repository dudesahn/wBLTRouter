from brownie import chain, Contract, interface, accounts
import pytest


def test_basic_swaps(
    bmx,
    screamsh,
    w_blt,
    router,
    weth,
    factory,
    usdc,
):
    # clear out any balance
    reward_router = Contract("0x49a97680938b4f1f73816d1b70c3ab801fad124b")
    glp_manager = Contract("0x9fAc7b75f367d5B35a6D6D0a09572eFcC3D406C5")
    s_glp = Contract("0x64755939a80BC89E1D2d0f93A312908D348bC8dE")
    weth_to_mint = 2e15
    s_glp.approve(w_blt, 2**256 - 1, {"from": screamsh})
    if s_glp.balanceOf(screamsh) > 0:
        w_blt.deposit({"from": screamsh})

    # test views
    to_mint = router.getMintAmountWrappedBLT(weth, weth_to_mint)
    print("\n🥸 Mint wBLT with 0.002 ETH", "{:,.18f}".format(to_mint / 1e18))

    # how much weth do we need for that same amount of WBLT?
    weth_needed = router.quoteMintAmountBLT(weth, to_mint, {"from": screamsh})
    error = abs(weth_needed - weth_to_mint) / weth_to_mint * 100
    print("Error:", "{:,.10f}%".format(error))

    print(
        "WETH needed for",
        "{:,.18f}".format(to_mint / 1e18),
        "wBLT",
        "{:,.18f}".format(weth_needed / 1e18),
    )

    # swap for wBLT, compare it to minting directly on morphex
    # mint via our router
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    weth_to_wblt = [
        (weth.address, w_blt.address, False),
    ]
    weth_to_mint = 2e15
    before = w_blt.balanceOf(screamsh)
    router.swapExactTokensForTokens(
        weth_to_mint, 0, weth_to_wblt, screamsh, 2**256 - 1, {"from": screamsh}
    )
    received_swap = w_blt.balanceOf(screamsh) - before
    chain.undo()

    # mint directly, should be exactly the same
    weth.approve(glp_manager, 2**256 - 1, {"from": screamsh})
    before_new = w_blt.balanceOf(screamsh)
    reward_router.mintAndStakeGlp(weth.address, weth_to_mint, 0, 0, {"from": screamsh})

    helper = Contract("0x7EF2dBc5B28A3BdE7162442f95C691Be7F820867")
    estimated_shares = helper.amountToShares(w_blt.address, s_glp.balanceOf(screamsh))

    fs_blp = Contract("0x2D5875ab0eFB999c1f49C798acb9eFbd1cfBF63c")
    print("Started:", s_glp.balanceOf(screamsh))
    vault_before = fs_blp.balanceOf(w_blt)
    s_vault_before = s_glp.balanceOf(w_blt)
    w_blt.deposit({"from": screamsh})
    received_mint = w_blt.balanceOf(screamsh) - before_new
    fs_blp_transferred = fs_blp.balanceOf(w_blt) - vault_before
    s_blp_transferred = s_glp.balanceOf(w_blt) - s_vault_before
    print("FS:", fs_blp_transferred)
    print("S:", fs_blp_transferred)

    # check that we got the same if no locked profit left
    decay_time = 1e18 / w_blt.lockedProfitDegradation()
    if chain.time() - w_blt.lastReport() > decay_time:
        assert received_mint == received_swap

    # print our two values
    print(
        "\nSwap for wBLT",
        "{:,.18f}".format(received_swap / 1e18),
        "\nwBLT received from minting directly",
        "{:,.18f}".format(received_mint / 1e18),
        "\nEstimated mint",
        "{:,.18f}".format(estimated_shares / 1e18),
    )

    chain.sleep(86400)
    chain.mine(1)

    weth_to_swap = 2e16
    weth_to_bmx = [
        (weth.address, w_blt.address, False),
        (w_blt.address, bmx.address, False),
    ]
    amounts = router.getAmountsOut(weth_to_swap, weth_to_bmx)
    print("🥸 Get amounts out for 0.002 ETH:", amounts)

    # swap for some BMX
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    before = bmx.balanceOf(screamsh)
    swap = router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_bmx, screamsh, 2**256 - 1, {"from": screamsh}
    )
    print("💯 Actual amounts out", swap.return_value)

    assert bmx.balanceOf(screamsh) > before
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("✅  Swapped to BMX")

    # approve our BMX, swap for USDC
    bmx.approve(router, 2**256 - 1, {"from": screamsh})
    bmx_to_usdc = [
        (bmx.address, w_blt.address, False),
        (w_blt.address, usdc.address, False),
    ]
    bmx_to_swap = bmx.balanceOf(screamsh)
    before = usdc.balanceOf(screamsh)
    router.swapExactTokensForTokens(
        bmx_to_swap, 0, bmx_to_usdc, screamsh.address, 2**256 - 1, {"from": screamsh}
    )
    assert usdc.balanceOf(screamsh) > before
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("✅  Swapped back from BMX to USDC")

    # swap to wBLT
    weth_to_swap = 1e14
    weth_to_wblt = [(weth.address, w_blt.address, False)]
    before = w_blt.balanceOf(screamsh)
    router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_wblt, screamsh, 2**256 - 1, {"from": screamsh}
    )
    assert w_blt.balanceOf(screamsh) > before
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("✅  Swapped from WETH to wBLT")

    # swap wBLT to WETH
    wblt_to_swap = w_blt.balanceOf(screamsh)
    w_blt.approve(router, 2**256 - 1, {"from": screamsh})
    back_to_weth = [(w_blt.address, weth.address, False)]
    before = weth.balanceOf(screamsh)
    router.swapExactTokensForTokens(
        wblt_to_swap, 0, back_to_weth, screamsh, 2**256 - 1, {"from": screamsh}
    )
    assert weth.balanceOf(screamsh) > before
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("✅  Swapped from wBLT back to WETH\n")


def test_eth_swaps(
    bmx,
    screamsh,
    w_blt,
    router,
    weth,
    factory,
    usdc,
):
    # ETH whale sends some to screamsh
    eth_whale = accounts.at("0x224D8Fd7aB6AD4c6eb4611Ce56EF35Dec2277F03", force=True)
    eth_whale.transfer(screamsh, 5e18)
    assert screamsh.balance() > 1e18

    # basic data
    weth_to_swap = 1e17
    weth_to_bmx = [
        (weth.address, w_blt.address, False),
        (w_blt.address, bmx.address, False),
    ]
    weth_to_wblt = [(weth.address, w_blt.address, False)]

    # swap ETH to wBLT
    before = w_blt.balanceOf(screamsh)
    before_eth = screamsh.balance()
    router.swapExactETHForTokens(
        weth_to_swap,
        0,
        weth_to_wblt,
        screamsh,
        2**256 - 1,
        {"from": screamsh, "value": 1e17},
    )
    assert screamsh.balance() < before_eth
    assert w_blt.balanceOf(screamsh) > before
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("\n✅  Swapped from ether to wBLT")

    # swap wBLT to ETH
    wblt_to_swap = w_blt.balanceOf(screamsh)
    w_blt.approve(router, 2**256 - 1, {"from": screamsh})
    back_to_weth = [(w_blt.address, weth.address, False)]
    before_eth = screamsh.balance()
    router.swapExactTokensForETH(
        wblt_to_swap, 0, back_to_weth, screamsh, 2**256 - 1, {"from": screamsh}
    )
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert w_blt.balanceOf(screamsh) == 0
    assert screamsh.balance() > before_eth
    print("✅  Swapped from wBLT back to ether")

    # swap for some BMX from ETH
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    before = bmx.balanceOf(screamsh)
    before_eth = screamsh.balance()
    router.swapExactETHForTokens(
        weth_to_swap,
        0,
        weth_to_bmx,
        screamsh,
        2**256 - 1,
        {"from": screamsh, "value": 1e17},
    )
    assert bmx.balanceOf(screamsh) > before
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert screamsh.balance() < before_eth
    print("✅  Swapped ether to BMX")

    # approve our BMX, back to ETH
    bmx.approve(router, 2**256 - 1, {"from": screamsh})
    bmx_to_usdc = [
        (bmx.address, w_blt.address, False),
        (w_blt.address, usdc.address, False),
    ]
    before_eth = screamsh.balance()
    bmx_to_swap = bmx.balanceOf(screamsh)
    before = usdc.balanceOf(screamsh)
    router.swapExactTokensForETH(
        bmx_to_swap, 0, bmx_to_usdc, screamsh.address, 2**256 - 1, {"from": screamsh}
    )
    assert usdc.balanceOf(screamsh) == before
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert bmx.balanceOf(screamsh) == 0
    assert screamsh.balance() > before_eth
    print("✅  Swapped back from BMX to ether\n")


def test_long_route_swap(
    bmx,
    screamsh,
    w_blt,
    router,
    weth,
    factory,
    usdc,
):
    # whales deposit USDC and WETH to give us some flexibility, USDC-WETH pool on aerodrome
    token_whale = accounts.at("0xB4885Bc63399BF5518b994c1d0C153334Ee579D0", force=True)
    weth.approve(router, 2**256 - 1, {"from": token_whale})
    usdc.approve(router, 2**256 - 1, {"from": token_whale})

    weth_to_wblt = [
        (weth.address, w_blt.address, False),
    ]
    weth_to_swap = 10e18

    usdc_to_wblt = [
        (usdc.address, w_blt.address, False),
    ]
    usdc_to_swap = 10_000e6

    router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_wblt, token_whale, 2**256 - 1, {"from": token_whale}
    )

    router.swapExactTokensForTokens(
        usdc_to_swap, 0, usdc_to_wblt, token_whale, 2**256 - 1, {"from": token_whale}
    )

    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("\n✅  Lots of deposits to wBLT")

    # swap for some BMX via WETH -> USDC
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    weth_to_swap = 1e15
    before = bmx.balanceOf(screamsh)
    weth_to_bmx_long = [
        (weth.address, usdc.address, False),
        (usdc.address, w_blt.address, False),
        (w_blt.address, bmx.address, False),
    ]
    router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_bmx_long, screamsh, 2**256 - 1, {"from": screamsh}
    )
    assert bmx.balanceOf(screamsh) > before
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("✅  Long swap WETH -> USDC -> BMX")

    # swap back to USDC now via WETH
    bmx.approve(router, 2**256 - 1, {"from": screamsh})
    bmx_to_swap = bmx.balanceOf(screamsh) / 2
    before = usdc.balanceOf(screamsh)
    bmx_to_usdc_long = [
        (bmx.address, w_blt.address, False),
        (w_blt.address, weth.address, False),
        (weth.address, usdc.address, False),
    ]
    router.swapExactTokensForTokens(
        bmx_to_swap,
        0,
        bmx_to_usdc_long,
        screamsh.address,
        2**256 - 1,
        {"from": screamsh},
    )
    assert usdc.balanceOf(screamsh) > before
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("✅  Long swap BMX -> WETH -> USDC\n")


def test_add_liq(
    bmx,
    screamsh,
    w_blt,
    router,
    weth,
    factory,
    usdc,
):

    # add liquidity
    # swap for some BMX
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    bmx.approve(router, 2**256 - 1, {"from": screamsh})
    weth_to_swap = 1e15
    weth_to_bmx = [
        (weth.address, w_blt.address, False),
        (w_blt.address, bmx.address, False),
    ]
    before = bmx.balanceOf(screamsh)
    router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_bmx, screamsh, 2**256 - 1, {"from": screamsh}
    )
    assert bmx.balanceOf(screamsh) > before

    # calculate how much liquidity we need to add
    quote = router.quoteAddLiquidityUnderlying(
        weth, bmx, 1e15, 1e18, {"from": screamsh}
    )
    underlying_to_add = quote[0]
    wblt_expected = quote[1]
    token_to_add = quote[2]

    print("\n🥸 Quote:", quote.dict())

    lp = Contract("0xd272920b2b4ebee362a887451edbd6d68a76e507")
    assert lp.balanceOf(screamsh) == 0
    real = router.addLiquidity(
        weth,
        underlying_to_add,
        bmx,
        wblt_expected,
        token_to_add,
        0,
        0,
        screamsh.address,
        {"from": screamsh},
    )
    print("💯 Real:", real.return_value.dict())
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert lp.balanceOf(router) == 0
    assert lp.balanceOf(screamsh) > 0
    print("✅  Added liquidity for BMX-wBLT with WETH\n")


def test_add_liq_ether(
    bmx,
    screamsh,
    w_blt,
    router,
    weth,
    factory,
    usdc,
):
    # ETH whale sends some to screamsh
    eth_whale = accounts.at("0x224D8Fd7aB6AD4c6eb4611Ce56EF35Dec2277F03", force=True)
    eth_whale.transfer(screamsh, 5e18)
    assert screamsh.balance() > 1e18

    # add liquidity
    # swap for some BMX
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    bmx.approve(router, 2**256 - 1, {"from": screamsh})
    weth_to_swap = 1e15
    weth_to_bmx = [
        (weth.address, w_blt.address, False),
        (w_blt.address, bmx.address, False),
    ]
    before = bmx.balanceOf(screamsh)
    router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_bmx, screamsh, 2**256 - 1, {"from": screamsh}
    )
    assert bmx.balanceOf(screamsh) > before

    # calculate how much liquidity we need to add
    quote = router.quoteAddLiquidityUnderlying(weth, bmx, 1e15, 1e18)
    underlying_to_add = quote[0]
    wblt_expected = quote[1]
    token_to_add = quote[2]

    lp = Contract("0xd272920b2b4ebee362a887451edbd6d68a76e507")
    assert lp.balanceOf(screamsh) == 0

    router.addLiquidityETH(
        underlying_to_add,
        bmx,
        wblt_expected,
        token_to_add,
        0,
        0,
        screamsh.address,
        {"from": screamsh, "value": underlying_to_add},
    )
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert lp.balanceOf(router) == 0
    assert lp.balanceOf(screamsh) > 0
    print("\n✅  Added liquidity for BMX-wBLT with Ether\n")


def test_remove_liq(
    bmx,
    screamsh,
    w_blt,
    router,
    weth,
    factory,
    usdc,
):
    # whales deposit USDC and WETH to give us some flexibility, USDC-WETH pool on aerodrome
    token_whale = accounts.at("0xB4885Bc63399BF5518b994c1d0C153334Ee579D0", force=True)
    weth.approve(router, 2**256 - 1, {"from": token_whale})
    usdc.approve(router, 2**256 - 1, {"from": token_whale})

    # send screamsh WETH and oBMX
    weth_whale = accounts.at("0xB4885Bc63399BF5518b994c1d0C153334Ee579D0", force=True)
    weth.transfer(screamsh, 10e18, {"from": weth_whale})

    weth_to_wblt = [
        (weth.address, w_blt.address, False),
    ]
    weth_to_swap = 10e18

    usdc_to_wblt = [
        (usdc.address, w_blt.address, False),
    ]
    usdc_to_swap = 10_000e6

    router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_wblt, token_whale, 2**256 - 1, {"from": token_whale}
    )

    router.swapExactTokensForTokens(
        usdc_to_swap, 0, usdc_to_wblt, token_whale, 2**256 - 1, {"from": token_whale}
    )

    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("\n✅  Lots of deposits to wBLT")

    # add liquidity
    # swap for some BMX
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    bmx.approve(router, 2**256 - 1, {"from": screamsh})
    weth_to_swap = 1e17
    weth_to_bmx = [
        (weth.address, w_blt.address, False),
        (w_blt.address, bmx.address, False),
    ]
    before = bmx.balanceOf(screamsh)
    router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_bmx, screamsh, 2**256 - 1, {"from": screamsh}
    )
    assert bmx.balanceOf(screamsh) > before
    lp = Contract("0xd272920b2b4ebee362a887451edbd6d68a76e507")
    assert lp.balanceOf(screamsh) == 0
    router.addLiquidity(
        weth,
        weth_to_swap,
        bmx,
        50e18,
        50e18,
        0,
        0,
        screamsh.address,
        {"from": screamsh},
    )
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert lp.balanceOf(router) == 0
    assert lp.balanceOf(screamsh) > 0
    print("✅  Added liquidity for BMX-wBLT with WETH")
    chain.sleep(1)
    chain.mine(1)

    # remove our liq
    lp.approve(router, 2**256 - 1, {"from": screamsh})
    before_bmx = bmx.balanceOf(screamsh)
    before_weth = weth.balanceOf(screamsh)

    # predict what we would get
    simulate = router.quoteRemoveLiquidityUnderlying(
        weth, bmx, lp.balanceOf(screamsh), {"from": screamsh}
    )

    print("🥸 Estimated amounts:", simulate.dict())

    real = router.removeLiquidity(
        weth, bmx, lp.balanceOf(screamsh), 0, 0, screamsh.address, {"from": screamsh}
    )
    print("💯 Real amounts:", real.return_value.dict())

    assert before_bmx < bmx.balanceOf(screamsh)
    assert before_weth < weth.balanceOf(screamsh)
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert lp.balanceOf(router) == 0
    assert lp.balanceOf(screamsh) == 0
    print("✅  Removed liquidity for BMX-wBLT to WETH+BMX\n")


def test_remove_liq_ether(
    bmx,
    screamsh,
    w_blt,
    router,
    weth,
    factory,
    usdc,
):
    # whales deposit USDC and WETH to give us some flexibility, USDC-WETH pool on aerodrome
    token_whale = accounts.at("0xB4885Bc63399BF5518b994c1d0C153334Ee579D0", force=True)
    weth.approve(router, 2**256 - 1, {"from": token_whale})
    usdc.approve(router, 2**256 - 1, {"from": token_whale})

    # send screamsh WETH and oBMX
    weth_whale = accounts.at("0xB4885Bc63399BF5518b994c1d0C153334Ee579D0", force=True)
    weth.transfer(screamsh, 10e18, {"from": weth_whale})

    weth_to_wblt = [
        (weth.address, w_blt.address, False),
    ]
    weth_to_swap = 10e18

    usdc_to_wblt = [
        (usdc.address, w_blt.address, False),
    ]
    usdc_to_swap = 10_000e6

    router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_wblt, token_whale, 2**256 - 1, {"from": token_whale}
    )

    router.swapExactTokensForTokens(
        usdc_to_swap, 0, usdc_to_wblt, token_whale, 2**256 - 1, {"from": token_whale}
    )

    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    print("\n✅  Lots of deposits to wBLT")

    # add liquidity
    # swap for some BMX
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    bmx.approve(router, 2**256 - 1, {"from": screamsh})
    weth_to_swap = 1e17
    weth_to_bmx = [
        (weth.address, w_blt.address, False),
        (w_blt.address, bmx.address, False),
    ]
    before = bmx.balanceOf(screamsh)
    router.swapExactTokensForTokens(
        weth_to_swap, 0, weth_to_bmx, screamsh, 2**256 - 1, {"from": screamsh}
    )
    assert bmx.balanceOf(screamsh) > before
    lp = Contract("0xd272920b2b4ebee362a887451edbd6d68a76e507")
    assert lp.balanceOf(screamsh) == 0
    router.addLiquidity(
        weth,
        weth_to_swap,
        bmx,
        50e18,
        50e18,
        0,
        0,
        screamsh.address,
        {"from": screamsh},
    )
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert lp.balanceOf(router) == 0
    assert lp.balanceOf(screamsh) > 0
    print("✅  Added liquidity for BMX-wBLT with WETH")
    chain.sleep(1)
    chain.mine(1)

    # remove our liq
    lp.approve(router, 2**256 - 1, {"from": screamsh})
    before_bmx = bmx.balanceOf(screamsh)
    before_eth = screamsh.balance()
    router.removeLiquidityETH(
        bmx, lp.balanceOf(screamsh), 0, 0, screamsh.address, {"from": screamsh}
    )
    assert before_bmx < bmx.balanceOf(screamsh)
    assert before_eth < screamsh.balance()
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert lp.balanceOf(router) == 0
    assert lp.balanceOf(screamsh) == 0
    print("✅  Removed liquidity for BMX-wBLT to ether+BMX\n")


def test_options(
    bmx,
    screamsh,
    w_blt,
    router,
    weth,
    factory,
    usdc,
    gauge,
    obmx,
):

    # send screamsh WETH and oBMX
    weth_whale = accounts.at("0xB4885Bc63399BF5518b994c1d0C153334Ee579D0", force=True)
    weth.transfer(screamsh, 10e18, {"from": weth_whale})
    obmx_whale = accounts.at("0xeA00CFb98716B70760A6E8A5Ffdb8781Ef63fa5A", force=True)
    obmx.transfer(screamsh, 100e18, {"from": obmx_whale})

    # testing oBMX
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    obmx.approve(router, 2**256 - 1, {"from": screamsh})

    # figure out how much weth we need for our oBMX balance
    # calculate wBLT needed for our oBMX
    to_exercise = 1e17
    discount = 35
    output = router.quoteTokenNeededToExerciseLp(
        weth, to_exercise, discount, {"from": screamsh}
    )
    weth_needed = output.return_value[1]
    print(
        "WETH (safe) needed for LP exercising 1e17 oBMX:", weth_needed / 1e18
    )  # this should be around 0.00062499027
    lp = Contract("0xd272920b2b4ebee362a887451edbd6d68a76e507")
    assert lp.balanceOf(screamsh) == 0
    w_blt_before = w_blt.balanceOf(screamsh)
    before_obmx = obmx.balanceOf(screamsh)
    before_weth = weth.balanceOf(screamsh)

    router.exerciseLpWithUnderlying(
        weth.address,
        weth_needed,
        to_exercise,
        discount,
        2**256 - 1,
        {"from": screamsh},
    )
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert lp.balanceOf(router) == 0
    assert gauge.balanceOf(screamsh) > 0
    assert lp.balanceOf(screamsh) == 0
    assert weth.balanceOf(screamsh) < before_weth
    assert obmx.balanceOf(screamsh) < before_obmx
    print(
        "Extra wBLT sent back to user:",
        (w_blt.balanceOf(screamsh) - w_blt_before) / 1e18,
    )


def test_options_eth(
    bmx,
    screamsh,
    w_blt,
    router,
    weth,
    factory,
    usdc,
    gauge,
    obmx,
):
    # ETH whale sends some to screamsh
    eth_whale = accounts.at("0x224D8Fd7aB6AD4c6eb4611Ce56EF35Dec2277F03", force=True)
    eth_whale.transfer(screamsh, 5e18)
    assert screamsh.balance() > 1e18

    # send screamsh WETH and oBMX
    weth_whale = accounts.at("0xB4885Bc63399BF5518b994c1d0C153334Ee579D0", force=True)
    weth.transfer(screamsh, 10e18, {"from": weth_whale})
    obmx_whale = accounts.at("0xeA00CFb98716B70760A6E8A5Ffdb8781Ef63fa5A", force=True)
    obmx.transfer(screamsh, 100e18, {"from": obmx_whale})

    # testing oBMX
    weth.approve(router, 2**256 - 1, {"from": screamsh})
    obmx.approve(router, 2**256 - 1, {"from": screamsh})

    # figure out how much weth we need for our oBMX balance
    # calculate wBLT needed for our oBMX
    to_exercise = 1e17
    discount = 35
    output = router.quoteTokenNeededToExerciseLp(
        weth, to_exercise, discount, {"from": screamsh}
    )
    weth_needed = output.return_value[1]
    print(
        "ETH (safe) needed for LP exercising 1e17 oBMX:", weth_needed / 1e18
    )  # this should be around 0.00062499027

    # calculate our WETH needed for wBLT
    lp = Contract("0xd272920b2b4ebee362a887451edbd6d68a76e507")
    assert lp.balanceOf(screamsh) == 0
    w_blt_before = w_blt.balanceOf(screamsh)
    before_obmx = obmx.balanceOf(screamsh)
    before_eth = screamsh.balance()

    router.exerciseLpWithUnderlyingETH(
        weth_needed,
        to_exercise,
        discount,
        2**256 - 1,
        {"from": screamsh, "value": weth_needed},
    )
    assert bmx.balanceOf(router) == 0
    assert weth.balanceOf(router) == 0
    assert usdc.balanceOf(router) == 0
    assert w_blt.balanceOf(router) == 0
    assert lp.balanceOf(router) == 0
    assert gauge.balanceOf(screamsh) > 0
    assert lp.balanceOf(screamsh) == 0
    assert before_eth > screamsh.balance()
    assert obmx.balanceOf(screamsh) < before_obmx
    print(
        "Extra wBLT sent back to user:",
        (w_blt.balanceOf(screamsh) - w_blt_before) / 1e18,
    )