/* Lightweight, dependency-free chart renderer for the GUIMPOWERCORE prototype. */
(function () {
  'use strict';

  const toRadians = degrees => (degrees * Math.PI) / 180;
  const isTransparent = color => !color || color === 'transparent';
  // Axis text, grid lines and point rings follow the light/dark theme (see --chart-* in style.css).
  const themeColor = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

  class ChartLite {
    constructor(canvas, config) {
      this.canvas = canvas;
      this.config = config || {};
      this.context = canvas.getContext('2d');
      this.chartBox = canvas.closest('.chart-box');
      this.displayWidth = Number(canvas.getAttribute('width')) || 300;
      this.displayHeight = Number(canvas.getAttribute('height')) || 150;
      if (this.chartBox) {
        canvas.style.width = '100%';
        canvas.style.height = '100%';
      } else {
        canvas.style.width = `${this.displayWidth}px`;
        canvas.style.height = `${this.displayHeight}px`;
      }
      this.draw = this.draw.bind(this);
      this.resizeObserver = window.ResizeObserver
        ? new ResizeObserver(this.draw)
        : null;
      if (this.resizeObserver) this.resizeObserver.observe(canvas.parentElement || canvas);
      window.addEventListener('resize', this.draw, { passive: true });
      window.addEventListener('electro:themechange', this.draw);
      if (typeof this.config.tooltip === 'function' && this.chartBox) this.initTooltip();
      requestAnimationFrame(this.draw);
    }

    // Optional config.tooltip(index) -> HTML string (or null): shown beside the nearest point on hover or tap.
    initTooltip() {
      this.hoverIndex = null;
      this.tip = document.createElement('div');
      this.tip.className = 'chart-tip';
      this.tip.hidden = true;
      this.tip.setAttribute('role', 'status');
      this.chartBox.appendChild(this.tip);
      const move = event => {
        if (!this.linePlot) return;
        const { plot, count } = this.linePlot;
        const x = event.clientX - this.canvas.getBoundingClientRect().left;
        const step = (plot.right - plot.left) / Math.max(count - 1, 1);
        const index = Math.max(0, Math.min(count - 1, Math.round((x - plot.left) / step)));
        if (index !== this.hoverIndex) this.showTip(index);
      };
      this.canvas.addEventListener('pointermove', move);
      this.canvas.addEventListener('pointerdown', move);
      this.canvas.addEventListener('pointerleave', () => this.showTip(null));
    }

    showTip(index) {
      const html = index == null ? null : this.config.tooltip(index);
      this.hoverIndex = html ? index : null;
      this.draw();
      if (!html) {
        this.tip.hidden = true;
        return;
      }
      this.tip.innerHTML = html;
      this.tip.hidden = false;
      const { plot, count } = this.linePlot;
      const x = plot.x(index, count);
      const box = this.chartBox.clientWidth;
      const width = this.tip.offsetWidth;
      // Keep the card beside the guide line and inside the chart.
      const left = x + 12 + width > box ? Math.max(0, x - 12 - width) : x + 12;
      this.tip.style.left = `${left}px`;
    }

    size() {
      const rect = this.chartBox?.getBoundingClientRect();
      const width = this.chartBox
        ? Math.max(220, Math.round(rect.width || 600))
        : this.displayWidth;
      const height = this.chartBox
        ? Math.max(120, Math.round(rect.height || 260))
        : this.displayHeight;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      if (this.canvas.width !== width * ratio || this.canvas.height !== height * ratio) {
        this.canvas.width = width * ratio;
        this.canvas.height = height * ratio;
      }
      this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
      return { width, height };
    }

    draw() {
      const { width, height } = this.size();
      this.context.clearRect(0, 0, width, height);
      if (this.config.type === 'doughnut') this.drawDoughnut(width, height);
      else if (this.config.type === 'bar') this.drawBar(width, height);
      else this.drawLine(width, height);
      if (this.hoverIndex != null && this.linePlot) this.drawGuide(this.hoverIndex);
    }

    drawGuide(index) {
      const ctx = this.context;
      const { plot, count } = this.linePlot;
      const x = Math.round(plot.x(index, count)) + 0.5;
      ctx.save();
      ctx.strokeStyle = themeColor('--chart-text', '#648587');
      ctx.globalAlpha = 0.6;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, plot.top);
      ctx.lineTo(x, plot.bottom);
      ctx.stroke();
      ctx.restore();
    }

    font(size = 11, weight = 500) {
      return `${weight} ${size}px Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
    }

    drawAxes(width, height, values, suggestedMax) {
      const ctx = this.context;
      const plot = { left: 44, right: width - 14, top: 14, bottom: height - 31 };
      const cleanValues = values.filter(Number.isFinite);
      const rawMax = suggestedMax || Math.max(...cleanValues, 1);
      const rawMin = Math.min(...cleanValues, 0);
      const span = Math.max(rawMax - rawMin, 1);
      const step = Math.pow(10, Math.floor(Math.log10(span)));
      const niceMax = suggestedMax || Math.ceil(rawMax / step) * step;
      const min = rawMin < 0 ? Math.floor(rawMin / step) * step : 0;
      const max = Math.max(niceMax, 1);

      ctx.font = this.font(10);
      ctx.fillStyle = themeColor('--chart-text', '#648587');
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      for (let i = 0; i <= 4; i += 1) {
        const y = plot.top + ((plot.bottom - plot.top) * i) / 4;
        const value = Math.round(max - ((max - min) * i) / 4);
        ctx.beginPath();
        ctx.strokeStyle = themeColor('--chart-grid', '#E2F3F4');
        ctx.lineWidth = 1;
        ctx.moveTo(plot.left, y);
        ctx.lineTo(plot.right, y);
        ctx.stroke();
        ctx.fillText(String(value), plot.left - 9, y);
      }

      return {
        ...plot,
        x: (index, count) => plot.left + ((plot.right - plot.left) * index) / Math.max(count - 1, 1),
        y: value => plot.bottom - ((value - min) / (max - min)) * (plot.bottom - plot.top)
      };
    }

    drawLabels(labels, plot) {
      const ctx = this.context;
      ctx.font = this.font(10);
      ctx.fillStyle = themeColor('--chart-text', '#648587');
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      // Draw left to right and skip any label that would touch the previous one, so narrow charts stay readable.
      const gap = 8;
      let lastRight = -Infinity;
      labels.forEach((label, index) => {
        const text = String(label ?? '');
        if (!text) return;
        const align = index === 0 ? 'left' : index === labels.length - 1 ? 'right' : 'center';
        const x = plot.x(index, labels.length);
        const width = ctx.measureText(text).width;
        const left = align === 'left' ? x : align === 'right' ? x - width : x - width / 2;
        if (left < lastRight + gap) return;
        ctx.textAlign = align;
        ctx.fillText(text, x, plot.bottom + 11);
        lastRight = left + width;
      });
    }

    drawLine(width, height) {
      const ctx = this.context;
      const labels = this.config.data?.labels || [];
      const datasets = this.config.data?.datasets || [];
      const values = datasets.flatMap(dataset => dataset.data || []);
      const plot = this.drawAxes(width, height, values);
      this.linePlot = { plot, count: labels.length };
      this.drawLabels(labels, plot);

      const fillPair = datasets.findIndex(dataset => typeof dataset.fill === 'string');
      if (fillPair >= 0 && datasets[fillPair + 1]) {
        const upper = datasets[fillPair];
        const lower = datasets[fillPair + 1];
        ctx.beginPath();
        upper.data.forEach((value, index) => {
          if (!Number.isFinite(value)) return;
          const x = plot.x(index, labels.length);
          const y = plot.y(value);
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        for (let index = lower.data.length - 1; index >= 0; index -= 1) {
          const value = lower.data[index];
          if (Number.isFinite(value)) ctx.lineTo(plot.x(index, labels.length), plot.y(value));
        }
        ctx.closePath();
        ctx.fillStyle = upper.backgroundColor || 'rgba(192,217,218,.3)';
        ctx.fill();
      }

      datasets.forEach((dataset, datasetIndex) => {
        if (!dataset.data) return;
        ctx.beginPath();
        let drawing = false;
        dataset.data.forEach((value, index) => {
          if (!Number.isFinite(value)) {
            drawing = false;
            return;
          }
          const x = plot.x(index, labels.length);
          const y = plot.y(value);
          if (!drawing) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
          drawing = true;
        });

        if (dataset.fill === true) {
          const finite = dataset.data.map((value, index) => ({ value, index })).filter(item => Number.isFinite(item.value));
          if (finite.length) {
            const last = finite[finite.length - 1];
            const first = finite[0];
            ctx.lineTo(plot.x(last.index, labels.length), plot.bottom);
            ctx.lineTo(plot.x(first.index, labels.length), plot.bottom);
            ctx.closePath();
            ctx.fillStyle = dataset.backgroundColor || 'rgba(0,144,153,.08)';
            ctx.fill();
            ctx.beginPath();
            finite.forEach((item, index) => {
              const x = plot.x(item.index, labels.length);
              const y = plot.y(item.value);
              if (index === 0) ctx.moveTo(x, y);
              else ctx.lineTo(x, y);
            });
          }
        }

        ctx.strokeStyle = dataset.borderColor || ['#009099', '#16A34A', '#C0D9DA'][datasetIndex % 3];
        ctx.lineWidth = datasetIndex < 2 ? 2.25 : 1.25;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.setLineDash(dataset.borderDash || []);
        ctx.stroke();
        ctx.setLineDash([]);

        if ((dataset.pointRadius || 0) > 0) {
          dataset.data.forEach((value, index) => {
            if (!Number.isFinite(value)) return;
            ctx.beginPath();
            ctx.arc(plot.x(index, labels.length), plot.y(value), dataset.pointRadius, 0, Math.PI * 2);
            ctx.fillStyle = dataset.borderColor || '#009099';
            ctx.fill();
            ctx.strokeStyle = themeColor('--chart-ring', '#fff');
            ctx.lineWidth = 1.5;
            ctx.stroke();
          });
        }
      });
    }

    drawBar(width, height) {
      const labels = this.config.data?.labels || [];
      const dataset = this.config.data?.datasets?.[0] || { data: [] };
      const suggestedMax = this.config.options?.scales?.y?.suggestedMax;
      const plot = this.drawAxes(width, height, dataset.data, suggestedMax);
      this.drawLabels(labels, plot);
      const slot = (plot.right - plot.left) / Math.max(labels.length, 1);
      const barWidth = Math.min(dataset.maxBarThickness || 34, slot * 0.58);
      const colors = Array.isArray(dataset.backgroundColor)
        ? dataset.backgroundColor
        : dataset.data.map(() => dataset.backgroundColor || '#009099');

      dataset.data.forEach((value, index) => {
        const x = plot.left + slot * index + (slot - barWidth) / 2;
        const y = plot.y(value);
        const h = plot.bottom - y;
        const radius = Math.min(dataset.borderRadius || 0, barWidth / 2, h / 2);
        ctxRoundRect(this.context, x, y, barWidth, h, radius);
        this.context.fillStyle = colors[index];
        this.context.fill();
      });
    }

    drawDoughnut(width, height) {
      const dataset = this.config.data?.datasets?.[0] || { data: [] };
      const values = dataset.data || [];
      const colors = dataset.backgroundColor || [];
      const hasTransparentSegment = colors.some(isTransparent);
      const total = values.reduce((sum, value, index) => {
        return sum + (hasTransparentSegment && isTransparent(colors[index]) ? 0 : Math.max(value, 0));
      }, 0) || 1;
      const circumference = toRadians(dataset.circumference || this.config.options?.circumference || 360);
      const rotation = hasTransparentSegment && circumference <= Math.PI
        ? Math.PI
        : toRadians(dataset.rotation || this.config.options?.rotation || 0);
      const cutoutText = this.config.options?.cutout || '68%';
      const cutout = parseFloat(cutoutText) / 100;
      const radius = Math.min(width, height) * (circumference <= Math.PI ? 0.78 : 0.43);
      const cx = width / 2;
      const cy = circumference <= Math.PI ? height * 0.82 : height / 2;
      let angle = rotation;

      values.forEach((value, index) => {
        if (hasTransparentSegment && isTransparent(colors[index])) return;
        const next = angle + (Math.max(value, 0) / total) * circumference;
        if (!isTransparent(colors[index])) {
          this.context.beginPath();
          this.context.arc(cx, cy, radius, angle, next);
          this.context.arc(cx, cy, radius * cutout, next, angle, true);
          this.context.closePath();
          this.context.fillStyle = colors[index] || '#009099';
          this.context.fill();
        }
        angle = next;
      });
    }
  }

  function ctxRoundRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height);
    ctx.lineTo(x, y + height);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }

  window.Chart = ChartLite;
})();
