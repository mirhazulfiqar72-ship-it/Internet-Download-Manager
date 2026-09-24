(() => {
  const repo = 'mirhazulfiqar72-ship-it/Internet-Download-Manager';
  const fallbackVersion = '1.5.10';
  const latestInstaller = `https://github.com/${repo}/releases/latest/download/InternetDownloadManager_Setup.exe`;

  document.querySelectorAll('.download-link').forEach(link => {
    link.href = latestInstaller;
  });

  const setVersion = version => {
    document.querySelectorAll('.version-text').forEach(el => {
      el.textContent = version.startsWith('v') ? version : `v${version}`;
    });
  };

  const formatBytes = bytes => {
    if (!Number.isFinite(bytes) || bytes <= 0) return '~92 MB';
    const mb = bytes / 1024 / 1024;
    return `${mb.toFixed(mb >= 100 ? 0 : 1)} MB`;
  };

  setVersion(fallbackVersion);
  document.getElementById('year').textContent = new Date().getFullYear();

  fetch(`https://api.github.com/repos/${repo}/releases/latest`, {
    headers: { Accept: 'application/vnd.github+json' }
  })
    .then(response => {
      if (!response.ok) throw new Error('Release lookup failed');
      return response.json();
    })
    .then(release => {
      if (release && release.tag_name) setVersion(release.tag_name);
      const asset = Array.isArray(release.assets)
        ? release.assets.find(item => item.name === 'InternetDownloadManager_Setup.exe')
        : null;
      if (asset && asset.browser_download_url) {
        document.querySelectorAll('.download-link').forEach(link => {
          link.href = asset.browser_download_url;
        });
        document.getElementById('installer-size').textContent = formatBytes(Number(asset.size));
      }
      document.getElementById('release-status').textContent = 'Latest stable release';
    })
    .catch(() => {
      document.getElementById('release-status').textContent = 'Windows download manager';
    });

  const toggle = document.querySelector('.menu-toggle');
  const nav = document.querySelector('.main-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      const open = nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    nav.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        nav.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  document.querySelectorAll('details').forEach(detail => {
    detail.addEventListener('toggle', () => {
      if (!detail.open) return;
      document.querySelectorAll('details').forEach(other => {
        if (other !== detail) other.open = false;
      });
    });
  });
})();
