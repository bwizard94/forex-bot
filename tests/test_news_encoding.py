from types import SimpleNamespace
import pytest
import requests
from src.data import news


def test_rss_uses_xml_encoding_not_http_text_decoding(monkeypatch):
    content=b'\xef\xbb\xbf<?xml version="1.0" encoding="utf-8"?><rss><channel><item><title>Fed policy caf\xc3\xa9</title><link>https://example.test</link></item></channel></rss>'
    monkeypatch.setattr(news,'_get',lambda url:SimpleNamespace(content=content,text=content.decode('latin1')))
    items=news._rss_items('https://example.test','Fed')
    assert len(items)==1 and items[0].title=='Fed policy café'


def test_http_errors_are_reported_before_parsing(monkeypatch):
    r=requests.Response();r.status_code=503;r.url='https://example.test'
    monkeypatch.setattr(news.requests,'get',lambda *a,**kw:r)
    with pytest.raises(requests.HTTPError):news._get(r.url)
