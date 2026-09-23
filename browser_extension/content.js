(() => {
  const ROOT_ID = 'odm-video-download-root';
  let root = null;
  let menu = null;
  let button = null;
  let currentVideo = null;

  let menuPage = "";
  const formatCache = new Map();
  const CACHE_MS = 5 * 60 * 1000;

  function mediaKey() {
    const url = new URL(location.href);
    if (/(^|\.)youtube\.com$/.test(url.hostname) && url.searchParams.get('v')) {
      return url.origin + '/watch?v=' + encodeURIComponent(url.searchParams.get('v'));
    }
    return location.href + '|' + (currentVideo && (currentVideo.currentSrc || currentVideo.src) || '');
  }

  function prepareQualities() {
    const key = mediaKey();
    const pageUrl = location.href;
    let entry = formatCache.get(key);
    if (entry && (entry.pending || Date.now() < entry.expires)) return entry;
    entry = {pending:true, result:null, expires:0};
    formatCache.set(key, entry);
    // Keep metadata only; download URLs are still resolved by the desktop app.
    if (formatCache.size > 12) formatCache.delete(formatCache.keys().next().value);
    Promise.resolve().then(() => chrome.runtime.sendMessage({action:'mediaFormats', idmUrl:pageUrl}))
      .then(result => {
        entry.result = result && result.ok && result.formats && result.formats.length ? result : null;
        entry.error = (result && result.error) || 'Could not read this video. Click to retry.';
      }).catch(() => { entry.error = 'Could not read this video. Reload the extension and retry.'; })
      .finally(() => {
        entry.pending = false;
        entry.expires = Date.now() + (entry.result ? CACHE_MS : 15000);
        if (key === mediaKey()) schedulePosition();
      });
    return entry;
  }

  function largestVisibleVideo() {
    let best = null;
    let bestArea = 0;
    for (const v of document.querySelectorAll('video')) {
      const r = v.getBoundingClientRect();
      if (r.width < 240 || r.height < 135) continue;
      const cs = getComputedStyle(v);
      if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity || 1) === 0) continue;
      const area = r.width * r.height;
      if (area > bestArea) { bestArea = area; best = v; }
    }
    return best;
  }

  function directMediaUrl(video) {
    if (!video) return '';
    const candidates = [video.currentSrc, video.src];
    for (const s of video.querySelectorAll('source')) candidates.push(s.src);
    return candidates.find(u => /^https?:\/\//i.test(u || '')) || '';
  }

  function cleanVideoTitle() {
    return String(document.title || 'Video').replace(/\s*-\s*YouTube\s*$/i, '').trim() || 'Video';
  }

  function sendPreset(quality, kind) {
    chrome.runtime.sendMessage({
      action: 'mediaPreset',
      idmUrl: location.href,
      quality,
      kind,
      title: document.title || ''
    });
    closeMenu();
  }

  function sendDirect() {
    const url = directMediaUrl(currentVideo);
    if (url) {
      chrome.runtime.sendMessage({action:'directMedia', idmUrl:url});
      closeMenu();
    }
  }

  function closeMenu() {
    if (menu) menu.style.display = 'none';
  }

  function menuStatus(text) {
    menu.replaceChildren();
    const head = document.createElement('div');
    head.textContent = 'File Name — File Type — Quality';
    head.style.cssText = 'padding:8px 12px 9px;font-weight:700;border-bottom:1px solid #e5e7eb;background:#f8fafc';
    const status = document.createElement('div');
    status.textContent = text;
    status.style.cssText = 'padding:9px 13px;color:#64748b';
    menu.append(head, status);
    return status;
  }

  function toggleMenu() {
    if (!menu) return;
    if (menu.style.display !== 'none') { closeMenu(); return; }
    const page = mediaKey();
    const entry = prepareQualities();
    if (!entry.result) {
      // The button is hidden during the initial lookup; never show a loading menu.
      if (!entry.pending) {
        showStatusToast(entry.error, false);
        formatCache.delete(page);
        positionUI();
      }
      return;
    }
    const result = entry.result;
    menuPage = page;
    menuStatus('').remove();
      const title = result.title || cleanVideoTitle();
      const short = title.length > 31 ? title.slice(0,31).trim() + '...' : title;
      result.formats.forEach(opt => {
        const item = document.createElement('button');
        item.type = 'button';
        const h = Number(opt.quality);
        const quality = `${h}p${h >= 4320 ? ' 8K' : h >= 2160 ? ' 4K' : h >= 720 ? ' HD' : ''}`;
        item.textContent = `${short} — ${opt.type} file — quality ${quality}`;
        item.title = `${title} — ${opt.type} file — quality ${quality}`;
        item.style.cssText = 'display:block;width:100%;text-align:left;padding:9px 13px;border:0;background:#fff;color:#1f2937;font:14px Segoe UI,Arial,sans-serif;cursor:pointer';
        item.addEventListener('mouseenter', () => item.style.background = '#eef6ff');
        item.addEventListener('mouseleave', () => item.style.background = '#fff');
        item.addEventListener('click', e => {
          e.preventDefault(); e.stopPropagation();
          if (page !== mediaKey()) { closeMenu(); return; }
          sendPreset(String(opt.quality), 'video');
        });
        menu.appendChild(item);
      });
    menu.style.display = 'block';
  }

  function buildUI() {
    if (root) return;
    root = document.createElement('div');
    root.id = ROOT_ID;
    root.style.cssText = [
      'position:fixed','z-index:2147483647','display:none','font-family:Segoe UI,Arial,sans-serif',
      'font-size:14px','line-height:1.25','color:#fff','pointer-events:auto'
    ].join(';');

    button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-label','Download this video');
    button.style.cssText = [
      'height:34px','padding:0 12px','border:1px solid rgba(0,0,0,.45)','border-radius:5px',
      'background:linear-gradient(#253749,#111b26)','color:#fff','font-weight:600','cursor:pointer',
      'box-shadow:0 2px 7px rgba(0,0,0,.45)','display:flex','align-items:center','gap:8px'
    ].join(';');
    const play = document.createElement('span');
    play.textContent = '▶';
    play.style.cssText = 'color:#43d35f;font-size:17px;line-height:1';
    const txt = document.createElement('span');
    txt.textContent = 'Download this video';
    const arrow = document.createElement('span');
    arrow.textContent = '▾';
    arrow.style.cssText = 'font-size:12px;opacity:.9';
    button.append(play, txt, arrow);
    button.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); toggleMenu(); });

    menu = document.createElement('div');
    menu.style.cssText = [
      'display:none','position:absolute','top:38px','left:0','width:520px','max-height:480px','overflow:auto',
      'background:#fff','color:#1c1c1c','border:1px solid #aeb6bf','border-radius:6px','box-shadow:0 10px 30px rgba(0,0,0,.35)',
      'padding:6px 0'
    ].join(';');

    root.append(button, menu);
    document.documentElement.appendChild(root);

    document.addEventListener('click', e => {
      if (root && !root.contains(e.target)) closeMenu();
    }, true);
  }

  let positionScheduled = false;
  function schedulePosition() {
    if (positionScheduled) return;
    positionScheduled = true;
    requestAnimationFrame(() => { positionScheduled = false; positionUI(); });
  }

  function positionUI() {
    buildUI();
    if (menuPage && menuPage !== mediaKey()) { menuPage = ""; closeMenu(); }
    currentVideo = largestVisibleVideo();
    if (!currentVideo) {
      root.style.display = 'none';
      closeMenu();
      return;
    }
    const r = currentVideo.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) {
      root.style.display = 'none';
      return;
    }
    if (menuPage && menuPage !== mediaKey()) { menuPage = ""; closeMenu(); }
    const formats = prepareQualities();
    root.style.display = formats.pending ? 'none' : 'block';
    if (formats.pending) closeMenu();
    const left = Math.max(8, Math.min(innerWidth - 365, r.left + 10));
    const top = Math.max(8, r.top + 10);
    root.style.left = `${left}px`;
    root.style.top = `${top}px`;
    const direct = root.querySelector('#odm-direct-media-item');
    if (direct) direct.style.display = directMediaUrl(currentVideo) ? 'block' : 'none';
  }



  function showStatusToast(text, ok) {
    let toast = document.getElementById('odm-status-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'odm-status-toast';
      toast.style.cssText = [
        'position:fixed','right:18px','bottom:18px','z-index:2147483647','max-width:420px',
        'padding:11px 14px','border-radius:7px','font:13px Segoe UI,Arial,sans-serif','color:#fff',
        'box-shadow:0 5px 20px rgba(0,0,0,.35)','transition:opacity .2s ease'
      ].join(';');
      document.documentElement.appendChild(toast);
    }
    toast.textContent = text;
    toast.style.background = ok ? '#167c3a' : '#a52a2a';
    toast.style.opacity = '1';
    clearTimeout(showStatusToast._timer);
    showStatusToast._timer = setTimeout(() => { if (toast) toast.style.opacity = '0'; }, 3200);
  }

  chrome.runtime.onMessage.addListener(msg => {
    if (msg && msg.action === 'idmStatus') showStatusToast(msg.text || '', !!msg.ok);
  });

  buildUI();
  positionUI();
  addEventListener('resize', schedulePosition, {passive:true});
  addEventListener('scroll', schedulePosition, {passive:true});
  setInterval(schedulePosition, 1200);

  const observer = new MutationObserver(schedulePosition);
  observer.observe(document.documentElement, {subtree:true, childList:true});
})();
