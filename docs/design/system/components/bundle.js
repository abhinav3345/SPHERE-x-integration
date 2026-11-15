/* @ds-bundle: {"format":4,"namespace":"Comparator","components":[{"name":"Wordmark"},{"name":"TypeProof"},{"name":"Icons"},{"name":"StateGrammar"},{"name":"Button"},{"name":"Segmented"},{"name":"Toggle"},{"name":"Slider"},{"name":"Chip"},{"name":"Notice"},{"name":"Tooltip"},{"name":"ShortcutHint"},{"name":"CopyLink"},{"name":"DataTable"},{"name":"SearchField"},{"name":"BandSelector"},{"name":"ImageFrame"},{"name":"FrameLabel"},{"name":"Timeline"},{"name":"Playback"},{"name":"DisplayControls"},{"name":"Provenance"},{"name":"SpectrumPanel"},{"name":"TargetCard"},{"name":"ImageDisplay"},{"name":"DifferenceScale"},{"name":"EpochComposite"},{"name":"ThreeColour"},{"name":"Markers"},{"name":"CompassScale"},{"name":"SpectrumChart"},{"name":"StateBuilding"},{"name":"StateNoCoverage"},{"name":"StatePartialResult"},{"name":"StateBusy"},{"name":"StateArchiveUnreachable"},{"name":"StateSaturatedStar"},{"name":"StateThinPartial"},{"name":"Proof390"},{"name":"Proof1280"}]} */
/* Blink comparator helpers. Plain script, no dependencies, nothing loaded from outside.
   Everything visual reads its colours from the CSS tokens, so the tokens stay the one source. */
