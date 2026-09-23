const HOST_NAME = 'com.originaldownloadmanager.integration';
const BRIDGE_URL = 'http://127.0.0.1:17654/v1/download';

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({id:'idm-link',title:'Download link with Internet Download Manager',contexts:['link']});
    chrome.contextMenus.create({id:'idm-media',title:'Download video/audio with Internet Download Manager',contexts:['video','audio']});
    chrome.contextMenus.create({id:'idm-page-media',title:'Download video/media from this page',contexts:['page']});
  });
});

async function postToRunningApp(message) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 900);
  try {
    const res = await fetch(BRIDGE_URL, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(message),
      cache: 'no-store',
      signal: controller.signal
    });
    if (!res.ok) return {ok:false};
    const data = await res.json().catch(() => ({}));
    return {ok: data && data.ok === true && data.application === 'InternetDownloadManager'};
  } catch (_) {
    return {ok:false};
  } finally {
    clearTimeout(timer);
  }
}

function sendNative(message) {
  return new Promise(resolve => {
    try {
      chrome.runtime.sendNativeMessage(HOST_NAME, message, response => {
        if (chrome.runtime.lastError) {
          resolve({ok:false, error:chrome.runtime.lastError.message || 'Desktop integration is not installed.'});
          return;
        }
        resolve(response && response.ok ? {ok:true} : {ok:false, error:(response && response.error) || 'Desktop app did not accept the request.'});
      });
    } catch (e) {
      resolve({ok:false, error:String(e)});
    }
  });
}

async function sendToDesktop(message) {
  // Fast path: if the desktop app is already running, send directly to its
  // loopback bridge. No browser tab, custom URL, or confirmation prompt.
  const local = await postToRunningApp(message);
  if (local.ok) return local;

  // Fallback: the registered native-messaging host launches the desktop app
  // directly, again without navigating the browser to an idm:// URL.
  return await sendNative(message);
}

function notifyTab(tabId, text, ok=false) {
  if (!tabId) return;
  chrome.tabs.sendMessage(tabId, {action:'idmStatus', text, ok}).catch(() => {});
}

const recentRequests = new Map();
const interceptedBrowserDownloads = new Set();

// Intercept ordinary HTTP/HTTPS browser downloads and route them through the
// same desktop File Info -> Progress -> Complete flow. Blob/data URLs and
// extension-internal downloads are intentionally left to Chrome.
if (chrome.downloads && chrome.downloads.onCreated) {
  chrome.downloads.onCreated.addListener(item => {
    const url = (item.finalUrl || item.url || '').trim();
    if (!item.id || !/^https?:\/\//i.test(url) || interceptedBrowserDownloads.has(item.id)) return;
    interceptedBrowserDownloads.add(item.id);
    chrome.downloads.cancel(item.id, () => {
      chrome.runtime.lastError;
      chrome.downloads.erase({id:item.id}, () => chrome.runtime.lastError);
      handle({action:'directMedia', url}, null);
    });
    setTimeout(() => interceptedBrowserDownloads.delete(item.id), 10000);
  });
}


async function handle(message, tabId) {
  if (!message || !message.url || !/^https?:\/\//i.test(message.url)) return;
  const key = [message.action, message.url, message.quality || '', message.kind || ''].join('|');
  const now = Date.now();
  const last = recentRequests.get(key) || 0;
  if (now - last < 1500) return;
  recentRequests.set(key, now);
  message.requestId = message.requestId || (crypto.randomUUID ? crypto.randomUUID() : `${now}-${Math.random()}`);
  for (const [k,t] of recentRequests) if (now - t > 10000) recentRequests.delete(k);
  const result = await sendToDesktop(message);
  if (result.ok) notifyTab(tabId, 'Download sent directly to Internet Download Manager.', true);
  else notifyTab(tabId, result.error || 'Desktop app not detected. Run INSTALL_BROWSER_INTEGRATION.bat and try again.', false);
}

chrome.action.onClicked.addListener(tab => {
  handle({action:'pageMedia', url:tab.url || ''}, tab.id);
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const tabId = tab && tab.id;
  if (info.menuItemId === 'idm-media' && info.srcUrl) return handle({action:'directMedia', url:info.srcUrl}, tabId);
  if (info.menuItemId === 'idm-link' && info.linkUrl) return handle({action:'directMedia', url:info.linkUrl}, tabId);
  if (info.menuItemId === 'idm-page-media') return handle({action:'pageMedia', url:info.pageUrl || (tab && tab.url) || ''}, tabId);
});

async function readMediaFormats(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const response = await fetch(BRIDGE_URL, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'mediaFormats', url}), signal:controller.signal
    });
    const data = await response.json();
    if (data.application === 'InternetDownloadManager' && ('formats' in data || data.error)) return data;
  } catch (_) {
  } finally { clearTimeout(timer); }
  return new Promise(resolve => {
    const deadline = setTimeout(() => resolve({ok:false,error:'Video lookup timed out. Click again to retry.'}), 45000);
    try {
      chrome.runtime.sendNativeMessage(HOST_NAME, {action:'mediaFormats',url}, response => {
        clearTimeout(deadline);
        const error = chrome.runtime.lastError;
        resolve(error ? {ok:false,error:'Run the updated app / INSTALL_BROWSER_INTEGRATION.bat, then retry.'} :
          response || {ok:false,error:'Could not read available video qualities.'});
      });
    } catch (_) {
      clearTimeout(deadline);
      resolve({ok:false,error:'Desktop integration is unavailable. Run INSTALL_BROWSER_INTEGRATION.bat.'});
    }
  });
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.action === 'mediaFormats' && /^https?:\/\//i.test(msg.idmUrl || '')) {
    readMediaFormats(msg.idmUrl).then(sendResponse).catch(() => sendResponse({ok:false,error:'Video lookup failed. Click again to retry.'}));
    return true;
  }

  if (!msg || !msg.idmUrl) return;
  let payload;
  if (msg.action === 'mediaPreset') {
    payload = {action:'mediaPreset', url:msg.idmUrl, quality:msg.quality || 'best', kind:msg.kind || 'video', title:msg.title || ''};
  } else if (msg.action === 'directMedia') {
    payload = {action:'directMedia', url:msg.idmUrl};
  } else {
    payload = {action:'pageMedia', url:msg.idmUrl};
  }
  handle(payload, sender.tab && sender.tab.id).then(() => sendResponse({ok:true}));
  return true;
});
