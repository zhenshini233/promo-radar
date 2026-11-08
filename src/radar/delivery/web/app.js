/* promo-radar dashboard — Vue 3（本地 vendor，无构建）。
 * 数据来自内联 JSON（file:// 可用）；serve 模式提供手动/细分刷新。
 * 筛选、分页全部走 computed，Vue 负责 diff 渲染，避免全量 innerHTML 卡顿。
 */
(function () {
  "use strict";

  var dataEl = document.getElementById("radar-data");
  if (!dataEl || !window.Vue) return; // Vue 缺失时保留 SSR 内容
  // 全量由 data.js 提供（file:// 与 HTTP 都可用）；内联 JSON 只是兜底子集，
  // 保证 data.js 加载失败时页面仍可交互。
  var DATA = window.__RADAR_FULL__ || JSON.parse(dataEl.textContent);
  // v10：统一目录——所有来源都写 offers，前端只读这一份
  var MONITORS = DATA.monitors || [];
  var OFFERS = DATA.offers || [];
  var DEALS = OFFERS;
  var SCENARIOS = DATA.scenarios || [];
  var VENDORS = DATA.vendors || [];
  var VERTICAL_CN = {
    ai_api: "AI 促销", ai_compute: "免费算力", cloud: "云计算", vps: "VPS 特价", paas: "部署平台",
    storage: "存储", database: "数据库", cdn: "CDN / 网络", devtool: "开发者工具",
  };
  var CLAIM_KEY = "radar.claims.v1";
  // 用途不是独立页面，而是资源的一个筛选维度
  var USE_CASES = [
    { id: "static", label: "静态站", keywords: ["pages", "netlify", "vercel", "surge", "firebase", "hosting"] },
    { id: "fullstack", label: "全栈 + 数据库", keywords: ["supabase", "neon", "turso", "upstash", "mongo", "postgres", "database"] },
    { id: "backend", label: "后端 / 容器", keywords: ["render", "koyeb", "fly", "railway", "cloud run", "workers", "deno", "serverless"] },
    { id: "storage", label: "对象存储", keywords: ["r2", "b2", "backblaze", "storage", "bucket"] },
    { id: "vps", label: "自建 VPS", keywords: ["oracle", "hetzner", "racknerd", "contabo", "vps", "compute"] },
  ];

  var STATUS_NAMES = { "new": "新增", "updated": "有更新", "expired": "已过期", "active": "可用", "unknown": "待确认" };
  var AMOUNT_BUCKETS = ["<$10", "$10–99", "$100–999", "$1k+", "无金额"];

  // 源元数据由 payload 下发（唯一来源 coverage.py），避免前端手抄漂移
  var SRC_TYPE = DATA.source_meta || {};
  var SRC_ORDER = DATA.source_order || Object.keys(SRC_TYPE);
  var SRC_NAMES = {};
  Object.keys(SRC_TYPE).forEach(function (id) { SRC_NAMES[id] = SRC_TYPE[id].name; });

  /* 类型归并：raw 关键词标签 → 人话分类 */
  var TYPE_GROUPS = [
    ["降价", ["降价"]],
    ["兑换码", ["兑换码", "promo code"]],
    ["限时", ["限时", "grant/startup credits"]],
    ["免绑卡", ["no credit card"]],
    ["免费试用", ["free tier", "free trial", "免费试用/领取", "体验额度", "token plan", "free api/key", "免费使用/送"]],
    ["注册赠送", ["free credits", "signup bonus", "welcome credit", "signup credit", "注册送/赠送额度", "新人福利", "留ID送", "送额度", "额度送", "送…额度/刀", "免费额度"]],
    ["赠送额度", ["$X credits", "额度(弱)", "绑卡"]],
  ];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function norm(s) { return String(s || "").toLowerCase(); }

  Vue.createApp({
    delimiters: ["[[", "]]"],
    setup() {
      var reactive = Vue.reactive, computed = Vue.computed, ref = Vue.ref,
          watch = Vue.watch, onMounted = Vue.onMounted;

      var st = reactive({
        page: "overview",
        dealView: "cards",
        q: "", qd: "",
        sources: {}, types: {}, amounts: {}, statuses: {}, verticals: {}, regions: {},
        sort: "recent", pageNum: 1, pageSize: 24,
        monFilter: "all", coverSource: "全部",
        monQ: "", monQd: "", monPage: 1, monPageSize: 30, monV: "all",
        serveMode: false, refreshing: false, refreshMsg: "", showLocal: false,
        proxyUrl: "", proxyMsg: "", proxySaving: false,
        refreshSel: {}, expandedVendors: null,
        votes: {}, feedbackMsg: "",
        useCase: "all", claims: loadClaims(), claimMsg: "",
      });

      function loadClaims() {
        try { return JSON.parse(localStorage.getItem(CLAIM_KEY) || "{}") || {}; }
        catch (e) { return {}; }
      }
      function saveClaims(c) {
        try { localStorage.setItem(CLAIM_KEY, JSON.stringify(c)); } catch (e) {}
      }

      // ---------- 工具 ----------
      function firstAmount(d) {
        var s = d.amount_hint || "";
        var m = /\$\s?[\d,]+(?:\.\d+)?\s*[kK]?|[~≈]?\s?\d[\d,]*\s*(?:万|亿)?\s*tokens/i.exec(s);
        return m ? m[0].replace(/\s+/g, " ").trim() : "";
      }
      function amountValue(d) {
        var m = /\$\s?([\d,]+(?:\.\d+)?)\s*([kK]?)/.exec(d.amount_hint || "");
        if (!m) return -1;
        var v = parseFloat(m[1].replace(/,/g, ""));
        return m[2] ? v * 1000 : v;
      }
      function amountBucket(d) {
        var v = amountValue(d);
        if (v < 0) return "无金额";
        if (v < 10) return "<$10";
        if (v < 100) return "$10–99";
        if (v < 1000) return "$100–999";
        return "$1k+";
      }
      function categoryOf(d) {
        if (d.type_cn) return d.type_cn;
        var m = d.matched || [];
        for (var i = 0; i < TYPE_GROUPS.length; i++) {
          var g = TYPE_GROUPS[i];
          for (var j = 0; j < g[1].length; j++) if (m.indexOf(g[1][j]) >= 0) return g[0];
        }
        return "其他";
      }

      // ---------- 活动页 computed ----------
      var filteredDeals = computed(function () {
        var hasSrc = Object.keys(st.sources).length > 0;
        var hasV = Object.keys(st.verticals).length > 0;
        var hasSt = Object.keys(st.statuses).length > 0;
        var hasAmt = Object.keys(st.amounts).length > 0;
        var hasType = Object.keys(st.types).length > 0;
        return DEALS.filter(function (d) {
          // 已过期只在「已过期」页展示；资源页默认只看仍可用的
          if (d.status === "expired" && !st.statuses.expired) return false;
          if (hasSrc && !st.sources[d.source]) return false;
          if (hasV && !st.verticals[d.vertical]) return false;
          if (hasSt && !st.statuses[d.status]) return false;
          if (hasAmt && !st.amounts[amountBucket(d)]) return false;
          if (hasType && st.types[categoryOf(d)] !== true) return false;
          if (Object.keys(st.regions).length) {
            var regs = (d.regions && d.regions.length) ? d.regions : ["GLOBAL"];
            var hitReg = false;
            for (var ri = 0; ri < regs.length; ri++) if (st.regions[regs[ri]]) hitReg = true;
            if (!hitReg) return false;
          }
          if (st.useCase !== "all") {
            var uc = null;
            for (var ui = 0; ui < USE_CASES.length; ui++) {
              if (USE_CASES[ui].id === st.useCase) uc = USE_CASES[ui];
            }
            if (uc) {
              var uh = ((d.provider || "") + " " + (d.title || "") + " " +
                        (d.category || "") + " " + (d.evidence || "")).toLowerCase();
              if (!uc.keywords.some(function (k) { return uh.indexOf(k) >= 0; })) return false;
            }
          }
          if (st.qd) {
            var hay = (d.title + " " + (d.provider || "") + " " + (d.evidence || "")).toLowerCase();
            if (hay.indexOf(st.qd) < 0) return false;
          }
          return true;
        });
      });
      var sortedDeals = computed(function () {
        var arr = filteredDeals.value.slice();
        // 反馈回灌：误报与暂时不关心排到后面（down > snooze > 正常）
        var fbWeight = function (d) {
          var v = voteOf(d);
          return v === "down" ? 2 : v === "snooze" ? 1 : 0;
        };
        var primary = function (a, b) {
          if (st.sort === "score") return b.score - a.score || (a.first_seen_at < b.first_seen_at ? 1 : -1);
          if (st.sort === "amount") return amountValue(b) - amountValue(a);
          return a.last_changed_at < b.last_changed_at ? 1 : -1;
        };
        arr.sort(function (a, b) { return fbWeight(a) - fbWeight(b) || primary(a, b); });
        return arr;
      });
      var dealPages = computed(function () {
        return Math.max(1, Math.ceil(sortedDeals.value.length / st.pageSize));
      });
      var pagedDeals = computed(function () {
        var arr = sortedDeals.value;
        var p = Math.min(st.pageNum, dealPages.value);
        return arr.slice((p - 1) * st.pageSize, p * st.pageSize);
      });
      var pageList = computed(function () {
        var total = dealPages.value, p = Math.min(st.pageNum, total), nums = [];
        for (var i = 1; i <= total; i++) {
          if (i === 1 || i === total || Math.abs(i - p) <= 2) nums.push(i);
          else if (nums[nums.length - 1] !== "…") nums.push("…");
        }
        return nums;
      });

      var chipGroups = computed(function () {
        function countBy(fn) {
          var m = {};
          DEALS.forEach(function (d) {
            var keys = fn(d);
            (Array.isArray(keys) ? keys : [keys]).forEach(function (k) {
              if (k == null || k === "") return;
              m[k] = (m[k] || 0) + 1;
            });
          });
          return m;
        }
        var out = [];
        var sel = { status: st.statuses, source: st.sources, type: st.types, amount: st.amounts };
        var stC = countBy(function (d) { return d.status; });
        var stRow = ["active", "expired", "unknown"].map(function (s) {
          return { g: "status", k: s, label: STATUS_NAMES[s], count: stC[s] || 0, on: !!st.statuses[s] };
        });
        var srcC = countBy(function (d) { return d.source; });
        var srcRow = Object.keys(srcC).sort(function (a, b) { return srcC[b] - srcC[a]; })
          .map(function (s) { return { g: "source", k: s, label: SRC_NAMES[s] || s, count: srcC[s], on: !!st.sources[s] }; });
        out.push({ label: "状态", chips: stRow.concat([{ g: "label", k: "src", label: "来源", count: 0, on: false }], srcRow) });
        var vC = countBy(function (d) { return d.vertical; });
        var vRow = Object.keys(vC).sort(function (a, b) { return vC[b] - vC[a]; })
          .map(function (v) { return { g: "vertical", k: v, label: VERTICAL_CN[v] || v, count: vC[v], on: !!st.verticals[v] }; });
        out.push({ label: "领域", chips: vRow });
        var regC = countBy(function (d) {
          return (d.regions && d.regions.length) ? d.regions : ["GLOBAL"];
        });
        var regRow = [
          { g: "region", k: "CN", label: "国内", count: regC["CN"] || 0, on: !!st.regions["CN"] },
          { g: "region", k: "GLOBAL", label: "海外 / 全球", count: regC["GLOBAL"] || 0, on: !!st.regions["GLOBAL"] },
        ];
        out.push({ label: "地区", chips: regRow });
        var typeC = countBy(categoryOf);
        var typeRow = Object.keys(typeC).sort(function (a, b) { return typeC[b] - typeC[a]; })
          .map(function (t) { return { g: "type", k: t, label: t, count: typeC[t], on: !!st.types[t] }; });
        var amtC = countBy(amountBucket);
        var amtRow = AMOUNT_BUCKETS.map(function (b) {
          return { g: "amount", k: b, label: b, count: amtC[b] || 0, on: !!st.amounts[b] }; });
        out.push({ label: "类型", chips: typeRow.concat([{ g: "label", k: "amt", label: "金额", count: 0, on: false }], amtRow) });
        return out;
      });
      var anyFilter = computed(function () {
        return Object.keys(st.sources).length || Object.keys(st.types).length
          || Object.keys(st.amounts).length || Object.keys(st.statuses).length
          || Object.keys(st.verticals).length || Object.keys(st.regions).length
          || st.useCase !== "all" || !!st.qd;
      });
      var emptyHint = computed(function () {
        if (filteredDeals.value.length) return "";
        var sel = Object.keys(st.sources);
        if (sel.length === 1 && Object.keys(st.types).length === 0
            && Object.keys(st.amounts).length === 0 && Object.keys(st.statuses).length === 0 && !st.qd) {
          var id = sel[0];
          var oc = originCounts.value;
          if (id === "linuxdo") return "Linux.do 对服务器/数据中心 IP 全部风控（本地与 Actions 均 403），恢复后国内活动会出现在这里。";
          if (id === "litellm") return "价格库是发现雷达：" + ((DATA.catalog_stats || {}).litellm || 0).toLocaleString("en-US") + " 个模型价格基线已建立，出现新免费模型或大幅降价时这里才会出现条目。";
          return "该来源是发现型数据源：登记行业现状、只在出现新变化时产生条目，其覆盖的厂商见「厂商」页。";
        }
        return "没有符合条件的活动";
      });

// ---------- 厂商页（统一：AI + 云） ----------
      var vendorVerticals = computed(function () {
        var m = {};
        VENDORS.forEach(function (v) { m[v.vertical] = (m[v.vertical] || 0) + 1; });
        return Object.keys(m).sort(function (a, b) { return m[b] - m[a]; })
          .map(function (k) { return { id: k, label: VERTICAL_CN[k] || k, count: m[k] }; });
      });
      var filteredVendors = computed(function () {
        return VENDORS.filter(function (v) {
          if (st.monFilter === "monitored" && !v.monitored) return false;
          if (st.monFilter === "catalog" && v.monitored) return false;
          if (st.monV !== "all" && v.vertical !== st.monV) return false;
          if (st.monQd) {
            var hay = (v.name + " " + (v.categories || []).join(" ")).toLowerCase();
            if (hay.indexOf(st.monQd) < 0) return false;
          }
          return true;
        });
      });
      var vendorPages = computed(function () {
        return Math.max(1, Math.ceil(filteredVendors.value.length / st.monPageSize));
      });
      var pagedVendors = computed(function () {
        var p = Math.min(st.monPage, vendorPages.value);
        return filteredVendors.value.slice((p - 1) * st.monPageSize, p * st.monPageSize);
      });

      // ---------- 侧栏数据源（点击筛选其活动；厂商数跳厂商页） ----------
      var originCounts = computed(function () {
        var m = {};
        MONITORS.forEach(function (x) { m[x.origin] = (m[x.origin] || 0) + 1; });
        return m;
      });
      var sourceCards = computed(function () {
        var runBy = {};
        (DATA.source_runs || []).forEach(function (r) { runBy[r.source] = r; });
        var counts = {};
        DEALS.forEach(function (d) { counts[d.source] = (counts[d.source] || 0) + 1; });
        var cs = DATA.catalog_stats || {};
        var sizes = DATA.registry_sizes || {};
        return SRC_ORDER.map(function (id) {
          var meta = SRC_TYPE[id];
          var run = runBy[id];
          var catalogText = "—";
          if (id === "aicredits") catalogText = (counts["aicredits"] || 0) + " 条目录";
          else if (id === "watchlist") catalogText = MONITORS.length + " 个页面";
          else if (id === "openrouter") catalogText = (cs.openrouter || 0) + " 家有 :free 模型";
          else if (id === "modelsdev") catalogText = (cs.modelsdev || 0) + " 家供应商";
          else if (id === "mnfst") catalogText = (cs.mnfst || 0) + " 家";
          else if (id === "freetoken") catalogText = (cs.freetoken || 0) + " 条";
          else if (id === "litellm") catalogText = (cs.litellm || 0) + " 个模型价格";
          else if (id === "aa_providers") catalogText = (cs.aa || 0) + " 家实验室";
          return {
            id: id, name: SRC_NAMES[id], type: meta.type, blurb: meta.blurb,
            ok: run ? run.status === "ok" : null,
            error: run ? (run.error || "") : "",
            dealsCount: counts[id] || 0,
            vendorCount: sizes[id] || 0,
            catalogText: catalogText,
          };
        });
      });
      var srcSummary = computed(function () {
        var okN = sourceCards.value.filter(function (x) { return x.ok !== false; }).length;
        return sourceCards.value.length + " 个源 · 活动 " + DEALS.length + " 条 · 监控厂商 "
          + MONITORS.length + " 家 · 上次运行 " + okN + "/" + sourceCards.value.length + " 正常";
      });
      var srcRows = computed(function () {
        var runBy = {};
        (DATA.last_run && DATA.last_run.sources || []).forEach(function (s) { runBy[s.source] = s; });
        var counts = {};
        DEALS.forEach(function (d) { counts[d.source] = (counts[d.source] || 0) + 1; });
        var sizes = DATA.registry_sizes || {};
        return SRC_ORDER.map(function (id) {
          var run = runBy[id];
          return {
            id: id, name: SRC_NAMES[id],
            count: counts[id] || 0,
            vendorCount: sizes[id] || 0,
            ok: run ? run.status === "ok" : null,
            title: (run ? (run.status === "ok" ? "正常" : "失败: " + run.error) : "尚未运行")
              + " · 活动条目 " + (counts[id] || 0)
              + " · 覆盖厂商 " + (sizes[id] || 0),
          };
        });
      });
      function goMonitors(sourceId) {
        st.coverSource = sourceId || "全部";
        st.monPage = 1; st.page = "monitors";
        location.hash = "#/monitors";
      }

      // ---------- 总览 ----------
      var DIGEST = DATA.digest || {};
      var todayNew = computed(function () {
        var today = DIGEST.today || "";
        return DEALS.filter(function (d) { return (d.first_seen_at || "").slice(0, 10) === today; })
          .sort(function (a, b) { return (b.first_seen_at || "").localeCompare(a.first_seen_at || ""); })
          .slice(0, 6);
      });
      var recentTop = computed(function () {
        var today = DIGEST.today || "";
        return DEALS.filter(function (d) {
          if (["new", "active"].indexOf(d.status) < 0) return false;
          return (d.first_seen_at || "").slice(0, 10) !== today;
        }).sort(function (a, b) { return (b.score || 0) - (a.score || 0); }).slice(0, 5);
      });
      var recentDeals = computed(function () {
        return DEALS.slice().sort(function (a, b) { return a.first_seen_at < b.first_seen_at ? 1 : -1; }).slice(0, 8);
      });
      var activeMonitorsTop = computed(function () {
        return MONITORS.filter(function (m) { return !!m.promo_keywords; })
          .slice(0, 10);
      });
      var timelineDays = computed(function () {
        var byDay = {};
        sortedDeals.value.forEach(function (d) {
          var day = (d.first_seen_at || "").slice(0, 10) || "未知";
          (byDay[day] = byDay[day] || []).push(d);
        });
        return Object.keys(byDay).sort().reverse().map(function (day) {
          return { day: day, rows: byDay[day] };
        });
      });

      // ---------- 动作 ----------
      function toggle(group, key) {
        var bucket = group === "amount" ? st.amounts : group === "type" ? st.types
          : group === "status" ? st.statuses
          : group === "vertical" ? st.verticals
          : group === "region" ? st.regions : st.sources;
        if (bucket[key]) delete bucket[key]; else bucket[key] = true;
        st.pageNum = 1;
      }
      function clearFilters() {
        st.sources = {}; st.types = {}; st.amounts = {}; st.statuses = {}; st.verticals = {}; st.regions = {}; st.useCase = "all";
        st.q = ""; st.qd = ""; st.pageNum = 1;
      }
      function goSource(id) {
        st.sources = {}; st.sources[id] = true;
        st.pageNum = 1; st.page = "deals";
        location.hash = "#/deals";
      }
      function goTo(page) {
        st.page = page;
        location.hash = "#/" + page;
        st.pageNum = 1; st.monPage = 1;
      }
      function dealPageGo(p) {
        st.pageNum = Math.min(Math.max(1, p), dealPages.value);
      }
      function toggleVendors(id) {
        st.expandedVendors = st.expandedVendors === id ? null : id;
      }
      function toggleTheme() {
        var root = document.documentElement;
        var cur = root.getAttribute("data-theme")
          || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
        var next = cur === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try { localStorage.setItem("radar-theme", next); } catch (e) {}
      }

      // ---------- 手动刷新（serve 模式） ----------
      function startRefresh() {
        var sel = Object.keys(st.refreshSel).filter(function (k) { return st.refreshSel[k]; });
        st.refreshing = true;
        st.refreshMsg = "刷新中…（1~5 分钟，取决于所选源）";
        fetch("/api/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(sel.length ? { sources: sel } : {}),
        }).then(function (r) { return r.json(); }).then(function () {
          var timer = setInterval(function () {
            fetch("/api/status").then(function (r) { return r.json(); }).then(function (s) {
              if (!s.running) {
                clearInterval(timer);
                st.refreshing = false;
                if (s.error) { st.refreshMsg = "刷新失败：" + s.error; return; }
                st.refreshMsg = "完成，载入新数据…";
                setTimeout(function () { location.reload(); }, 600);
              }
            });
          }, 3000);
        }).catch(function (e) {
          st.refreshing = false;
          st.refreshMsg = "刷新请求失败：" + e;
        });
      }

      // ---------- 代理设置（serve 模式） ----------
      function saveProxy() {
        st.proxySaving = true;
        st.proxyMsg = "保存中…";
        fetch("/api/proxy", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: st.proxyUrl.trim(), auto_detect: true }),
        }).then(function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
            return j;
          });
        }).then(function (j) {
          st.proxyUrl = j.url || "";
          st.proxyMsg = j.message || "已保存";
        }).catch(function (e) {
          st.proxyMsg = "保存失败：" + e.message;
        }).then(function () {
          st.proxySaving = false;
        });
      }

      // ---------- 领取跟踪（localStorage，无后端） ----------
      function claimOf(o) { return st.claims[o.dedup_key] || ""; }
      function claimLabel(o) {
        var v = claimOf(o);
        return v === "claimed" ? "已领取" : v === "skipped" ? "已跳过" : "标记已领";
      }
      function toggleClaim(o) {
        var next = Object.assign({}, st.claims);
        if (next[o.dedup_key] === "claimed") delete next[o.dedup_key];
        else next[o.dedup_key] = "claimed";
        st.claims = next;
        saveClaims(next);
        st.claimMsg = "已保存到本机浏览器";
      }
      function exportClaims() {
        var blob = new Blob([JSON.stringify(st.claims, null, 2)], { type: "application/json" });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "radar-claims.json";
        a.click();
        URL.revokeObjectURL(a.href);
      }
      function importClaims(ev) {
        var file = ev.target.files && ev.target.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function () {
          try {
            var parsed = JSON.parse(String(reader.result || "{}"));
            if (parsed && typeof parsed === "object") {
              st.claims = parsed;
              saveClaims(parsed);
              st.claimMsg = "已导入 " + Object.keys(parsed).length + " 条记录";
            }
          } catch (e) { st.claimMsg = "导入失败：不是有效 JSON"; }
        };
        reader.readAsText(file);
      }
      function verticalName(id) { return VERTICAL_CN[id] || id; }

      // ---------- 反馈（serve 模式） ----------
      function voteOf(d) { return st.votes[d.dedup_key] || d.vote || ""; }
      function sendFeedback(d, vote) {
        if (!st.serveMode) {
          st.feedbackMsg = "反馈仅在 radar serve 模式下可用（双击 file:// 或 Pages 为静态托管，无后端写入）";
          return;
        }
        var next = voteOf(d) === vote ? "" : vote; // 再点一次同 vote = 清除
        fetch("/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: d.dedup_key, vote: next }),
        }).then(function (r) { return r.json(); }).then(function () {
          st.votes[d.dedup_key] = next;
        }).catch(function (e) { st.feedbackMsg = "反馈失败：" + e; });
      }

      function sendVerify(d) {
        if (!st.serveMode) {
          st.feedbackMsg = "核实仅在 radar serve 模式下可用；静态页面只显示核实状态";
          return;
        }
        fetch("/api/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: d.dedup_key }),
        }).then(function (r) { return r.ok ? r.json() : null; }).then(function (res) {
          if (res && res.ok) {
            d.verified_at = new Date().toISOString();
            d.verified_by = "user";
          }
        }).catch(function (e) { st.feedbackMsg = "核实失败：" + e; });
      }

      // 防抖搜索
      var qt = null, mqt = null, cqt = null;
      watch(function () { return st.q; }, function (v) {
        clearTimeout(qt);
        qt = setTimeout(function () { st.qd = v.trim().toLowerCase(); st.pageNum = 1; }, 200);
      });
      watch(function () { return st.monQ; }, function (v) {
        clearTimeout(mqt);
        mqt = setTimeout(function () { st.monQd = v.trim().toLowerCase(); st.monPage = 1; }, 200);
      });
      watch(function () { return st.cloudQ; }, function (v) {
        clearTimeout(cqt);
        cqt = setTimeout(function () { st.cloudQd = v.trim().toLowerCase(); st.cloudPage = 1; }, 200);
      });
      ["monV", "monFilter"].forEach(function (k) {
        watch(function () { return st[k]; }, function () { st.monPage = 1; });
      });
      ["cloudV", "cloudType", "cloudNoCard", "cloudAlways"].forEach(function (k) {
        watch(function () { return st[k]; }, function () { st.cloudPage = 1; });
      });
      watch(function () { return st.cloudPageSize; }, function () { st.cloudPage = 1; });
      ["sources", "types", "amounts", "statuses"].forEach(function (k) {
        watch(function () { return st[k]; }, function () { st.pageNum = 1; });
      });
      watch(function () { return st.pageSize; }, function () { st.pageNum = 1; });
      watch(function () { return st.monPageSize; }, function () { st.monPage = 1; });

      onMounted(function () {
        function route() {
          var p = (location.hash || "").replace("#/", "") || "overview";
          st.page = ["overview", "deals", "monitors", "archive", "sources"].indexOf(p) >= 0 ? p : "overview";
        }
        window.addEventListener("hashchange", route);
        route();
        try {
          var t = localStorage.getItem("radar-theme");
          if (t) document.documentElement.setAttribute("data-theme", t);
        } catch (e) {}
        // serve 模式探测：有后端才显示手动刷新
        fetch("/api/status").then(function (r) { return r.ok ? r.json() : null; }).then(function (s) {
          if (s) {
            st.serveMode = true;
            if (s.running) { st.refreshing = true; }
            fetch("/api/proxy").then(function (r) { return r.ok ? r.json() : null; }).then(function (p) {
              if (!p) return;
              st.proxyUrl = p.url || "";
              if (p.url && !p.available) st.proxyMsg = "当前代理端口不可达，运行时会自动直连";
            }).catch(function () {});
          }
        }).catch(function () {});
      });

      return {
        st: st, SRC_NAMES: SRC_NAMES, STATUS_NAMES: STATUS_NAMES,
        kpis: DATA.kpis || {}, signal_pages: DATA.kpis ? DATA.kpis.signal_pages : 0,
        generated_at: DATA.generated_at || "",
        firstAmount: firstAmount, srcName: function (s) { return SRC_NAMES[s] || s; },
        deals: DEALS, monitors: MONITORS, useCases: USE_CASES,
        offers: OFFERS, verticals: DATA.verticals || [],
        vendors: VENDORS, filteredVendors: filteredVendors, pagedVendors: pagedVendors,
        vendorPages: vendorPages, vendorVerticals: vendorVerticals,
        claimLabel: claimLabel, toggleClaim: toggleClaim, exportClaims: exportClaims,
        importClaims: importClaims, verticalName: verticalName,
        sortedDeals: sortedDeals, pagedDeals: pagedDeals, dealPages: dealPages, pageList: pageList,
        filteredDeals: filteredDeals, chipGroups: chipGroups, anyFilter: anyFilter,
        timelineDays: timelineDays,
        srcRows: srcRows, recentDeals: recentDeals, activeMonitorsTop: activeMonitorsTop,
        expiredDeals: DEALS.filter(function (d) { return d.status === "expired"; }),
        categoryOf: categoryOf, amountBucket: amountBucket,
        toggle: toggle, clearFilters: clearFilters, goSource: goSource, goTo: goTo,
        dealPageGo: dealPageGo, toggleTheme: toggleTheme,
        goMonitors: goMonitors, emptyHint: emptyHint,
        sourceCards: sourceCards, srcSummary: srcSummary,
        startRefresh: startRefresh, saveProxy: saveProxy,
        sendFeedback: sendFeedback, voteOf: voteOf, sendVerify: sendVerify,
        feedbackStats: DATA.feedback_stats || { total: 0, up: 0, down: 0, snooze: 0 },
        digest: DIGEST,
        todayNew: todayNew, recentTop: recentTop,
        providerCategories: DATA.provider_categories || [],
        toggleVendors: toggleVendors, sourceVendors: DATA.source_vendors || {},
        pendingEnroll: DATA.pending_enroll || [],
      };
    },
    template: "#tpl-app",
  }).mount("#app");
})();