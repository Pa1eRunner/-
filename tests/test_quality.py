from newsbot.config import load_config
from newsbot.quality import is_low_information_sentence, quality_issues


def test_detects_low_information_transition_sentence() -> None:
    assert is_low_information_sentence("在此背景下，出售该公司理由也很充分。")
    assert not is_low_information_sentence("公司拟转让99%股权，交易对价为7.5亿元。")


def test_blocks_meta_disclaimer_and_unsourced_ranking() -> None:
    issues = quality_issues("该公司是行业前二；该口径属于历史披露，不代表当前排名。")
    assert "包含未经当前信源验证的行业排名或头部表述" in issues
    assert any(issue.startswith("包含元叙述") for issue in issues)


def test_all_configured_company_profiles_pass_quality_gate() -> None:
    config = load_config("config/config.yaml")
    for company, profile in config.company_profiles.items():
        assert quality_issues(profile) == [], company
