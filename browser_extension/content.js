(() => {
  const ROOT_ID = 'odm-video-download-root';
  if (globalThis.__idmContentActive) return;
  globalThis.__idmContentActive = true;
  document.getElementById(ROOT_ID)?.remove();

  // Catch clear file-download links before Chrome starts its own download.
  // Downloads without a recognizable link are still routed by downloads.onCreated.
  const DOWNLOAD_FILE_EXT = /\.(?:7z|apk|appx|avif|bat|bin|bmp|bz2|cab|cmd|com|csv|deb|dmg|dll|docx?|epub|exe|flac|flv|gif|gz|heic|heif|ico|iso|jar|jpe?g|m4a|m4v|midi?|mkv|mov|mp3|mp4|mpeg|mpg|msi|msix|ods|odt|ogg|pdf|png|pptx?|psd|rar|raw|rpm|rtf|svg|tar|tgz|tiff?|txt|wav|webp|webm|wmv|xls[xm]?|xapk|zip)(?:$|[?#])/i;
  function shouldRouteDownload(anchor, href) {
    let url;
    try { url = new URL(href, location.href); } catch (_) { return false; }
    if (!/^https?:$/.test(url.protocol)) return false;
    if (anchor.hasAttribute('download')) return true;
    if (DOWNLOAD_FILE_EXT.test(url.pathname)) return true;
    if (url.searchParams.has('download')) return true;
    return /(^|\.)drive\.google\.com$/i.test(url.hostname) &&
      url.pathname === '/uc' && url.searchParams.get('export') === 'download';
  }
  document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
        event.shiftKey || event.altKey) return;
    const anchor = event.target && event.target.closest && event.target.closest('a[href]');
    if (!anchor || !shouldRouteDownload(anchor, anchor.href)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try { chrome.runtime.sendMessage({action:'directMedia', idmUrl:anchor.href}); } catch (_) {}
  }, true);

  function sendMessage(message) {
    return new Promise((resolve, reject) => {
      try {
        chrome.runtime.sendMessage(message, response => {
          const error = chrome.runtime.lastError;
          if (error) reject(new Error(error.message));
          else resolve(response);
        });
      } catch (error) { reject(error); }
    });
  }
  async function requestFormats(url) {
    let failure;
    for (let attempt=0; attempt<2; attempt++) {
      try { return await sendMessage({action:'mediaFormats', idmUrl:url}); }
      catch (error) {
        failure=error;
        if (!chrome.runtime?.id) break;
        await new Promise(resolve => setTimeout(resolve, 350));
      }
    }
    throw failure;
  }

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

  function isFacebookInsightsPage() {
    const page = new URL(location.href);
    return /(^|\\.)facebook\\.com$/i.test(page.hostname) && /^\\/content\\/insights\\/?$/i.test(page.pathname);
  }

  function facebookInsightsVideoUrl(video) {
    const source = directMediaUrl(video);
    if (!source) return '';
    try {
      const host = new URL(source).hostname.toLowerCase();
      return host === 'fbcdn.net' || host.endsWith('.fbcdn.net') ? source : '';
    } catch (_) { return ''; }
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
    if (isFacebookInsightsPage()) {
      const mediaUrl = facebookInsightsVideoUrl(currentVideo);
      entry.pending = false;
      entry.expires = Date.now() + (mediaUrl ? 30000 : 15000);
      if (mediaUrl) {
        const fileType = /\\.(m4v|mov|webm)(?:$|[?#])/i.exec(mediaUrl)?.[1]?.toUpperCase() || 'MP4';
        entry.directUrl = mediaUrl;
        entry.directType = fileType;
        entry.result = {ok:true, title:cleanVideoTitle(), formats:[]};
      } else {
        entry.error = 'This Facebook Insights preview does not expose a direct video file. Open the original video post and try again.';
      }
      return entry;
    }
    requestFormats(pageUrl)
      .then(result => {
        entry.result = result && result.ok && result.formats && result.formats.length ? result : null;
        entry.error = (result && result.error) || 'Could not read this video. Click to retry.';
      }).catch(error => { entry.error = !chrome.runtime?.id ? 'The extension was updated. Refresh this video page once to reconnect.' : 'Browser connection interrupted. Click again to retry. ' + String(error.message || ''); })
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

  function sendDirect(url = directMediaUrl(currentVideo)) {
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
      if (entry.directUrl) {
        const item = document.createElement('button');
        item.type = 'button';
        item.textContent = `${short} — ${entry.directType} file — Original quality`;
        item.title = `${title} — ${entry.directType} file — Original quality`;
        item.style.cssText = 'display:block;width:100%;text-align:left;padding:9px 13px;border:0;background:#fff;color:#1f2937;font:14px Segoe UI,Arial,sans-serif;cursor:pointer';
        item.addEventListener('mouseenter', () => item.style.background = '#eef6ff');
        item.addEventListener('mouseleave', () => item.style.background = '#fff');
        item.addEventListener('click', e => {
          e.preventDefault(); e.stopPropagation();
          if (page !== mediaKey()) { closeMenu(); return; }
          sendDirect(entry.directUrl);
        });
        menu.appendChild(item);
        menu.style.display = 'block';
        return;
      }
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
    if (!chrome.runtime?.id) return;
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
