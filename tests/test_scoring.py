"""打分测试：促销样例过线、噪音样例丢弃、金额/绑卡线索抽取。"""

from radar.domain.models import RawItem
from radar.domain.scoring import score_item

THRESHOLD = 4.0


def _score(title: str, evidence: str = ""):
    return score_item(RawItem(source="t", title=title, evidence=evidence))


def test_promo_samples_pass_threshold():
    promos = [
        ("新用户注册送 $25 额度", ""),
        ("【魔芋AI】专属福利10额度送送送", "通过该链接注册会赠送2额度，回复ID可获10额度兑换码"),
        ("阿里云百炼平台免费额度", ""),
        ("[合租巴士] gpt-5.5 低至0.12/刀，评论留id送额度！新老用户都送！", ""),
        ("Show HN: River AI – $25 in free credits for new signups", ""),
        ("[富可敌国] Baby max20.cn 新用户留ID领10刀余额", "我们发放 $10 专属测试兑换码"),
        ("免费领取glm5.2 key的一个网站", "Free GLM-5.2 API Access, get a free key instantly"),
        ("免费试用glm5.1，华为云免费试用", "可以免费使用glm5.1"),
    ]
    for title, ev in promos:
        s = _score(title, ev)
        assert s.score >= THRESHOLD, f"应过线但被丢弃: {title!r} score={s.score} matched={s.matched}"


def test_noise_samples_dropped():
    noise = [
        "瑞幸抽免单，6.29-6.30",
        "【6.29】券商万一免五开户！低佣金股票账户推荐",
        "六月见底，别忘了领阿里云朵挂件",
        "Google Play 一波游戏促销比如0.1刀的气球塔防6",
        "网易云黑胶会员领取随机天数",
        "感谢各位佬的机场，我也分享一个闲置的机场，7月1号过期",
    ]
    for title in noise:
        s = _score(title)
        assert s.score < THRESHOLD, f"噪音被误放行: {title!r} score={s.score} matched={s.matched}"


def test_amount_extraction():
    s = _score("注册送 $25 额度", "welcome credit for new signups")
    assert s.item.amount_hint == "$25"

    s2 = _score("免费额度大放送", "首月赠送 $100 额度")
    assert s2.item.amount_hint == "$100"


def test_card_required_extraction():
    assert _score("绑卡送额度活动", "").item.card_required_hint is True
    assert _score("注册送额度", "no credit card required").item.card_required_hint is False
    assert _score("注册送额度", "无需绑卡即可领取").item.card_required_hint is False
    assert _score("注册送额度", "").item.card_required_hint is None


def test_explicit_amount_hint_not_overridden():
    item = RawItem(source="t", title="注册送 $25 额度", amount_hint="$25 signup bonus")
    s = score_item(item)
    assert s.item.amount_hint == "$25 signup bonus"


def test_evidence_truncated():
    s = _score("注册送额度", "x" * 1000)
    assert len(s.item.evidence) <= 300
