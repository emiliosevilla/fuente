from fuente.bootstrap import is_gestajo_agent_install_request


def test_only_the_fixed_gestajo_agent_url_can_open_the_installer():
    assert is_gestajo_agent_install_request(["fuente://gestajo-agent/install"])
    assert not is_gestajo_agent_install_request(["fuente://gestajo-agent/install?force=true"])
    assert not is_gestajo_agent_install_request(["fuente://other/install"])