(function () {
  'use strict';

  var doc = document;

  function token(name) {
    return getComputedStyle(doc.documentElement).getPropertyValue('--' + name).trim();
  }
  function px(name, fallback) {
    var v = parseFloat(token(name));
    return isNaN(v) ? fallback : v;
  }
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function each(root, selector, fn) {
    Array.prototype.forEach.call((root || doc).querySelectorAll(selector), fn);
  }

  /* ------------------------------------------------------------ icons: 20px grid, 1.5px stroke, square ends */
  var ICONS = {
    'play': '<path d="M6.5 4.5v11l9-5.5z"/>',
    'pause': '<path d="M6 4.5h2.5v11H6zM11.5 4.5H14v11h-2.5z"/>',
    'previous': '<path d="M5 4.5v11"/><path d="M15 4.5v11L7.5 10z"/>',
    'next': '<path d="M15 4.5v11"/><path d="M5 4.5v11l7.5-5.5z"/>',
    'flip': '<path d="M3.5 7h12"/><path d="M12.5 4l3 3-3 3"/><path d="M16.5 13h-12"/><path d="M7.5 10l-3 3 3 3"/>',
    'side-by-side': '<path d="M3 4.5h6v11H3zM11 4.5h6v11h-6z"/>',
    'difference': '<circle cx="7.5" cy="10" r="5"/><circle cx="12.5" cy="10" r="5"/>',
    'invert': '<path d="M3.5 3.5h13v13h-13z"/><path class="bc-icon__solid" d="M16.5 3.5v13h-13z"/>',
    'contrast': '<circle cx="10" cy="10" r="6.5"/><path class="bc-icon__solid" d="M10 3.5a6.5 6.5 0 0 1 0 13z"/>',
    'zoom': '<circle cx="8.5" cy="8.5" r="5"/><path d="M12.5 12.5l4.5 4.5"/>',
    'recentre': '<circle cx="10" cy="10" r="4.5"/><path d="M10 2v3.5M10 14.5V18M2 10h3.5M14.5 10H18"/><circle class="bc-icon__solid" cx="10" cy="10" r="1"/>',
    'copy-link': '<path d="M8.6 11.4a3 3 0 0 0 4.2 0l2.6-2.6a3 3 0 0 0-4.2-4.2l-1 1"/><path d="M11.4 8.6a3 3 0 0 0-4.2 0l-2.6 2.6a3 3 0 0 0 4.2 4.2l1-1"/>',
    'information': '<circle cx="10" cy="10" r="7"/><path d="M10 9v5"/><circle class="bc-icon__solid" cx="10" cy="6.3" r="0.9"/>',
    'warning': '<path d="M10 3l7.5 13.5h-15z"/><path d="M10 8v4"/><circle class="bc-icon__solid" cx="10" cy="14.2" r="0.9"/>',
    'external-link': '<path d="M8 4.5H4.5v11h11V12"/><path d="M11 3.5h5.5V9"/><path d="M16.5 3.5l-7 7"/>',
    'close': '<path d="M5 5l10 10M15 5L5 15"/>'
  };

  function icon(name, label) {
    var body = ICONS[name];
    if (!body) return '';
    var a11y = label ? 'role="img" aria-label="' + esc(label) + '"' : 'aria-hidden="true"';
    return '<svg class="bc-icon" viewBox="0 0 20 20" focusable="false" ' + a11y + '>' + body + '</svg>';
  }
  function mountIcons(root) {
    each(root, '[data-icon]', function (el) {
      var html = icon(el.getAttribute('data-icon'), el.getAttribute('data-label'));
      if (html) el.outerHTML = html;
    });
  }

  /* ------------------------------------------------------------ image maths */

  /* Whole device pixels per image pixel, so every image pixel is the same size on screen. */
  function displayScale(boxCssPx, imagePx, dpr) {
    dpr = dpr || window.devicePixelRatio || 1;
    var k = Math.max(1, Math.floor(boxCssPx * dpr / imagePx));
    return { devicePx: k, cssPx: k / dpr, sizeCss: imagePx * k / dpr };
  }

  /* 45 degree hatch. Each stripe is a third of one displayed image pixel (never less than one device
     pixel), so every no-data pixel holds both greys. Sky pixels are flat, so the two cannot be confused. */
  function hatchPattern(ctx, devicePxPerImagePx) {
    var stripe = Math.max(1, Math.round((devicePxPerImagePx || 6) / 3));
    var size = stripe * 2;
    var tile = doc.createElement('canvas');
    tile.width = size; tile.height = size;
    var t = tile.getContext('2d');
    t.fillStyle = token('nodata-b');
    t.fillRect(0, 0, size, size);
    t.fillStyle = token('nodata-a');
    for (var y = 0; y < size; y++) {
      for (var x = 0; x < size; x++) {
        if (((x + y) % size) < stripe) t.fillRect(x, y, 1, 1);
      }
    }
    return ctx.createPattern(tile, 'repeat');
  }

  /* frame: { width, height, data: Uint8ClampedArray of greys, or fill: 0-255, mask: Uint8Array (1 = no data) }
     opts:  { box: css px available, invert: bool, dpr } */
  function paintFrame(canvas, frame, opts) {
    opts = opts || {};
    var dpr = opts.dpr || window.devicePixelRatio || 1;
    var box = opts.box || (canvas.parentNode && canvas.parentNode.parentNode ? canvas.parentNode.parentNode.clientWidth : frame.width * 3);
    var s = displayScale(box, frame.width, dpr);
    var k = s.devicePx, W = frame.width * k, H = frame.height * k;
    canvas.width = W; canvas.height = H;
    canvas.style.width = (W / dpr) + 'px';
    canvas.style.height = (H / dpr) + 'px';

    var off = doc.createElement('canvas');
    off.width = frame.width; off.height = frame.height;
    var octx = off.getContext('2d');
    var img = octx.createImageData(frame.width, frame.height);
    var n = frame.width * frame.height;
    for (var i = 0; i < n; i++) {
      var v = frame.data ? frame.data[i] : frame.fill;
      if (opts.invert) v = 255 - v;
      img.data[i * 4] = v; img.data[i * 4 + 1] = v; img.data[i * 4 + 2] = v; img.data[i * 4 + 3] = 255;
    }
    octx.putImageData(img, 0, 0);

    var ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(off, 0, 0, W, H);

    if (frame.mask) {
      ctx.fillStyle = hatchPattern(ctx, k);
      for (var y = 0; y < frame.height; y++) {
        for (var x = 0; x < frame.width; x++) {
          if (frame.mask[y * frame.width + x]) ctx.fillRect(x * k, y * k, k, k);
        }
      }
    }
    return s;
  }

  /* Two-epoch composite. a and b are display values 0-255 for the earlier and later frame.
     Earlier is orange (255,102,0), later is blue (0,153,255); equal values give neutral grey. */
  function compositeAB(a, b) {
    return [a, Math.round(0.4 * a + 0.6 * b), b];
  }

  /* Difference image colour for a value in units of noise (later minus earlier). Clipped at 5 sigma. */
  function hexToRgb(h) {
    h = h.replace('#', '');
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  function diffColor(sigma) {
    var s = Math.max(-5, Math.min(5, sigma));
    var side = s < 0 ? 'earlier' : 'later';
    var m = Math.abs(s), lo = Math.floor(m), hi = Math.min(5, lo + 1), f = m - lo;
    var c0 = hexToRgb(lo === 0 ? token('diff-zero') : token('diff-' + side + '-' + lo));
    var c1 = hexToRgb(hi === 0 ? token('diff-zero') : token('diff-' + side + '-' + hi));
    return [0, 1, 2].map(function (i) { return Math.round(c0[i] + (c1[i] - c0[i]) * f); });
  }

  /* placeholder frames for the reference page: a flat neutral block, never sky */
  function placeholderFrame(size, fill, maskKind) {
    var mask = null, x, y;
    if (maskKind) {
      mask = new Uint8Array(size * size);
      var kinds = maskKind.split(' ');
      kinds.forEach(function (kind) {
        if (kind === 'edge') {            /* off the detector: a slanted strip along one side */
          for (y = 0; y < size; y++) for (x = 0; x < size; x++) if (x > size - 12 - Math.round(y * 0.12)) mask[y * size + x] = 1;
        } else if (kind === 'core') {     /* saturated core: a small round patch in the middle */
          var c = (size - 1) / 2;
          for (y = 0; y < size; y++) for (x = 0; x < size; x++) if ((x - c) * (x - c) + (y - c) * (y - c) <= 12.5) mask[y * size + x] = 1;
        } else if (kind === 'pixels') {   /* a few masked pixels, to show the hatch at single-pixel scale */
          [[20, 30], [21, 30], [64, 18], [90, 77], [91, 77], [91, 78], [35, 96]].forEach(function (p) {
            if (p[0] < size && p[1] < size) mask[p[1] * size + p[0]] = 1;
          });
        }
      });
    }
    return { width: size, height: size, fill: fill, mask: mask };
  }
  function mountFrames(root) {
    each(root, 'canvas[data-frame]', function (canvas) {
      var size = parseInt(canvas.getAttribute('data-frame'), 10) || 119;
      var fill = parseInt(canvas.getAttribute('data-fill') || '60', 10);
      var frame = placeholderFrame(size, fill, canvas.getAttribute('data-mask'));
      var host = canvas.closest('.bc-frame');
      function draw() {
        var box = host ? host.clientWidth : size * 3;
        if (!box) return;
        var s = paintFrame(canvas, frame, { box: box, invert: canvas.getAttribute('data-invert') === 'true' });
        var overlay = canvas.parentNode.querySelector('.bc-frame__overlay');
        if (overlay) {
          overlay.setAttribute('viewBox', '0 0 ' + s.sizeCss + ' ' + s.sizeCss);
          var spec = overlay.getAttribute('data-markers');
          if (spec) overlay.innerHTML = overlayMarkup(JSON.parse(spec), s.sizeCss);
        }
        if (canvas.id) each(doc, '[data-scalebar][data-for="' + canvas.id + '"]', function (el) { scaleBar(el, s.cssPx); });
        canvas.dispatchEvent(new CustomEvent('bc:painted', { bubbles: true, detail: s }));
      }
      draw();
      if (window.ResizeObserver && host) new ResizeObserver(draw).observe(host);
      canvas.bcRedraw = draw;
    });
  }

  /* ------------------------------------------------------------ markers (SVG strings, screen pixels) */
  var MARKER_PATHS = {
    position: function () { return 'M-9 0a9 9 0 1 0 18 0a9 9 0 1 0 -18 0'; },
    gaia: function () { return 'M0 -12V-5M0 5V12M-12 0H-5M5 0H12'; },
    catwise: function () { return 'M0 -9L9 0L0 9L-9 0Z'; },
    was: function () { return 'M-11 -11H11V11H-11Z'; }
  };
  function marker(kind, x, y, label) {
    var d = MARKER_PATHS[kind] ? MARKER_PATHS[kind]() : '';
    var out = '<g class="bc-mk bc-mk--' + kind + '" transform="translate(' + x + ' ' + y + ')">' +
      '<path class="bc-mk__casing" d="' + d + '"/><path class="bc-mk__ink" d="' + d + '"/>';
    if (label) out += '<text class="bc-mk__label" x="16" y="4">' + esc(label) + '</text>';
    return out + '</g>';
  }
  /* predicted track: a hairline through the positions, with a short cross tick at each visit */
  function track(points) {
    if (points.length < 2) return '';
    var d = 'M' + points.map(function (p) { return p[0] + ' ' + p[1]; }).join('L');
    var dx = points[points.length - 1][0] - points[0][0], dy = points[points.length - 1][1] - points[0][1];
    var len = Math.sqrt(dx * dx + dy * dy) || 1, nx = -dy / len * 4, ny = dx / len * 4;
    points.forEach(function (p) {
      d += 'M' + (p[0] - nx) + ' ' + (p[1] - ny) + 'L' + (p[0] + nx) + ' ' + (p[1] + ny);
    });
    return '<g class="bc-mk bc-mk--track"><path class="bc-mk__casing" d="' + d + '"/><path class="bc-mk__ink" d="' + d + '"/></g>';
  }
  function spotlight(w, h, cx, cy, r) {
    var ring = 'M' + (cx - r) + ' ' + cy + 'a' + r + ' ' + r + ' 0 1 0 ' + (2 * r) + ' 0a' + r + ' ' + r + ' 0 1 0 ' + (-2 * r) + ' 0';
    return '<path class="bc-spotlight" fill-rule="evenodd" d="M0 0H' + w + 'V' + h + 'H0Z' + ring + 'Z"/>' +
      '<path class="bc-spotlight__ring bc-spotlight__ring--casing" d="' + ring + '"/><path class="bc-spotlight__ring" d="' + ring + '"/>';
  }

  /* Overlay from a list. Positions are fractions of the image width, sizes are screen pixels.
     ["spotlight", x, y, radiusPx]  ["track", [[x, y], ...]]  [kind, x, y, label] */
  function overlayMarkup(list, size) {
    var under = '', over = '';
    list.forEach(function (item) {
      if (item[0] === 'spotlight') under += spotlight(size, size, item[1] * size, item[2] * size, item[3]);
      else if (item[0] === 'track') over += track(item[1].map(function (p) { return [p[0] * size, p[1] * size]; }));
      else over += marker(item[0], Math.round(item[1] * size * 2) / 2, Math.round(item[2] * size * 2) / 2, item[3]);
    });
    return under + over;
  }
  /* Scale bar: an exact length for a round number of arcseconds, with end ticks. */
  function scaleBar(el, cssPxPerImagePx) {
    var arcsec = parseFloat(el.getAttribute('data-scalebar')) || 60;
    var pixscale = parseFloat(el.getAttribute('data-pixscale')) || 3.075;
    var len = Math.round(arcsec / pixscale * cssPxPerImagePx * 2) / 2;
    el.setAttribute('role', 'img');
    el.setAttribute('aria-label', 'Scale bar: ' + arcsec + ' arcseconds');
    el.innerHTML = '<svg width="' + (len + 1) + '" height="9" viewBox="0 0 ' + (len + 1) + ' 9" aria-hidden="true">' +
      '<path d="M0.5 0V9M0.5 4.5H' + (len + 0.5) + 'M' + (len + 0.5) + ' 0V9"/></svg><span aria-hidden="true">' + arcsec + '″</span>';
  }

  /* Compass for the frame margin: north up, east left. */
  function compass() {
    return '<svg class="bc-compass" viewBox="0 0 44 44" role="img" aria-label="North is up, east is left">' +
      '<path d="M32.5 36V12M29 16l3.5-4 3.5 4M32.5 36H10M14 32.5l-4 3.5 4 3.5"/>' +
      '<text x="32.5" y="9" text-anchor="middle">N</text><text x="4" y="40" text-anchor="middle">E</text></svg>';
  }
  function mountCompasses(root) {
    each(root, '[data-compass]', function (el) { el.outerHTML = compass(); });
  }

  /* ------------------------------------------------------------ the wavelength rule: 102 ticks, no rainbow */
  var BANDS = [
    { id: 'D1', min: 0.74, max: 1.12 }, { id: 'D2', min: 1.10, max: 1.65 }, { id: 'D3', min: 1.64, max: 2.42 },
    { id: 'D4', min: 2.42, max: 3.82 }, { id: 'D5', min: 3.81, max: 4.42 }, { id: 'D6', min: 4.41, max: 5.00 }
  ];
  var SELECTIONS = {
    'all': { min: 0.74, max: 5.00, label: 'All bands, 0.74 to 5.00 micrometres' },
    'cold': { min: 4.0, max: 5.0, label: 'Cold objects, 4.0 to 5.0 micrometres' },
    'rgb': { min: 0.74, max: 5.00, label: 'Three-colour: red 3.8 to 5.0, green 1.6 to 3.8, blue 0.74 to 1.65 micrometres' }
  };
  var RGB = [{ k: 'b', letter: 'B', min: 0.74, max: 1.65 }, { k: 'g', letter: 'G', min: 1.6, max: 3.8 }, { k: 'r', letter: 'R', min: 3.8, max: 5.0 }];

  /* 17 nominal channels per detector, evenly spaced in log wavelength, as the instrument samples them */
  function channels() {
    var out = [];
    BANDS.forEach(function (b) {
      for (var i = 0; i < 17; i++) {
        var lo = b.min * Math.pow(b.max / b.min, i / 17), hi = b.min * Math.pow(b.max / b.min, (i + 1) / 17);
        out.push({ band: b.id, index: i + 1, min: lo, max: hi, centre: Math.sqrt(lo * hi) });
      }
    });
    return out;
  }

  /* The rule is graduated by channel, not by micrometre: each detector gets the same length and its
     17 channels are evenly spaced, at a whole number of pixels, like the ticks of an engraved rule. */
  var EDGES = ['0.74', '1.11', '1.65', '2.42', '3.82', '4.42', '5.00'];
  function ruleFraction(w) {
    for (var i = 0; i < BANDS.length; i++) {
      var b = BANDS[i];
      if (w <= b.max || i === BANDS.length - 1) {
        var f = Math.log(Math.max(w, b.min) / b.min) / Math.log(b.max / b.min);
        return (i + Math.min(1, Math.max(0, f))) / BANDS.length;
      }
    }
    return 1;
  }
  function wavelengthRule(el, selection) {
    selection = selection || 'D6';
    var W = Math.floor(el.clientWidth || 328);
    if (W < 206) return;
    var pitch = Math.max(2, Math.floor((W - 2) / 102));       /* whole pixels between ticks */
    var L = pitch * 102, x0 = Math.floor((W - L) / 2);        /* rule length, left edge */
    var rgb = selection === 'rgb';
    var yBand = 11, yTop = 18, yBase = 36, yNum = 54, H = rgb ? 86 : 58;
    function X(w) { return x0 + ruleFraction(w) * L; }
    var sel = SELECTIONS[selection], band = null;
    BANDS.forEach(function (b) { if (b.id === selection) band = b; });
    var range = band || sel || SELECTIONS.all;
    var s = '<line class="bc-rule__base" x1="' + x0 + '" y1="' + (yBase + 0.5) + '" x2="' + (x0 + L) + '" y2="' + (yBase + 0.5) + '"/>';
    channels().forEach(function (c, n) {
      var lit = band ? c.band === band.id : (c.centre >= range.min && c.centre <= range.max);
      var x = x0 + n * pitch + Math.floor(pitch / 2) + 0.5;
      var top = lit ? yTop : (c.index === 9 ? yBase - 10 : yBase - 7);
      s += '<line class="bc-rule__tick' + (lit ? ' bc-rule__tick--lit' : '') + '" x1="' + x + '" x2="' + x + '" y1="' + top + '" y2="' + yBase + '"/>';
    });
    BANDS.forEach(function (b, i) {
      var lit = band ? b.id === band.id : (b.max > range.min + 0.05);
      s += '<text class="bc-rule__band' + (lit ? ' bc-rule__band--lit' : '') + '" text-anchor="middle" x="' + (x0 + (i + 0.5) * 17 * pitch) + '" y="' + yBand + '">' + b.id + '</text>';
    });
    EDGES.forEach(function (label, i) {
      var x = x0 + i * 17 * pitch + (i === 6 ? -0.5 : 0.5);
      s += '<line class="bc-rule__edge" x1="' + x + '" x2="' + x + '" y1="' + (yTop - 4) + '" y2="' + (yBase + 5) + '"/>';
      s += '<text class="bc-rule__num" text-anchor="' + (i === 0 ? 'start' : i === 6 ? 'end' : 'middle') + '" x="' + (i === 0 ? x0 : i === 6 ? x0 + L : x) + '" y="' + yNum + '">' + label + '</text>';
    });
    if (W - (x0 + L) >= 24) s += '<text class="bc-rule__num" x="' + (x0 + L + 5) + '" y="' + yNum + '">µm</text>';
    if (!rgb) {
      s += '<line class="bc-rule__span" x1="' + X(range.min) + '" x2="' + X(range.max) + '" y1="' + (yBase + 1.5) + '" y2="' + (yBase + 1.5) + '"/>';
    } else {
      RGB.forEach(function (c, i) {
        var xa = x0 + i * 34 * pitch + (i === 0 ? 0.5 : 1.5), xb = x0 + (i + 1) * 34 * pitch - (i === 2 ? 0.5 : 1.5);
        s += '<rect class="bc-rule__channel bc-rule__channel--' + c.k + '" x="' + xa + '" y="62.5" width="' + (xb - xa) + '" height="6"/>';
        s += '<text class="bc-rule__letter" text-anchor="middle" x="' + ((xa + xb) / 2) + '" y="82">' + c.letter + '</text>';
      });
    }
    var label = band ? (band.id + ', ' + band.min.toFixed(2) + ' to ' + band.max.toFixed(2) + ' micrometres') : (sel ? sel.label : '');
    el.innerHTML = '<svg class="bc-rule" role="img" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" aria-label="' +
      esc('Wavelength rule with one tick for each of 102 channels, from 0.74 to 5.00 micrometres. Shown: ' + label + '.') + '">' + s + '</svg>';
  }
  function mountRules(root) {
    each(root, '[data-rule]', function (el) {
      function draw() { wavelengthRule(el, el.getAttribute('data-rule')); }
      draw();
      if (window.ResizeObserver) new ResizeObserver(draw).observe(el);
      var group = el.getAttribute('data-rule-for') && doc.getElementById(el.getAttribute('data-rule-for'));
      if (group) group.addEventListener('bc:change', function (e) { el.setAttribute('data-rule', e.detail.value); draw(); });
    });
  }

  /* ------------------------------------------------------------ spectrum chart */
  var SHAPES = ['circle', 'square', 'triangle', 'diamond', 'triangle-down'];
  var SERIES_FOR = { 1: [3], 2: [1, 5], 3: [1, 3, 5], 4: [1, 2, 4, 5], 5: [1, 2, 3, 4, 5] };

  function shapePath(kind, x, y, r) {
    if (kind === 'square') return 'M' + (x - r) + ' ' + (y - r) + 'h' + (2 * r) + 'v' + (2 * r) + 'h' + (-2 * r) + 'Z';
    if (kind === 'triangle') return 'M' + x + ' ' + (y - r * 1.2) + 'L' + (x + r * 1.15) + ' ' + (y + r * 0.85) + 'L' + (x - r * 1.15) + ' ' + (y + r * 0.85) + 'Z';
    if (kind === 'triangle-down') return 'M' + x + ' ' + (y + r * 1.2) + 'L' + (x + r * 1.15) + ' ' + (y - r * 0.85) + 'L' + (x - r * 1.15) + ' ' + (y - r * 0.85) + 'Z';
    if (kind === 'diamond') return 'M' + x + ' ' + (y - r * 1.3) + 'L' + (x + r * 1.3) + ' ' + y + 'L' + x + ' ' + (y + r * 1.3) + 'L' + (x - r * 1.3) + ' ' + y + 'Z';
    return 'M' + (x - r) + ' ' + y + 'a' + r + ' ' + r + ' 0 1 0 ' + (2 * r) + ' 0a' + r + ' ' + r + ' 0 1 0 ' + (-2 * r) + ' 0Z';
  }
  function seriesKey(n, kind) {
    var cls = kind === 'flagged' ? 'bc-pt bc-pt--flagged' : (kind === 'binned' ? 'bc-pt bc-pt--binned' : 'bc-pt');
    var r = kind === 'binned' ? 5 : (kind === 'flagged' ? 3.5 : 3.5);
    return '<svg class="bc-key bc-series-' + n + '" viewBox="0 0 16 16" aria-hidden="true"><path class="' + cls + '" d="' + shapePath(SHAPES[n - 1], 8, 8, r) + '"/></svg>';
  }

  /* Deterministic example values for the reference page. They are layout fixtures, not measurements. */
  function exampleSpectrum(nVisits) {
    var seed = 20260514;
    function rnd() { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; }
    var counts = [4, 19, 3, 21, 12];
    var labels = nVisits > 4 ? ['Visit 1', 'Visit 2', 'Visit 3', 'Visit 4', 'Visit 5']
      : ['5–6 May 2025', '31 Oct–14 Nov 2025', '11–13 Dec 2025', '21 Apr–14 May 2026'];
    var visits = [];
    for (var v = 0; v < nVisits; v++) {
      var pts = [], scale = 1 + (v - (nVisits - 1) / 2) * 0.06;
      for (var i = 0; i < counts[v]; i++) {
        var w = 0.8 + rnd() * 4.15;
        var base = (40 + 26 * w + 60 * Math.exp(-Math.pow((w - 4.5) / 0.35, 2))) * scale;
        var e = 6 + rnd() * 10;
        pts.push({ w: w, f: base + (rnd() - 0.5) * 2.2 * e, e: e, flag: rnd() < 0.12 });
      }
      pts.sort(function (a, b) { return a.w - b.w; });
      var binned = [];
      if (counts[v] >= 8) {
        [[0.75, 1.65], [1.65, 2.42], [2.42, 3.82], [3.82, 4.42], [4.42, 5.0]].forEach(function (b) {
          var inb = pts.filter(function (p) { return p.w >= b[0] && p.w < b[1] && !p.flag; });
          if (inb.length >= 2) {
            var mw = 0, mf = 0;
            inb.forEach(function (p) { mw += p.w; mf += p.f; });
            binned.push({ w: mw / inb.length, f: mf / inb.length, e: 9 / Math.sqrt(inb.length) });
          }
        });
      }
      visits.push({ label: labels[v], points: pts, binned: binned });
    }
    return { visits: visits, yMax: 240 };
  }

  function spectrum(el, data, opts) {
    opts = opts || {};
    var W = Math.floor(el.clientWidth || 328), H = opts.height || 240;
    if (W < 160) return;
    var ml = 40, mr = 10, mt = 10, mb = 40;
    var x0 = 0.75, x1 = 5.0, y0 = 0, y1 = data.yMax;
    function X(w) { return ml + (w - x0) / (x1 - x0) * (W - ml - mr); }
    function Y(f) { return mt + (1 - (f - y0) / (y1 - y0)) * (H - mt - mb); }
    var s = '';
    if (opts.band) {
      s += '<rect class="bc-chart__band" x="' + X(opts.band[0]) + '" y="' + mt + '" width="' + (X(opts.band[1]) - X(opts.band[0])) + '" height="' + (H - mt - mb) + '"/>';
    }
    for (var f = 0; f <= y1; f += 60) {
      var gy = Math.round(Y(f)) + 0.5;
      s += '<line class="' + (f === 0 ? 'bc-chart__axis' : 'bc-chart__grid') + '" x1="' + ml + '" x2="' + (W - mr) + '" y1="' + gy + '" y2="' + gy + '"/>';
      s += '<text class="bc-chart__num" text-anchor="end" x="' + (ml - 6) + '" y="' + (gy + 4) + '">' + f + '</text>';
    }
    [1, 2, 3, 4, 5].forEach(function (u) {
      var gx = Math.round(X(u)) + (u === 5 ? -0.5 : 0.5);
      s += '<line class="bc-chart__axis" x1="' + gx + '" x2="' + gx + '" y1="' + (H - mb) + '" y2="' + (H - mb + 5) + '"/>';
      s += '<text class="bc-chart__num" text-anchor="' + (u === 5 ? 'end' : 'middle') + '" x="' + (u === 5 ? W - mr : gx) + '" y="' + (H - mb + 18) + '">' + u + '</text>';
    });
    s += '<line class="bc-chart__axis" x1="' + (ml + 0.5) + '" x2="' + (ml + 0.5) + '" y1="' + mt + '" y2="' + (H - mb) + '"/>';
    s += '<text class="bc-chart__title" text-anchor="middle" x="' + ((ml + W - mr) / 2) + '" y="' + (H - 6) + '">Wavelength λ (µm)</text>';
    s += '<text class="bc-chart__title" x="0" y="' + (mt + 4) + '" transform="rotate(-90 0 ' + (mt + 4) + ') translate(' + (-(H - mt - mb) / 2 - 34) + ' 10)">Flux (µJy)</text>';
    var map = SERIES_FOR[data.visits.length] || SERIES_FOR[5];
    /* per-exposure points first, binned points on top */
    data.visits.forEach(function (v, i) {
      var n = map[i], shape = SHAPES[n - 1];
      s += '<g class="bc-series-' + n + '">';
      v.points.forEach(function (p) {
        var cx = X(p.w), cy = Y(p.f);
        s += '<path class="bc-pt__err" d="M' + cx + ' ' + Y(p.f - p.e) + 'V' + Y(p.f + p.e) + '"/>';
        s += '<path class="bc-pt' + (p.flag ? ' bc-pt--flagged' : '') + '" d="' + shapePath(shape, cx, cy, p.flag ? 3 : 2.5) + '"/>';
      });
      s += '</g>';
    });
    data.visits.forEach(function (v, i) {
      var n = map[i], shape = SHAPES[n - 1];
      s += '<g class="bc-series-' + n + '">';
      v.binned.forEach(function (p) {
        s += '<path class="bc-pt__err" d="M' + X(p.w) + ' ' + Y(p.f - p.e) + 'V' + Y(p.f + p.e) + '"/>';
        s += '<path class="bc-pt bc-pt--binned" d="' + shapePath(shape, X(p.w), Y(p.f), 5) + '"/>';
      });
      s += '</g>';
    });
    el.innerHTML = '<svg class="bc-chart" role="img" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" aria-label="' +
      esc(opts.label || 'Spectrum: flux in microjansky against wavelength from 0.75 to 5.0 micrometres. The same values are in the table view.') + '">' + s + '</svg>';
    return map;
  }
  function mountSpectra(root) {
    each(root, '[data-spectrum]', function (el) {
      var n = parseInt(el.getAttribute('data-spectrum'), 10) || 4;
      var data = exampleSpectrum(n);
      var band = el.getAttribute('data-band');
      function draw() {
        spectrum(el, data, { height: parseInt(el.getAttribute('data-height') || '240', 10), band: band ? band.split(',').map(Number) : null,
          label: 'Example spectrum for layout: flux in microjansky against wavelength from 0.75 to 5.0 micrometres, ' + n + ' visits.' });
      }
      draw();
      if (window.ResizeObserver) new ResizeObserver(draw).observe(el);
      var legend = el.getAttribute('data-legend') && doc.getElementById(el.getAttribute('data-legend'));
      if (legend) {
        var map = SERIES_FOR[n];
        legend.innerHTML = data.visits.map(function (v, i) {
          return '<span class="bc-legend__item">' + seriesKey(map[i], 'point') + '<span>' + esc(v.label) + '</span></span>';
        }).join('') +
          '<span class="bc-legend__item">' + seriesKey(3, 'binned') + '<span>Larger: binned</span></span>' +
          '<span class="bc-legend__item">' + seriesKey(3, 'flagged') + '<span>Hollow: flagged</span></span>';
      }
      var table = el.getAttribute('data-table') && doc.getElementById(el.getAttribute('data-table'));
      if (table) {
        var rows = [];
        data.visits.forEach(function (v, i) {
          v.points.slice(0, 3).forEach(function (p) {
            rows.push('<tr><td><span class="bc-table__flag">' + seriesKey(SERIES_FOR[n][i], p.flag ? 'flagged' : 'point') + esc(v.label) + '</span></td><td>' +
              p.w.toFixed(3) + '</td><td>' + p.f.toFixed(1) + '</td><td>±' + p.e.toFixed(1) + '</td><td class="bc-table__text">' + (p.flag ? 'Flagged' : '') + '</td></tr>');
          });
        });
        table.innerHTML = rows.join('');
      }
    });
  }

  /* ------------------------------------------------------------ small behaviours for the previews and the app */
  function wireRadioGroups(root) {
    each(root, '[role="radiogroup"]', function (group) {
      var options = Array.prototype.slice.call(group.querySelectorAll('[role="radio"]'));
      function enabled(o) { return o.getAttribute('aria-disabled') !== 'true'; }
      function select(o, focus) {
        if (!enabled(o)) return;
        options.forEach(function (x) { x.setAttribute('aria-checked', x === o ? 'true' : 'false'); x.tabIndex = x === o ? 0 : -1; });
        if (focus) o.focus();
        group.dispatchEvent(new CustomEvent('bc:change', { bubbles: true, detail: { value: o.getAttribute('data-value') || o.textContent.trim() } }));
      }
      options.forEach(function (o) {
        o.tabIndex = o.getAttribute('aria-checked') === 'true' ? 0 : -1;
        o.addEventListener('click', function () { select(o, false); });
        o.addEventListener('keydown', function (e) {
          var dir = (e.key === 'ArrowRight' || e.key === 'ArrowDown') ? 1 : (e.key === 'ArrowLeft' || e.key === 'ArrowUp') ? -1 : 0;
          var list = options.filter(enabled), i = list.indexOf(o);
          if (dir && i > -1) { e.preventDefault(); select(list[(i + dir + list.length) % list.length], true); }
          if (e.key === 'Home') { e.preventDefault(); select(list[0], true); }
          if (e.key === 'End') { e.preventDefault(); select(list[list.length - 1], true); }
          if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); select(o, false); }
        });
      });
      if (!options.some(function (o) { return o.tabIndex === 0; })) { var first = options.filter(enabled)[0]; if (first) first.tabIndex = 0; }
      var shows = group.getAttribute('data-shows');
      if (shows) {
        group.addEventListener('bc:change', function (e) {
          each(doc, '[data-panel-of="' + shows + '"]', function (p) { p.hidden = p.getAttribute('data-panel') !== e.detail.value; });
        });
      }
    });
  }
  function wireSwitches(root) {
    each(root, '[role="switch"]', function (sw) {
      sw.addEventListener('click', function () {
        if (sw.disabled || sw.getAttribute('aria-disabled') === 'true') return;
        var on = sw.getAttribute('aria-checked') !== 'true';
        sw.setAttribute('aria-checked', on ? 'true' : 'false');
        var state = sw.querySelector('.bc-toggle__state');
        if (state) state.textContent = on ? (sw.getAttribute('data-on') || 'On') : (sw.getAttribute('data-off') || 'Off');
        sw.dispatchEvent(new CustomEvent('bc:change', { bubbles: true, detail: { value: on } }));
      });
    });
  }
  /* hold to flip: one change on press, one on release. Works with pointer, Space and Enter. */
  function wireFlip(root) {
    each(root, '.bc-flip', function (key) {
      function set(on) {
        if (key.disabled) return;
        if ((key.getAttribute('aria-pressed') === 'true') === on) return;
        key.setAttribute('aria-pressed', on ? 'true' : 'false');
        key.dispatchEvent(new CustomEvent('bc:flip', { bubbles: true, detail: { held: on } }));
      }
      key.addEventListener('pointerdown', function (e) { if (key.setPointerCapture) { try { key.setPointerCapture(e.pointerId); } catch (err) {} } set(true); });
      ['pointerup', 'pointercancel', 'lostpointercapture', 'blur'].forEach(function (t) { key.addEventListener(t, function () { set(false); }); });
      key.addEventListener('keydown', function (e) { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); set(true); } });
      key.addEventListener('keyup', function (e) { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); set(false); } });
      key.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    });
  }
  function wireCopy(root) {
    each(root, '[data-copy]', function (btn) {
      var status = doc.getElementById(btn.getAttribute('data-copy'));
      var timer = null;
      function say(text) {
        if (!status) return;
        status.textContent = text;
        clearTimeout(timer);
        timer = setTimeout(function () { status.textContent = ''; }, 4000);
      }
      btn.addEventListener('click', function () {
        var ok = (status && status.getAttribute('data-done')) || 'Link copied';
        var no = (status && status.getAttribute('data-failed')) || 'Could not copy. Select the address bar instead.';
        var url = btn.getAttribute('data-url') || location.href;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(function () { say(ok); }, function () { say(no); });
        } else {
          say(no);
        }
      });
    });
  }
  function wireTooltips(root) {
    each(root, '.bc-tiphost', function (host) {
      host.addEventListener('keydown', function (e) { if (e.key === 'Escape') host.classList.add('is-dismissed'); });
      ['mouseleave', 'focusout'].forEach(function (t) { host.addEventListener(t, function () { host.classList.remove('is-dismissed'); }); });
    });
  }
  function wireOutputs(root) {
    each(root, 'input[type="range"][data-output]', function (input) {
      var out = doc.getElementById(input.getAttribute('data-output'));
      var unit = input.getAttribute('data-unit') || '';
      function show() { if (out) out.textContent = input.value + unit; }
      input.addEventListener('input', show);
      show();
    });
  }
  function wireInvert(root) {
    each(root, '[data-inverts]', function (sw) {
      sw.addEventListener('bc:change', function (e) {
        each(doc, sw.getAttribute('data-inverts'), function (canvas) {
          canvas.setAttribute('data-invert', e.detail.value ? 'true' : 'false');
          if (canvas.bcRedraw) canvas.bcRedraw();
        });
      });
    });
  }

  function enhance(root) {
    root = root || doc;
    mountIcons(root);
    mountCompasses(root);
    mountFrames(root);
    mountRules(root);
    mountSpectra(root);
    wireRadioGroups(root);
    wireSwitches(root);
    wireFlip(root);
    wireCopy(root);
    wireTooltips(root);
    wireOutputs(root);
    wireInvert(root);
  }

  var api = {
    token: token, icons: ICONS, icon: icon,
    displayScale: displayScale, paintFrame: paintFrame, hatchPattern: hatchPattern,
    compositeAB: compositeAB, diffColor: diffColor,
    bands: BANDS, channels: channels, wavelengthRule: wavelengthRule,
    marker: marker, track: track, spotlight: spotlight, overlayMarkup: overlayMarkup, scaleBar: scaleBar, compass: compass,
    spectrum: spectrum, exampleSpectrum: exampleSpectrum, seriesKey: seriesKey, seriesFor: SERIES_FOR, shapes: SHAPES,
    placeholderFrame: placeholderFrame, enhance: enhance
  };
  window.Comparator = api;
})();
