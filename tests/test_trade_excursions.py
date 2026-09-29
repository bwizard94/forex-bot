import pytest
from src.analysis.trade_excursions import analyze, fetch_window, timestamp


def trade(side='SELL'):
    return dict(trade_id='1', symbol='EUR/USD', ownership='bot', side=side,
                opened_at='2026-09-16T00:00:30Z', closed_at='2026-09-16T00:03:30Z',
                entry_price='1.1000', price_pl='-10', financing='0')


def candle(minute, low='1.0990', high='1.1010', complete=True):
    return {'time': f'2026-09-16T00:{minute:02d}:00Z', 'complete': complete,
            'bid': {'o':'1.1000','h':high,'l':low,'c':'1.1000'},
            'ask': {'o':'1.1002','h':str(float(high)+.0002),'l':str(float(low)+.0002),'c':'1.1002'}}


@pytest.mark.parametrize('side,favorable,adverse', [('SELL',8,12),('BUY',10,10)])
def test_executable_side_and_boundary_exclusion(side, favorable, adverse):
    rows = [candle(0,low='1.0000'), candle(1), candle(2), candle(3,high='1.9000')]
    result = analyze(trade(side), rows)
    assert float(result['favorable_excursion_observed_pips']) == pytest.approx(favorable)
    assert float(result['adverse_excursion_observed_pips']) == pytest.approx(adverse)
    assert result['full_bars_observed'] == result['full_wall_clock_minutes'] == 2
    assert float(result['mean_bar_open_spread_pips']) == pytest.approx(2)


def test_missing_and_incomplete_bars_never_claim_full_coverage():
    result = analyze(trade(), [candle(1,complete=False)])
    assert result['favorable_excursion_observed_pips'] is None
    assert result['unobserved_wall_clock_minutes'] == 2


def test_duplicate_and_nonfinite_prices_rejected():
    with pytest.raises(ValueError):
        analyze(trade(), [candle(1),candle(1)])
    row = candle(1); row['ask']['h'] = 'NaN'
    with pytest.raises(ValueError):
        analyze(trade(), [row])


def test_market_gap_explicit_not_filled():
    t = trade(); t['closed_at'] = '2026-09-16T00:05:00Z'
    result = analyze(t, [candle(1),candle(4)])
    assert result['interior_gaps'][0]['missing_minutes'] == 2
    assert result['unobserved_wall_clock_minutes'] == 2


def test_daily_chunks_are_get_only_and_keep_bid_ask():
    class Client:
        def __init__(self): self.calls=[]
        def request(self, ep):
            assert ep.method == 'GET'
            self.calls.append(ep.params)
            return {'instrument':'EUR_USD','granularity':'M1','candles':[]}
    client=Client()
    rows=fetch_window(client,timestamp('2026-09-16T00:00:30Z'),timestamp('2026-09-18T01:00:00Z'))
    assert rows == [] and len(client.calls)==3
    assert all(c['price']=='BA' and 'count' not in c for c in client.calls)
