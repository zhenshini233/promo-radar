/* promo-radar dashboard — Vue 3（本地 vendor，无构建）。
 * 数据来自内联 JSON（file:// 可用）；serve 模式提供手动/细分刷新。
 * 筛选、分页全部走 computed，Vue 负责 diff 渲染，避免全量 innerHTML 卡顿。
 */
(function () {
  "use strict";

  var dataEl = document.getElementById("radar-data");
  if (!dataEl || !window.Vue) return; // Vue 缺失时保留 SSR 内容
  var DATA = JSON.parse(dataEl.textContent);
  var DEALS = DATA.deals || [];
  var MONITORS = DATA.monitors || [];

  var STATUS_NAMES = { "new": "新增", "updated": "有更新", "expired": "已过期" };
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
        sources: {}, types: {}, amounts: {}, statuses: {},
        sort: "recent", pageNum: 1, pageSize: 24,
        monFilter: "all", coverSource: "全部",
        monQ: "", monQd: "", monPage: 1, monPageSize: 30,
        serveMode: false, refreshing: false, refreshMsg: "",
        refreshSel: {}, expandedVendors: null,
      });

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
        var hasSt = Object.keys(st.statuses).length > 0;
        var hasAmt = Object.keys(st.amounts).length > 0;
        var hasType = Object.keys(st.types).length > 0;
        return DEALS.filter(function (d) {
          if (hasSrc && !st.sources[d.source]) return false;
          if (hasSt && !st.statuses[d.status]) return false;
          if (hasAmt && !st.amounts[amountBucket(d)]) return false;
          if (hasType && st.types[categoryOf(d)] !== true) return false;
          if (st.qd) {
            var hay = (d.title + " " + (d.provider || "") + " " + (d.evidence || "")).toLowerCase();
            if (hay.indexOf(st.qd) < 0) return false;
          }
          return true;
        });
      });
      var sortedDeals = computed(function () {
        var arr = filteredDeals.value.slice();
        if (st.sort === "score") {
          arr.sort(function (a, b) { return b.score - a.score || (a.first_seen_at < b.first_seen_at ? 1 : -1); });
        } else if (st.sort === "amount") {
          arr.sort(function (a, b) { return amountValue(b) - amountValue(a); });
        } else {
          arr.sort(function (a, b) { return a.last_changed_at < b.last_changed_at ? 1 : -1; });
        }
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
        var stRow = ["new", "updated", "expired"].map(function (s) {
          return { g: "status", k: s, label: STATUS_NAMES[s], count: stC[s] || 0, on: !!st.statuses[s] };
        });
        var srcC = countBy(function (d) { return d.source; });
        var srcRow = Object.keys(srcC).sort(function (a, b) { return srcC[b] - srcC[a]; })
          .map(function (s) { return { g: "source", k: s, label: SRC_NAMES[s] || s, count: srcC[s], on: !!st.sources[s] }; });
        out.push({ label: "状态", chips: stRow.concat([{ g: "label", k: "src", label: "来源", count: 0, on: false }], srcRow) });
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
          || Object.keys(st.amounts).length || Object.keys(st.statuses).length || !!st.qd;
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

      // ---------- 厂商页 computed ----------
      var coverChips = computed(function () {
        var chips = [{ id: "全部", label: "全部", count: MONITORS.length }];
        var sizes = DATA.registry_sizes || {};
        Object.keys(SRC_NAMES).forEach(function (sid) {
          if (sizes[sid]) chips.push({ id: sid, label: SRC_NAMES[sid], count: sizes[sid] });
        });
        var uncovered = MONITORS.filter(function (m) { return !(m.covered_by || []).length; }).length;
        chips.push({ id: "未覆盖", label: "未覆盖", count: uncovered });
        return chips;
      });
      var filteredMonitors = computed(function () {
        return MONITORS.filter(function (m) {
          if (st.monFilter === "active" && !m.promo_keywords) return false;
          if (st.monFilter === "new" && (m.checked_days || 0) >= 3) return false;
          if (st.coverSource === "未覆盖" && (m.covered_by || []).length) return false;
          if (st.coverSource !== "全部" && st.coverSource !== "未覆盖"
              && (m.covered_by || []).indexOf(st.coverSource) < 0) return false;
          if (st.monQd && (m.provider + " " + m.label).toLowerCase().indexOf(st.monQd) < 0) return false;
          return true;
        });
      });
      var monPages = computed(function () {
        return Math.max(1, Math.ceil(filteredMonitors.value.length / st.monPageSize));
      });
      var pagedMonitors = computed(function () {
        var p = Math.min(st.monPage, monPages.value);
        return filteredMonitors.value.slice((p - 1) * st.monPageSize, p * st.monPageSize);
      });
      var monPageList = computed(function () {
        var total = monPages.value, p = Math.min(st.monPage, total), nums = [];
        for (var i = 1; i <= total; i++) {
          if (i === 1 || i === total || Math.abs(i - p) <= 2) nums.push(i);
          else if (nums[nums.length - 1] !== "…") nums.push("…");
        }
        return nums;
      });
      var activeMonCount = computed(function () {
        return MONITORS.filter(function (m) { return !!m.promo_keywords; }).length;
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
          : group === "status" ? st.statuses : st.sources;
        if (bucket[key]) delete bucket[key]; else bucket[key] = true;
        st.pageNum = 1;
      }
      function clearFilters() {
        st.sources = {}; st.types = {}; st.amounts = {}; st.statuses = {};
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
      function monPageGo(p) {
        st.monPage = Math.min(Math.max(1, p), monPages.value);
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

      // 防抖搜索
      var qt = null, mqt = null;
      watch(function () { return st.q; }, function (v) {
        clearTimeout(qt);
        qt = setTimeout(function () { st.qd = v.trim().toLowerCase(); st.pageNum = 1; }, 200);
      });
      watch(function () { return st.monQ; }, function (v) {
        clearTimeout(mqt);
        mqt = setTimeout(function () { st.monQd = v.trim().toLowerCase(); st.monPage = 1; }, 200);
      });
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
          if (s) { st.serveMode = true; if (s.running) { st.refreshing = true; } }
        }).catch(function () {});
      });

      return {
        st: st, SRC_NAMES: SRC_NAMES, STATUS_NAMES: STATUS_NAMES,
        kpis: DATA.kpis || {}, signal_pages: DATA.kpis ? DATA.kpis.signal_pages : 0,
        generated_at: DATA.generated_at || "",
        firstAmount: firstAmount, srcName: function (s) { return SRC_NAMES[s] || s; },
        deals: DEALS, monitors: MONITORS,
        sortedDeals: sortedDeals, pagedDeals: pagedDeals, dealPages: dealPages, pageList: pageList,
        filteredDeals: filteredDeals, chipGroups: chipGroups, anyFilter: anyFilter,
        filteredMonitors: filteredMonitors, pagedMonitors: pagedMonitors,
        coverChips: coverChips,
        monPages: monPages, monPageList: monPageList, activeMonCount: activeMonCount,
        timelineDays: timelineDays,
        srcRows: srcRows, recentDeals: recentDeals, activeMonitorsTop: activeMonitorsTop,
        expiredDeals: DEALS.filter(function (d) { return d.status === "expired"; }),
        categoryOf: categoryOf, amountBucket: amountBucket,
        toggle: toggle, clearFilters: clearFilters, goSource: goSource, goTo: goTo,
        dealPageGo: dealPageGo, monPageGo: monPageGo, toggleTheme: toggleTheme,
        goMonitors: goMonitors, emptyHint: emptyHint,
        coverChips: coverChips,
        sourceCards: sourceCards, srcSummary: srcSummary,
        startRefresh: startRefresh,
        toggleVendors: toggleVendors, sourceVendors: DATA.source_vendors || {},
        pendingEnroll: DATA.pending_enroll || [],
      };
    },
    template: "#tpl-app",
  }).mount("#app");
})();
