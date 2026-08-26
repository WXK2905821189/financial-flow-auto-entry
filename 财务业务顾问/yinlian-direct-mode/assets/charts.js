(function () {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var m1 = style.getPropertyValue('--m1').trim();
  var m2 = style.getPropertyValue('--m2').trim();
  var m3 = style.getPropertyValue('--m3').trim();

  var baseFont = "'WorkSans','PingFang SC','Microsoft YaHei',sans-serif";
  var monoFont = "'JetBrainsMono',monospace";
  var axis = {
    axisLine: { lineStyle: { color: rule } },
    axisLabel: { color: muted, fontFamily: baseFont, fontSize: 12 },
    splitLine: { lineStyle: { color: rule } }
  };

  // --- Chart: 单家初始投入成本（对数刻度） ---
  var costDom = document.getElementById('chart-cost');
  if (costDom) {
    var c1 = echarts.init(costDom, null, { renderer: 'svg' });
    c1.setOption({
      animation: false,
      tooltip: { trigger: 'axis', appendToBody: true, axisPointer: { type: 'shadow' } },
      legend: { data: ['初始投入（万元，对数）', '部署周期（周）'], top: 0, textStyle: { color: ink, fontFamily: baseFont, fontSize: 12 } },
      grid: { left: 50, right: 50, top: 46, bottom: 40 },
      xAxis: {
        type: 'category', data: ['模式一\n专线前置机', '模式二\n银行API直连', '模式三\n统一API聚合'],
        axisLabel: { color: ink, fontFamily: baseFont, fontSize: 12.5, lineHeight: 16 },
        axisLine: { lineStyle: { color: rule } }
      },
      yAxis: [
        { type: 'log', name: '万元 / 对数', nameTextStyle: { color: muted, fontFamily: baseFont, fontSize: 11 }, axisLabel: { color: muted, fontFamily: monoFont, fontSize: 11 }, splitLine: { lineStyle: { color: rule } }, axisLine: { lineStyle: { color: rule } } }
      ],
      series: [{
        name: '初始投入（万元，对数）',
        type: 'bar',
        barWidth: 44,
        data: [
          { value: 35, itemStyle: { color: m1 }, label: { show: true, position: 'top', formatter: '20–50万', color: ink, fontFamily: baseFont, fontSize: 12, fontWeight: 600 } },
          { value: 3.5, itemStyle: { color: m2 }, label: { show: true, position: 'top', formatter: '2–5万', color: ink, fontFamily: baseFont, fontSize: 12, fontWeight: 600 } },
          { value: 0.0002, itemStyle: { color: m3 }, label: { show: true, position: 'top', formatter: '0.02万(年/户)', color: ink, fontFamily: baseFont, fontSize: 11, fontWeight: 600 } }
        ]
      }]
    });
    window.addEventListener('resize', function () { c1.resize(); });
  }

  // --- Chart: 累计成本随银行数量增长 ---
  var growDom = document.getElementById('chart-growth');
  if (growDom) {
    var banks = [1, 2, 3, 5, 10, 20];
    var mode1 = banks.map(function (n) { return +(35 * n).toFixed(1); });
    var mode2 = banks.map(function (n) { return +(3.5 * n).toFixed(1); });
    var mode3 = banks.map(function (n) { return +Math.min(n * 0.02, 0.02 + (n > 1 ? 0.5 : 0)).toFixed(2); });

    var c2 = echarts.init(growDom, null, { renderer: 'svg' });
    c2.setOption({
      animation: false,
      tooltip: { trigger: 'axis', appendToBody: true },
      legend: {
        top: 0,
        data: ['模式一 · 专线前置机（万元）', '模式二 · 银行API直连（万元）', '模式三 · 统一API聚合（万元）'],
        textStyle: { color: ink, fontFamily: baseFont, fontSize: 12 }
      },
      grid: { left: 52, right: 60, top: 44, bottom: 44 },
      xAxis: { type: 'category', data: banks.map(function (n) { return n + '家'; }), axisLabel: { color: ink, fontFamily: baseFont, fontSize: 12 }, axisLine: { lineStyle: { color: rule } } },
      yAxis: {
        type: 'value', name: '累计成本', nameTextStyle: { color: muted, fontFamily: baseFont, fontSize: 11 },
        axisLabel: { color: muted, fontFamily: monoFont, fontSize: 11 }, splitLine: { lineStyle: { color: rule } }, axisLine: { lineStyle: { color: rule } }
      },
      series: [
        { name: '模式一 · 专线前置机（万元）', type: 'line', smooth: true, data: mode1, symbolSize: 7, lineStyle: { width: 3, color: m1 }, itemStyle: { color: m1 }, areaStyle: { color: m1 + '22' } },
        { name: '模式二 · 银行API直连（万元）', type: 'line', smooth: true, data: mode2, symbolSize: 7, lineStyle: { width: 3, color: m2 }, itemStyle: { color: m2 } },
        { name: '模式三 · 统一API聚合（万元）', type: 'line', smooth: true, data: mode3, symbolSize: 7, lineStyle: { width: 3, color: m3 }, itemStyle: { color: m3 } }
      ]
    });
    window.addEventListener('resize', function () { c2.resize(); });
  }
})();