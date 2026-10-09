/* MetricHub v2 共享框架: 侧栏 + 顶栏(右上角新旧版切换)。
   页面只放 <div id="side"></div><header id="top"></header>, 导航由这里渲染,
   当前页按路径高亮 —— 改导航只动这一个文件。 */
(function () {
  var NAV = [
    { g: '开始' },
    { t: '总览', h: 'index.html' },
    { g: '构建 · 从业务到口径' },
    { t: '业务结构与数据域', h: 'domains.html', n: '01' },
    { t: '语义层构建', h: 'semantic.html', n: '02' },
    { t: '指标目录', h: 'layer.html', sub: 1 },
    { t: '指标体系与北极星', h: 'metrics.html', n: '03' },
    { g: '消费 · 从口径到决策' },
    { t: '数据服务场景', h: 'services.html', n: '04' },
    { t: '流批对账', h: 'realtime.html', sub: 1 },
    { t: '应用层', h: 'apps.html', n: '05' },
    { t: '指标看板', h: 'dashboard.html', sub: 1 },
    { t: 'AI 问答 · Text2SQL · AI 开发', h: 'ai.html', n: '06' },
    { g: '附录' },
    { t: '公开信源', h: 'sources.html' },
    { t: 'dbt 血缘图', h: 'dbt-docs/index.html' }
  ];
  var here = location.pathname.split('/').pop() || 'index.html';

  var side = document.getElementById('side');
  if (side) {
    var html = '<div class="brand"><span class="dot">M</span><span><b>MetricHub</b>' +
      '<small>受 AI 消费的指标语义层</small></span></div>';
    NAV.forEach(function (item) {
      if (item.g) { html += '<div class="grp">' + item.g + '</div>'; return; }
      // 子页(目录/看板/流批)与普通页一样按路径高亮 —— 否则打开子页时侧栏零高亮, 用户失位
      var cls = 'it' + (item.sub ? ' sub' : '') + (here === item.h.split('/').pop() ? ' on' : '');
      html += '<a class="' + cls + '" href="' + item.h + '">' +
        (item.n ? '<span class="no">' + item.n + '</span>' : '') + item.t + '</a>';
    });
    html += '<div class="foot-note">数据为确定性模拟（固定种子 · 锚定可复现），' +
      '业务设定的公开出处见「公开信源」。八道门禁不过不发布。</div>';
    side.innerHTML = html;
  }

  var top = document.getElementById('top');
  if (top) {
    var cur = null;
    NAV.forEach(function (item) { if (item.h && item.h.split('/').pop() === here) cur = item.t; });
    top.innerHTML =
      '<span class="crumb">' + (cur || 'MetricHub') + '</span>' +
      '<span class="ver">v2</span><span class="sp"></span>' +
      '<a class="tlink" href="dbt-docs/index.html">dbt 血缘图</a>' +
      '<a class="tlink" href="https://github.com/dragonxu202610/metrichub" target="_blank" rel="noopener">GitHub</a>' +
      '<a class="switch" href="v1/index.html" title="切换到旧版(纸白编辑风)">← 旧版 v1</a>';
  }
})();
