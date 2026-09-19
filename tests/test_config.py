import json

from tdxhub import config
from tdxhub.consts import EX_HOSTS, HQ_HOSTS


def _endpoints(hosts):
    return [(str(host[1]), int(host[2])) for host in hosts]


def test_setup_appends_new_default_quote_hosts_to_persisted_lists(tmp_path):
    original_conf = config.CONF
    persisted_hq = [
        ["自定义行情", "127.0.0.1", 7709],
        ["旧名称", HQ_HOSTS[0][1], HQ_HOSTS[0][2]],
    ]
    persisted_ex = [["旧扩展名称", EX_HOSTS[0][1], EX_HOSTS[0][2]]]
    local_conf = tmp_path / "config.json"
    local_conf.write_text(
        json.dumps({"SERVER": {"HQ": persisted_hq, "EX": persisted_ex}}),
        encoding="utf-8",
    )

    try:
        config.CONF = local_conf
        config.setup(force=True)

        loaded_hq = config.get("SERVER.HQ")
        loaded_ex = config.get("SERVER.EX")
        hq_endpoints = _endpoints(loaded_hq)
        ex_endpoints = _endpoints(loaded_ex)

        assert loaded_hq[:2] == persisted_hq
        assert loaded_ex[0] == persisted_ex[0]
        assert len(hq_endpoints) == len(HQ_HOSTS) + 1
        assert len(ex_endpoints) == len(EX_HOSTS)
        assert len(hq_endpoints) == len(set(hq_endpoints))
        assert len(ex_endpoints) == len(set(ex_endpoints))
        assert set(_endpoints(HQ_HOSTS)) <= set(hq_endpoints)
        assert set(_endpoints(EX_HOSTS)) <= set(ex_endpoints)
    finally:
        config.CONF = original_conf
        config.setup(force=True)
