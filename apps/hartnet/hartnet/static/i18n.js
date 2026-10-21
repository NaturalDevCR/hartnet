// Only interface-owned strings are localized. Project names and profile data are untouched.
const spanish = await (await fetch(new URL('./es.json', import.meta.url))).json();
let current;
try { current = localStorage.getItem('hartnet.language'); } catch { /* Storage may be unavailable. */ }
if (!['en', 'es'].includes(current)) {
  current = navigator.language?.toLowerCase().startsWith('es') ? 'es' : 'en';
}
export const language = () => current;
export const t = (message) => current === 'es' ? spanish[message] ?? message : message;
export function setLanguage(value) {
  if (!['en', 'es'].includes(value)) return;
  current = value;
  try { localStorage.setItem('hartnet.language', value); } catch { /* Keep the session preference. */ }
}
// Capture only the original shell, before dynamic or user-provided content is rendered.
const shellText = [];
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
while (walker.nextNode()) {
  const node = walker.currentNode;
  if (node.parentElement.closest('#language')) continue;
  if (node.textContent.trim()) shellText.push([node, node.textContent]);
}
const shellAttributes = [...document.querySelectorAll('[aria-label]')]
  .map(node => [node, node.getAttribute('aria-label')]);
export function localizeShell() {
  document.documentElement.lang = current;
  for (const [node, original] of shellText) {
    const trimmed = original.trim();
    node.textContent = original.replace(trimmed, t(trimmed));
  }
  for (const [node, original] of shellAttributes) node.setAttribute('aria-label', t(original));
}

const patterns = Object.entries(spanish).filter(([key]) => /\{\d+\}/.test(key)).map(([key, value]) => {
  const slots = [];
  const expression = key.split(/(\{\d+\})/).map(part => {
    if (/^\{\d+\}$/.test(part)) { slots.push(part); return '(.*?)'; }
    return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }).join('');
  return [new RegExp(`^${expression}$`), value, slots];
});
export function localizeMessage(message) {
  if (current !== 'es' || spanish[message]) return t(message);
  for (const [expression, value, slots] of patterns) {
    const match = expression.exec(message);
    if (match) return value.replace(/\{\d+\}/g, slot => match[slots.indexOf(slot) + 1] ?? slot);
  }
  return message;
}
