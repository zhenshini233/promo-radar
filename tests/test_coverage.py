"""覆盖/登记名单的反向匹配测试（vendor_links + 品牌表兜底）。"""



from radar.domain.brands import BRANDS, _GROUPS
from radar.domain.coverage import norm, vendor_links


def test_vendor_links_matches_registry_keys_to_monitors():
    registries = {"litellm": ["groq", "fireworksai", "zzz"]}
    monitors = [
        {"provider": "Groq", "label": "home", "url": "https://groq.com"},
        {"provider": "Fireworks", "label": "home", "url": "https://fireworks.ai"},
    ]
    links = vendor_links(registries, monitors)
    assert links["litellm"]["groq"] == ("Groq", "https://groq.com")
    # 命名变体：fireworksai ↔ Fireworks 双向包含
    assert links["litellm"]["fireworksai"] == ("Fireworks", "https://fireworks.ai")
    # 无匹配厂商且无品牌注解 → 不产生链接
    assert "zzz" not in links["litellm"]


def test_vendor_links_prefers_exact_key_match():
    registries = {"openrouter": ["mistralai"]}
    monitors = [
        {"provider": "Mistral", "label": "home", "url": "https://mistral.ai"},
        {"provider": "MistralAI Router", "label": "home", "url": "https://router.example.com"},
    ]
    links = vendor_links(registries, monitors)
    # 精确命中优先于包含匹配，且取名字序靠前者
    assert links["openrouter"]["mistralai"][0] == "Mistral"


def test_vendor_links_brand_fallback():
    registries = {"litellm": ["v0", "azure", "bespoke"]}
    monitors = []  # watchlist 全没收录
    links = vendor_links(registries, monitors)
    # 键太短（v0）或 watchlist 未收录（azure）的键由品牌表兜底
    assert links["litellm"]["v0"] == ("v0（Vercel）", "https://v0.app")
    assert links["litellm"]["azure"] == ("Microsoft Azure", "https://azure.microsoft.com")
    assert links["litellm"]["bespoke"] == ("Bespoke Labs", "https://bespokelabs.ai")


def test_vendor_links_brand_resolves_through_monitor():
    registries = {"litellm": ["cartesiasonic3", "kyma"]}
    monitors = [{"provider": "Cartesia", "label": "home", "url": "https://cartesia.ai"}]
    links = vendor_links(registries, monitors)
    # 品牌官网域名已被监控 → 显示名/链接取监控（单一事实源）
    assert links["litellm"]["cartesiasonic3"] == ("Cartesia", "https://cartesia.ai")
    # 监控没有的域名 → 用品牌表自己的数据
    assert links["litellm"]["kyma"] == (
        "SAP Kyma", "https://www.sap.com/products/technology-platform/kyma.html")


def test_brands_table_keys_are_normalized():
    for k, (label, url) in BRANDS.items():
        assert norm(k) == k, f"键 {k!r} 不是 norm 形式"
        assert label.strip(), f"{k} 显示名为空"
        assert url == "" or url.startswith(("http://", "https://")), f"{k} 的 url 非法: {url!r}"


def test_brands_groups_have_no_alias_collision():
    total = sum(1 + len(aliases) for _, _, _, aliases in _GROUPS)
    assert len(BRANDS) == total, "组间键冲突：同一别名被两个品牌定义"
