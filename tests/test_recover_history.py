from types import SimpleNamespace
import pytest
from src.analysis.recover_history import recover


def row(key='10', stamp='fs-test', **extra):
    return dict(id=key, instrument='EUR_USD', state='CLOSED', initialUnits='-100000',
                openTime='2026-09-16T00:00:00Z', closeTime='2026-09-16T01:00:00Z',
                price='1.1', averageClosePrice='1.10023', realizedPL='-23', financing='0.1',
                clientExtensions={'id': stamp}, closingTransactionIDs=['11'], **extra)


class Client:
    account_id = 'private-account'
    settings = SimpleNamespace(oanda_environment='practice')

    def __init__(self, pages, tx=None):
        self.pages = iter(pages)
        self.calls = []
        self.tx = tx or {'id': '11', 'type': 'ORDER_FILL', 'reason': 'STOP_LOSS_ORDER',
                         'tradesClosed': [{'tradeID': '10'}]}

    def request(self, endpoint):
        assert endpoint.method == 'GET'
        self.calls.append(endpoint)
        if type(endpoint).__name__ == 'TransactionDetails':
            return {'transaction': self.tx}
        return {'trades': next(self.pages)}


def test_recovery_separates_ownership_costs_and_unknown_evidence():
    client = Client([[row(), row('9', 'human')], []])
    result = recover(client, page_size=2)
    assert result['summary']['bot']['price_pl'] == '-23'
    assert result['summary']['bot']['financing_known'] == '0.1'
    assert result['summary']['human']['closed_trades'] == 1
    assert client.calls[-1].params['beforeID'] == '8'
    assert 'private-account' not in str(result)
    assert result['trades'][1]['close_evidence'][0]['reason'] == 'STOP_LOSS_ORDER'
    assert all(r['initial_risk'] is None and not r['eligible_for_live_learning'] for r in result['trades'])


def test_missing_financing_is_not_zero():
    data = row('10', 'manual'); data.pop('financing')
    result = recover(Client([[data], []]))
    assert result['summary']['human']['financing_missing'] == 1
    assert result['trades'][0]['financing'] is None


@pytest.mark.parametrize('change', [{'instrument': 'GBP_USD'}, {'state': 'OPEN'}, {'realizedPL': 'NaN'}])
def test_invalid_broker_record_rejected(change):
    data = row(); data.update(change)
    with pytest.raises(ValueError):
        recover(Client([[data], []]))


def test_nonadvancing_page_and_truncation_rejected():
    with pytest.raises(ValueError, match='advance'):
        recover(Client([[row()], [row()]]))
    with pytest.raises(ValueError, match='limit'):
        recover(Client([[row()]]), max_pages=1)


def test_unrelated_close_rejected():
    client = Client([[row()]], tx={'id': '11', 'tradesClosed': [{'tradeID': '999'}]})
    with pytest.raises(ValueError, match='reference'):
        recover(client)


def test_live_account_rejected_before_request():
    client = Client([]); client.settings = SimpleNamespace(oanda_environment='live')
    with pytest.raises(ValueError, match='practice'):
        recover(client)
    assert client.calls == []
