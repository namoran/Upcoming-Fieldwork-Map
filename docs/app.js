/* Florida Fieldwork Notifications — map page.
 *
 * Reads data/fieldwork.json, which fetch_fieldwork.py writes on a schedule
 * (see .github/workflows/fieldwork.yml). Nothing here talks to FDEP: the data
 * is already in the JSON, so the page loads instantly and works offline.
 */
(function () {
  'use strict';

  var FLORIDA = [27.9, -82.4];
  var START_ZOOM = 6;

  var map = L.map('map', { center: FLORIDA, zoom: START_ZOOM, zoomSnap: 0.5, preferCanvas: true });
  window.fieldworkMap = map;      // handy for embedding / debugging
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  var msg = document.getElementById('msg');
  var listEl = document.getElementById('counties');
  var qEl = document.getElementById('q');

  var all = [];              // facilities with markers
  var markers = [];
  var byCounty = {};         // county name -> [marker]
  var activeCounty = null;

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function shortDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) return iso;
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return months[+m[2] - 1] + ' ' + (+m[3]);
  }

  function prettyCounty(c) {
    if (!c) return 'Unknown';
    // FDEP gives uppercase names: MIAMI-DADE, PALM BEACH, ST. JOHNS.
    return c.toLowerCase().replace(/(^|[\s.\-])([a-z])/g, function (m, sep, ch) {
      return sep + ch.toUpperCase();
    });
  }

  function popupHtml(f) {
    var docs = f.documents.map(function (d) {
      var subject = d.subject || 'Field work notification';
      var label = d.link ? '<a href="' + esc(d.link) + '" target="_blank" rel="noopener">' + esc(subject) + '</a>'
                         : esc(subject);
      return '<li><span class="d">' + esc(shortDate(d.date)) + '</span> ' +
             '<span class="s">' + label + '</span></li>';
    }).join('');
    var place = [f.address, f.city].filter(Boolean).join(', ');
    return '<div class="fac">' + esc(f.name || 'Facility ' + f.id) + '</div>' +
           '<div class="addr">' + esc(prettyCounty(f.county)) + ' County' +
           (place ? ' &middot; ' + esc(place) : '') + '</div>' +
           '<ul>' + docs + '</ul>';
  }

  function radius(f) { return Math.min(4.5 + f.documents.length * 1.3, 11); }

  function draw(facilities) {
    facilities.forEach(function (f) {
      var marker = L.circleMarker([f.lat, f.lon], {
        radius: radius(f),
        color: '#ffffff',
        weight: 1.5,
        fillColor: '#0b5f8a',
        fillOpacity: 0.62
      });
      marker.bindPopup(function () { return popupHtml(f); }, { maxWidth: 320, maxHeight: 300 });
      marker.facility = f;
      f._marker = marker;
      marker.addTo(map);
      markers.push(marker);
      var key = (f.county || '').toUpperCase();
      (byCounty[key] = byCounty[key] || []).push(marker);
    });
  }

  function countyList(counts) {
    var max = 1;
    Object.keys(counts).forEach(function (k) { if (counts[k] > max) max = counts[k]; });

    var html = Object.keys(counts)
      .sort(function (a, b) { return counts[b] - counts[a] || a.localeCompare(b); })
      .map(function (name) {
        var n = counts[name];
        return '<li><button type="button" data-county="' + esc(name) + '">' +
               '<span class="name">' + esc(prettyCounty(name)) + '</span>' +
               '<span class="bar" style="width:' + Math.max(8, Math.round(n / max * 54)) + 'px"></span>' +
               '<span class="n">' + n + '</span></button></li>';
      }).join('');
    listEl.innerHTML = html;

    listEl.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-county]');
      if (btn) zoomCounty(btn.dataset.county);
    });
  }

  function setActive(name) {
    Array.prototype.forEach.call(listEl.querySelectorAll('button[data-county]'), function (b) {
      b.classList.toggle('active', b.dataset.county === name);
    });
  }

  function zoomCounty(name) {
    map.closePopup();

    if (activeCounty === name) {                 // clicking the same county again clears it
      activeCounty = null;
      setActive(null);
      map.flyTo(FLORIDA, START_ZOOM, { duration: 0.6 });
      return;
    }

    var group = byCounty[name] || [];
    if (!group.length) return;
    activeCounty = name;
    setActive(name);
    map.flyToBounds(L.featureGroup(group).getBounds().pad(0.15), { duration: 0.6, maxZoom: 11 });
  }

  function search(term) {
    var t = term.trim().toLowerCase();
    if (!t) {
      map.flyTo(FLORIDA, START_ZOOM, { duration: 0.5 });
      return;
    }
    var hits = all.filter(function (f) {
      return [f.name, f.address, f.city, f.county, f.id].some(function (v) {
        return v && String(v).toLowerCase().indexOf(t) !== -1;
      });
    });
    if (!hits.length) return;
    var group = hits.map(function (f) { return f._marker; });
    map.flyToBounds(L.featureGroup(group).getBounds().pad(0.2), { duration: 0.6, maxZoom: 12 });
  }

  var searchTimer = null;
  qEl.addEventListener('input', function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { search(qEl.value); }, 220);
  });

  // Leaflet has to be told when its container changes size (phone rotation,
  // responsive layout, browser window drag).
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { map.invalidateSize(); }, 120);
  });

  fetch('data/fieldwork.json', { cache: 'no-cache' })
    .then(function (r) {
      if (!r.ok) throw new Error('could not load data/fieldwork.json (HTTP ' + r.status + ')');
      return r.json();
    })
    .then(function (data) {
      var list = (data.facilities || []).filter(function (f) {
        return typeof f.lat === 'number' && typeof f.lon === 'number';
      });

      document.getElementById('n-fac').textContent = list.length;
      document.getElementById('n-doc').textContent = data.document_count != null
        ? data.document_count : list.reduce(function (n, f) { return n + f.documents.length; }, 0);
      document.getElementById('n-county').textContent = Object.keys(data.by_county || {}).length;

      var w = data.window || {};
      var when = w.from && w.to ? shortDate(w.from) + ' – ' + shortDate(w.to) : 'unknown window';
      document.getElementById('window').textContent =
        'notices filed ' + when + ' · updated ' + new Date(data.generated).toLocaleString();

      draw(list);
      all = list;

      countyList(data.by_county || {});
      if (!list.length) {
        msg.textContent = 'No field work notices for this window yet.';
        return;
      }
      msg.classList.add('hidden');
      map.fitBounds(L.featureGroup(markers).getBounds().pad(0.08), { maxZoom: 7 });
    })
    .catch(function (err) {
      msg.className = 'msg error';
      msg.textContent = err.message + ' — run the fetch workflow to generate it.';
    });
})();
