/** Transient notices, and the copy button the request preview draws. */

/** Show a message in the bottom-right corner for about two seconds. */
export function toast(msg) {
  const t = document.createElement('div');
  t.style.cssText = 'position:fixed;bottom:16px;right:16px;background:var(--panel-2);border:1px solid var(--accent);color:var(--ink);padding:10px 16px;border-radius:9px;font-size:12.5px;z-index:200;box-shadow:0 8px 30px rgba(0,0,0,.4);max-width:420px';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; }, 1800);
  setTimeout(() => t.remove(), 2200);
}

/** Copy the <pre> that holds this button. Bound from an inline handler. */
export function copyPre(btn) {
  const text = btn.parentElement.innerText.replace(/^Copy\n/, '');
  navigator.clipboard && navigator.clipboard.writeText(text);
  btn.textContent = 'Copied!';
  setTimeout(() => btn.textContent = 'Copy', 1200);
}
